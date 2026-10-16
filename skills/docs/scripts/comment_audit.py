#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gitpython>=3.1.50",
#     "markdown-it-py>=4.2.0",
#     "pygments>=2.21.0",
#     "typer>=0.26.7",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///
"""Audit the comments and docstrings a diff adds, and pass or fail each one."""

import ast
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import io
from pathlib import Path
import re
import sys
from types import MappingProxyType
from typing import Annotated, Any, Final

import git
from markdown_it import MarkdownIt
from markdown_it.token import Token
from pygments.lexers import get_lexer_for_filename
from pygments.token import Comment, String
from pygments.util import ClassNotFound
import typer


@dataclass(frozen=True, slots=True, kw_only=True)
class _Language:
    """Where one language departs from what a Pygments comment token already says.

    A lexer marks most languages' comments as `Comment` and nothing else is needed, so
    every field here is an exception: `doc_token_types` for a lexer that puts doc
    comments outside `Comment` altogether, `doc_prefixes` for one that lexes them as
    ordinary block comments, and `docstrings_from_ast` where a parser reads them
    instead.
    """

    doc_token_types: tuple[Any, ...] = ()
    doc_prefixes: tuple[str, ...] = ()
    docstrings_from_ast: bool = False


_PLAIN: Final = _Language()
_RUST: Final = _Language(doc_token_types=(String.Doc,))
_JSDOC: Final = _Language(doc_prefixes=("/**",))
_PYTHON: Final = _Language(docstrings_from_ast=True)
# An allowlist, so a lexer recognising a data or prose file cannot sweep it in.
_LANGUAGES: Final[Mapping[str, _Language]] = MappingProxyType(
    {
        ".bash": _PLAIN,
        ".cjs": _JSDOC,
        ".go": _PLAIN,
        ".hcl": _PLAIN,
        ".js": _JSDOC,
        ".jsx": _JSDOC,
        ".mjs": _JSDOC,
        ".py": _PYTHON,
        ".pyi": _PYTHON,
        ".rs": _RUST,
        ".sh": _PLAIN,
        ".sql": _PLAIN,
        ".tf": _PLAIN,
        ".toml": _PLAIN,
        ".ts": _JSDOC,
        ".tsx": _JSDOC,
        ".yaml": _PLAIN,
        ".yml": _PLAIN,
    }
)
_NAMED_LANGUAGES: Final[Mapping[str, _Language]] = MappingProxyType(
    {"Makefile": _PLAIN}
)
_DEFAULT_BASE: Final = "origin/main"
# A hunk header names the added side as `+<start>[,<count>]`.
_HUNK: Final = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
# A shebang, encoding declaration or lint directive is machine-read, not prose; the
# shebang gets its own branch so a Rust `//!` inner doc comment is not read as one.
_DIRECTIVE: Final = re.compile(
    r"^\s*(?:#!"
    r"|(?:#|//|/\*)\s*"
    r"(?:-\*-|type:|noqa|ruff:|mypy:|pyright:|ty:|fmt:|isort:|nosec|pylint:"
    r"|eslint|biome-ignore|prettier-ignore|@ts-|nosemgrep"
    r"|shellcheck|go:|golangci|tflint-ignore|checkov:))"
)
# PEP 723 inline metadata is a dependency declaration the runner parses, not commentary.
_PEP723_OPEN: Final = re.compile(r"^# /// [a-zA-Z0-9-]+\s*$")
_PEP723_CLOSE: Final = re.compile(r"^# ///\s*$")
# Merging joins a doc-comment run, and the pieces a lexer splits one block comment into.
_MERGEABLE: Final[tuple[Any, ...]] = (Comment.Multiline, String.Doc)
_COMMENT_OPEN: Final = re.compile(r"^\s*(?:///|//!|//|/\*[*!]?|\*(?=\s|$)|#|--)\s*")
_COMMENT_CLOSE: Final = re.compile(r"\s*\*/\s*$")
# Comment prose is read as CommonMark, so code spans and list items are what render.
_MARKDOWN: Final = MarkdownIt("commonmark")
# A terminator, optional closing punctuation, then the start of something capitalised.
_SENTENCE_BREAK: Final = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9(\[\"'])")
_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    {"al.", "approx.", "ca.", "cf.", "e.g.", "etc.", "fig.", "i.e.", "no.", "vs."}
)
_COMMENT_RULE: Final = "comment — keep it only for an unavoidable smell you can name"
_DOC_RULE: Final = (
    "doc comment — keep it only where it carries semantics the signature does not"
)


