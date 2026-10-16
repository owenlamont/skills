#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "markdown-it-py>=4.2.0",
#     "mdit-py-plugins>=0.6.1",
#     "orjson>=3.12.0",
#     "textstat>=0.7.13",
#     "typer>=0.26.7",
# ]
#
# [tool.uv]
# exclude-newer = "1 week"
# ///
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from html.parser import HTMLParser
import io
from pathlib import Path
import re
import sys
from typing import Annotated, Final

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
import orjson
import textstat
import typer


# Conservative for technical prose; the adult silent mean is ~238 wpm (Brysbaert 2019).
PROSE_WPM: Final[int] = 200
# Fenced code is skimmed, not read word-by-word; charged per line, not per word.
CODE_SECONDS_PER_LINE: Final[float] = 3.0
# Rendered as a picture: counted and reported, never charged, so it costs nothing.
_DIAGRAM_LANGUAGES: Final[frozenset[str]] = frozenset(
    {"geojson", "mermaid", "stl", "topojson"}
)

# Ceilings from hand-written bodies here: body p95, and any single section.
SUMMARY_WORD_TARGET: Final[int] = 60
SUMMARY_WORD_WARN: Final[int] = 60
SECTION_WORD_WARN: Final[int] = 60
BODY_WORD_WARN: Final[int] = 150

# The headings that name an explicit must-read summary.
_SUMMARY_HEADING: Final = re.compile(r"(summary|tl;?dr|overview)\b", re.IGNORECASE)
# Inline formatting that renders its text in place, which a comment also joins across;
# any other tag, `<br>` among them, separates the text either side of it.
_FORMATTING_TAGS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "abbr",
        "b",
        "bdi",
        "bdo",
        "cite",
        "code",
        "data",
        "del",
        "dfn",
        "em",
        "i",
        "ins",
        "kbd",
        "mark",
        "q",
        "s",
        "samp",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "time",
        "tt",
        "u",
        "var",
    }
)
# CommonMark plus the GFM extensions GitHub renders, raw HTML left on as GitHub has it.
_MARKDOWN: Final = (
    MarkdownIt("commonmark")
    .enable(["table", "strikethrough"])
    .use(tasklists_plugin)
    .use(footnote_plugin)
)


@dataclass
class CodeStats:
    """Counts of fenced code blocks and the lines inside them."""

    block_count: int
    line_count: int


@dataclass
class DiagramStats:
    """Counts of fenced diagram blocks and the lines inside them."""

    block_count: int
    line_count: int


class SummaryStatus(StrEnum):
    """Whether the document has a distinct must-read summary to budget.

    `SINGLE_SECTION` is a document of one section that declared no summary of its own,
    so the extractor would return the entire body and the budget would only ask for
    substance to be cut; it is judged on its total instead. An issue or PR *comment* is
    normally this shape, and so is a posted code review — a lead line, then bold finding
    headers — where warning that it has no lead text when every word of it is lead text
    sends the writer after a defect that isn't there.

    `MISSING` is a body carrying no visible prose at all: empty, only code or a diagram,
    or nothing outside a collapsed block, a `<summary>` caption counting as visible
    prose. A body with no headings is not `MISSING`; it is one undivided section.
    """

    MEASURED = "measured"
    SINGLE_SECTION = "single-section"
    MISSING = "missing"


@dataclass(frozen=True, slots=True, kw_only=True)
class SummarySpan:
    """A candidate must-read summary, and whether it is distinct from the whole body."""

    text: str
    distinct: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SectionMeasure:
    """One visible section's heading and the prose words under it."""

    heading: str
    word_count: int


@dataclass
class TextMeasure:
    """Reading measures for one span of prose (code already stripped out)."""

    word_count: int
    reading_seconds: float
    flesch_reading_ease: float | None


@dataclass
class Report:
    """Full reading-cost report for a document and its must-read summary."""

    body: TextMeasure
    code: CodeStats
    diagrams: DiagramStats
    code_skim_seconds: float
    total_reading_seconds: float
    summary: TextMeasure | None
    summary_status: SummaryStatus
    sections: list[SectionMeasure]
    collapsed: TextMeasure
    collapsed_block_count: int
    collapsed_code_lines: int
    collapsed_reading_seconds: float
    visible_code_lines: int
    rendered_diagram_lines: int
    warnings: list[str]


