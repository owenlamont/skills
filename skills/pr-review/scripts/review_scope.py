#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gitpython>=3.1.50",
#     "typer>=0.26.7",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///
from collections.abc import Callable
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Annotated, Final

from git import Actor, BadName, InvalidGitRepositoryError, NoSuchPathError, Repo
import typer


# Guidance filenames, in the order an agent should read them within one directory.
GUIDANCE_NAMES: Final[tuple[str, ...]] = ("AGENTS.md", "CLAUDE.md")

# `index <old>..<new>`, with the trailing mode git omits when the mode itself changed.
INDEX_LINE: Final[re.Pattern[str]] = re.compile(
    r"^index [0-9a-f]+\.\.[0-9a-f]+( [0-7]{6})?$"
)

# Markers for a diff carrying no hunks to compare, only a blob identity.
BINARY_MARKERS: Final[tuple[str, ...]] = ("Binary files ", "GIT binary patch")

# Flags neutralising the caller's git config on the diffs we compare: an external differ
# or a textconv filter can empty the output altogether, which would read as an unchanged
# diff, and colour codes would defeat the index-line match.
DIFF_FLAGS: Final[tuple[str, ...]] = ("--no-ext-diff", "--no-textconv", "--no-color")

SELF_CHECK_ACTOR: Final[Actor] = Actor("self-check", "self-check@example.invalid")


class ScopeError(Exception):
    """A base or diff could not be resolved."""


@dataclass(frozen=True, slots=True)
class Scope:
    base: str
    base_source: str
    paths: tuple[str, ...]
    guidance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Comparison:
    identical: bool
    reason: str
    changed: tuple[str, ...]