class Verdict(StrEnum):
    """What the audit concluded about one added comment or docstring."""

    # The one call this script can make without the `docs` skill's judgement.
    FAIL = "FAIL"
    CHECK = "CHECK"


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """One added comment or docstring line the audit has something to say about."""

    path: str
    line: int
    verdict: Verdict
    rule: str
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _CommentRun:
    """One own-line comment, or a stack of adjacent ones, and the prose it carries.

    `prose_lines` holds its lines with their comment markers stripped and blank ones
    dropped, so a run reads as the sentences it carries rather than as source lines.
    """

    first: int
    last: int
    is_doc: bool
    prose_lines: tuple[str, ...]


def _numstat_paths(fields: Sequence[str]) -> list[str]:
    """The head-side path of each file a `--numstat -z` block covers.

    A rename spans three fields — counts with an empty path, source, destination — and
    the destination is the side the patch's hunks number.
    """
    paths: list[str] = []
    index = 0
    while index < len(fields):
        path = fields[index].split("\t", 2)[2]
        if path:
            paths.append(path)
            index += 1
        else:
            paths.append(fields[index + 2])
            index += 3
    return paths


def _added_lines(git_repo: git.Repo, base: str) -> dict[str, set[int]]:
    """Map each changed file to the head-side line numbers the diff adds.

    Paths come from a `--numstat -z` run of its own, which lists the files in the order
    the patch emits them: a patch header is C-quoted for a non-ASCII, quote or
    backslash path, tab-terminated for one holding a space, and unprefixed under
    `diff.noprefix`. Asking one run for both would mean splitting patch text on NUL,
    which a removed line can itself hold where `.gitattributes` forces a binary file
    through the textual diff. At `-U0` every hunk header counts its own added lines, so
    no `+` line is read.
    """
    fields = git_repo.git.diff("--numstat", "-z", "--merge-base", base).split("\0")
    paths = iter(_numstat_paths([field for field in fields if field]))
    added: dict[str, set[int]] = defaultdict(set)
    path = ""
    for line in git_repo.git.diff("-U0", "--merge-base", base).splitlines():
        if line.startswith("diff --git "):
            path = next(paths, "")
        elif hunk := _HUNK.match(line):
            start = int(hunk.group(1))
            added[path] |= set(range(start, start + int(hunk.group(2) or 1)))
    return {path: numbers for path, numbers in added.items() if path and numbers}


def _language_for(file: Path) -> _Language | None:
    """The language record for a file the audit reads, or None when it reads none."""
    language = _LANGUAGES.get(file.suffix)
    if language is None:
        return _NAMED_LANGUAGES.get(file.name)
    return language


def _lines_beyond_default_base(
    git_repo: git.Repo, added: dict[str, set[int]]
) -> dict[str, int]:
    """Per audited file, how many lines an `origin/main` base would not have covered.

    Both diffs share the head side, so the line numbers are comparable. Counts only
    the files the audit reads, and is empty where the base covers no more or where
    `origin/main` fails to resolve.
    """
    try:
        from_default = _added_lines(git_repo, _DEFAULT_BASE)
    except git.GitCommandError:
        return {}
    return {
        path: beyond
        for path, line_numbers in added.items()
        if _language_for(Path(path)) is not None
        and (beyond := len(line_numbers - from_default.get(path, set())))
    }


def _is_comment_token(token_type: Any, language: _Language) -> bool:
    """Whether a token is commentary the audit reads.

    Excludes the preprocessor classes, which carry a Rust attribute or a C directive
    rather than prose, and admits the token types a language puts its doc comments in.
    """
    if token_type in Comment.Preproc or token_type in Comment.PreprocFile:
        return False
    return token_type in Comment or any(
        token_type in doc_type for doc_type in language.doc_token_types
    )