class _SegmentKind(StrEnum):
    PROSE = "prose"
    HEADING = "heading"
    DETAILS_OPEN = "details-open"


@dataclass(frozen=True, slots=True, kw_only=True)
class _Segment:
    """One run of rendered text, in document order, and whether it starts collapsed."""

    kind: _SegmentKind
    text: str
    collapsed: bool


class _TagEventKind(StrEnum):
    DATA = "data"
    START = "start"
    END = "end"
    COMMENT = "comment"


@dataclass(frozen=True, slots=True, kw_only=True)
class _TagEvent:
    kind: _TagEventKind
    value: str
    is_open: bool = False


class _TagStream(HTMLParser):
    """The text, tag and comment events of one raw-HTML fragment."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[_TagEvent] = []

    def handle_data(self, data: str) -> None:
        self.events.append(_TagEvent(kind=_TagEventKind.DATA, value=data))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        is_open = any(name == "open" for name, _ in attrs)
        self.events.append(
            _TagEvent(kind=_TagEventKind.START, value=tag, is_open=is_open)
        )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # HTML has no self-closing `<details/>`; a browser opens the element.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        self.events.append(_TagEvent(kind=_TagEventKind.END, value=tag))

    def handle_comment(self, data: str) -> None:
        self.events.append(_TagEvent(kind=_TagEventKind.COMMENT, value=data))


def _discloses(fragment: str) -> bool:
    return any(
        event.kind in {_TagEventKind.START, _TagEventKind.END}
        and event.value in {"details", "summary"}
        for event in _tag_events(fragment)
    )


def _joins_text(fragment: str) -> bool:
    return all(
        event.kind is _TagEventKind.COMMENT or event.value in _FORMATTING_TAGS
        for event in _tag_events(fragment)
        if event.kind is not _TagEventKind.DATA
    )


def _tag_events(fragment: str) -> list[_TagEvent]:
    stream = _TagStream()
    stream.feed(fragment)
    stream.close()
    return stream.events


@dataclass(slots=True, kw_only=True)
class _Walker:
    """Document-order state over the Markdown token stream.

    `stack` holds one entry per open `<details>`, True where that block hides its
    contents. Content is collapsed while ANY enclosing block hides, so an `open` block
    inside a closed one is still not on screen. An unclosed `<details>` collapses to end
    of document, matching how GitHub renders it.
    """

    segments: list[_Segment] = field(default_factory=list)
    stack: list[bool] = field(default_factory=list)
    in_caption: bool = False
    preformatted: list[str] | None = None
    collapsed_block_count: int = 0
    code: CodeStats = field(default_factory=lambda: CodeStats(0, 0))
    diagrams: DiagramStats = field(default_factory=lambda: DiagramStats(0, 0))
    visible_code_lines: int = 0
    collapsed_code_lines: int = 0
    quote_depth: int = 0
    source_lines: Sequence[str] = ()

    def emit(self, kind: _SegmentKind, text: str) -> None:
        """Record a run of text; a caption is on screen while its enclosers are open."""
        if text.strip():
            enclosing = self.stack[:-1] if self.in_caption else self.stack
            self.segments.append(
                _Segment(kind=kind, text=text, collapsed=any(enclosing))
            )

    def html(self, fragment: str) -> None:
        """Apply a raw-HTML fragment's tags, joining text across inline formatting."""
        held: list[str] = []
        for event in _tag_events(fragment):
            match event:
                case _TagEvent(kind=_TagEventKind.DATA) if (
                    self.preformatted is not None
                ):
                    self.preformatted.append(event.value)
                case _TagEvent(kind=_TagEventKind.DATA):
                    held.append(event.value)
                case _TagEvent(kind=_TagEventKind.COMMENT):
                    continue
                case _TagEvent(value=tag) if tag in _FORMATTING_TAGS:
                    continue
                case _:
                    self.emit(_SegmentKind.PROSE, "".join(held))
                    held.clear()
                    self.tag(event)
        self.emit(_SegmentKind.PROSE, "".join(held))

    def tag(self, event: _TagEvent) -> None:
        """Apply one structural tag: a disclosure, a caption, or `<pre>` code."""
        match event:
            case _TagEvent(kind=_TagEventKind.START, value="pre"):
                self.preformatted = []
            case _TagEvent(kind=_TagEventKind.END, value="pre") if (
                self.preformatted is not None
            ):
                code = "".join(self.preformatted).strip("\n")
                self.charge_code(len(code.splitlines()))
                self.preformatted = None
            case _TagEvent(value="summary"):
                self.in_caption = event.kind is _TagEventKind.START
            case _TagEvent(kind=_TagEventKind.START, value="details"):
                self.open_details(hides=not event.is_open)
            case _TagEvent(kind=_TagEventKind.END, value="details"):
                if self.stack:
                    self.stack.pop()
                # A caption cannot outlive its block: an unclosed <summary> stops.
                self.in_caption = False

    def open_details(self, *, hides: bool) -> None:
        if hides and not any(self.stack):
            self.collapsed_block_count += 1
        self.segments.append(
            _Segment(kind=_SegmentKind.DETAILS_OPEN, text="", collapsed=any(self.stack))
        )
        self.stack.append(hides)

    def inline(self, token: Token, kind: _SegmentKind) -> None:
        """Keep an inline run's rendered text as prose, applying any raw HTML inside it.

        Only what GitHub displays is counted: a link's target, an image, a task-list
        checkbox, emphasis markers and every inline tag drop out, and a line break or
        a block tag separates words. A heading stays one segment, as it renders.
        """
        held: list[str] = []
        for child in token.children or ():
            match child.type:
                case "html_inline" if _discloses(child.content):
                    if kind is _SegmentKind.PROSE:
                        self.emit(kind, "".join(held))
                        held.clear()
                    self.html(child.content)
                case "html_inline" if not _joins_text(child.content):
                    held.append("\n")
                case "text" | "code_inline":
                    held.append(child.content)
                case "softbreak" | "hardbreak":
                    held.append("\n")
        self.emit(kind, "".join(held))

    def fence(self, token: Token) -> None:
        """Tally a code block; a diagram fence is counted apart and never charged."""
        lines = len(token.content.splitlines())
        words = token.info.split(maxsplit=1)
        if token.type == "fence" and words and words[0].lower() in _DIAGRAM_LANGUAGES:
            self.diagrams.block_count += 1
            self.diagrams.line_count += lines
            return
        self.charge_code(lines)

    def charge_code(self, lines: int) -> None:
        self.code.block_count += 1
        self.code.line_count += lines
        if any(self.stack):
            self.collapsed_code_lines += lines
        else:
            self.visible_code_lines += lines

    def lazy_lines(self, token: Token) -> None:
        """Charge, as rendered, the quoted lines that carry no `>` of their own.

        CommonMark's lazy continuation renders them inside the quote, but they are the
        author's prose, so a forgotten blank line does not make them free. A line is
        lazy when the parser stripped no marker from it: its source matches its content.
        """
        if token.map is None:
            return
        source = self.source_lines[token.map[0] : token.map[1]]
        lazy = [
            content
            for line, content in zip(source, token.content.split("\n"), strict=False)
            if content.strip() and line.strip() == content.strip()
        ]
        if lazy:
            rendered = _Walker()
            rendered.walk(_MARKDOWN.parseInline("\n".join(lazy)))
            self.emit(_SegmentKind.PROSE, _prose(rendered.segments))

    def walk(self, tokens: Sequence[Token]) -> None:
        heading = False
        for token in tokens:
            match token.type:
                case "blockquote_open":
                    self.quote_depth += 1
                case "blockquote_close":
                    self.quote_depth -= 1
                case "inline" if self.quote_depth:
                    self.lazy_lines(token)
                case "html_block" if self.quote_depth:
                    continue
                case "fence" | "code_block":
                    self.fence(token)
                case "html_block":
                    self.html(token.content)
                case "heading_open":
                    # A section is a top-level ATX heading; setext reads as prose.
                    heading = token.level == 0 and token.markup.startswith("#")
                case "heading_close":
                    heading = False
                case "inline":
                    kind = _SegmentKind.HEADING if heading else _SegmentKind.PROSE
                    self.inline(token, kind)
        if self.preformatted is not None:
            # An unclosed `<pre>` runs to the end of the document, as GitHub renders it.
            self.tag(_TagEvent(kind=_TagEventKind.END, value="pre"))