def _gh(args: list[str], *, cwd: Path) -> str:
    """Run a `gh` command, which has no library binding the way git has GitPython."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        args, cwd=cwd, capture_output=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        joined = " ".join(args)
        raise ScopeError(f"`{joined}` failed: {result.stderr.strip() or 'no output'}")
    return result.stdout


def _nul_paths(raw: str) -> list[str]:
    """Split NUL-separated `git -z` output.

    Never split git path output on whitespace: `space dir/old file.txt` would become
    three invented paths, and without `-z` git also octal-quotes non-ASCII names.
    """
    return [entry for entry in raw.split("\0") if entry]


def _open_repo(start: Path) -> Repo:
    try:
        return Repo(start, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError) as error:
        raise ScopeError(f"No git checkout at {start}.") from error


def _root(repo: Repo) -> Path:
    if repo.working_tree_dir is None:
        raise ScopeError("A bare repository has no working tree to inspect.")
    return Path(repo.working_tree_dir)


def _resolves(repo: Repo, revision: str) -> bool:
    """Whether `revision` names a commit this checkout actually holds.

    `repo.commit()` alone is not the test: given a full-length OID it builds a lazy
    `Commit` without consulting the object database, so a pruned commit resolves
    happily. Reading a field forces the lookup. An absent object raises here; a broken
    object database raises something else, and only the first is an answer about the
    revision rather than about git.
    """
    try:
        _ = repo.commit(revision).tree
    except BadName, ValueError:
        return False
    return True


def _default_branch(repo: Repo) -> str:
    raw = _gh(["gh", "repo", "view", "--json", "defaultBranchRef"], cwd=_root(repo))
    # A bare branch name, so it composes into a ref as `origin/<name>`. Deliberately
    # not refs/remotes/origin/HEAD, which already carries the `origin/` prefix, goes
    # stale when the remote default is renamed, and is unset in a --single-branch clone.
    return str(json.loads(raw)["defaultBranchRef"]["name"])


def _pr_scope(repo: Repo, number: int) -> tuple[str, str, list[str]]:
    # `gh pr view --json files` is capped at 100 with no pagination and no warning —
    # a 219-file PR silently reports 100 — so take the paths from the paginated REST
    # endpoint instead. --slurp keeps them as JSON, so a path is never split on a
    # delimiter the way `gh pr diff --name-only` splits one containing a newline.
    root = _root(repo)
    summary = json.loads(
        _gh(
            ["gh", "pr", "view", str(number), "--json", "baseRefName,changedFiles"],
            cwd=root,
        )
    )
    pages = json.loads(
        _gh(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{{owner}}/{{repo}}/pulls/{number}/files",
            ],
            cwd=root,
        )
    )
    paths = [str(entry["filename"]) for page in pages for entry in page]
    # Cross-check against the count GitHub reports separately. Any future cap or
    # pagination change then fails loudly here instead of quietly under-reporting,
    # which would drop the nested guidance governing every omitted path.
    expected = int(summary["changedFiles"])
    if len(paths) != expected:
        raise ScopeError(
            f"PR #{number}: got {len(paths)} paths but GitHub reports {expected} "
            f"changed files — the listing is truncated, so guidance would be missed."
        )
    return str(summary["baseRefName"]), f"PR #{number} baseRefName", paths


def _resolve_ref(repo: Repo, base: str) -> str:
    """Return a ref that exists for `base`, preferring the remote-tracking one.

    `origin/<base>` is authoritative after a fetch, but a repo may have no remote,
    or the base may only exist locally — so fall back rather than hard-coding it.
    """
    for candidate in (f"origin/{base}", base):
        if _resolves(repo, candidate):
            return candidate
    raise ScopeError(f"No ref found for base '{base}' as origin/{base} or {base}.")


def _branch_scope(repo: Repo, base: str | None) -> tuple[str, str, list[str]]:
    if base is None:
        base = _default_branch(repo)
        source = "repo default branch (no --base given, and no PR to read it from)"
    else:
        source = "--base"
    ref = _resolve_ref(repo, base)
    if ref != f"origin/{base}":
        source = f"{source}; no origin/{base}, using local {ref}"
    tracked = _nul_paths(
        repo.git.diff("--merge-base", ref, "--name-only", "-z", *DIFF_FLAGS)
    )
    # --merge-base covers committed, staged and unstaged changes to tracked files, but
    # is blind to untracked ones: an entire new module is otherwise invisible.
    return base, source, [*tracked, *repo.untracked_files]


def _guidance_for(root: Path, paths: list[str]) -> list[str]:
    """Collect the guidance files governing `paths`, outermost first.

    A subdirectory's file can narrow or override the root's, so every ancestor
    directory of every changed path contributes, not just the repo root.
    """
    found: dict[str, None] = {}
    directories = {Path(p).parent for p in paths} | {Path()}
    # Sort by depth so the root's guidance is read before anything that narrows it.
    for directory in sorted(directories, key=lambda d: len(d.parts)):
        for ancestor in [*reversed(directory.parents), directory]:
            for name in GUIDANCE_NAMES:
                candidate = root / ancestor / name
                if candidate.is_file():
                    found.setdefault(str(candidate.relative_to(root)), None)
    return list(found)


def resolve(repo: Repo, *, pr: int | None, base: str | None) -> Scope:
    """Resolve the review base, the changed paths, and the guidance governing them."""
    if pr is not None and base is not None:
        raise ScopeError("Pass --pr or --base, not both: a PR already names its base.")
    if pr is not None:
        resolved, source, paths = _pr_scope(repo, pr)
    else:
        resolved, source, paths = _branch_scope(repo, base)
    return Scope(
        base=resolved,
        base_source=source,
        paths=tuple(sorted(set(paths))),
        guidance=tuple(_guidance_for(_root(repo), paths)),
    )


def _oid_pair(value: str) -> tuple[str, str]:
    base, separator, head = value.partition(":")
    if not base or not separator or not head:
        raise ScopeError(f"Expected <base-oid>:<head-oid>, got '{value}'.")
    return base, head


def _three_dot_diff(repo: Repo, base: str, head: str) -> str:
    # Three-dot is merge-base-to-head, which is the diff GitHub shows for a PR.
    return repo.git.diff(*DIFF_FLAGS, f"{base}...{head}")


def _records(diff: str) -> list[tuple[str, tuple[str, ...]]]:
    """Split a diff into per-file records, dropping what is noise rather than change.

    The `index <old>..<new>` blob OIDs move whenever a file's content changes anywhere,
    so an upstream edit clear of the reviewed hunks would otherwise read as a moved
    diff. A binary record keeps them, being all that distinguishes one payload from
    another. A mode change survives either way: git carries it on its own `old mode` and
    `new mode` lines, and drops the trailing mode from the index line.

    Ordered, not keyed by header: `diff --git a/x b/y b/z` is ambiguous when a path
    contains a space, so two records can share one header, and keying on it would let an
    unchanged record mask a changed one.
    """
    grouped: list[list[str]] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            grouped.append([])
        if grouped:
            grouped[-1].append(line)
    records: list[tuple[str, tuple[str, ...]]] = []
    for body in grouped:
        binary = any(entry.startswith(BINARY_MARKERS) for entry in body)
        kept = body if binary else [e for e in body if not INDEX_LINE.match(e)]
        records.append((body[0], tuple(kept)))
    return records


def compare_diffs(repo: Repo, pinned: str, current: str) -> Comparison:
    """Compare the diff a review was built from against the diff as it stands now."""
    pairs = (_oid_pair(pinned), _oid_pair(current))
    missing = [oid for pair in pairs for oid in pair if not _resolves(repo, oid)]
    if missing:
        # A force-pushed base leaves nothing to compare against, so the diff cannot be
        # shown unchanged — which is the answer that would license posting.
        return Comparison(
            identical=False,
            reason=(
                f"{', '.join(missing)} not in this checkout, so nothing to compare — "
                "fetch it (git fetch origin pull/<n>/head for a PR head), unless the "
                "base was force-pushed away"
            ),
            changed=(),
        )
    before = _records(_three_dot_diff(repo, *pairs[0]))
    after = _records(_three_dot_diff(repo, *pairs[1]))
    if before == after:
        return Comparison(
            identical=True, reason="the reviewed diff is unchanged", changed=()
        )
    # The verdict is the ordered comparison above; these names are only for the report,
    # so collapsing a colliding pair here costs nothing.
    changed = sorted(
        header.removeprefix("diff --git ") for header, _ in set(before) ^ set(after)
    )
    return Comparison(
        identical=False, reason="the reviewed diff moved", changed=tuple(changed)
    )


def _scratch_repo(root: Path) -> Repo:
    """Initialise a repo the caller's global git config cannot reach into.

    Signing is the one that bites: a global `commit.gpgsign` with no usable key aborts
    every commit here, and it has to be unset on the repo rather than waved off
    per-command, since `git merge` takes no such flag.
    """
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", SELF_CHECK_ACTOR.name)
        config.set_value("user", "email", SELF_CHECK_ACTOR.email)
        config.set_value("commit", "gpgsign", "false")
    return repo


def _commit(repo: Repo, message: str) -> str:
    # --no-verify so a global core.hooksPath cannot run the caller's hooks in here.
    repo.git.add("-A")
    repo.git.commit("-q", "--no-verify", "-m", message)
    return str(repo.head.commit.hexsha)


def _merge(repo: Repo, branch: str, message: str) -> str:
    repo.git.merge("-q", "--no-verify", "--no-edit", "-m", message, branch)
    return str(repo.head.commit.hexsha)


def _numbered(count: int) -> str:
    return "".join(f"line {n}\n" for n in range(1, count + 1))


def _case_parent_merge(root: Path) -> tuple[str, str]:
    """A stacked PR whose author merges the updated parent branch in."""
    repo = _scratch_repo(root)
    (root / "app.txt").write_text("app v1\n", encoding="utf-8")
    _commit(repo, "base")
    repo.git.checkout("-q", "-b", "parent")
    (root / "feature.txt").write_text("parent feature\n", encoding="utf-8")
    parent_before = _commit(repo, "parent work")
    repo.git.checkout("-q", "-b", "pr")
    (root / "app.txt").write_text("app v2, using the feature\n", encoding="utf-8")
    head_before = _commit(repo, "pr work")
    repo.git.checkout("-q", "parent")
    (root / "helper.txt").write_text("parent helper\n", encoding="utf-8")
    parent_after = _commit(repo, "more parent work")
    repo.git.checkout("-q", "pr")
    head_after = _merge(repo, "parent", "merge the parent branch in")
    return f"{parent_before}:{head_before}", f"{parent_after}:{head_after}"


def _case_upstream_edit_clear_of_hunk(root: Path) -> tuple[str, str]:
    """An upstream edit to the same file, far enough off to leave the hunk alone."""
    repo = _scratch_repo(root)
    (root / "app.txt").write_text(_numbered(10), encoding="utf-8")
    base_before = _commit(repo, "base")
    repo.git.checkout("-q", "-b", "pr")
    (root / "app.txt").write_text(
        _numbered(10).replace("line 1\n", "line 1, edited\n"), encoding="utf-8"
    )
    head_before = _commit(repo, "pr work")
    repo.git.checkout("-q", "main")
    (root / "app.txt").write_text(
        _numbered(10) + "line 11, upstream\n", encoding="utf-8"
    )
    base_after = _commit(repo, "upstream append")
    repo.git.checkout("-q", "pr")
    head_after = _merge(repo, "main", "merge upstream in")
    return f"{base_before}:{head_before}", f"{base_after}:{head_after}"


def _case_upstream_edit_shifting_hunk(root: Path) -> tuple[str, str]:
    """An upstream edit that shifts the reviewed hunk's line numbers."""
    repo = _scratch_repo(root)
    (root / "app.txt").write_text(_numbered(10), encoding="utf-8")
    base_before = _commit(repo, "base")
    repo.git.checkout("-q", "-b", "pr")
    (root / "app.txt").write_text(
        _numbered(10).replace("line 8\n", "line 8, edited\n"), encoding="utf-8"
    )
    head_before = _commit(repo, "pr work")
    repo.git.checkout("-q", "main")
    (root / "app.txt").write_text(
        "line 0, upstream\n" + _numbered(10), encoding="utf-8"
    )
    base_after = _commit(repo, "upstream prepend")
    repo.git.checkout("-q", "pr")
    head_after = _merge(repo, "main", "merge upstream in")
    return f"{base_before}:{head_before}", f"{base_after}:{head_after}"


