#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "orjson>=3.12.0",
#     "tree-sitter>=0.26.0",
#     "tree-sitter-bash>=0.25.1",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///
"""PreToolUse hook that routes package adds through the dependency-adoption skill.

The first package add in a session is blocked with an instruction to load the skill.
After that, only an add that would install is blocked: the lock-only forms pass, so
the locked version can be assessed before any of its code runs. Exit 2 blocks and
shows stderr to the model; anything unparsable exits 0 so the hook cannot wedge a
session.
"""

import argparse
from dataclasses import dataclass
import io
import os
from pathlib import Path
import shlex
import sys
import tempfile
from typing import Final

import orjson
from tree_sitter import Language, Node, Parser
import tree_sitter_bash


_PARSER: Final = Parser(Language(tree_sitter_bash.language()))
# Wrapper options whose value is the next word, e.g. `env -u VAR`, `sudo -u user`.
_WRAPPER_VALUE_OPTIONS: Final = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S"}),
    "sudo": frozenset({"-u", "--user", "-g", "--group", "-C", "-D", "-h", "-p", "-U"}),
}
_WRAPPERS: Final = frozenset({"command", "env", "exec", "nohup", "sudo", "time"})
_ADD_VERBS: Final = {
    "uv": frozenset({"add"}),
    "pnpm": frozenset({"add", "install", "i"}),
    "npm": frozenset({"add", "install", "i"}),
}
_LOCK_ONLY: Final = {
    "uv": frozenset({"--no-sync", "--script"}),
    "pnpm": frozenset({"--lockfile-only"}),
    "npm": frozenset({"--package-lock-only"}),
}
_REQUIREMENTS_FILES: Final = frozenset({"-r", "--requirements"})
_FALSE_VALUES: Final = frozenset({"false", "0", "no"})
# Options whose value is the next word, so the value is neither the verb nor a package.
_VALUE_OPTIONS: Final = {
    "uv": frozenset(
        {
            "--project",
            "--directory",
            "--python",
            "-p",
            "--cache-dir",
            "--config-file",
            "--color",
            "--script",
            "--group",
            "--optional",
            "--extra",
            "--index",
            "--default-index",
            "--rev",
            "--tag",
            "--branch",
            "--marker",
            "-m",
            "--requirements",
            "-r",
            "--constraints",
            "-c",
            "--package",
            "--bounds",
        }
    ),
    "pnpm": frozenset(
        {"--filter", "-F", "--dir", "-C", "--reporter", "--loglevel", "--config"}
    ),
    "npm": frozenset({"--workspace", "-w", "--prefix", "--registry", "--tag"}),
}
_MARKERS: Final = Path(tempfile.gettempdir()) / "dependency-adoption-hook"
_LOAD_SKILL: Final = (
    "Blocked by the dependency-adoption hook: load the dependency-adoption skill "
    "before adding a dependency, then follow it — lock without installing "
    "(`uv add --no-sync --no-build`, `pnpm add --lockfile-only`, "
    "`npm install --package-lock-only`), assess the locked version, and install "
    "only once it passes."
)
_LOCK_FIRST: Final = (
    "Blocked by the dependency-adoption hook: this add would install before the "
    "dependency is assessed. Lock without installing (`uv add --no-sync --no-build`, "
    "`pnpm add --lockfile-only`, `npm install --package-lock-only`), assess the "
    "locked version with the skill's script, then install."
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageAdd:
    tool: str
    lock_only: bool


def _words(segment: str) -> list[str]:
    lexer = shlex.shlex(segment, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    words = list(lexer)
    while words and (words[0] in _WRAPPERS or "=" in words[0]):
        wrapper = words.pop(0)
        takes_value = _WRAPPER_VALUE_OPTIONS.get(wrapper, frozenset())
        while words and words[0].startswith("-"):
            option = words.pop(0)
            if option in takes_value and words:
                words.pop(0)
    return words


def _positionals(tool: str, words: list[str]) -> list[str]:
    takes_value = _VALUE_OPTIONS.get(tool, frozenset())
    positionals = []
    skip_next = False
    for word in words:
        if skip_next:
            skip_next = False
        elif word.startswith("-"):
            skip_next = "=" not in word and word in takes_value
        else:
            positionals.append(word)
    return positionals


def _as_add(words: list[str]) -> PackageAdd | None:
    if not words:
        return None
    tool = words[0].rsplit("/", maxsplit=1)[-1]
    verb, *packages = _positionals(tool, words[1:]) or [""]
    options = [word.partition("=") for word in words if word.startswith("-")]
    flags = {name for name, _, value in options if value.lower() not in _FALSE_VALUES}
    if verb not in _ADD_VERBS.get(tool, frozenset()):
        return None
    if not packages and not (tool == "uv" and flags & _REQUIREMENTS_FILES):
        return None
    return PackageAdd(
        tool=tool, lock_only=bool(_LOCK_ONLY.get(tool, frozenset()) & flags)
    )


def package_adds(command: str) -> list[PackageAdd]:
    """Return every package-adding command in a shell command line."""
    encoded = command.encode()
    adds = []
    pending: list[Node] = [_PARSER.parse(encoded).root_node]
    while pending:
        node = pending.pop()
        if node.type == "command":
            try:
                words = _words(encoded[node.start_byte : node.end_byte].decode())
            except ValueError:
                words = []
            if (add := _as_add(words)) is not None:
                adds.append(add)
        pending.extend(node.named_children)
    return adds


def _first_in_session(session_id: str) -> bool:
    _MARKERS.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(_MARKERS / session_id, os.O_CREAT | os.O_EXCL))
    except FileExistsError:
        return False
    return True


def verdict(adds: list[PackageAdd], *, first_in_session: bool) -> str | None:
    """Return the block message for these adds, or ``None`` to allow them."""
    if not adds:
        return None
    if first_in_session:
        return _LOAD_SKILL
    if any(not add.lock_only for add in adds):
        return _LOCK_FIRST
    return None


def main() -> None:
    """Read a PreToolUse payload on stdin; exit 2 to block, 0 to allow."""
    try:
        payload = orjson.loads(sys.stdin.buffer.read())
    except orjson.JSONDecodeError:
        return
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return
    command = (payload.get("tool_input") or {}).get("command")
    session_id = payload.get("session_id")
    if not isinstance(command, str):
        return
    adds = package_adds(command)
    first = (
        isinstance(session_id, str)
        and bool(adds)
        and _first_in_session(session_id.replace("/", "_"))
    )
    if (message := verdict(adds, first_in_session=first)) is not None:
        print(message, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    argparse.ArgumentParser(description=__doc__).parse_args()
    main()