def _prose(segments: Iterable[_Segment]) -> str:
    """The text a set of segments carries, headings included, one run per line."""
    return "\n".join(
        s.text for s in segments if s.kind is not _SegmentKind.DETAILS_OPEN
    )


def _until_heading(segments: Sequence[_Segment], start: int) -> str:
    """The prose from ``start`` up to the next heading or the end of the document."""
    body: list[_Segment] = []
    for segment in segments[start:]:
        if segment.kind is _SegmentKind.HEADING:
            break
        body.append(segment)
    return _prose(body)


def _count_words(text: str) -> int:
    """Count whitespace-delimited tokens that contain at least one alphanumeric."""
    return sum(1 for token in text.split() if any(char.isalnum() for char in token))


def _measure(text: str) -> TextMeasure:
    """Measure word count, reading time, and Flesch readability of prose.

    Readability is None when there are no words. Flesch Reading Ease (via
    ``textstat``) is higher for plainer text: 60-70 is plain English, below 30
    is dense/academic.
    """
    word_count = _count_words(text)
    reading_seconds = word_count / PROSE_WPM * 60
    flesch: float | None = None
    if word_count:
        # textstat binds its functions dynamically, so ty cannot resolve them.
        ease = textstat.flesch_reading_ease(text)  # ty: ignore[unresolved-attribute]
        flesch = round(ease, 1)
    return TextMeasure(
        word_count=word_count,
        reading_seconds=reading_seconds,
        flesch_reading_ease=flesch,
    )