def _prose_lines(text: str) -> tuple[str, ...]:
    """A comment's lines with their markers stripped and the blank ones dropped."""
    stripped = (
        _COMMENT_OPEN.sub("", _COMMENT_CLOSE.sub("", line)).strip()
        for line in text.splitlines()
    )
    return tuple(line for line in stripped if line)


def _sentence_count(prose_lines: Sequence[str]) -> int:
    """How many sentences a comment carries; a wrap adds none, a list item adds one.

    Code is blanked first, since a backticked identifier or version number holds
    periods that end no sentence. The placeholder is capitalised so a sentence opening
    with one still reads as a break, and a terminator closing a known abbreviation does
    not. Counts at least one, for prose with no terminator at all.
    """
    tokens = _MARKDOWN.parse("\n".join(prose_lines))
    joined = " ".join(
        _inline_prose(token) if token.type == "inline" else token.content
        for token in tokens
        if token.type in {"inline", "html_block"}
    )
    sentences = 1 + sum(
        1
        for match in _SENTENCE_BREAK.finditer(joined)
        if not _ends_with_abbreviation(joined[: match.start()])
    )
    items = sum(1 for token in tokens if token.type == "list_item_open")
    return max(sentences, items)


def _inline_prose(token: Token) -> str:
    """An inline run's text, with each code span read as the word `Code`."""
    parts: list[str] = []
    for child in token.children or ():
        match child.type:
            case "code_inline":
                parts.append("Code")
            case "softbreak" | "hardbreak":
                parts.append(" ")
            case "text" | "html_inline":
                parts.append(child.content)
    return "".join(parts)


def _ends_with_abbreviation(text: str) -> bool:
    words = text.rsplit(maxsplit=1)
    return bool(words) and words[-1].lower().lstrip("([\"'") in _ABBREVIATIONS


def _comment_runs(
    path: str, source: str, language: _Language
) -> list[_CommentRun] | None:
    """Own-line comments, adjacent ones joined into a run; None when no lexer fits.

    A real lexer is what keeps a `#` or `//` inside a string, heredoc or template
    literal from reading as a comment, which line matching cannot do. A run is the unit
    the one-sentence rule applies to, so a sentence wrapped over three `//` lines is one
    comment and three unrelated ones stacked together are one comment of three.
    """
    try:
        lexer = get_lexer_for_filename(path)
    except ClassNotFound:
        return None
    metadata = _pep723_lines(source.splitlines())
    runs: list[_CommentRun] = []
    for index, token_type, value in _merged_comment_tokens(
        lexer.get_tokens_unprocessed(source)
    ):
        if not _is_comment_token(token_type, language):
            continue
        text = value.strip()
        if not text:
            continue
        # A lexer may fold surrounding whitespace into the token value.
        start_index = index + len(value) - len(value.lstrip())
        line_start = source.rfind("\n", 0, start_index) + 1
        if source[line_start:start_index].strip() and "\n" not in text:
            continue  # a one-line trailing comment annotates its line; not narrative
        if _DIRECTIVE.match(text):
            continue
        first = source.count("\n", 0, start_index) + 1
        last = first + text.count("\n")
        if metadata & set(range(first, last + 1)):
            continue
        is_doc = text.startswith(language.doc_prefixes) or any(
            token_type in doc_type for doc_type in language.doc_token_types
        )
        _append_run(
            runs,
            _CommentRun(
                first=first, last=last, is_doc=is_doc, prose_lines=_prose_lines(text)
            ),
        )
    return runs


def _append_run(runs: list[_CommentRun], run: _CommentRun) -> None:
    """Add a comment to the list, joining it onto the run it continues."""
    previous = runs[-1] if runs else None
    if (
        previous is not None
        and previous.is_doc == run.is_doc
        and run.first == previous.last + 1
    ):
        runs[-1] = _CommentRun(
            first=previous.first,
            last=run.last,
            is_doc=run.is_doc,
            prose_lines=previous.prose_lines + run.prose_lines,
        )
    else:
        runs.append(run)


