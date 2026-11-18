#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2>=2.11.0",
#     "license-expression>=30.4.4",
#     "orjson>=3.12.0",
#     "packaging>=26.0",
#     "py-yaml12>=0.2.0",
#     "pytest>=9.0.0",
#     "typer>=0.26.7",
# ]
# ///
from dataclasses import replace
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any, Final

import assess_dependency
import httpx2 as httpx
import orjson
import pytest


_FIXTURES: Final = Path(__file__).parent / "fixtures"
_FAR_FUTURE: Final = datetime(2030, 1, 1, tzinfo=UTC)
_CHECKOUT_SHA: Final = "11d5960a326750d5838078e36cf38b85af677262"


def _load(name: str) -> Any:
    return orjson.loads((_FIXTURES / name).read_bytes())


def _attested_by(repository: str) -> dict[str, Any]:
    publisher = {"kind": "GitHub", "repository": repository}
    return {"attestation_bundles": [{"publisher": publisher}]}


def _verdicts(checks: list[Any]) -> dict[str, str]:
    return {c.name: c.verdict.name for c in checks}


@pytest.fixture
def frozendict_facts() -> Any:
    def build(*, provenance: bool, previous: bool, vulns: tuple[str, ...] = ()) -> Any:
        return assess_dependency.parse_pypi(
            _load("pypi_frozendict_project.json"),
            _load("pypi_frozendict_2.5.1.json"),
            attestation=assess_dependency.Attestation(present=provenance),
            previous_provenance=previous,
            vulnerabilities=vulns,
        )

    return build


@pytest.fixture
def action_facts() -> Any:
    def build(**overrides: Any) -> Any:
        checkout = assess_dependency.ActionFacts(
            reference=f"actions/checkout@{_CHECKOUT_SHA}",
            repo="actions/checkout",
            ref=_CHECKOUT_SHA,
            resolved_sha=_CHECKOUT_SHA,
            committed=datetime(2025, 1, 1, tzinfo=UTC),
            archived=False,
            runs_using="node20",
            docker_image=None,
            licence="MIT",
        )
        return replace(checkout, **overrides)

    return build


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        pytest.param("MIT", "PASS", id="permissive"),
        pytest.param("MIT OR GPL-2.0-only", "PASS", id="or takes the best option"),
        pytest.param("MPL-2.0 AND MIT", "REVIEW", id="and takes the worst option"),
        pytest.param("LGPL-3.0-only", "REVIEW", id="weak copyleft"),
        pytest.param("AGPL-3.0-only", "FAIL", id="forbidden"),
        pytest.param(
            "Apache-2.0 WITH LLVM-exception", "PASS", id="exception on permissive"
        ),
        pytest.param(
            "GPL-2.0-only WITH Classpath-exception-2.0",
            "FAIL",
            id="exception on forbidden",
        ),
        pytest.param("OFL-1.1", "FAIL", id="on no list"),
        pytest.param("BSD-4-Clause", "FAIL", id="bsd with the advertising clause"),
        pytest.param("LicenseRef-Proprietary", "REVIEW", id="custom licence reference"),
    ],
)
def test_licence_expression(expression: str, expected: str) -> None:
    check = assess_dependency.licence_check(
        expression=expression, classifiers=(), text=None
    )

    assert check.verdict.name == expected


@pytest.mark.parametrize(
    ("classifiers", "expected"),
    [
        pytest.param(("License :: OSI Approved :: MIT License",), "PASS", id="mit"),
        pytest.param(
            ("License :: OSI Approved :: BSD License",),
            "REVIEW",
            id="bsd classifier does not say which clauses",
        ),
        pytest.param(
            ("License :: OSI Approved :: GNU Lesser General Public License v3",),
            "REVIEW",
            id="lesser is not mistaken for general",
        ),
        pytest.param(
            ("License :: OSI Approved :: GNU General Public License v3 (GPLv3)",),
            "FAIL",
            id="gpl",
        ),
        pytest.param(
            (
                "License :: OSI Approved :: GNU Affero General Public License v3",
                "License :: OSI Approved :: MIT License",
            ),
            "REVIEW",
            id="mixed families",
        ),
        pytest.param(
            (
                "License :: Other/Proprietary License",
                "License :: OSI Approved :: MIT License",
            ),
            "REVIEW",
            id="unrecognised classifier is not dropped",
        ),
    ],
)
def test_licence_classifiers(classifiers: tuple[str, ...], expected: str) -> None:
    check = assess_dependency.licence_check(
        expression=None, classifiers=classifiers, text=None
    )

    assert check.verdict.name == expected