def _visible_sections(visible: Sequence[_Segment]) -> list[SectionMeasure]:
    """Each heading's visible prose, and any lead text above the first, as sections.

    The heading itself is not counted, matching how the summary is measured. A document
    with no heading has no sections: it is one undivided body, judged on its total. Only
    a top-level ATX heading counts; a setext underline reads as prose.
    """
    headings = [i for i, s in enumerate(visible) if s.kind is _SegmentKind.HEADING]
    if not headings:
        return []
    sections: list[SectionMeasure] = []
    lead = _prose(visible[: headings[0]])
    if lead.strip():
        sections.append(SectionMeasure(heading="(lead)", word_count=_count_words(lead)))
    sections.extend(
        SectionMeasure(
            heading=visible[index].text.strip(),
            word_count=_count_words(_until_heading(visible, index + 1)),
        )
        for index in headings
    )
    return sections


def _extract_summary(
    visible: Sequence[_Segment], segments: Sequence[_Segment]
) -> SummarySpan | None:
    """Return the must-read summary span, or None when the body has no visible prose.

    Tried in order: an explicit ``## Summary`` / ``TL;DR`` / ``Overview`` section; any
    lead text above the first heading; otherwise the first heading's own section, which
    is where a repo PR template puts the must-read part (one typically opens with a
    ``# What changed`` heading and defines no section called "Summary"). A document
    with no headings at all falls back to the lead text before its first ``<details>``.

    Visible text is searched, so an optional ``## Summary`` is never reported as
    mandatory. Where nothing distinct is found, the whole visible body is returned with
    ``distinct`` False, and the caller reports no summary rather than scoring the entire
    document against the summary budget.
    """
    headings = [i for i, s in enumerate(visible) if s.kind is _SegmentKind.HEADING]
    explicit = next(
        (i for i in headings if _SUMMARY_HEADING.match(visible[i].text.strip())), None
    )
    if explicit is not None:
        return SummarySpan(text=_until_heading(visible, explicit + 1), distinct=True)
    if headings:
        lead = _prose(visible[: headings[0]])
        if lead.strip():
            return SummarySpan(text=lead, distinct=True)
        # Without a second heading there is nothing else for the first to summarise.
        return SummarySpan(
            text=_until_heading(visible, headings[0] + 1), distinct=len(headings) > 1
        )
    first_details = next(
        (i for i, s in enumerate(segments) if s.kind is _SegmentKind.DETAILS_OPEN), None
    )
    if first_details is not None and _prose(segments[:first_details]).strip():
        return SummarySpan(text=_prose(segments[:first_details]), distinct=True)
    whole = _prose(visible)
    return SummarySpan(text=whole, distinct=False) if whole.strip() else None


