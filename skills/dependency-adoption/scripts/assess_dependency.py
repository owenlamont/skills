#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2>=2.11.0",
#     "license-expression>=30.4.4",
#     "orjson>=3.12.0",
#     "packaging>=26.0",
#     "py-yaml12>=0.2.0",
#     "typer>=0.26.7",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, UTC
from enum import IntEnum
import io
import os
import re
import sys
from typing import Annotated, Any, Final
from urllib.parse import urlparse

import httpx2 as httpx
from license_expression import (
    AND,
    ExpressionError,
    get_spdx_licensing,
    LicenseSymbol,
    LicenseWithExceptionSymbol,
    OR,
)
import orjson
from packaging.version import InvalidVersion, Version
import typer
import yaml12


COOLDOWN: Final = timedelta(days=7)
INACTIVE: Final = timedelta(days=365)
OSV_QUERY: Final = "https://api.osv.dev/v1/query"
GITHUB_API: Final = "https://api.github.com"
FULL_SHA: Final = re.compile(r"[0-9a-f]{40}")
MAX_EXPRESSION_LENGTH: Final = 200
MAX_TAGS_PER_PAGE: Final = 100
# Registries do not mark bot accounts, so names are the only signal.
AUTOMATION_HINTS: Final = ("bot", "deploy", "release", "automation")

# A default policy for code distributed under a permissive or proprietary licence;
# the skill's Licences section reads the same, so change both together.
PERMISSIVE: Final = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BlueOak-1.0.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC0-1.0",
        "HPND",
        "ISC",
        "MIT",
        "MIT-0",
        "PSF-2.0",
        "Python-2.0",
        "Unicode-3.0",
        "Unicode-DFS-2016",
        "Unlicense",
        "X11",
        "Zlib",
    }
)
WEAK_COPYLEFT: Final = ("LGPL-", "MPL-", "EPL-", "CDDL-")
FORBIDDEN: Final = ("GPL-", "AGPL-", "SSPL-", "BUSL-", "CC-BY-NC")


class Verdict(IntEnum):
    """Ordered so that the worst of several verdicts is their max."""

    INFO = 0
    PASS = 1
    REVIEW = 2
    FAIL = 3