def _case_mode_change(root: Path) -> tuple[str, str]:
    """A mode change added between the two revisions, leaving the hunks identical."""
    repo = _scratch_repo(root)
    (root / "run.sh").write_text("echo hello\nexit 0\n", encoding="utf-8")
    base = _commit(repo, "base")
    repo.git.checkout("-q", "-b", "pr")
    (root / "run.sh").write_text("echo goodbye\nexit 0\n", encoding="utf-8")
    head_before = _commit(repo, "pr work")
    (root / "run.sh").chmod(0o755)
    head_after = _commit(repo, "make it executable")
    return f"{base}:{head_before}", f"{base}:{head_after}"


def _case_binary_payload(root: Path) -> tuple[str, str]:
    """A binary payload replaced between the revisions, with no hunks either side."""
    repo = _scratch_repo(root)
    (root / "payload.bin").write_bytes(bytes(range(32)))
    base = _commit(repo, "base")
    repo.git.checkout("-q", "-b", "pr")
    (root / "payload.bin").write_bytes(bytes(range(32, 64)))
    head_before = _commit(repo, "first payload")
    (root / "payload.bin").write_bytes(bytes(range(64, 96)))
    head_after = _commit(repo, "second payload")
    return f"{base}:{head_before}", f"{base}:{head_after}"


