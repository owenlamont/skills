#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "markdown-it-py>=4.2.0",
#     "mdit-py-plugins>=0.6.1",
#     "orjson>=3.12.0",
#     "pytest>=9.0.0",
#     "textstat>=0.7.13",
#     "typer>=0.26.7",
# ]
# ///
import pytest
from reading_cost import build_report


def words(text: str) -> int:
    return build_report(text).body.word_count


def test_blockquote_costs_nothing() -> None:
    text = "Four plain words here.\n\n> Quoted evidence the reader only skims.\n"

    assert words(text) == 4


def test_nested_blockquote_and_its_list_cost_nothing() -> None:
    text = "Four plain words here.\n\n> outer\n>\n> > inner\n>\n> - item one\n"

    assert words(text) == 4


def test_prose_after_a_blockquote_is_charged_again() -> None:
    text = "> quoted\n\nTwo words\n\n> quoted again\n\nthree more words\n"

    assert words(text) == 5


def test_blockquote_does_not_count_toward_a_section() -> None:
    quote = "\n".join(["> word"] * 80)
    report = build_report(f"## Evidence\n\nSee below.\n\n{quote}\n")

    assert [s.word_count for s in report.sections] == [2]
    assert report.warnings == []


def test_table_cells_stay_charged() -> None:
    text = "| a | b |\n|---|---|\n| one two | three |\n"

    assert words(text) == 5


def test_quoted_html_costs_nothing() -> None:
    text = "Four plain words here.\n\n> <p>quoted html words</p>\n"

    assert words(text) == 4


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "> quoted line\nthree lazy words\n", 3, id="a lazy line after a quote"
        ),
        pytest.param(
            "> outer\n> > inner\nfour lazy words here\n",
            4,
            id="a lazy line after a nested quote",
        ),
        pytest.param(
            "> quoted line\n> still quoted\n", 0, id="a continuation marked with >"
        ),
        pytest.param(
            "> quote that runs to the end", 0, id="a quote ending the file unclosed"
        ),
    ],
)
def test_a_line_without_its_own_quote_marker_is_charged(
    text: str, expected: int
) -> None:
    assert words(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("- > quoted words here\n", 0, id="a quote inside a bullet"),
        pytest.param(
            "1. > quoted words here\n", 0, id="a quote inside a numbered item"
        ),
        pytest.param(
            "- > quoted words here\n  four lazy words here\n",
            4,
            id="a lazy line in a quote inside a bullet",
        ),
        pytest.param(
            "> quoted\n![screenshot of passing checks](https://example.com/a.png)\n",
            0,
            id="a lazy image",
        ),
        pytest.param(
            "> quoted\nfour lazy words here <!-- hidden commentary words -->\n",
            4,
            id="a lazy line with an HTML comment",
        ),
        pytest.param(
            '> quoted\nThe <span title="extra hidden words">fix</span> works.\n',
            3,
            id="a lazy line with HTML attributes",
        ),
        pytest.param(
            "> quoted words here\n    four lazy words here\n",
            4,
            id="an indented lazy line stays paragraph text",
        ),
    ],
)
def test_a_lazy_line_is_charged_as_rendered(text: str, expected: int) -> None:
    assert words(text) == expected
