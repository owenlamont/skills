# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "pytest>=8.3",
# ]
# ///
"""Tests for `check_script_floors.py`, and the repo's own scripts against it."""

from collections.abc import Callable
import pathlib
import shutil
import subprocess
import sys
from typing import Final

import pytest


ROOT: Final = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from check_script_floors import (  # noqa: E402
    check,
    compile_error,
    declared_floor,
    entry_points,
    held_back_floor,
    HeldBack,
    project_floor,
    uv_rejects,
)


ScriptFactory = Callable[..., pathlib.Path]

FLOOR: Final = ">=3.14"
BLOCK: Final = (
    '# /// script\n# requires-python = ">=3.14"\n# dependencies = []\n# ///\n'
)
SHEBANG: Final = "#!/usr/bin/env -S uv run --script\n"
GIT: Final = shutil.which("git") or "git"


@pytest.fixture
def script(tmp_path: pathlib.Path) -> ScriptFactory:
    def write(*, body: str, name: str = "s.py") -> pathlib.Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    return write


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(BLOCK, FLOOR, id="one block, one floor"),
        pytest.param(SHEBANG + BLOCK, FLOOR, id="shebang above the block"),
        pytest.param(
            BLOCK + '# /// script\n# requires-python = ">=3.11"\n# ///\n',
            None,
            id="two adjacent blocks read as one, whose content is not TOML",
        ),
        pytest.param(
            BLOCK + '\nprint(1)\n\n# /// script\n# requires-python = ">=3.11"\n# ///\n',
            None,
            id="two separated script blocks are a file the spec rejects",
        ),
        pytest.param(
            '"""Docs.\n\n    # /// script\n    # requires-python = ">=3.11"\n"""\n',
            None,
            id="a floor quoted in a docstring is not a declaration",
        ),
        pytest.param(
            '"""Docs.\n\n    # requires-python = ">=3.11"\n"""\n' + BLOCK,
            FLOOR,
            id="the block wins over a line quoted above it",
        ),
        pytest.param(
            "# /// script\n# requires-python = not-toml\n# ///\n",
            None,
            id="content that is not TOML",
        ),
        pytest.param(
            "# /// script\n# dependencies = []\n# ///\n",
            None,
            id="a block declaring no floor",
        ),
        pytest.param(
            "# /// script\n# requires-python = 314\n# ///\n",
            None,
            id="a floor that is not a string",
        ),
        pytest.param(
            '# /// pyproject\n# [project]\n# requires-python = ">=3.14"\n# ///\n',
            None,
            id="a block of another type is not a script block",
        ),
        pytest.param("print(1)\n", None, id="no block at all"),
    ],
)
def test_declared_floor(script: ScriptFactory, body: str, expected: str | None) -> None:
    assert declared_floor(script(body=body)) == expected


def test_uv_accepts_a_well_formed_block(script: ScriptFactory) -> None:
    assert uv_rejects(script(body=BLOCK)) is None


def test_uv_rejects_a_second_script_block(script: ScriptFactory) -> None:
    body = BLOCK + '# /// script\n# requires-python = ">=3.11"\n# ///\n'
    assert uv_rejects(script(body=body)) is not None


def test_compile_error_is_none_for_source_the_floor_accepts(
    script: ScriptFactory,
) -> None:
    body = BLOCK + "try:\n    pass\nexcept ValueError, TypeError:\n    pass\n"
    assert compile_error(script(body=body), FLOOR) is None


def test_compile_error_names_a_syntax_error(script: ScriptFactory) -> None:
    detail = compile_error(script(body=BLOCK + "def (\n"), FLOOR)
    assert detail is not None
    assert "SyntaxError" in detail


def test_check_reports_a_floor_that_is_not_the_project_floor(
    script: ScriptFactory,
) -> None:
    body = '# /// script\n# requires-python = ">=3.11"\n# ///\n'
    (verdict,) = check([script(body=body)], FLOOR)
    assert not verdict.ok
    assert verdict.detail == f"declares >=3.11; the project floor is {FLOOR}"


def test_check_reports_source_the_floor_cannot_compile(script: ScriptFactory) -> None:
    (verdict,) = check([script(body=BLOCK + "def (\n")], FLOOR)
    assert not verdict.ok
    assert "SyntaxError" in (verdict.detail or "")


def test_check_reports_a_missing_block(script: ScriptFactory) -> None:
    (verdict,) = check([script(body="print(1)\n")], FLOOR)
    assert not verdict.ok
    assert "no single readable `script` block" in (verdict.detail or "")


def test_check_passes_a_script_that_declares_and_compiles(
    script: ScriptFactory,
) -> None:
    (verdict,) = check([script(body=BLOCK + "print(1)\n")], FLOOR)
    assert verdict.ok
    assert verdict.detail is None