def _case_colliding_rename_headers(root: Path) -> tuple[str, str]:
    """Two renames sharing one `diff --git` header, only the first of them then edited.

    `a/x b/y b/z` reads as both `x` -> `y b/z` and `x b/y` -> `z`, so a comparison keyed
    on the header lets the unchanged record mask the changed one.
    """
    repo = _scratch_repo(root)
    shared = _numbered(40)
    (root / "x").write_text(f"first marker\n{shared}", encoding="utf-8")
    (root / "x b").mkdir()
    (root / "x b" / "y").write_text(f"second marker\n{shared}", encoding="utf-8")
    base = _commit(repo, "base")
    repo.git.checkout("-q", "-b", "pr")
    (root / "y b").mkdir()
    repo.git.mv("x", "y b/z")
    repo.git.mv("x b/y", "z")
    head_before = _commit(repo, "both renames")
    renamed = root / "y b" / "z"
    renamed.write_text(
        renamed.read_text(encoding="utf-8").replace("line 5\n", "line 5, edited\n"),
        encoding="utf-8",
    )
    head_after = _commit(repo, "edit inside the first rename")
    return f"{base}:{head_before}", f"{base}:{head_after}"


def _case_missing_oid(root: Path) -> tuple[str, str]:
    """A pinned OID that no longer resolves, as after a force-push to the base."""
    repo = _scratch_repo(root)
    (root / "app.txt").write_text("app v1\n", encoding="utf-8")
    base = _commit(repo, "base")
    repo.git.checkout("-q", "-b", "pr")
    (root / "app.txt").write_text("app v2\n", encoding="utf-8")
    head = _commit(repo, "pr work")
    return f"{'0' * 40}:{head}", f"{base}:{head}"


