#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gitpython>=3.1.50",
#     "orjson>=3.12.0",
#     "typer>=0.26.7",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
import io
from pathlib import Path
import sys
import tempfile
from typing import Annotated, Any, Final

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
import orjson
import typer


@dataclass(frozen=True)
class FileMetrics:
    """Byte and line counts for a single file."""

    path: str
    root: str
    bytes: int
    lines: int


app = typer.Typer(
    add_completion=False, context_settings={"help_option_names": ["-h", "--help"]}
)


def normalize_extensions(raw_extensions: list[str]) -> set[str]:
    """Expand each filter to the forms a path can match.

    A filter matches a suffix (`py` -> `.py`) or a whole filename, so
    extensionless sources such as `Dockerfile` and `Makefile` are selectable.
    """
    return {
        form
        for extension in raw_extensions
        for form in (extension, f".{extension.removeprefix('.')}")
    }


_ROOTS_HINT: Final = (
    "roots are positional, not an option: source_size.py <dir> [<dir> ...]"
)


def resolve_roots(raw_roots: list[str] | None) -> list[str]:
    """Resolve the effective root list, defaulting to src and tests."""
    return raw_roots or ["src", "tests"]


def tracked_files(base_dir: Path) -> set[Path]:
    """Absolute paths of every file Git tracks in the tree holding base_dir."""
    repo = find_repo(base_dir)
    work_tree = Path(repo.working_tree_dir or base_dir).resolve()
    names = repo.git.ls_files("-z").split("\0")
    return {work_tree / name for name in names if name}


def iter_files(root: Path, extensions: set[str], tracked: set[Path]) -> list[Path]:
    """Return the tracked files under a root, optionally filtered by extension.

    Git decides what counts, so an ignored or untracked file is never measured —
    a build cache, a virtualenv, an editor's scratch file. Two tracked entries are
    still skipped: a path deleted from the working tree, which is an index entry
    and not a file, and a symlink, whose target is not what Git stores.
    """
    files = [
        path
        for path in tracked
        if root in path.parents and path.is_file() and not path.is_symlink()
    ]
    if not extensions:
        return sorted(files)
    return sorted(
        path for path in files if path.suffix in extensions or path.name in extensions
    )