def test_free_text_licence_is_reviewed_and_quoted() -> None:
    check = assess_dependency.licence_check(expression=None, classifiers=(), text="BSD")

    assert check.verdict.name == "REVIEW"
    assert "'BSD'" in check.detail


def test_pypi_release_past_cooldown_flags_its_single_owner(
    frozendict_facts: Any,
) -> None:
    facts = frozendict_facts(provenance=False, previous=False)

    result = _verdicts(
        assess_dependency.evaluate_package(facts, facts.released + timedelta(days=30))
    )

    assert result["cooldown"] == "PASS"
    assert result["licence"] == "REVIEW"
    assert result["maintainers"] == "REVIEW"


def test_release_inside_cooldown_fails(frozendict_facts: Any) -> None:
    facts = frozendict_facts(provenance=True, previous=True)

    result = _verdicts(
        assess_dependency.evaluate_package(facts, facts.released + timedelta(days=3))
    )

    assert result["cooldown"] == "FAIL"


def test_provenance_downgrade_and_advisory_fail(frozendict_facts: Any) -> None:
    facts = frozendict_facts(provenance=False, previous=True, vulns=("GHSA-test",))

    result = _verdicts(assess_dependency.evaluate_package(facts, _FAR_FUTURE))

    assert result["provenance"] == "FAIL"
    assert result["advisories"] == "FAIL"


def test_npm_deprecated_version_fails() -> None:
    facts = assess_dependency.parse_npm(
        _load("npm_eslint_packument.json"), "8.57.1", vulnerabilities=()
    )

    result = _verdicts(assess_dependency.evaluate_package(facts, _FAR_FUTURE))

    assert result["withdrawn"] == "FAIL"
    assert result["licence"] == "PASS"


def test_tag_reference_fails_and_suggests_the_full_path_pin(action_facts: Any) -> None:
    facts = action_facts(
        reference="github/codeql-action/init@v3", repo="github/codeql-action", ref="v3"
    )

    pin = next(
        c
        for c in assess_dependency.evaluate_action(facts, _FAR_FUTURE)
        if c.name == "pin"
    )

    assert pin.verdict.name == "FAIL"
    assert f"github/codeql-action/init@{_CHECKOUT_SHA} # v3" in pin.detail


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, "INFO", id="javascript action"),
        pytest.param({"runs_using": None}, "REVIEW", id="no manifest at the path"),
        pytest.param(
            {"runs_using": "docker", "docker_image": "docker://alpine:3.22"},
            "REVIEW",
            id="registry image by tag",
        ),
        pytest.param(
            {"runs_using": "composite", "nested_uses": ("./setup",)},
            "INFO",
            id="composite with a local step",
        ),
        pytest.param(
            {"runs_using": "composite", "nested_uses": ("actions/cache@v4",)},
            "REVIEW",
            id="composite with an unpinned step",
        ),
        pytest.param(
            {
                "runs_using": "composite",
                "nested_uses": (f"actions/cache@v1-{_CHECKOUT_SHA}",),
            },
            "REVIEW",
            id="sha embedded in a tag is not a pin",
        ),
    ],
)
def test_action_execution(
    action_facts: Any, overrides: dict[str, Any], expected: str
) -> None:
    result = _verdicts(
        assess_dependency.evaluate_action(action_facts(**overrides), _FAR_FUTURE)
    )

    assert result["execution"] == expected


def test_dockerfile_action_asks_for_its_from_pins(action_facts: Any) -> None:
    facts = action_facts(runs_using="docker", docker_image="Dockerfile")

    execution = next(
        c
        for c in assess_dependency.evaluate_action(facts, _FAR_FUTURE)
        if c.name == "execution"
    )

    assert execution.verdict.name == "REVIEW"
    assert "`FROM`" in execution.detail


