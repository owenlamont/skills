#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.15"
# dependencies = []
# ///
"""Check every bundled script declares this repo's Python floor, and compiles under it.

`uv run --script` resolves the *newest* interpreter a script's `requires-python`
allows rather than the floor it declares, so a script using syntax newer than its floor
runs fine wherever that newer interpreter is installed and dies with a `SyntaxError`
before any of its own error handling wherever only the floor is. ruff, ty and the test
suite all run under one interpreter, so none of them reads the declaration.

**It does not write its own PEP 723 parser.** Three things have to agree, and none is a
regex of this author's devising:

- **PEP 723's own regex**, copied from the specification's reference implementation,
  finds the blocks. More than one `script` block is a file the spec requires a reader to
  reject.
- **`tomllib`** reads `requires-python` out of that block's content.
- **uv** validates the metadata, through `uv python find --script`, which resolves a
  script's interpreter without executing it.

It is stricter than uv in one place: a block with no `requires-python` fails here,
because an undeclared floor is the state this exists to stop.

The floor is the newest stable Python, read from `pyproject.toml`, so bumping one file
moves every script. The one exception is mechanical too: a script depending on a
package listed in `[tool.script-floors] stragglers`, one with no wheel yet on the
newest Python, declares that table's `held-back` floor instead, and every other script
must not. The held-back floor carries an upper bound, which is what keeps
`uv run --script` on the older interpreter's wheels rather than a source build.

    uv run --script tests/check_script_floors.py

Exits 1 naming each script that declares something other than the floor it owes, that
uv will not accept, or that will not compile under it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
import io
import pathlib
import re
import subprocess
import sys
import tomllib
from typing import Any, Final


# Every entry-point script this repo ships declares its floor in PEP 723 metadata, this
# one included -- a gate exempt from its own rule is the first place that rule stops
# holding.
_ROOT: Final = pathlib.Path(__file__).resolve().parent.parent
_PYPROJECT: Final = _ROOT / "pyproject.toml"
# What makes a file an entry point is its shape, not the directory holding it, so a
# script with a shebang and no metadata is still checked -- the undeclared floor this
# exists to stop.
_SHEBANG: Final = "uv run --script"
# Every file directly under a skill's `scripts/` is a standalone script, so one there
# counts whatever it looks like: a missing block is the state this checks for, and
# discovering by shape alone would drop that script from the check instead.
_SCRIPT_DIR_PARTS: Final = ("skills", "scripts")
# PEP 508's name, and PEP 503's normalisation of it, so `tree_sitter>=0.25` and
# `Tree-Sitter` both name the straggler `tree-sitter`.
_NAME: Final = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
_SEPARATORS: Final = re.compile(r"[-_.]+")
_LOWER_BOUND: Final = re.compile(r">=\s*([0-9][0-9.]*)")
# PEP 723's own normative regex, copied from the specification's reference
# implementation rather than written here. Reading `requires-python` off the whole file
# instead let a line quoted in a docstring stand in for a declaration -- twice, in two
# different review rounds -- while the real metadata said `>= 3.14`, `~=3.14` or
# nothing.
# The spec also requires an error on a second block of the same type, which is why the
# caller counts matches rather than taking the first.
_BLOCK: Final = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Verdict:
    """One script, and what happened when the project's floor was held against it."""

    path: pathlib.Path
    detail: str | None

    @property
    def ok(self) -> bool:
        """Whether this script honours the floor the project declares."""
        return self.detail is None


@dataclass(frozen=True, slots=True, kw_only=True)
class HeldBack:
    """The floor for a script that needs a package with no wheel on the project floor.

    Read from `[tool.script-floors]` in `pyproject.toml`: `held-back` is the floor such
    a script declares, and `stragglers` names the packages that put a script there.
    Taking a package off the list makes every script that used it fail until it moves
    up.
    """

    floor: str
    stragglers: frozenset[str]


def project_floor() -> str:
    """The `requires-python` in `pyproject.toml`, which every script has to match.

    Read from the project rather than hardcoded, so the newest-stable rule is applied by
    bumping one file. Raises rather than guessing: a floor this cannot read is one it
    cannot check against, and passing everything silently is the failure it exists to
    stop.
    """
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    floor = declared.get("project", {}).get("requires-python")
    if not isinstance(floor, str) or not floor:
        message = f"{_PYPROJECT} declares no project.requires-python"
        raise ValueError(message)
    return floor


def held_back_floor() -> HeldBack | None:
    """The held-back floor `pyproject.toml` declares, or None where it declares none.

    Raises
    ------
    ValueError
        When `[tool.script-floors]` gives one of `held-back` and `stragglers` without
        the other, or either in the wrong shape.
    """
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    table = declared.get("tool", {}).get("script-floors")
    if table is None:
        return None
    floor = table.get("held-back")
    stragglers = table.get("stragglers")
    if not (
        isinstance(floor, str)
        and floor
        and isinstance(stragglers, list)
        and stragglers
        and all(isinstance(name, str) for name in stragglers)
    ):
        message = (
            f"{_PYPROJECT} [tool.script-floors] needs a held-back string and a "
            f"non-empty stragglers list"
        )
        raise ValueError(message)
    return HeldBack(
        floor=floor, stragglers=frozenset(_canonical(name) for name in stragglers)
    )


def _canonical(name: str) -> str:
    return _SEPARATORS.sub("-", name).lower()


