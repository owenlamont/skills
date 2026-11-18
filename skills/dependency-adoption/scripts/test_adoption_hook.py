#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "orjson>=3.12.0",
#     "pytest>=9.0.0",
#     "tree-sitter>=0.26.0",
#     "tree-sitter-bash>=0.25.1",
# ]
# ///
import adoption_hook
import pytest


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param("uv add httpx", [("uv", False)], id="uv add installs"),
        pytest.param("uv add --no-sync httpx", [("uv", True)], id="uv lock only"),
        pytest.param(
            "uv add --script tool.py httpx", [("uv", True)], id="pep 723 script"
        ),
        pytest.param("cd web && pnpm add -D vite", [("pnpm", False)], id="chained"),
        pytest.param(
            "pnpm add --lockfile-only vite", [("pnpm", True)], id="pnpm lock only"
        ),
        pytest.param("npm i lodash", [("npm", False)], id="npm short verb"),
        pytest.param("pnpm install", [], id="install from the lockfile"),
        pytest.param("uv sync --locked", [], id="sync"),
        pytest.param("echo 'uv add httpx'", [], id="quoted text is not a command"),
        pytest.param(
            "UV_NO_SYNC=1 uv add httpx", [("uv", False)], id="leading assignment"
        ),
        pytest.param(
            "uv --project services/api add httpx",
            [("uv", False)],
            id="global option before the verb",
        ),
        pytest.param("pnpm --filter web add zod", [("pnpm", False)], id="pnpm filter"),
        pytest.param("pnpm -C web add zod", [("pnpm", False)], id="pnpm dir"),
        pytest.param(
            "pnpm install --filter web --frozen-lockfile",
            [],
            id="filter value is not a package",
        ),
        pytest.param(
            "uv add --script=tool.py httpx", [("uv", True)], id="script with equals"
        ),
        pytest.param(
            "env -u VIRTUAL_ENV uv add httpx", [("uv", False)], id="env with options"
        ),
        pytest.param(
            "sudo -u builder uv add httpx", [("uv", False)], id="sudo with options"
        ),
    ],
)
def test_package_adds(command: str, expected: list[tuple[str, bool]]) -> None:
    adds = adoption_hook.package_adds(command)

    assert [(a.tool, a.lock_only) for a in adds] == expected


@pytest.mark.parametrize(
    ("lock_only", "first", "expected"),
    [
        pytest.param(True, True, "load the dependency-adoption skill", id="first add"),
        pytest.param(False, False, "would install", id="later installing add"),
        pytest.param(True, False, None, id="later lock-only add"),
    ],
)
def test_verdict(lock_only: bool, first: bool, expected: str | None) -> None:
    message = adoption_hook.verdict(
        [adoption_hook.PackageAdd(tool="uv", lock_only=lock_only)],
        first_in_session=first,
    )

    assert message is None if expected is None else expected in (message or "")
