#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "orjson>=3.12.0",
#     "py-yaml12>=0.2.0",
#     "pytest>=9.0.0",
#     "typer>=0.26.7",
# ]
# ///
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import orjson
import pytest
from skills_used import (
    find_transcript,
    Harness,
    render_table,
    SkillLoad,
    SkillsUsedError,
)


SESSION: Final = "0f0f0f0f-0000-4000-8000-000000000000"
RUN_SCRIPT: Final = "uv run --script ~/skills/pr-review/scripts/skills_used.py"

type Row = dict[str, Any]


@pytest.fixture
def bash_call() -> Callable[[str, str], Row]:
    def build(call: str, command: str) -> Row:
        arguments = {"command": command}
        block = {"type": "tool_use", "id": call, "name": "Bash", "input": arguments}
        return {"type": "assistant", "message": {"content": [block]}}

    return build


@pytest.fixture
def tool_result() -> Callable[[str], Row]:
    def build(call: str) -> Row:
        block = {"type": "tool_result", "tool_use_id": call}
        return {"type": "user", "message": {"content": [block]}}

    return build


@pytest.fixture
def transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    projects = tmp_path / ".claude" / "projects" / "-repo"

    def write(relative: str, *rows: Row) -> Path:
        path = projects / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(orjson.dumps(row) + b"\n" for row in rows))
        return path

    return write


def test_a_subagent_reads_its_own_transcript_not_its_parents(
    transcript: Callable[..., Path],
    bash_call: Callable[[str, str], Row],
    tool_result: Callable[[str], Row],
) -> None:
    transcript(f"{SESSION}.jsonl", bash_call("parent", "ls"), tool_result("parent"))
    transcript(f"{SESSION}/subagents/agent-idle.jsonl", bash_call("idle", "ls"))
    running = transcript(
        f"{SESSION}/subagents/agent-reviewer.jsonl", bash_call("now", RUN_SCRIPT)
    )

    assert find_transcript(Harness.CLAUDE_CODE) == running


def test_a_finished_run_of_the_script_leaves_the_main_transcript_chosen(
    transcript: Callable[..., Path],
    bash_call: Callable[[str, str], Row],
    tool_result: Callable[[str], Row],
) -> None:
    main = transcript(f"{SESSION}.jsonl", bash_call("parent", "ls"))
    transcript(
        f"{SESSION}/subagents/agent-done.jsonl",
        bash_call("before", RUN_SCRIPT),
        tool_result("before"),
    )

    assert find_transcript(Harness.CLAUDE_CODE) == main


def test_two_transcripts_running_the_script_are_not_guessed_between(
    transcript: Callable[..., Path], bash_call: Callable[[str, str], Row]
) -> None:
    transcript(f"{SESSION}.jsonl", bash_call("a", RUN_SCRIPT))
    transcript(f"{SESSION}/subagents/agent-b.jsonl", bash_call("b", RUN_SCRIPT))

    with pytest.raises(SkillsUsedError, match="several transcripts"):
        find_transcript(Harness.CLAUDE_CODE)


def test_a_load_from_another_repo_is_a_row_naming_its_source() -> None:
    table = render_table(
        [
            SkillLoad(
                name="docs", version="v0.21.3", repo="example/old-skills", source="/a"
            ),
            SkillLoad(
                name="docs", version="v0.1.0", repo="owenlamont/skills", source="/b"
            ),
            SkillLoad(
                name="pr-review",
                version="v0.1.0",
                repo="owenlamont/skills",
                source="/c",
            ),
            SkillLoad(name="vendored", version=None, repo=None, source="/d"),
        ]
    )

    assert table.splitlines()[2:] == [
        "| `docs` | v0.21.3 from example/old-skills (v0.1.0 mid-session) |",
        "| `pr-review` | v0.1.0 |",
        "| `vendored` | unversioned from unknown source |",
    ]