def _merged_comment_tokens(
    tokens: Iterable[tuple[int, Any, str]],
) -> Iterator[tuple[int, Any, str]]:
    """Yield the token stream with adjacent pieces of one comment joined into one.

    Some lexers emit a `/* ... */` comment as several tokens, and a Rust doc comment as
    one per line, which would otherwise read as a run of separate comments rather than
    as the single one the source holds.
    """
    pending: tuple[int, Any, str] | None = None
    for index, token_type, value in tokens:
        if pending is not None:
            start, kind, text = pending
            if token_type is kind and index == start + len(text):
                pending = (start, kind, text + value)
                continue
            yield pending
            pending = None
        if any(token_type is mergeable for mergeable in _MERGEABLE):
            pending = (index, token_type, value)
        else:
            yield index, token_type, value
    if pending is not None:
        yield pending


def _pep723_lines(lines: list[str]) -> set[int]:
    """Line numbers of any PEP 723 inline-metadata block, which the runner parses."""
    span: set[int] = set()
    start: int | None = None
    for number, line in enumerate(lines, start=1):
        if start is None and _PEP723_OPEN.match(line):
            start = number
        elif start is not None and _PEP723_CLOSE.match(line):
            span |= set(range(start, number + 1))
            start = None
    return span


def _audit_comments(
    path: str, source: str, added: set[int], runs: Iterable[_CommentRun]
) -> list[Finding]:
    """Report each added comment against the rule its kind has to clear."""
    lines = source.splitlines()
    findings: list[Finding] = []
    for run in runs:
        covered = added & set(range(run.first, run.last + 1))
        if not covered:
            continue
        anchor = min(covered)
        findings.append(
            _run_finding(
                path=path,
                run=run,
                anchor=anchor,
                text=lines[anchor - 1].strip(),
                added_count=len(covered),
            )
        )
    return findings


def _run_finding(
    *, path: str, run: _CommentRun, anchor: int, text: str, added_count: int
) -> Finding:
    """A comment carrying more than one sentence FAILs; every other one is a CHECK."""
    span = run.last - run.first + 1
    if run.is_doc:
        rule = _DOC_RULE
        if span > 1:
            rule = (
                f"doc comment at line {run.first} spans {span} lines, "
                f"{added_count} added — keep only the semantics the signature does not "
                "carry"
            )
        return Finding(
            path=path, line=anchor, verdict=Verdict.CHECK, rule=rule, text=text
        )
    sentences = _sentence_count(run.prose_lines)
    if sentences > 1:
        return Finding(
            path=path,
            line=anchor,
            verdict=Verdict.FAIL,
            rule=f"comment at line {run.first} carries {sentences} sentences over "
            f"{span} line(s) — a comment is one sentence; {added_count} added",
            text=text,
        )
    return Finding(
        path=path, line=anchor, verdict=Verdict.CHECK, rule=_COMMENT_RULE, text=text
    )


def _docstring_nodes(tree: ast.Module) -> list[tuple[str, ast.Constant, int]]:
    """Every docstring in the module, tagged with the kind of node holding it."""
    found: list[tuple[str, ast.Constant, int]] = []
    for node in ast.walk(tree):
        match node:
            case ast.Module():
                kind = "module"
            case ast.ClassDef():
                kind = "class"
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                kind = "function"
            case _:
                continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            span = (first.value.end_lineno or first.value.lineno) - first.value.lineno
            found.append((kind, first.value, span + 1))
    return found