def _budget_warnings(
    *,
    body: TextMeasure,
    summary: TextMeasure | None,
    summary_status: SummaryStatus,
    sections: list[SectionMeasure],
) -> list[str]:
    """The ceilings a document breaks, one line each.

    Wherever a heading makes a section, every section carries the ceiling, the summary
    among them, so the summary gets no warning of its own there. A body with no heading
    is one undivided piece judged on its total, and only its summary can warn.
    """
    warnings: list[str] = []
    if summary_status is SummaryStatus.MISSING:
        warnings.append(
            "Nothing to summarise — the body has no visible prose. "
            "Open with the must-read summary."
        )
    elif sections:
        warnings.extend(
            f"Section '{section.heading}' is {section.word_count} words (ceiling "
            f"{SECTION_WORD_WARN}); drop a whole bullet rather than tightening."
            for section in sections
            if section.word_count > SECTION_WORD_WARN
        )
    elif summary is not None and summary.word_count > SUMMARY_WORD_WARN:
        warnings.append(
            f"Summary is {summary.word_count} words "
            f"(warn above {SUMMARY_WORD_WARN}, target <= {SUMMARY_WORD_TARGET})."
        )
    if body.word_count > BODY_WORD_WARN:
        warnings.append(
            f"Body is {body.word_count} prose words (warn above {BODY_WORD_WARN}); "
            "delete a whole section rather than tightening sentences."
        )
    return warnings


def build_report(markdown_text: str) -> Report:
    """Build the full reading-cost report for a Markdown document.

    The document is parsed as CommonMark with GFM tables, so what counts as code, a
    heading or a disclosure is what GitHub renders as one. Summary metrics are computed
    on prose alone, so fenced code inside the must-read summary is excluded from the
    summary's word budget and counted only in the document's code-skim estimate.

    ``body`` measures only what the reader is forced to read: collapsed ``<details>``
    content is measured separately and excluded from the body budget and the headline
    total, since expanding it is the reader's choice. Fenced diagrams are excluded from
    both as well, wherever they sit: they are counted and reported, never charged. An
    HTML comment is invisible on GitHub, so nothing inside one is counted at all.

    A leading byte-order mark is dropped: GitHub discards one, but it sits in front of
    an opening fence delimiter and would stop that fence being recognised at all.
    """
    source = markdown_text.removeprefix("﻿")
    walker = _Walker(source_lines=source.splitlines())
    walker.walk(_MARKDOWN.parse(source))
    visible = [s for s in walker.segments if not s.collapsed]
    body = _measure(_prose(visible))
    collapsed = _measure(_prose(s for s in walker.segments if s.collapsed))
    code_skim_seconds = walker.visible_code_lines * CODE_SECONDS_PER_LINE
    collapsed_reading_seconds = (
        collapsed.reading_seconds + walker.collapsed_code_lines * CODE_SECONDS_PER_LINE
    )

    span = _extract_summary(visible, walker.segments)
    summary: TextMeasure | None = None
    if span is None:
        summary_status = SummaryStatus.MISSING
    elif span.distinct:
        summary_status = SummaryStatus.MEASURED
        summary = _measure(span.text)
    else:
        summary_status = SummaryStatus.SINGLE_SECTION

    sections = _visible_sections(visible)
    warnings = _budget_warnings(
        body=body, summary=summary, summary_status=summary_status, sections=sections
    )

    return Report(
        body=body,
        code=walker.code,
        diagrams=walker.diagrams,
        code_skim_seconds=code_skim_seconds,
        total_reading_seconds=body.reading_seconds + code_skim_seconds,
        summary=summary,
        summary_status=summary_status,
        sections=sections,
        collapsed=collapsed,
        collapsed_block_count=walker.collapsed_block_count,
        collapsed_code_lines=walker.collapsed_code_lines,
        collapsed_reading_seconds=collapsed_reading_seconds,
        visible_code_lines=walker.visible_code_lines,
        rendered_diagram_lines=walker.diagrams.line_count,
        warnings=warnings,
    )


def _format_duration(seconds: float) -> str:
    """Render a duration as a compact human string, e.g. ``2m 30s`` or ``45s``."""
    whole_seconds = round(seconds)
    minutes, remainder = divmod(whole_seconds, 60)
    return f"{minutes}m {remainder:02d}s" if minutes else f"{remainder}s"


