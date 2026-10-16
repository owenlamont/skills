# /// script
# requires-python = ">=3.14"
# dependencies = ["pytest>=8.3"]
# ///
"""Run every bundled script's own command help, which importing it never reaches.

A script whose ``if __name__ == "__main__"`` block is cut off still imports, so its
unit tests stay green while every invocation exits 0 having printed nothing —
``--help`` included. Nothing in a unit suite sees that, because a unit suite imports.

So this drives each script the way a caller does, and asserts the two things a severed
entry point breaks: exit 0, and output.
"""

import pathlib
import subprocess
from typing import Final

import pytest


ROOT: Final = pathlib.Path(__file__).resolve().parent.parent


def bundled_scripts() -> list[pathlib.Path]:
    """Every script under a skill's ``scripts/`` with PEP 723 metadata, tests aside."""
    return [
        path
        for path in sorted((ROOT / "skills").glob("*/scripts/*.py"))
        if not path.name.startswith("test_")
        and "# /// script" in path.read_text(encoding="utf-8")
    ]


@pytest.mark.parametrize(
    "script", bundled_scripts(), ids=lambda path: path.relative_to(ROOT).as_posix()
)
def test_bundled_script_answers_help(script: pathlib.Path) -> None:
    """Each script prints its own help and exits 0 when asked for it."""
    done = subprocess.run(
        ["uv", "run", "--script", str(script), "--help"],
        capture_output=True,
        encoding="utf-8",
        check=False,
        cwd=ROOT,
        input="",
    )
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    assert done.stdout.strip(), f"exited 0 having printed nothing\n{done.stderr}"


def test_every_bundled_script_is_found() -> None:
    """A layout change that empties this list would pass it silently otherwise."""
    assert bundled_scripts(), "no bundled scripts found — the glob has drifted"