def _audit_docstrings(path: str, source: str, added: set[int]) -> list[Finding]:
    """Report each added docstring against the rule its kind has to clear.

    Uses `ast` rather than the lexer because a lexer cannot tell a docstring from any
    other string literal, nor say which kind of node owns it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    rules = {
        "module": "module docstring — most need none; a CLI's usage goes in its "
        "command help",
        "class": "class docstring — only where the name and fields don't carry the "
        "contract",
        "function": "function docstring — delete it unless it carries semantics the "
        "signature does not",
    }
    findings: list[Finding] = []
    for kind, node, span in _docstring_nodes(tree):
        covered = added & set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        if not covered:
            continue
        anchor = min(covered)
        rule = rules[kind]
        if kind == "function" and span > 1:
            rule = (
                f"docstring at line {node.lineno} spans {span} lines, "
                f"{len(covered)} added — keep only the side effects, raised exceptions "
                "and bound inclusivity"
            )
        findings.append(
            Finding(
                path=path,
                line=anchor,
                verdict=Verdict.CHECK,
                rule=rule,
                text=lines[anchor - 1].strip(),
            )
        )
    return findings


app = typer.Typer(
    add_completion=False, context_settings={"help_option_names": ["-h", "--help"]}
)


@app.command()
def main(
    base: Annotated[
        str, typer.Option("--base", help="Base ref to diff against, e.g. origin/main.")
    ] = _DEFAULT_BASE,
    repo: Annotated[
        Path, typer.Option("--repo", help="Checkout or worktree to audit.")
    ] = Path(),
) -> None:
    """Audit every comment and docstring a diff adds, and pass or fail each one.

    Runs the `docs` skill's enumerate-and-delete pass mechanically. Comments come from a
    Pygments lexer, so a `#` or `//` inside a string, heredoc or template literal is not
    mistaken for one, and every language it lexes is covered; per-language handling adds
    only the exceptions to that, so Rust attributes are not read as comments and Rust
    `///`/`//!` and JSDoc blocks audit as doc comments rather than as prose. Python
    docstrings come from `ast`, which a lexer cannot replace because it cannot tell a
    docstring from any other string literal.

    A comment carrying more than one sentence FAILs and exits non-zero — wrapping one
    sentence over several lines does not make it two, and adjacent own-line comments
    count as the single comment they read as. A doc comment is exempt, since it ships to
    a consumer. Every other line is a CHECK: not a pass, but a line to justify against
    the `docs` skill's *Code: never narrate* — `python-code-style`'s *Comments and
    docstrings* for a Python docstring — or delete.

    The closing line names how many changed files were actually audited, since a suffix
    outside its list is skipped in silence — enumerate those by hand. A `--base` that
    reaches lines an `origin/main` base would not is reported there and above the
    findings, since those lines are already in `origin/main` and their comments belong
    to whoever wrote them.

      uv run --script comment_audit.py --repo <checkout> --base origin/main
    """
    git_repo = git.Repo(repo, search_parent_directories=True)
    # Diff paths are relative to the work tree, whatever directory was named.
    root = Path(git_repo.working_tree_dir or repo)
    added = _added_lines(git_repo, base)
    beyond = _lines_beyond_default_base(git_repo, added)
    if beyond:
        print(
            f"WARNING  --base {base} audits {sum(beyond.values())} line(s) across "
            f"{len(beyond)} file(s) that --base {_DEFAULT_BASE} would not. Those are "
            "other contributors' unless this branch is a stack; drop --base to audit "
            "only what the branch adds.\n"
        )
    findings: list[Finding] = []
    audited = 0
    for path, line_numbers in sorted(added.items()):
        file_findings = _audit_file(root / path, path, line_numbers)
        if file_findings is None:
            continue
        audited += 1
        findings.extend(file_findings)

    fails = [f for f in findings if f.verdict is Verdict.FAIL]
    checks = [f for f in findings if f.verdict is Verdict.CHECK]
    for finding in sorted(findings, key=lambda f: (f.verdict, f.path, f.line)):
        print(f"{finding.verdict}  {finding.path}:{finding.line}  {finding.rule}")
        print(f"        {finding.text[:96]}")
    over_wide_base = (
        f", over a base reaching {sum(beyond.values())} line(s) past {_DEFAULT_BASE}"
        if beyond
        else ""
    )
    print(
        f"\n{len(fails)} fail, {len(checks)} to justify, across {audited} of "
        f"{len(added)} changed file(s){over_wide_base}."
    )
    if fails:
        raise typer.Exit(1)


def _audit_file(file: Path, path: str, added: set[int]) -> list[Finding] | None:
    """Audit one changed file, or return None when it is not one this script reads."""
    language = _language_for(file)
    if language is None or not file.is_file():
        return None
    source = file.read_text(encoding="utf-8", errors="replace")
    runs = _comment_runs(path, source, language)
    if runs is None:
        return None
    findings = _audit_comments(path, source, added, runs)
    if language.docstrings_from_ast:
        findings.extend(_audit_docstrings(path, source, added))
    return findings


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()
