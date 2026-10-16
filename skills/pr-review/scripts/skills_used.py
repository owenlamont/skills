#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "orjson>=3.12.0",
#     "py-yaml12>=0.2.0",
#     "typer>=0.26.7",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///
"""Print `pr-review`'s *Skills used* table from the skills this session loaded.

The transcript is the record of what loaded, so the rows are read from it rather than
from recollection:

- **Claude Code** loads a skill with a `Skill` tool call, and records its body in a meta
  row naming that call and opening with the base directory it loaded from. The body's
  frontmatter is stripped, so the version is read only from a stamp a `PostToolUse`
  hook wrote into the same call's attachments. With no such stamp the load reads
  `unversioned` — the installed copy's label now is not proof of what loaded then.
- **Codex** loads a skill by reading its installed `SKILL.md` with a shell command, so a
  load is a command naming that file whose output shows the file's `gh skill` stamp. A
  command that only names the path, or reads a part of the file below its frontmatter,
  is not a load.

Every load is a row. Its source is the stamp's repo, or, for an unstamped Claude load,
the `github-repo` in the loaded copy's frontmatter; a load from anywhere but
`owenlamont/skills` names that source beside its version rather than being dropped.
When the repo under review is public, a load whose source is not public goes to stderr
instead, so the table never names a private repo on a public page.

A Claude Code subagent shares its parent's session id but writes its own transcript, so
the transcript chosen is the one whose unanswered Bash call is running this script.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Annotated, Any, Final
from urllib.parse import urlsplit

import orjson
import typer
import yaml12


CATALOGUE: Final = "owenlamont/skills"
UNVERSIONED: Final = "unversioned"
UNKNOWN_SOURCE: Final = "unknown source"
# Enough of a transcript's end to hold the call running this script and the rows
# a hook appends after it.
_TAIL_BYTES: Final = 1 << 20
_SCRIPT_NAME: Final = Path(__file__).name

_BASE_PREFIX: Final = "Base directory for this skill: "
_FRONTMATTER_DELIMITER: Final = "---"
# `gh skill` writes these three keys in this order into an installed copy's metadata,
# matched rather than YAML-parsed since Codex can truncate away the opening `---`.
_STAMP_RE: Final = re.compile(
    r"github-path: skills/(?P<name>[\w.-]+)[ \t]*\r?\n"
    r"[ \t]*github-ref: refs/tags/(?P<ref>v\d+\.\d+\.\d+)[ \t]*\r?\n"
    r"[ \t]*github-repo: https://github\.com/(?P<repo>[\w.-]+/[\w.-]+?)(?:\.git)?\s"
)
_HOOK_STAMP_RE: Final = re.compile(
    r"^Skill `(?P<name>[^`]+)` loaded from `(?P<dir>[^`]+)` at "
    r"`refs/tags/(?P<ref>v\d+\.\d+\.\d+)` of `(?P<repo>[\w.-]+/[\w.-]+)`\.$",
    re.MULTILINE,
)
# One or more separators, so a Windows path still matches inside JSON-escaped text,
# and searched rather than shell-parsed since the command may be bash or PowerShell.
# A command still running when its call returned reports the session a later
# `write_stdin` polls for the rest of its output.
_RUNNING_RE: Final = re.compile(r'(?:"session_id"\s*:\s*|session ID )(\d+)')
_POLL_RE: Final = re.compile(r'write_stdin\b.*?session_id"?\s*:\s*(\d+)', re.DOTALL)
_INSTALLED_SKILL_RE: Final = re.compile(
    r"[^\s\"'`;|&<>()=,\[\]]*[\\/]+\.(?:agents|codex|claude)[\\/]+skills[\\/]+"
    r"(?P<name>[\w.-]+)[\\/]+SKILL\.md"
)
_CODEX_CALLS: Final = frozenset({"custom_tool_call", "function_call"})
_CODEX_OUTPUTS: Final = frozenset({"function_call_output", "custom_tool_call_output"})


class Harness(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class SkillsUsedError(Exception):
    """A transcript that cannot be found or chosen, reported rather than guessed."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillLoad:
    """One skill load, as far as the transcript establishes it."""

    name: str
    version: str | None
    repo: str | None
    source: str
    """Where it loaded from: a directory, or the path the command read."""


