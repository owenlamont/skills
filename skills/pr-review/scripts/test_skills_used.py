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
from pathlib import Path
from typing import Any

import orjson
import pytest
from skills_used import (
    find_transcript,
    Harness,
    render_table,
    SkillLoad,
    SkillsUsedError,
)


SESSION = "0f0f0f0f-0000-4000-8000-000000000000"


def skill_call(call: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call, "name": "Skill"}]},
    }


def bash_call(call: str, command: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": call,
                    "name": "Bash",
                    "input": {"command": command},
                }
            ]
        },
    }


def result(call: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": call}]},
    }


def write(path: Path, *rows: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(orjson.dumps(row) + b"\n" for row in rows))
    return path


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    return tmp_path / ".claude" / "projects" / "-repo"


def test_a_subagent_reads_its_own_transcript_not_its_parents(projects: Path) -> None:
    write(projects / f"{SESSION}.jsonl", skill_call("parent"), result("parent"))
    subagents = projects / SESSION / "subagents"
    write(subagents / "agent-idle.jsonl", bash_call("idle", "ls"), result("idle"))
    running = write(
        subagents / "agent-reviewer.jsonl",
        skill_call("own"),
        result("own"),
        bash_call("now", "uv run --script ~/skills/pr-review/scripts/skills_used.py"),
    )

    assert find_transcript(Harness.CLAUDE_CODE) == running


def test_a_finished_run_of_the_script_does_not_choose_a_subagent(
    projects: Path,
) -> None:
    main = write(projects / f"{SESSION}.jsonl", skill_call("parent"))
    write(
        projects / SESSION / "subagents" / "agent-done.jsonl",
        bash_call("before", "uv run --script skills_used.py"),
        result("before"),
    )

    assert find_transcript(Harness.CLAUDE_CODE) == main


def test_two_transcripts_running_the_script_are_not_guessed_between(
    projects: Path,
) -> None:
    write(projects / f"{SESSION}.jsonl", bash_call("a", "skills_used.py"))
    write(
        projects / SESSION / "subagents" / "agent-b.jsonl",
        bash_call("b", "skills_used.py"),
    )

    with pytest.raises(SkillsUsedError, match="several transcripts"):
        find_transcript(Harness.CLAUDE_CODE)


def load(name: str, version: str | None, repo: str | None) -> SkillLoad:
    return SkillLoad(name=name, version=version, repo=repo, source=f"/skills/{name}")


def test_a_load_from_another_repo_is_a_row_naming_its_source() -> None:
    table = render_table(
        [
            load("docs", "v0.21.3", "example/old-skills"),
            load("docs", "v0.1.0", "owenlamont/skills"),
            load("pr-review", "v0.1.0", "owenlamont/skills"),
            load("vendored", None, None),
        ]
    )

    assert table.splitlines()[2:] == [
        "| `docs` | v0.21.3 from example/old-skills (v0.1.0 mid-session) |",
        "| `pr-review` | v0.1.0 |",
        "| `vendored` | unversioned from unknown source |",
    ]