def _format_report(report: Report) -> str:
    """Render a report as a scannable plain-text block, headline first."""
    body = report.body
    code = report.code
    total = _format_duration(report.total_reading_seconds)
    prose_time = _format_duration(body.reading_seconds)
    code_time = _format_duration(report.code_skim_seconds)
    lines = [
        f"Reading cost: ~{total}  ({prose_time} prose + {code_time} code)",
        "",
        f"  Prose words : {body.word_count}",
        # The visible count, so this and the headline describe the same charge.
        (
            f"  Code        : {code.block_count} block(s), "
            f"{report.visible_code_lines} line(s) to read"
        ),
    ]
    if report.diagrams.block_count:
        lines.append(
            f"  Diagrams    : {report.diagrams.block_count} block(s), "
            f"{report.rendered_diagram_lines} line(s), not counted"
        )
    if report.collapsed_block_count:
        collapsed_time = _format_duration(report.collapsed_reading_seconds)
        collapsed_code = (
            f", {report.collapsed_code_lines} code line(s)"
            if report.collapsed_code_lines
            else ""
        )
        lines.append(
            f"  Collapsed   : {report.collapsed.word_count} words{collapsed_code} in "
            f"{report.collapsed_block_count} block(s), ~{collapsed_time} if expanded "
            f"(not counted above)"
        )
    if body.flesch_reading_ease is not None:
        ease = body.flesch_reading_ease
        lines.append(f"  Readability : {ease} Flesch ease (higher is plainer)")
    if report.summary is not None:
        summary = report.summary
        within = "within" if summary.word_count <= SUMMARY_WORD_TARGET else "over"
        summary_time = _format_duration(summary.reading_seconds)
        lines.append(
            f"  Summary     : {summary.word_count} words, ~{summary_time} "
            f"({within} the {SUMMARY_WORD_TARGET}-word target)"
        )
    elif report.summary_status is SummaryStatus.SINGLE_SECTION:
        lines.append(
            "  Summary     : n/a — nothing distinct from the body to summarise"
        )
    if len(report.sections) > 1:
        largest = max(report.sections, key=lambda section: section.word_count)
        lines.append(
            f"  Sections    : {len(report.sections)}, largest {largest.word_count} "
            f"words ({largest.heading}); ceiling {SECTION_WORD_WARN} each"
        )
    if report.warnings:
        lines.append("")
        lines.extend(f"  ! {warning}" for warning in report.warnings)
    return "\n".join(lines)


def _read_input(path: str | None) -> str:
    """Read the document from a file path, or from stdin when path is None or ``-``."""
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


app = typer.Typer(
    add_completion=False, context_settings={"help_option_names": ["-h", "--help"]}
)


@app.command()
def main(
    path: Annotated[
        str | None,
        typer.Argument(help="Markdown file to measure; omit or use '-' for stdin."),
    ] = None,
    # path stays positional for the Typer CLI; the * makes the flags keyword-only.
    *,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the report as JSON.")
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Exit non-zero when any budget warning fires."),
    ] = False,
) -> None:
    """Measure the human reading cost of a Markdown document and report it.

    A static, deterministic estimate of how long a person spends reading a PR
    description, issue, or other Markdown — so agent-authored prose can be kept
    within a budget a fatigued reviewer can actually absorb. Prose and code
    are measured separately, and any must-read summary (a `## Summary` / `TL;DR`
    section, or the lead text before the first `<details>` block) is scored against
    a tighter budget than the whole body, and every ATX heading's visible prose is held
    to the same per-section ceiling (a setext underline is read as prose). A
    single-section document that declares no
    `## Summary` — an issue or PR comment — has none distinct from itself, so none is
    reported and the total is the figure to judge. Content inside a collapsed
    `<details>` block — its prose and any code fenced within it — is reported on its
    own line and left out of the headline and the body budget, since the reader
    expands it only if they choose to. A fenced diagram (`mermaid`, `geojson`,
    `topojson`, `stl`) is reported and left out too, wherever it sits.

    Reads raw Markdown from a file or stdin, so it points at any GitHub text via `gh`:
      uv run --script reading_cost.py PATH
      gh pr view 123 --json body -q .body | uv run --script reading_cost.py -
      gh issue view 45 --json body -q .body | uv run --script reading_cost.py -
    """
    report = build_report(_read_input(path))
    if json_output:
        typer.echo(orjson.dumps(asdict(report), option=orjson.OPT_INDENT_2).decode())
    else:
        typer.echo(_format_report(report))
    if strict and report.warnings:
        raise typer.Exit(1)


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()