def _frontmatter(text: str) -> Mapping[Any, Any] | None:
    """The YAML mapping between a file's opening `---` line and the next one."""
    lines = [line.rstrip() for line in text.splitlines()]
    if not lines or lines[0] != _FRONTMATTER_DELIMITER:
        return None
    try:
        closer = lines.index(_FRONTMATTER_DELIMITER, 1)
        data = yaml12.parse_yaml("\n".join(lines[1:closer]))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _github_repo(url: Any) -> str | None:
    """`owner/name` from a `https://github.com/owner/name[.git]` URL."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    path = parts.path.strip("/").removesuffix(".git")
    if parts.scheme != "https" or parts.netloc != "github.com" or path.count("/") != 1:
        return None
    return path


def _same_directory(left: str, right: str) -> bool:
    return (
        left.replace("\\", "/").rstrip("/").casefold()
        == right.replace("\\", "/").rstrip("/").casefold()
    )


def _directory_name(directory: str) -> str:
    return directory.replace("\\", "/").rstrip("/").rpartition("/")[2]


def _frontmatter_repo(directory: str) -> str | None:
    """The `github-repo` a loaded copy's frontmatter names: its source, not its ref."""
    try:
        text = (Path(directory) / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter = _frontmatter(text)
    metadata = frontmatter.get("metadata") if frontmatter else None
    return (
        _github_repo(metadata.get("github-repo"))
        if isinstance(metadata, dict)
        else None
    )


def _hook_stamps(attachment: Mapping[str, Any]) -> Iterator[re.Match[str]]:
    try:
        output = orjson.loads(str(attachment.get("stdout") or ""))
    except orjson.JSONDecodeError:
        return iter(())
    hook = output.get("hookSpecificOutput") if isinstance(output, dict) else None
    context = hook.get("additionalContext") if isinstance(hook, dict) else None
    return _HOOK_STAMP_RE.finditer(context) if isinstance(context, str) else iter(())


class _ClaudeLoads:
    def __init__(self) -> None:
        self._calls: list[str] = []
        self._directories: dict[str, str] = {}
        self._stamps: dict[str, list[re.Match[str]]] = {}

    def fold(self, row: Mapping[str, Any]) -> None:
        attachment = row.get("attachment")
        if isinstance(attachment, dict) and (call := attachment.get("toolUseID")):
            self._stamps.setdefault(str(call), []).extend(_hook_stamps(attachment))
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list) or not content:
            return
        if row.get("type") == "assistant":
            self._calls += [
                str(block.get("id"))
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "Skill"
            ]
        elif (source := row.get("sourceToolUseID")) and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str) and text.startswith(_BASE_PREFIX):
                directory = text.removeprefix(_BASE_PREFIX).partition("\n")[0].strip()
                self._directories[str(source)] = directory

    def loads(self) -> Iterator[SkillLoad]:
        """Each call whose body loaded; a built-in skill records none and is skipped."""
        for call in self._calls:
            directory = self._directories.get(call)
            if directory is None:
                continue
            stamp = next(
                (
                    match
                    for match in self._stamps.get(call, ())
                    if _same_directory(match["dir"], directory)
                ),
                None,
            )
            yield SkillLoad(
                name=_directory_name(directory),
                version=stamp["ref"] if stamp else None,
                repo=stamp["repo"] if stamp else _frontmatter_repo(directory),
                source=directory,
            )


def _codex_output_texts(payload: Mapping[str, Any]) -> Iterator[str]:
    """A tool output's text, plus the command output each JSON chunk envelope holds."""
    output = payload.get("output")
    if isinstance(output, list):
        output = "\n".join(
            str(part.get("text") or "") for part in output if isinstance(part, dict)
        )
    if not isinstance(output, str):
        return
    yield output
    for line in output.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            chunk = orjson.loads(line)
        except orjson.JSONDecodeError:
            continue
        if isinstance(chunk, dict) and isinstance(chunk.get("output"), str):
            yield chunk["output"]