def _metadata(path: pathlib.Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = [m for m in _BLOCK.finditer(text) if m.group("type") == "script"]
    if len(blocks) != 1:
        return None
    content = "\n".join(
        row[2:] if row.startswith("# ") else row[1:]
        for row in blocks[0].group("content").splitlines()
    )
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None


def declared_dependencies(path: pathlib.Path) -> frozenset[str]:
    """The canonical names of the packages `path`'s `script` block depends on."""
    metadata = _metadata(path) or {}
    dependencies = metadata.get("dependencies", [])
    if not isinstance(dependencies, list):
        return frozenset()
    names = (_NAME.match(entry) for entry in dependencies if isinstance(entry, str))
    return frozenset(_canonical(match.group(1)) for match in names if match)


def declared_floor(path: pathlib.Path) -> str | None:
    """The `requires-python` in `path`'s `script` block, or None where there is no one.

    None covers every way a script can fail to declare one thing: no block, more than
    one -- which PEP 723 requires a reader to reject -- content that is not TOML, or no
    `requires-python` key. The caller only has to compare what comes back.
    """
    declared = _metadata(path)
    if declared is None:
        return None
    found = declared.get("requires-python")
    return found if isinstance(found, str) else None


def uv_rejects(path: pathlib.Path) -> str | None:
    """Uv's own complaint about `path`'s inline metadata, or None where it accepts it.

    `uv python find --script` resolves the interpreter a script would run under and
    stops there, so this validates the metadata without executing anything.
    """
    result = subprocess.run(
        ["uv", "python", "find", "--script", str(path)],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        return None
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    return lines[0] if lines else f"uv exited {result.returncode} with no output"


def compile_error(path: pathlib.Path, floor: str) -> str | None:
    """The interpreter's complaint about `path` under `floor`, or None if it compiles.

    `--no-project` keeps this out of the repo's own environment, so the answer is about
    the grammar rather than about what happens to be installed.
    """
    lower = _LOWER_BOUND.search(floor)
    version = lower.group(1) if lower else floor.removeprefix(">=").strip()
    source = (
        f"import py_compile; "
        f"py_compile.compile({str(path)!r}, cfile=None, doraise=True)"
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "--python",
            version,
            "--no-project",
            "python",
            "-X",
            "utf8",
            "-c",
            source,
        ],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        return None
    lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
    return lines[-1] if lines else f"exited {result.returncode} with no output"


def entry_points() -> list[pathlib.Path]:
    """Every script this repo ships that an agent or a human runs directly.

    Every file directly under a skill's `scripts/`, whatever it looks like; elsewhere,
    whatever has a `uv run --script` shebang or PEP 723 metadata, so a script outside
    the skills is covered the day it lands rather than when its directory is listed.

    Two things keep that from over-reaching, and both were holes: the list comes from
    `git ls-files`, so an untracked scratch script in the working tree cannot fail a
    check it was never shipped by; and the metadata test is the anchored block regex
    rather than a substring search, so a module that merely mentions the opener in a
    string literal is not mistaken for a script that declares one.
    """
    listed = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", "-z", "*.py"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    found = []
    for name in listed.stdout.split("\0"):
        if not name:
            continue
        path = _ROOT / name
        if not path.is_file():
            # Deleted but not yet staged: git still lists it, and reading it would end
            # the check in a traceback during an ordinary delete-then-lint.
            continue
        parts = pathlib.PurePosixPath(name).parts
        if len(parts) == 4 and (parts[0], parts[2]) == _SCRIPT_DIR_PARTS:
            found.append(path)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        first = text.split("\n", 1)[0]
        shipped = first.startswith("#!") and _SHEBANG in first
        if shipped or any(m.group("type") == "script" for m in _BLOCK.finditer(text)):
            found.append(path)
    return sorted(found)


def check(
    paths: Iterable[pathlib.Path], floor: str, *, held_back: HeldBack | None = None
) -> list[Verdict]:
    """Every script's verdict against the floor it owes, in path order.

    A script depending on one of `held_back`'s stragglers owes the held-back floor;
    every other script owes the project floor.
    """
    verdicts = []
    for path in sorted(paths):
        declared = declared_floor(path)
        owed, owed_label = floor, "the project floor"
        if held_back is not None and held_back.stragglers & declared_dependencies(path):
            owed, owed_label = held_back.floor, "the held-back floor"
        if declared != owed:
            found = (
                "no single readable `script` block" if declared is None else declared
            )
            detail = f"declares {found}; {owed_label} is {owed}"
        else:
            detail = uv_rejects(path) or compile_error(path, owed)
        verdicts.append(Verdict(path=path, detail=detail))
    return verdicts


def main() -> int:
    """Report every bundled script against the floor `pyproject.toml` declares."""
    floor = project_floor()
    held_back = held_back_floor()
    verdicts = check(entry_points(), floor, held_back=held_back)
    if not verdicts:
        print(f"check_script_floors: no entry points under {_ROOT}", file=sys.stderr)
        return 1
    failed = [verdict for verdict in verdicts if not verdict.ok]
    for verdict in failed:
        print(f"{verdict.path.name}: {verdict.detail}", file=sys.stderr)
    checked = len(verdicts) - len(failed)
    print(
        f"check_script_floors: {checked} of {len(verdicts)} declare and compile "
        f"under {floor}"
        + (
            ""
            if held_back is None
            else f", or {held_back.floor} where they need "
            f"{', '.join(sorted(held_back.stragglers))}"
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