def test_project_floor_reads_pyproject(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nrequires-python = ">=3.14"\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules["check_script_floors"], "_PYPROJECT", pyproject)
    assert project_floor() == FLOOR


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param("[project]\nname = 'x'\n", id="no requires-python"),
        pytest.param("[project]\nrequires-python = 3.14\n", id="not a string"),
        pytest.param("[project]\nrequires-python = ''\n", id="empty"),
    ],
)
def test_project_floor_raises_rather_than_passing_everything(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(declared, encoding="utf-8")
    monkeypatch.setattr(sys.modules["check_script_floors"], "_PYPROJECT", pyproject)
    with pytest.raises(ValueError, match="requires-python"):
        project_floor()


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(sys.modules["check_script_floors"], "_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def tracked(repo: pathlib.Path, script: ScriptFactory) -> ScriptFactory:
    def add(*, body: str, name: str = "s.py") -> pathlib.Path:
        path = script(body=body, name=name)
        subprocess.run([GIT, "-C", str(repo), "add", "--", name], check=True)
        return path

    return add


def test_entry_points_finds_metadata_and_shebang_anywhere_in_the_tree(
    tracked: ScriptFactory,
) -> None:
    metadata = tracked(body=BLOCK, name="skills/example/with_block.py")
    shebang = tracked(body=SHEBANG + "print(1)\n", name="hooks/with_shebang.py")
    assert entry_points() == sorted([metadata, shebang])


def test_entry_points_skips_a_module_that_is_not_an_entry_point(
    tracked: ScriptFactory,
) -> None:
    tracked(body='"""A module.\n\n    # /// script\n"""\n', name="lib/plain.py")
    assert entry_points() == []


def test_entry_points_takes_a_skill_script_with_no_metadata(
    tracked: ScriptFactory,
) -> None:
    plain = tracked(body="print(1)\n", name="skills/example/scripts/plain.py")
    assert entry_points() == [plain]
    (verdict,) = check([plain], FLOOR)
    assert not verdict.ok


def test_entry_points_skips_an_untracked_script(
    repo: pathlib.Path, script: ScriptFactory
) -> None:
    script(body=BLOCK, name="scratch.py")
    assert entry_points() == []


def test_entry_points_survives_a_tracked_file_deleted_from_the_tree(
    tracked: ScriptFactory,
) -> None:
    kept = tracked(body=BLOCK, name="tools/kept.py")
    tracked(body=BLOCK, name="tools/gone.py").unlink()
    assert entry_points() == [kept]


NEWER_FLOOR: Final = ">=3.15"
HELD_BACK: Final = HeldBack(floor=">=3.14,<3.15", stragglers=frozenset({"tree-sitter"}))


def _block(floor: str, *dependencies: str) -> str:
    listed = ", ".join(f'"{name}"' for name in dependencies)
    return (
        f'# /// script\n# requires-python = "{floor}"\n'
        f"# dependencies = [{listed}]\n# ///\n"
    )


@pytest.mark.parametrize(
    ("floor", "dependencies", "expected"),
    [
        pytest.param(
            ">=3.14,<3.15",
            ("tree_sitter>=0.25",),
            None,
            id="a straggler, by a non-canonical name, on the held-back floor",
        ),
        pytest.param(
            ">=3.15",
            ("tree-sitter-bash>=0.25", "orjson"),
            None,
            id="a package that only shares the straggler's prefix",
        ),
        pytest.param(
            ">=3.15",
            ("tree-sitter",),
            "declares >=3.15; the held-back floor is >=3.14,<3.15",
            id="a straggler on the project floor",
        ),
        pytest.param(
            ">=3.14,<3.15",
            ("orjson",),
            "declares >=3.14,<3.15; the project floor is >=3.15",
            id="held back with no straggler",
        ),
    ],
)
def test_check_holds_back_only_a_script_that_needs_a_straggler(
    script: ScriptFactory,
    floor: str,
    dependencies: tuple[str, ...],
    expected: str | None,
) -> None:
    body = _block(floor, *dependencies) + "print(1)\n"
    (verdict,) = check([script(body=body)], NEWER_FLOOR, held_back=HELD_BACK)
    assert verdict.detail == expected


def test_check_compiles_a_held_back_script_under_its_own_floor(
    script: ScriptFactory,
) -> None:
    body = _block(">=3.14,<3.15", "tree-sitter") + "flat = [*row for row in [[1]]]\n"
    (verdict,) = check([script(body=body)], NEWER_FLOOR, held_back=HELD_BACK)
    assert "SyntaxError" in (verdict.detail or "")


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        pytest.param("[project]\nname = 'x'\n", None, id="no table"),
        pytest.param(
            "[tool.script-floors]\nheld-back = '>=3.14,<3.15'\n"
            "stragglers = ['Tree_Sitter']\n",
            HeldBack(floor=">=3.14,<3.15", stragglers=frozenset({"tree-sitter"})),
            id="a table, with a straggler name canonicalised",
        ),
    ],
)
def test_held_back_floor_reads_pyproject(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    declared: str,
    expected: HeldBack | None,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(declared, encoding="utf-8")
    monkeypatch.setattr(sys.modules["check_script_floors"], "_PYPROJECT", pyproject)
    assert held_back_floor() == expected


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param(
            "[tool.script-floors]\nheld-back = '>=3.14,<3.15'\n", id="no stragglers"
        ),
        pytest.param(
            "[tool.script-floors]\nstragglers = ['tree-sitter']\n", id="no floor"
        ),
    ],
)
def test_held_back_floor_raises_on_half_a_table(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(declared, encoding="utf-8")
    monkeypatch.setattr(sys.modules["check_script_floors"], "_PYPROJECT", pyproject)
    with pytest.raises(ValueError, match="script-floors"):
        held_back_floor()


def test_every_script_in_the_repo_declares_and_compiles_under_its_floor() -> None:
    verdicts = check(entry_points(), project_floor(), held_back=held_back_floor())
    assert [
        (verdict.path.name, verdict.detail) for verdict in verdicts if not verdict.ok
    ] == []