class _CodexLoads:
    def __init__(self) -> None:
        self._named: dict[str, dict[str, str]] = {}
        self._running: dict[str, dict[str, str]] = {}
        self._loads: list[SkillLoad] = []

    def fold(self, row: Mapping[str, Any]) -> None:
        payload = row.get("payload")
        if row.get("type") != "response_item" or not isinstance(payload, dict):
            return
        call = str(payload.get("call_id") or "")
        if payload.get("type") in _CODEX_CALLS:
            text = str(payload.get("arguments") or payload.get("input") or "")
            named = {
                match["name"]: match[0] for match in _INSTALLED_SKILL_RE.finditer(text)
            }
            for session in _POLL_RE.findall(f"{payload.get('name') or ''} {text}"):
                named |= self._running.pop(session, {})
            if named:
                self._named[call] = named
        elif payload.get("type") in _CODEX_OUTPUTS and (named := self._named.get(call)):
            self._fold_output(named, payload)

    def _fold_output(
        self, named: Mapping[str, str], payload: Mapping[str, Any]
    ) -> None:
        seen = {
            match["name"]: match
            for text in _codex_output_texts(payload)
            for match in _STAMP_RE.finditer(text)
        }
        self._loads += [
            SkillLoad(
                name=name, version=stamp["ref"], repo=stamp["repo"], source=named[name]
            )
            for name in named
            if (stamp := seen.get(name))
        ]
        if pending := {
            name: source for name, source in named.items() if name not in seen
        }:
            text = "".join(_codex_output_texts(payload))
            for session in _RUNNING_RE.findall(text):
                self._running[session] = pending

    def loads(self) -> Iterator[SkillLoad]:
        yield from self._loads


def _harness_from_environment() -> Harness:
    claude = bool(os.environ.get("CLAUDE_CODE_SESSION_ID"))
    codex = bool(os.environ.get("CODEX_THREAD_ID"))
    if claude and codex:
        raise SkillsUsedError(
            "both CLAUDE_CODE_SESSION_ID and CODEX_THREAD_ID are set, as in one agent "
            "run from the other; pass --harness for the one running this review"
        )
    if claude or codex:
        return Harness.CLAUDE_CODE if claude else Harness.CODEX
    raise SkillsUsedError(
        "neither CLAUDE_CODE_SESSION_ID nor CODEX_THREAD_ID is set; pass --transcript"
    )


def _content_blocks(lines: Iterable[bytes]) -> Iterator[Mapping[str, Any]]:
    for line in lines:
        try:
            row = orjson.loads(line)
        except orjson.JSONDecodeError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            yield from (block for block in content if isinstance(block, dict))


def _names_this_script(block: Mapping[str, Any]) -> bool:
    arguments = block.get("input")
    command = arguments.get("command") if isinstance(arguments, dict) else None
    return (
        block.get("type") == "tool_use"
        and block.get("name") == "Bash"
        and isinstance(command, str)
        and _SCRIPT_NAME in command
    )


def _running_this_script(path: Path) -> bool:
    """Whether `path` holds a Bash call naming this script that has no result yet."""
    with path.open("rb") as transcript:
        transcript.seek(max(0, path.stat().st_size - _TAIL_BYTES))
        tail = transcript.read().splitlines()
    running: set[str] = set()
    for block in _content_blocks(tail):
        if block.get("type") == "tool_result":
            running.discard(str(block.get("tool_use_id")))
        elif _names_this_script(block):
            running.add(str(block.get("id")))
    return bool(running)


def _claude_transcript(projects: Path, session: str) -> Path | None:
    """The session's transcript, or its subagent's, that is running this script.

    Raises
    ------
    SkillsUsedError
        When more than one of them is.
    """
    main = sorted(projects.glob(f"*/{session}.jsonl"))
    candidates = main + sorted(projects.glob(f"*/{session}/subagents/*.jsonl"))
    running = [path for path in candidates if _running_this_script(path)]
    if len(running) > 1:
        listed = "\n  ".join(str(path) for path in running)
        raise SkillsUsedError(
            f"several transcripts of session {session} are running this script; "
            f"pass --transcript with this agent's own:\n  {listed}"
        )
    return running[0] if running else next(iter(main), None)


def find_transcript(harness: Harness) -> Path:
    """The current session's transcript for `harness`, located by its session id.

    Raises
    ------
    SkillsUsedError
        When the harness's session id is unset, names no transcript, or names several
        Claude Code transcripts running this script at once.
    """
    variable = (
        "CLAUDE_CODE_SESSION_ID"
        if harness is Harness.CLAUDE_CODE
        else "CODEX_THREAD_ID"
    )
    session = os.environ.get(variable)
    if not session:
        raise SkillsUsedError(f"{variable} is not set; pass --transcript")
    home = Path.home()
    found = (
        _claude_transcript(home / ".claude" / "projects", session)
        if harness is Harness.CLAUDE_CODE
        else min(
            (home / ".codex" / "sessions").rglob(f"rollout-*-{session}.jsonl"),
            default=None,
        )
    )
    if found is None:
        raise SkillsUsedError(f"no transcript for {variable}={session} under {home}")
    return found


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as lines:
        for line in lines:
            try:
                row = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def _transcript_harness(path: Path) -> Harness:
    """Codex rows carry a `payload`; Claude Code rows never do."""
    first = next(_rows(path), {})
    return Harness.CODEX if "payload" in first else Harness.CLAUDE_CODE