def test_parse_reference_keeps_action_path() -> None:
    parsed = assess_dependency.parse_reference("github/codeql-action/init@v3")

    assert (parsed.repo, parsed.path, parsed.ref) == (
        "github/codeql-action",
        "init",
        "v3",
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, "PASS", id="resolved sha"),
        pytest.param({"resolved_sha": None}, "FAIL", id="sha github cannot resolve"),
    ],
)
def test_sha_pin_must_resolve(
    action_facts: Any, overrides: dict[str, Any], expected: str
) -> None:
    result = _verdicts(
        assess_dependency.evaluate_action(action_facts(**overrides), _FAR_FUTURE)
    )

    assert result["pin"] == expected


def test_action_release_inside_cooldown_fails_on_an_older_commit(
    action_facts: Any,
) -> None:
    facts = action_facts(
        committed=_FAR_FUTURE - timedelta(days=30),
        release="4.1.2",
        released=_FAR_FUTURE - timedelta(days=1),
    )

    result = _verdicts(assess_dependency.evaluate_action(facts, _FAR_FUTURE))

    assert result["cooldown"] == "FAIL"


def test_action_commit_inside_cooldown_fails(action_facts: Any) -> None:
    facts = action_facts(committed=_FAR_FUTURE - timedelta(days=2))

    result = _verdicts(assess_dependency.evaluate_action(facts, _FAR_FUTURE))

    assert result["cooldown"] == "FAIL"


def test_unknown_release_date_fails_the_cooldown(frozendict_facts: Any) -> None:
    facts = replace(frozendict_facts(provenance=True, previous=True), released=None)

    result = _verdicts(assess_dependency.evaluate_package(facts, _FAR_FUTURE))

    assert result["cooldown"] == "FAIL"


def test_archived_source_repository_fails(frozendict_facts: Any) -> None:
    facts = replace(
        frozendict_facts(provenance=True, previous=True), source_archived=True
    )

    result = _verdicts(assess_dependency.evaluate_package(facts, _FAR_FUTURE))

    assert result["withdrawn"] == "FAIL"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param(
            "git+https://github.com/biomejs/biome.git",
            "biomejs/biome",
            id="npm git+https",
        ),
        pytest.param(
            "git@github.com:changchang/seq-queue.git",
            "changchang/seq-queue",
            id="scp form",
        ),
        pytest.param("https://passlib.readthedocs.io", None, id="not github"),
    ],
)
def test_github_repo_from_source_url(url: str, expected: str | None) -> None:
    assert assess_dependency.github_repo(url) == expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param("4.1.2", ("GHSA-cxww-7g56-2vh6",), id="inside the affected range"),
        pytest.param("4.1.3", (), id="fixed release"),
        pytest.param("3.0.2", (), id="before the introduced release"),
    ],
)
def test_action_advisory_ranges(version: str, expected: tuple[str, ...]) -> None:
    advisory = _load("osv_GHSA-cxww-7g56-2vh6.json")

    affecting = assess_dependency.affecting(
        [advisory], packages=("actions/download-artifact",), version=version
    )

    assert affecting == expected


def test_advisory_filed_under_an_action_subpath_url_is_found() -> None:
    advisory = _load("osv_GHSA-hw6r-g8gj-2987.json")
    names = assess_dependency.osv_package_names(
        repo="pytorch/pytorch", path=".github/actions/filter-test-configs"
    )

    affecting = assess_dependency.affecting([advisory], packages=names, version="2.0.0")

    assert affecting == ("GHSA-hw6r-g8gj-2987",)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"release": "4.1.2"}, "PASS", id="tagged release, no advisory"),
        pytest.param(
            {"release": "4.1.2", "vulnerabilities": ("GHSA-x",)},
            "FAIL",
            id="affected release",
        ),
        pytest.param({}, "REVIEW", id="commit with no release tag"),
    ],
)
def test_action_advisories(
    action_facts: Any, overrides: dict[str, Any], expected: str
) -> None:
    result = _verdicts(
        assess_dependency.evaluate_action(action_facts(**overrides), _FAR_FUTURE)
    )

    assert result["advisories"] == expected