# Most specific first, since "Lesser General Public" contains "General Public".
CLASSIFIER_FAMILIES: Final = (
    ("Affero", Verdict.FAIL),
    ("Lesser General Public", Verdict.REVIEW),
    ("Library or Lesser", Verdict.REVIEW),
    ("Mozilla Public", Verdict.REVIEW),
    ("Eclipse Public", Verdict.REVIEW),
    ("General Public License", Verdict.FAIL),
    ("MIT", Verdict.PASS),
    ("BSD", Verdict.PASS),
    ("Apache", Verdict.PASS),
    ("ISC", Verdict.PASS),
    ("Python Software Foundation", Verdict.PASS),
    ("zlib", Verdict.PASS),
    ("Boost", Verdict.PASS),
    ("Public Domain", Verdict.PASS),
    ("Unlicense", Verdict.PASS),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Check:
    name: str
    verdict: Verdict
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageFacts:
    """What the registry says about one release, independent of which registry."""

    ecosystem: str
    name: str
    version: str
    released: datetime | None
    latest_release: datetime | None
    licence_expression: str | None
    licence_classifiers: tuple[str, ...] = ()
    licence_text: str | None = None
    accounts: tuple[str, ...] | None = None
    organization: str | None = None
    yanked: bool = False
    deprecated: str | None = None
    install_scripts: tuple[str, ...] = ()
    sdist_only: bool = False
    provenance: bool | None = None
    previous_provenance: bool | None = None
    publisher: str | None = None
    source_url: str | None = None
    source_archived: bool | None = None
    source_repo: str | None = None
    vulnerabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionFacts:
    reference: str
    repo: str
    ref: str
    resolved_sha: str | None
    committed: datetime | None
    archived: bool
    runs_using: str | None
    docker_image: str | None
    licence: str | None
    release: str | None = None
    vulnerabilities: tuple[str, ...] = ()
    nested_uses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Attestation:
    present: bool | None
    publisher: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionReference:
    repo: str
    path: str
    ref: str


def _licence(verdict: Verdict, detail: str) -> Check:
    return Check(name="licence", verdict=verdict, detail=detail)


def _symbol_check(key: str) -> Check:
    if key in PERMISSIVE:
        return _licence(Verdict.PASS, f"{key} is permissive")
    if key.startswith(WEAK_COPYLEFT):
        return _licence(
            Verdict.REVIEW,
            f"{key} is weak copyleft: allowed in code that never ships to a browser "
            "or a customer, needs an approved exception before it does",
        )
    if key.startswith(FORBIDDEN):
        return _licence(Verdict.FAIL, f"{key} is forbidden")
    return _licence(
        Verdict.FAIL, f"{key} is on no list: needs an approved exception to adopt"
    )


def _by_verdict(check: Check) -> Verdict:
    return check.verdict


def _node_check(node: Any) -> Check:
    if isinstance(node, OR):
        return min((_node_check(arg) for arg in node.args), key=_by_verdict)
    if isinstance(node, AND):
        return max((_node_check(arg) for arg in node.args), key=_by_verdict)
    if isinstance(node, LicenseWithExceptionSymbol):
        base = _symbol_check(node.license_symbol.key)
        if base.verdict is Verdict.PASS:
            return base
        return _licence(Verdict.FAIL, f"`{node}` needs an approved exception to adopt")
    if isinstance(node, LicenseSymbol):
        return _symbol_check(node.key)
    return _licence(Verdict.REVIEW, f"unrecognised licence term {node}")


def _expression_check(expression: str | None) -> Check | None:
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        return None
    try:
        parsed = get_spdx_licensing().parse(expression, validate=True)
    except ExpressionError:
        return None
    if parsed is None:
        return None
    graded = _node_check(parsed)
    return _licence(graded.verdict, f"`{parsed}`: {graded.detail}")


def _classifier_verdict(classifier: str) -> Verdict:
    return next(
        (verdict for needle, verdict in CLASSIFIER_FAMILIES if needle in classifier),
        Verdict.REVIEW,
    )


def _classifier_check(classifiers: Iterable[str]) -> Check | None:
    named = tuple(classifiers)
    if not named:
        return None
    verdicts = {_classifier_verdict(c) for c in named}
    names = "; ".join(named)
    if len(verdicts) > 1:
        return _licence(
            Verdict.REVIEW, f"classifiers mix families ({names}): confirm which applies"
        )
    return _licence(verdicts.pop(), f"classifier {names}")


def licence_check(
    *, expression: str | None, classifiers: Iterable[str], text: str | None
) -> Check:
    """Grade a licence from an SPDX expression, else trove classifiers, else free text.

    ``OR`` takes the best option, since we may choose it; ``AND`` takes the worst.
    """
    found = (
        _expression_check(expression)
        or _classifier_check(classifiers)
        or _expression_check(text)
    )
    if found is not None:
        return found
    stated = expression or text
    said = (
        f"licence field says {stated[:80]!r}, not an SPDX expression"
        if stated
        else "no licence metadata"
    )
    return _licence(
        Verdict.REVIEW, f"{said}: read the LICENSE file in the source repository"
    )


def _age(*, since: datetime, now: datetime) -> str:
    return f"{(now - since).days} days"


def _cooldown_check(facts: PackageFacts, now: datetime) -> Check:
    if facts.released is None:
        return Check(
            name="cooldown",
            verdict=Verdict.FAIL,
            detail="release date unknown: the cooldown cannot be shown to have passed",
        )
    age = _age(since=facts.released, now=now)
    if now - facts.released < COOLDOWN:
        return Check(
            name="cooldown",
            verdict=Verdict.FAIL,
            detail=f"released {age} ago, inside the {COOLDOWN.days}-day cooldown: "
            "pick an older version or cite the advisory it fixes",
        )
    return Check(name="cooldown", verdict=Verdict.PASS, detail=f"released {age} ago")


def _provenance_check(facts: PackageFacts) -> Check:
    if facts.previous_provenance and not facts.provenance:
        return Check(
            name="provenance",
            verdict=Verdict.FAIL,
            detail="the previous release had provenance and this one does not: "
            "needs an approved exception stating why",
        )
    if facts.provenance:
        return Check(name="provenance", verdict=Verdict.INFO, detail="attested")
    state = "none published" if facts.provenance is False else "unknown"
    return Check(name="provenance", verdict=Verdict.REVIEW, detail=state)


def _publisher_check(facts: PackageFacts) -> Check | None:
    if facts.publisher is None:
        return None
    kind, _, repository = facts.publisher.partition(":")
    declared = facts.source_repo or github_repo(facts.source_url)
    if kind != "GitHub" or declared is None:
        return Check(
            name="publisher",
            verdict=Verdict.REVIEW,
            detail=f"published from {facts.publisher}; confirm it is the project's "
            "own repository",
        )
    if repository.lower() == declared.lower():
        return Check(
            name="publisher",
            verdict=Verdict.PASS,
            detail=f"published from {repository}, the declared source",
        )
    if repository.partition("/")[0].lower() == declared.partition("/")[0].lower():
        return Check(
            name="publisher",
            verdict=Verdict.REVIEW,
            detail=f"published from {repository}, a different repository of the "
            f"declared source's owner ({declared}): confirm it is the release repo",
        )
    return Check(
        name="publisher",
        verdict=Verdict.FAIL,
        detail=f"published from {repository}, but the declared source is {declared} "
        "under another owner: needs an approved exception",
    )


def _looks_automated(account: str) -> bool:
    return any(hint in account.lower() for hint in AUTOMATION_HINTS)


def _maintainer_check(accounts: tuple[str, ...], organization: str | None) -> Check:
    automated = [a for a in accounts if _looks_automated(a)]
    listed = ", ".join(accounts) or "none"
    notes = [f"accounts: {listed}"]
    if automated:
        notes.append(f"possibly automated: {', '.join(automated)}")
    if organization:
        notes.append(f"organisation {organization}")
    people = len(accounts) - len(automated)
    return Check(
        name="maintainers",
        verdict=Verdict.REVIEW if people <= 1 else Verdict.INFO,
        detail="; ".join(notes),
    )


def _review_triggers(facts: PackageFacts, now: datetime) -> list[Check]:
    triggers = []
    if facts.accounts is not None:
        triggers.append(_maintainer_check(facts.accounts, facts.organization))
    if facts.latest_release and now - facts.latest_release > INACTIVE:
        age = _age(since=facts.latest_release, now=now)
        triggers.append(
            Check(
                name="activity", verdict=Verdict.REVIEW, detail=f"no release for {age}"
            )
        )
    if facts.install_scripts:
        scripts = ", ".join(facts.install_scripts)
        triggers.append(
            Check(
                name="install code",
                verdict=Verdict.REVIEW,
                detail=f"runs {scripts} on install: read it",
            )
        )
    if facts.sdist_only:
        triggers.append(
            Check(
                name="install code",
                verdict=Verdict.REVIEW,
                detail="no wheel: installing runs its build backend",
            )
        )
    return triggers


def evaluate_package(facts: PackageFacts, now: datetime) -> list[Check]:
    """Apply the gates and review triggers to one package release."""
    source = facts.source_url or "not declared"
    checks = [
        Check(
            name="identity",
            verdict=Verdict.INFO,
            detail=f"{facts.ecosystem} `{facts.name}` {facts.version}, source {source}",
        ),
        _cooldown_check(facts, now),
        Check(
            name="advisories",
            verdict=Verdict.FAIL if facts.vulnerabilities else Verdict.PASS,
            detail=", ".join(facts.vulnerabilities)
            or "no OSV advisory for this version",
        ),
    ]
    if facts.yanked or facts.deprecated or facts.source_archived:
        reason = (
            "yanked"
            if facts.yanked
            else f"deprecated: {facts.deprecated}"
            if facts.deprecated
            else "source repository is archived"
        )
        checks.append(Check(name="withdrawn", verdict=Verdict.FAIL, detail=reason))
    elif facts.source_archived is None:
        checks.append(
            Check(
                name="withdrawn",
                verdict=Verdict.REVIEW,
                detail="source repository not found on GitHub: confirm it is not "
                "archived",
            )
        )
    checks.append(
        licence_check(
            expression=facts.licence_expression,
            classifiers=facts.licence_classifiers,
            text=facts.licence_text,
        )
    )
    checks.append(_provenance_check(facts))
    if (publisher := _publisher_check(facts)) is not None:
        checks.append(publisher)
    return checks + _review_triggers(facts, now)


def _is_pinned(uses: str) -> bool:
    if uses.startswith("./"):
        return True
    if uses.startswith("docker://"):
        return "@sha256:" in uses
    return FULL_SHA.fullmatch(uses.rpartition("@")[2]) is not None


def _execution_check(facts: ActionFacts) -> Check:
    if facts.runs_using is None:
        return Check(
            name="execution",
            verdict=Verdict.REVIEW,
            detail="no readable manifest at the pinned path: check the path exists",
        )
    image = facts.docker_image
    if facts.runs_using == "docker" and image:
        if not image.startswith("docker://"):
            return Check(
                name="execution",
                verdict=Verdict.REVIEW,
                detail=f"builds `{image}` at the pinned commit: check its `FROM` pins",
            )
        if "@sha256:" in image:
            return Check(
                name="execution", verdict=Verdict.INFO, detail=f"runs `{image}`"
            )
        return Check(
            name="execution",
            verdict=Verdict.REVIEW,
            detail=f"runs `{image}` by tag: the image can change under the pin",
        )
    unpinned = [u for u in facts.nested_uses if not _is_pinned(u)]
    if unpinned:
        return Check(
            name="execution",
            verdict=Verdict.REVIEW,
            detail=f"{facts.runs_using}, nested unpinned: {', '.join(unpinned)}",
        )
    return Check(name="execution", verdict=Verdict.INFO, detail=facts.runs_using)


def _commit_cooldown_check(committed: datetime | None, now: datetime) -> Check:
    if committed is None:
        return Check(
            name="cooldown",
            verdict=Verdict.FAIL,
            detail="commit date unknown: the cooldown cannot be shown to have passed",
        )
    age = _age(since=committed, now=now)
    if now - committed < COOLDOWN:
        return Check(
            name="cooldown",
            verdict=Verdict.FAIL,
            detail=f"commit is {age} old, inside the {COOLDOWN.days}-day cooldown",
        )
    return Check(name="cooldown", verdict=Verdict.PASS, detail=f"commit is {age} old")


def _action_advisory_check(facts: ActionFacts) -> Check:
    if facts.vulnerabilities:
        return Check(
            name="advisories",
            verdict=Verdict.FAIL,
            detail=", ".join(facts.vulnerabilities),
        )
    if facts.release is None:
        return Check(
            name="advisories",
            verdict=Verdict.REVIEW,
            detail="no release tag points at this commit: check OSV by hand",
        )
    return Check(
        name="advisories",
        verdict=Verdict.PASS,
        detail=f"no OSV advisory for {facts.release}",
    )


def evaluate_action(facts: ActionFacts, now: datetime) -> list[Check]:
    """Apply the pinning, cooldown and execution checks to one ``uses:`` reference."""
    checks = [
        Check(name="identity", verdict=Verdict.INFO, detail=f"`{facts.reference}`")
    ]
    if FULL_SHA.fullmatch(facts.ref) and facts.resolved_sha == facts.ref:
        checks.append(
            Check(
                name="pin", verdict=Verdict.PASS, detail="pinned to a full commit SHA"
            )
        )
    elif FULL_SHA.fullmatch(facts.ref):
        checks.append(
            Check(
                name="pin",
                verdict=Verdict.FAIL,
                detail=f"no commit `{facts.ref}` in {facts.repo}",
            )
        )
    else:
        sha = facts.resolved_sha or "unresolved"
        target = facts.reference.partition("@")[0]
        checks.append(
            Check(
                name="pin",
                verdict=Verdict.FAIL,
                detail=f"`{facts.ref}` is mutable: use `{target}@{sha} # {facts.ref}`",
            )
        )
    checks.append(_commit_cooldown_check(facts.committed, now))
    checks.append(_action_advisory_check(facts))
    if facts.archived:
        checks.append(
            Check(
                name="withdrawn", verdict=Verdict.FAIL, detail="repository is archived"
            )
        )
    checks.append(_execution_check(facts))
    checks.append(
        Check(
            name="licence",
            verdict=Verdict.INFO,
            detail=facts.licence or "none declared",
        )
    )
    return checks


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def parse_pypi(
    project: Mapping[str, Any],
    release: Mapping[str, Any],
    *,
    attestation: Attestation,
    previous_provenance: bool | None,
    vulnerabilities: tuple[str, ...],
) -> PackageFacts:
    """Build facts from ``/pypi/<name>/json`` and ``/pypi/<name>/<version>/json``."""
    info = release["info"]
    files = release.get("urls", [])
    uploads = [
        _timestamp(f.get("upload_time_iso_8601"))
        for version_files in project.get("releases", {}).values()
        for f in version_files
    ]
    urls = info.get("project_urls") or {}
    source = next(
        (
            url
            for key, url in urls.items()
            if key.lower() in {"source", "source code", "repository", "github", "code"}
        ),
        None,
    ) or next((url for url in urls.values() if github_repo(url)), info.get("home_page"))
    roles = (project.get("ownership") or {}).get("roles")
    return PackageFacts(
        ecosystem="PyPI",
        name=info["name"],
        version=info["version"],
        released=min(
            (t for f in files if (t := _timestamp(f.get("upload_time_iso_8601")))),
            default=None,
        ),
        latest_release=max((u for u in uploads if u), default=None),
        licence_expression=info.get("license_expression"),
        licence_classifiers=tuple(
            c for c in info.get("classifiers") or [] if c.startswith("License ::")
        ),
        licence_text=info.get("license"),
        accounts=None
        if roles is None
        else tuple(sorted({r["user"] for r in roles}, key=str.lower)),
        organization=(project.get("ownership") or {}).get("organization"),
        yanked=bool(files) and all(f.get("yanked") for f in files),
        sdist_only=bool(files) and all(f["packagetype"] == "sdist" for f in files),
        provenance=attestation.present,
        publisher=attestation.publisher,
        previous_provenance=previous_provenance,
        source_url=source,
        vulnerabilities=vulnerabilities,
    )


def parse_npm(
    packument: Mapping[str, Any], version: str, *, vulnerabilities: tuple[str, ...]
) -> PackageFacts:
    """Build facts from the full npm packument for one version."""
    manifest = packument["versions"][version]
    times = packument.get("time", {})
    published = [
        _timestamp(t) for v, t in times.items() if v not in {"created", "modified"}
    ]
    ordered = sorted(
        (v for v in packument["versions"] if v in times), key=lambda v: times[v]
    )
    index = ordered.index(version) if version in ordered else -1
    previous = packument["versions"][ordered[index - 1]] if index > 0 else None
    licence = manifest.get("license")
    repository = manifest.get("repository")
    hooks = ("preinstall", "install", "postinstall")
    return PackageFacts(
        ecosystem="npm",
        name=manifest["name"],
        version=version,
        released=_timestamp(times.get(version)),
        latest_release=max((p for p in published if p), default=None),
        licence_expression=licence if isinstance(licence, str) else None,
        accounts=tuple(m["name"] for m in packument.get("maintainers") or []) or None,
        deprecated=manifest.get("deprecated"),
        install_scripts=tuple(
            f"{hook}: {manifest['scripts'][hook]}"
            for hook in hooks
            if hook in (manifest.get("scripts") or {})
        ),
        provenance="attestations" in manifest.get("dist", {}),
        previous_provenance=(
            None if previous is None else "attestations" in previous.get("dist", {})
        ),
        source_url=repository.get("url")
        if isinstance(repository, dict)
        else repository,
        vulnerabilities=vulnerabilities,
    )


def parse_reference(reference: str) -> ActionReference:
    """Split ``owner/repo[/path]@ref`` as written after ``uses:``.

    Raises
    ------
    typer.BadParameter
        When the reference has no repository or no ref.
    """
    target, _, ref = reference.partition("@")
    owner, _, rest = target.partition("/")
    repo, _, path = rest.partition("/")
    if not ref or not repo:
        msg = f"expected owner/repo[/path]@ref, got {reference!r}"
        raise typer.BadParameter(msg)
    return ActionReference(repo=f"{owner}/{repo}", path=path, ref=ref)


def _osv(
    client: httpx.Client, *, ecosystem: str, name: str, version: str
) -> tuple[str, ...]:
    response = client.post(
        OSV_QUERY,
        json={"package": {"name": name, "ecosystem": ecosystem}, "version": version},
    )
    response.raise_for_status()
    return tuple(v["id"] for v in orjson.loads(response.content).get("vulns", []))


def _publisher(bundle: Mapping[str, Any]) -> str | None:
    publisher = bundle.get("publisher") or {}
    if "repository" not in publisher:
        return None
    return f"{publisher.get('kind', 'unknown')}:{publisher['repository']}"


def _pypi_attestation(
    client: httpx.Client, *, name: str, version: str, files: list[Mapping[str, Any]]
) -> Attestation:
    """Report whether any file of the release is attested, and who published it.

    ``publisher`` is ``<kind>:<repository>``, e.g. ``GitHub:hynek/stamina``.
    """
    if not files:
        return Attestation(present=None)
    for file in files:
        response = client.get(
            f"https://pypi.org/integrity/{name}/{version}/{file['filename']}/provenance"
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            continue
        response.raise_for_status()
        bundles = orjson.loads(response.content).get("attestation_bundles", [])
        publishers = [p for b in bundles if (p := _publisher(b))]
        return Attestation(
            present=True, publisher=publishers[0] if publishers else None
        )
    return Attestation(present=False)


def fetch_pypi(client: httpx.Client, *, name: str, version: str | None) -> PackageFacts:
    """Fetch one PyPI release, its predecessor's provenance and its OSV advisories."""
    project = orjson.loads(
        client.get(f"https://pypi.org/pypi/{name}/json").raise_for_status().content
    )
    version = version or project["info"]["version"]
    release = orjson.loads(
        client.get(f"https://pypi.org/pypi/{name}/{version}/json")
        .raise_for_status()
        .content
    )
    ordered = sorted(
        (v for v, files in project["releases"].items() if files),
        key=lambda v: min(f["upload_time_iso_8601"] for f in project["releases"][v]),
    )
    index = ordered.index(version) if version in ordered else -1
    previous = ordered[index - 1] if index > 0 else None
    return parse_pypi(
        project,
        release,
        attestation=_pypi_attestation(
            client, name=name, version=version, files=release["urls"]
        ),
        previous_provenance=None
        if previous is None
        else _pypi_attestation(
            client, name=name, version=previous, files=project["releases"][previous]
        ).present,
        vulnerabilities=_osv(client, ecosystem="PyPI", name=name, version=version),
    )


def fetch_npm(client: httpx.Client, *, name: str, version: str | None) -> PackageFacts:
    """Fetch one npm release from its full packument, plus its OSV advisories."""
    packument = orjson.loads(
        client.get(f"https://registry.npmjs.org/{name.replace('/', '%2F')}")
        .raise_for_status()
        .content
    )
    version = version or packument["dist-tags"]["latest"]
    return parse_npm(
        packument,
        version,
        vulnerabilities=_osv(client, ecosystem="npm", name=name, version=version),
    )


def fetch_action(
    client: httpx.Client, reference: str, *, osv: httpx.Client
) -> ActionFacts:
    """Resolve an Action reference and read its manifest at the resolved commit."""
    parsed = parse_reference(reference)
    repo, path, ref = parsed.repo, parsed.path, parsed.ref
    meta = orjson.loads(
        client.get(f"{GITHUB_API}/repos/{repo}").raise_for_status().content
    )
    commit = client.get(f"{GITHUB_API}/repos/{repo}/commits/{ref}")
    commit_body = orjson.loads(commit.content) if commit.is_success else {}
    sha = commit_body.get("sha")
    committed = _timestamp(
        commit_body.get("commit", {}).get("committer", {}).get("date")
    )
    workflow = path.startswith(".github/workflows/")
    candidates = (path,) if workflow else (f"{path}/action.yml", f"{path}/action.yaml")
    manifest: Mapping[Any, Any] = {}
    for file_path in candidates:
        response = client.get(
            f"{GITHUB_API}/repos/{repo}/contents/{file_path.lstrip('/')}",
            params={"ref": sha or ref},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if response.is_success:
            document = yaml12.parse_yaml(response.text)
            manifest = document if isinstance(document, dict) else {}
            break
    runs = manifest.get("runs") or {}
    tagged = _version(ref)
    release = _release_tag(client, repo=repo, sha=sha) or (
        None if tagged is None else str(tagged)
    )
    return ActionFacts(
        reference=reference,
        repo=repo,
        ref=ref,
        resolved_sha=sha,
        committed=committed,
        archived=meta.get("archived", False),
        runs_using=None
        if not manifest
        else "reusable workflow"
        if workflow
        else runs.get("using"),
        docker_image=runs.get("image") if runs.get("using") == "docker" else None,
        licence=(meta.get("license") or {}).get("spdx_id"),
        release=release,
        vulnerabilities=_action_vulnerabilities(osv, repo=repo, release=release),
        nested_uses=_workflow_uses(manifest) if workflow else _step_uses(runs),
    )


def _version(tag: str) -> Version | None:
    try:
        return Version(tag.removeprefix("v"))
    except InvalidVersion:
        return None


def _specificity(version: Version) -> tuple[int, Version]:
    return len(version.release), version


def _release_tag(client: httpx.Client, *, repo: str, sha: str | None) -> str | None:
    """Return the most specific version tag pointing at ``sha``, without its ``v``."""
    if sha is None:
        return None
    versions: list[Version] = []
    url: str | None = f"{GITHUB_API}/repos/{repo}/tags?per_page={MAX_TAGS_PER_PAGE}"
    while url and not versions:
        response = client.get(url)
        if not response.is_success:
            return None
        versions = [
            version
            for tag in orjson.loads(response.content)
            if tag["commit"]["sha"] == sha and (version := _version(tag["name"]))
        ]
        url = response.links.get("next", {}).get("url")
    if not versions:
        return None
    return str(max(versions, key=_specificity))


def _in_range(version: Version, events: Iterable[Mapping[str, str]]) -> bool:
    affected = False
    for event in events:
        if "introduced" in event:
            introduced = event["introduced"]
            affected = introduced == "0" or version >= Version(introduced)
        elif ("fixed" in event and version >= Version(event["fixed"])) or (
            "last_affected" in event and version > Version(event["last_affected"])
        ):
            affected = False
    return affected


def affecting(
    advisories: Iterable[Mapping[str, Any]], *, package: str, version: str
) -> tuple[str, ...]:
    """Return the ids of advisories whose ECOSYSTEM ranges cover ``version``.

    OSV does not match versions for the GitHub Actions ecosystem, so ranges are
    evaluated here.
    """
    parsed = Version(version)
    return tuple(
        advisory["id"]
        for advisory in advisories
        if any(
            affected["package"]["name"].lower() == package.lower()
            and (
                version in affected.get("versions", [])
                or any(
                    _in_range(parsed, r["events"])
                    for r in affected.get("ranges", [])
                    if r["type"] == "ECOSYSTEM"
                )
            )
            for affected in advisory.get("affected", [])
        )
    )


def _action_vulnerabilities(
    client: httpx.Client, *, repo: str, release: str | None
) -> tuple[str, ...]:
    if release is None:
        return ()
    response = client.post(
        OSV_QUERY, json={"package": {"name": repo, "ecosystem": "GitHub Actions"}}
    )
    response.raise_for_status()
    advisories = orjson.loads(response.content).get("vulns", [])
    return affecting(advisories, package=repo, version=release)


def _step_uses(container: Mapping[Any, Any]) -> tuple[str, ...]:
    return tuple(
        step["uses"]
        for step in container.get("steps") or []
        if isinstance(step, dict) and "uses" in step
    )


def _workflow_uses(workflow: Mapping[Any, Any]) -> tuple[str, ...]:
    jobs = [
        job for job in (workflow.get("jobs") or {}).values() if isinstance(job, dict)
    ]
    return tuple(job["uses"] for job in jobs if "uses" in job) + tuple(
        uses for job in jobs for uses in _step_uses(job)
    )


def github_repo(url: str | None) -> str | None:
    """Return ``owner/repo`` when a package's source URL points at github.com."""
    if not url:
        return None
    parsed = urlparse(url.replace("git@github.com:", "https://github.com/"))
    if parsed.hostname != "github.com":
        return None
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None


def with_source_archive(github: httpx.Client, facts: PackageFacts) -> PackageFacts:
    """Look up the package's GitHub source repository: canonical name and archived."""
    repo = github_repo(facts.source_url)
    if repo is None:
        return facts
    response = github.get(f"{GITHUB_API}/repos/{repo}")
    if not response.is_success:
        return facts
    meta = orjson.loads(response.content)
    return replace(
        facts,
        source_archived=bool(meta.get("archived")),
        source_repo=meta.get("full_name"),
        publisher=_canonical_publisher(github, facts.publisher),
    )


def _canonical_publisher(github: httpx.Client, publisher: str | None) -> str | None:
    kind, _, repository = (publisher or "").partition(":")
    if kind != "GitHub":
        return publisher
    response = github.get(f"{GITHUB_API}/repos/{repository}")
    if not response.is_success:
        return publisher
    return f"GitHub:{orjson.loads(response.content)['full_name']}"


def render(title: str, checks: list[Check]) -> str:
    """Format the checks as a collapsed Markdown table for the PR body."""
    rows = (
        f"| {c.name} | {c.verdict.name.lower()} | {c.detail.replace('|', '\\|')} |"
        for c in checks
    )
    return "\n".join(
        (
            f"<details><summary>Dependency evidence: {title}</summary>",
            "",
            "| Check | Result | Detail |",
            "|---|---|---|",
            *rows,
            "",
            "</details>",
        )
    )


def _client(*, github: bool = False) -> httpx.Client:
    """Build the HTTP client; only a GitHub-only client carries the GitHub token."""
    headers = {"User-Agent": "dependency-adoption-check"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if github and token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(timeout=30, follow_redirects=True, headers=headers)


def _emit(title: str, checks: list[Check]) -> None:
    print(render(title, checks))
    if any(c.verdict is Verdict.FAIL for c in checks):
        raise typer.Exit(1)


app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Print the dependency evidence table for a pull request. Each check is pass, "
        "fail (a hard gate), review (a judgement to write up) or info; the exit status "
        "is 1 when any check fails. Queries public registries with the name given, so "
        "never pass an internal package name."
    ),
)
VersionOption = Annotated[
    str | None, typer.Option("--version", help="Release to assess; default latest.")
]


@app.command()
def pypi(*, name: str, version: VersionOption = None) -> None:
    """Assess a PyPI package release."""
    with _client() as client, _client(github=True) as github:
        facts = with_source_archive(
            github, fetch_pypi(client, name=name, version=version)
        )
    _emit(
        f"PyPI {facts.name} {facts.version}", evaluate_package(facts, datetime.now(UTC))
    )


@app.command()
def npm(*, name: str, version: VersionOption = None) -> None:
    """Assess an npm package release."""
    with _client() as client, _client(github=True) as github:
        facts = with_source_archive(
            github, fetch_npm(client, name=name, version=version)
        )
    _emit(
        f"npm {facts.name} {facts.version}", evaluate_package(facts, datetime.now(UTC))
    )


@app.command()
def action(reference: str) -> None:
    """Assess a GitHub Action reference, written as it appears after `uses:`."""
    with _client(github=True) as client, _client() as osv:
        facts = fetch_action(client, reference, osv=osv)
    _emit(f"action {reference}", evaluate_action(facts, datetime.now(UTC)))


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()