# Each case builds a scratch repo and returns the pinned and current OID pairs, with
# whether `compare` must call them identical. The false ones are what a cheaper
# comparison gets wrong: raw diff text trips on the index lines, a hunks-only comparison
# cannot see a mode change or a binary payload, and keying records by their header loses
# one of a colliding pair.
CASES: Final[tuple[tuple[str, Callable[[Path], tuple[str, str]], bool], ...]] = (
    ("stacked parent merge", _case_parent_merge, True),
    ("upstream edit clear of the hunk", _case_upstream_edit_clear_of_hunk, True),
    ("upstream edit shifting the hunk", _case_upstream_edit_shifting_hunk, False),
    ("mode change behind identical hunks", _case_mode_change, False),
    ("binary payload, no hunks either side", _case_binary_payload, False),
    ("colliding rename headers", _case_colliding_rename_headers, False),
    ("pinned OID no longer resolves", _case_missing_oid, False),
)


app = typer.Typer(
    add_completion=False, context_settings={"help_option_names": ["-h", "--help"]}
)


@app.command()
def compare(
    pinned: Annotated[
        str,
        typer.Option(
            "--pinned", help="<base-oid>:<head-oid> the review was built from."
        ),
    ],
    current: Annotated[
        str, typer.Option("--current", help="<base-oid>:<head-oid> as they stand now.")
    ],
    repo: Annotated[
        Path | None,
        typer.Option("--repo", help="Checkout to inspect; defaults to the cwd."),
    ] = None,
) -> None:
    """Say whether the diff under review moved. Exits 0 unchanged, 1 moved, 2 error."""
    try:
        result = compare_diffs(_open_repo(repo or Path.cwd()), pinned, current)
    except ScopeError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error

    typer.echo(f"{'unchanged' if result.identical else 'moved'}: {result.reason}")
    for header in result.changed:
        typer.echo(f"  {header}")
    if not result.identical:
        raise typer.Exit(1)


@app.command("self-check")
def self_check() -> None:
    """Check `compare` against the git behaviours it has to get right."""
    failures = 0
    for name, build, expect_identical in CASES:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Build before opening: the case is what creates the repo.
            pairs = build(root)
            result = compare_diffs(_open_repo(root), *pairs)
        got = "unchanged" if result.identical else "moved"
        if result.identical == expect_identical:
            typer.echo(f"  ok    {name}: {got}")
        else:
            failures += 1
            wanted = "unchanged" if expect_identical else "moved"
            typer.echo(f"  FAIL  {name}: got {got}, wanted {wanted}")
    typer.echo(f"{len(CASES) - failures}/{len(CASES)} cases pass")
    if failures:
        raise typer.Exit(1)


@app.command()
def scope(
    pr: Annotated[
        int | None,
        typer.Option("--pr", help="PR number; its base is read from GitHub."),
    ] = None,
    base: Annotated[
        str | None, typer.Option("--base", help="Base branch for a branch with no PR.")
    ] = None,
    repo: Annotated[
        Path | None,
        typer.Option("--repo", help="Checkout to inspect; defaults to the cwd."),
    ] = None,
) -> None:
    """Print the review base, the changed paths, and the guidance files to read."""
    try:
        scope = resolve(_open_repo(repo or Path.cwd()), pr=pr, base=base)
    except ScopeError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error

    typer.echo(f"base: {scope.base}  (from {scope.base_source})")
    typer.echo(f"changed paths: {len(scope.paths)}")
    for path in scope.paths:
        typer.echo(f"  {path}")
    typer.echo(f"guidance to read first ({len(scope.guidance)}):")
    for path in scope.guidance:
        typer.echo(f"  {path}")
    if not scope.guidance:
        typer.echo("  (none found)")


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()
    sys.exit(0)