def read_loads(path: Path, harness: Harness) -> tuple[SkillLoad, ...]:
    """Every skill load `path` records, in call order.

    Raises
    ------
    OSError
        When `path` cannot be read.
    """
    folder = _ClaudeLoads() if harness is Harness.CLAUDE_CODE else _CodexLoads()
    for row in _rows(path):
        folder.fold(row)
    return tuple(folder.loads())


def _label(load: SkillLoad) -> str:
    version = load.version or UNVERSIONED
    return (
        version
        if load.repo == CATALOGUE
        else f"{version} from {load.repo or UNKNOWN_SOURCE}"
    )


def version_cell(loads: Iterable[SkillLoad]) -> str:
    """The load's version, and any it changed to mid-session, in first-seen order.

    A load from outside `CATALOGUE` names its source.
    """
    first, *later = dict.fromkeys(_label(load) for load in loads)
    return f"{first} ({', '.join(later)} mid-session)" if later else first


def render_table(loads: Iterable[SkillLoad]) -> str:
    """The two-column table `pr-review` mandates, rows sorted by skill name."""
    by_name: dict[str, list[SkillLoad]] = {}
    for load in loads:
        by_name.setdefault(load.name, []).append(load)
    lines = ["| Skill | Version |", "| --- | --- |"]
    lines += [
        f"| `{name}` | {version_cell(group)} |"
        for name, group in sorted(by_name.items())
    ]
    return "\n".join(lines)


@cache
def is_public(repo: str | None) -> bool:
    """Whether GitHub reports `repo` as public; `None` is the repo in the cwd.

    Anything `gh` cannot answer reads as not public.
    """
    gh = shutil.which("gh")
    if gh is None:
        return False
    target = [repo] if repo else []
    query = ["--json", "visibility", "-q", ".visibility"]
    done = subprocess.run(  # noqa: S603 - fixed argv, absolute binary, no shell
        [gh, "repo", "view", *target, *query],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    return done.returncode == 0 and done.stdout.strip() == "PUBLIC"


@dataclass(frozen=True, slots=True)
class Publishable:
    shown: tuple[SkillLoad, ...]
    withheld: tuple[SkillLoad, ...]


def publishable(
    loads: Iterable[SkillLoad],
    *,
    target_is_public: bool,
    source_is_public: Callable[[str], bool],
) -> Publishable:
    """Split `loads` into those a table on the target repo may show and the rest."""
    loads = tuple(loads)
    if not target_is_public:
        return Publishable(shown=loads, withheld=())
    public = {
        repo
        for repo in {load.repo for load in loads}
        if repo and source_is_public(repo)
    }
    return Publishable(
        shown=tuple(load for load in loads if load.repo in public),
        withheld=tuple(load for load in loads if load.repo not in public),
    )


app = typer.Typer(
    add_completion=False, context_settings={"help_option_names": ["-h", "--help"]}
)


@app.command()
def main(
    harness: Annotated[
        Harness | None,
        typer.Option(help="The agent running this review; read from the environment."),
    ] = None,
    transcript: Annotated[
        Path | None,
        typer.Option(help="Read this transcript instead of the current session's."),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option(help="The owner/name the table is posted to; else the cwd's."),
    ] = None,
) -> None:
    """Print the Skills used table for the skills this session's transcript loaded.

    Each row's loaded-from path prints under the table, and a load from outside
    owenlamont/skills names its source in the version cell. On a public target
    repo, a load whose source is not public goes to stderr instead of the table.
    Exits 2 when no transcript can be chosen.

    Examples
    --------
      uv run --script skills_used.py
      uv run --script skills_used.py --harness codex
    """
    try:
        if transcript is None:
            harness = harness or _harness_from_environment()
            transcript = find_transcript(harness)
        loads = read_loads(transcript, harness or _transcript_harness(transcript))
    except (SkillsUsedError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error

    split = publishable(
        loads, target_is_public=is_public(repo), source_is_public=is_public
    )
    typer.echo(render_table(split.shown))
    if split.shown:
        typer.echo("")
    for name, source in sorted(
        dict.fromkeys((load.name, load.source) for load in split.shown)
    ):
        typer.echo(f"{name}\t{source}")
    for name, source in dict.fromkeys(
        (load.name, load.source) for load in split.withheld
    ):
        typer.echo(
            f"not a row: {name} from {source} (source not public, target is)", err=True
        )


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()