@pytest.mark.parametrize(
    ("accounts", "expected"),
    [
        pytest.param(("hynek",), "REVIEW", id="one account"),
        pytest.param(("someone", "project-bot"), "REVIEW", id="one person and a bot"),
        pytest.param(
            ("crmarsh", "zanie", "astral-bot"), "INFO", id="two people and a bot"
        ),
    ],
)
def test_maintainer_count_excludes_automation(
    frozendict_facts: Any, accounts: tuple[str, ...], expected: str
) -> None:
    facts = replace(frozendict_facts(provenance=True, previous=True), accounts=accounts)

    result = _verdicts(assess_dependency.evaluate_package(facts, _FAR_FUTURE))

    assert result["maintainers"] == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"publishers": ("GitHub:hynek/stamina",), "source_repo": "hynek/stamina"},
            "PASS",
            id="published from the declared source",
        ),
        pytest.param(
            {"publishers": ("GitHub:someone/stamina",), "source_repo": "hynek/stamina"},
            "FAIL",
            id="published from another owner",
        ),
        pytest.param(
            {
                "publishers": ("GitHub:example/example-release",),
                "source_repo": "example/example",
            },
            "REVIEW",
            id="release repository under the same owner",
        ),
        pytest.param(
            {"publishers": ("GitLab:group/project",), "source_repo": None},
            "REVIEW",
            id="publisher the script cannot compare",
        ),
        pytest.param(
            {
                "publishers": ("GitHub:hynek/stamina", "GitHub:someone/stamina"),
                "source_repo": "hynek/stamina",
            },
            "FAIL",
            id="files disagree and one is under another owner",
        ),
    ],
)
def test_publisher_matches_declared_source(
    frozendict_facts: Any, overrides: dict[str, Any], expected: str
) -> None:
    facts = replace(frozendict_facts(provenance=True, previous=True), **overrides)

    result = _verdicts(assess_dependency.evaluate_package(facts, _FAR_FUTURE))

    assert result["publisher"] == expected


def test_github_homepage_counts_as_the_source() -> None:
    release = _load("pypi_frozendict_2.5.1.json")
    release["info"] |= {
        "project_urls": {"Homepage": "https://github.com/tree-sitter/tree-sitter-bash"},
        "home_page": None,
    }

    facts = assess_dependency.parse_pypi(
        _load("pypi_frozendict_project.json"),
        release,
        attestation=assess_dependency.Attestation(present=None),
        previous_provenance=None,
        vulnerabilities=(),
    )

    assert facts.source_url == "https://github.com/tree-sitter/tree-sitter-bash"


def test_pypi_publishers_come_from_every_attested_file() -> None:
    release = _load("pypi_frozendict_2.5.1.json")
    first, second, _ = (f["filename"] for f in release["urls"])
    integrity = "/integrity/frozendict/2.5.1"
    routes = {
        "/pypi/frozendict/json": _load("pypi_frozendict_project.json"),
        "/pypi/frozendict/2.5.1/json": release,
        f"{integrity}/{first}/provenance": _attested_by("hynek/stamina"),
        f"{integrity}/{second}/provenance": _attested_by("someone/stamina"),
        "/v1/query": {},
    }
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json=routes[request.url.path])
            if request.url.path in routes
            else httpx.Response(httpx.codes.NOT_FOUND)
        )
    )

    with httpx.Client(transport=transport) as client:
        facts = assess_dependency.fetch_pypi(client, name="frozendict", version="2.5.1")

    assert facts.publishers == ("GitHub:hynek/stamina", "GitHub:someone/stamina")


def test_skill_names_every_licence_the_script_grades() -> None:
    skill = (Path(__file__).parents[1] / "SKILL.md").read_text(encoding="utf-8")
    graded = (
        assess_dependency.PERMISSIVE
        | set(assess_dependency.WEAK_COPYLEFT)
        | set(assess_dependency.FORBIDDEN)
    )

    assert {name for name in graded if f"`{name}`" not in skill} == set()