def count_lines(data: bytes) -> int:
    """Count logical lines from raw bytes without assuming an encoding."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def collect_metrics(
    base_dir: Path, root: Path, label: str, extensions: set[str], tracked: set[Path]
) -> list[FileMetrics]:
    """Collect byte and line counts for the tracked files under a root.

    `label` is the root as the caller asked for it, so two roots sharing a
    basename — `packages/a/src` and `packages/b/src` — stay distinguishable.
    """
    metrics: list[FileMetrics] = []
    for path in iter_files(root, extensions, tracked):
        data = path.read_bytes()
        metrics.append(
            FileMetrics(
                path=path.relative_to(base_dir).as_posix(),
                root=label,
                bytes=len(data),
                lines=count_lines(data),
            )
        )
    return metrics


def collect_metrics_by_root(
    base_dir: Path,
    roots: list[str],
    extensions: set[str],
    *,
    allow_missing: bool = False,
) -> dict[str, list[FileMetrics]]:
    """Collect metrics for each requested root relative to a base directory.

    With `allow_missing`, a root that is absent counts as empty rather than
    failing — a comparison has two sides, and a change that adds or removes a
    whole root leaves it missing from one of them.

    Raises
    ------
    SystemExit
        If a requested root is missing (unless `allow_missing`) or is not a
        directory.
    """
    tracked = tracked_files(base_dir)
    metrics_by_root: dict[str, list[FileMetrics]] = {}
    for raw_root in roots:
        root = base_dir / raw_root
        if root.is_symlink():
            raise SystemExit(f"root is a symlink: {raw_root}")
        root = root.resolve()
        if not root.exists():
            if allow_missing:
                metrics_by_root[raw_root] = []
                continue
            raise SystemExit(f"root does not exist: {raw_root}; {_ROOTS_HINT}")
        if not root.is_dir():
            raise SystemExit(f"root is not a directory: {raw_root}")
        metrics_by_root[raw_root] = collect_metrics(
            base_dir, root, raw_root, extensions, tracked
        )
    return metrics_by_root


def format_kib(size_bytes: int) -> str:
    """Format a byte count in kibibytes with one decimal place."""
    return f"{size_bytes / 1024:.1f}"


def format_delta(value: int) -> str:
    """Format a signed integer delta."""
    return f"{value:+d}"


def format_delta_kib(value: int) -> str:
    """Format a signed byte delta in kibibytes with one decimal place."""
    return f"{value / 1024:+.1f}"


def build_report(metrics_by_root: dict[str, list[FileMetrics]]) -> dict[str, Any]:
    """Build the aggregate report shared by both output modes."""
    per_root = []
    all_metrics: list[FileMetrics] = []
    for root, metrics in metrics_by_root.items():
        all_metrics.extend(metrics)
        per_root.append(
            {
                "root": root,
                "files": len(metrics),
                "bytes": sum(metric.bytes for metric in metrics),
                "lines": sum(metric.lines for metric in metrics),
            }
        )

    totals = {
        "files": len(all_metrics),
        "bytes": sum(metric.bytes for metric in all_metrics),
        "lines": sum(metric.lines for metric in all_metrics),
    }
    largest_files = sorted(
        (asdict(metric) for metric in all_metrics),
        key=lambda metric: (-metric["bytes"], metric["path"]),
    )

    return {"roots": per_root, "totals": totals, "largest_files": largest_files}


def build_diff_report(
    current_report: dict[str, Any], baseline_report: dict[str, Any]
) -> dict[str, Any]:
    """Build a diff report between current and baseline size reports."""
    current_roots = {entry["root"]: entry for entry in current_report["roots"]}
    baseline_roots = {entry["root"]: entry for entry in baseline_report["roots"]}
    all_roots = sorted(set(current_roots) | set(baseline_roots))

    root_deltas = []
    for root in all_roots:
        current = current_roots.get(root, {"files": 0, "lines": 0, "bytes": 0})
        baseline = baseline_roots.get(root, {"files": 0, "lines": 0, "bytes": 0})
        root_deltas.append(
            {
                "root": root,
                "files": current["files"] - baseline["files"],
                "lines": current["lines"] - baseline["lines"],
                "bytes": current["bytes"] - baseline["bytes"],
            }
        )

    current_files = {entry["path"]: entry for entry in current_report["largest_files"]}
    baseline_files = {
        entry["path"]: entry for entry in baseline_report["largest_files"]
    }
    file_deltas = []
    for path in sorted(set(current_files) | set(baseline_files)):
        current = current_files.get(
            path, {"root": path.split("/", 1)[0], "lines": 0, "bytes": 0}
        )
        baseline = baseline_files.get(
            path, {"root": path.split("/", 1)[0], "lines": 0, "bytes": 0}
        )
        lines_delta = current["lines"] - baseline["lines"]
        bytes_delta = current["bytes"] - baseline["bytes"]
        if lines_delta == 0 and bytes_delta == 0:
            continue
        file_deltas.append(
            {
                "path": path,
                "root": current.get("root", baseline.get("root")),
                "lines": lines_delta,
                "bytes": bytes_delta,
            }
        )

    file_deltas.sort(key=lambda entry: (-abs(entry["bytes"]), entry["path"]))

    return {
        "roots": root_deltas,
        "totals": {
            "files": current_report["totals"]["files"]
            - baseline_report["totals"]["files"],
            "lines": current_report["totals"]["lines"]
            - baseline_report["totals"]["lines"],
            "bytes": current_report["totals"]["bytes"]
            - baseline_report["totals"]["bytes"],
        },
        "files": file_deltas,
    }


def find_repo(start_dir: Path) -> Repo:
    """Resolve the Git repository for the current working tree.

    Raises
    ------
    SystemExit
        If the directory is not inside a Git repository.
    """
    try:
        return Repo(start_dir, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise SystemExit("failed to resolve git repository root") from exc


@contextmanager
def temporary_worktree(repo: Repo, git_ref: str):
    """Create and clean up a temporary detached worktree for a Git ref."""
    with tempfile.TemporaryDirectory(prefix="source-size-") as temp_dir:
        worktree_dir = Path(temp_dir).resolve() / "baseline"
        try:
            repo.git.worktree("add", "--detach", str(worktree_dir), git_ref)
            yield worktree_dir
        finally:
            with suppress(Exception):
                repo.git.worktree("remove", "--force", str(worktree_dir))


def print_text(report: dict[str, Any], top_n: int) -> None:
    """Print a human-readable table for the collected size report."""
    print("Root           Files      Lines      Bytes      KiB")
    for root in report["roots"]:
        print(
            f"{root['root']:<12} "
            f"{root['files']:>5} "
            f"{root['lines']:>10} "
            f"{root['bytes']:>10} "
            f"{format_kib(root['bytes']):>8}"
        )

    totals = report["totals"]
    print(
        f"{'TOTAL':<12} "
        f"{totals['files']:>5} "
        f"{totals['lines']:>10} "
        f"{totals['bytes']:>10} "
        f"{format_kib(totals['bytes']):>8}"
    )

    if top_n <= 0:
        return

    print()
    print(f"Top {min(top_n, len(report['largest_files']))} Largest Files")
    print("Path                                             Lines      Bytes      KiB")
    for metric in report["largest_files"][:top_n]:
        print(
            f"{metric['path']:<48.48} "
            f"{metric['lines']:>10} "
            f"{metric['bytes']:>10} "
            f"{format_kib(metric['bytes']):>8}"
        )


def print_diff_text(diff_report: dict[str, Any], git_ref: str, top_n: int) -> None:
    """Print a human-readable diff table against a Git baseline."""
    print(f"Delta Vs {git_ref}")
    print("Root           Files      Lines      Bytes    KiB Δ")
    for root in diff_report["roots"]:
        print(
            f"{root['root']:<12} "
            f"{format_delta(root['files']):>5} "
            f"{format_delta(root['lines']):>10} "
            f"{format_delta(root['bytes']):>10} "
            f"{format_delta_kib(root['bytes']):>8}"
        )

    totals = diff_report["totals"]
    print(
        f"{'TOTAL':<12} "
        f"{format_delta(totals['files']):>5} "
        f"{format_delta(totals['lines']):>10} "
        f"{format_delta(totals['bytes']):>10} "
        f"{format_delta_kib(totals['bytes']):>8}"
    )

    if top_n <= 0:
        return

    if not diff_report["files"]:
        print()
        print("No file deltas.")
        return

    print()
    print(f"Top {min(top_n, len(diff_report['files']))} File Deltas")
    print(
        "Path                                             Lines Δ    Bytes Δ    KiB Δ"
    )
    for metric in diff_report["files"][:top_n]:
        print(
            f"{metric['path']:<48.48} "
            f"{format_delta(metric['lines']):>10} "
            f"{format_delta(metric['bytes']):>10} "
            f"{format_delta_kib(metric['bytes']):>8}"
        )


@app.command()
def main(
    roots: Annotated[
        list[str] | None,
        typer.Argument(help="Directories to scan recursively (default: src tests)."),
    ] = None,
    ext: Annotated[
        list[str] | None,
        typer.Option(help="File extensions to measure (default: .py)."),
    ] = None,
    top: Annotated[
        int,
        typer.Option(help="How many largest files to show. Use 0 to hide the table."),
    ] = 15,
    compare_to: Annotated[
        str | None,
        typer.Option("--compare-to", help="Git branch, tag, or commit to compare to."),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the report as JSON instead of plain text."),
    ] = False,
) -> int:
    """Report source and test code size, and the delta a change introduces.

    Walks the roots (default: src tests), counting the Git-tracked source files
    (.py by default, override with --ext), lines, and bytes per root, and lists the
    largest files. Ignored and untracked files are never counted.
    With --compare-to it diffs against a Git ref via a temporary worktree, so you can
    watch the test-to-source ratio and how a change moves it.

    Examples (run from a repo root):
      uv run --script source_size.py
      uv run --script source_size.py --compare-to main
      uv run --script source_size.py --compare-to HEAD --json
      uv run --script source_size.py <dir> [<dir> ...] --ext .md --compare-to main
    """
    current_dir = Path.cwd().resolve()
    selected_roots = resolve_roots(roots)
    extensions = normalize_extensions(ext or ["py"])
    report = build_report(
        collect_metrics_by_root(
            current_dir,
            selected_roots,
            extensions,
            allow_missing=compare_to is not None,
        )
    )

    if compare_to is None:
        if as_json:
            print(
                orjson.dumps(
                    report, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS
                ).decode()
            )
        else:
            print_text(report, top)
        return 0

    repo = find_repo(current_dir)
    with temporary_worktree(repo, compare_to) as baseline_dir:
        absent = [
            raw_root
            for raw_root in selected_roots
            if not (current_dir / raw_root).is_dir()
            and not (baseline_dir / raw_root).is_dir()
        ]
        if absent:
            raise SystemExit(
                f"root does not exist on either side: {', '.join(absent)}; "
                f"{_ROOTS_HINT}"
            )
        baseline_report = build_report(
            collect_metrics_by_root(
                baseline_dir, selected_roots, extensions, allow_missing=True
            )
        )

    diff_report = build_diff_report(report, baseline_report)
    comparison = {
        "baseline_ref": compare_to,
        "baseline": baseline_report,
        "current": report,
        "delta": diff_report,
    }
    if as_json:
        print(
            orjson.dumps(
                comparison, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS
            ).decode()
        )
    else:
        print_text(report, top)
        print()
        print_diff_text(diff_report, compare_to, top)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()
