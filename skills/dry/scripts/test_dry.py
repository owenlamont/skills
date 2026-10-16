#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "datasketch>=1.6.5",
#     "orjson>=3.12.0",
#     "packaging>=26.0",
#     "pytest>=9.0.0",
#     "rapidfuzz>=3.14.1",
#     "tree-sitter>=0.26.0",
#     "tree-sitter-javascript>=0.25.0",
#     "tree-sitter-rust>=0.24.2",
#     "tree-sitter-typescript>=0.23.2",
#     "typer>=0.26.7",
# ]
# ///
from collections.abc import Callable, Mapping
from pathlib import Path
import shutil
import subprocess
from typing import Final

from dry import (
    Accounting,
    detect,
    FRAGMENT_KINDS,
    LanguageName,
    Report,
    RUST_BEHAVIOURAL,
    SCRIPT_BEHAVIOURAL,
    Settings,
)
import pytest
from tree_sitter import Language
import tree_sitter_javascript
import tree_sitter_rust
import tree_sitter_typescript


type MakeRepo = Callable[[str, Mapping[str, str]], Path]
type Detect = Callable[..., tuple[Report, Accounting]]

RUST_KINDS: Final = (
    "fn a() { let x = f(); } impl Foo { fn b(&self) { f(); } } "
    "trait T { fn c() { f(); } }"
)
SCRIPT_KINDS: Final = (
    "function a() { f(); } function* b() { yield 1; } "
    "class C { m() { f(); } x = () => f(); } "
    "const y = function () { f(); }; const z = { p: () => f() };"
)
CLONE: Final = {
    LanguageName.RUST: "fn {name}() {{ let x = read(); process(x); save(x); }}",
    LanguageName.TYPESCRIPT: (
        "function {name}() {{ const x = read(); process(x); save(x); }}"
    ),
    LanguageName.JAVASCRIPT: (
        "function {name}() {{ const x = read(); process(x); save(x); }}"
    ),
}
SUFFIX: Final = {
    LanguageName.RUST: ".rs",
    LanguageName.TYPESCRIPT: ".ts",
    LanguageName.JAVASCRIPT: ".js",
}


@pytest.fixture
def make_repo(tmp_path: Path) -> MakeRepo:
    git = shutil.which("git")
    assert git is not None

    def make(name: str, files: Mapping[str, str]) -> Path:
        root = tmp_path / name
        for relative, text in files.items():
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(text, encoding="utf-8")
        subprocess.run([git, "init", "-q", str(root)], check=True)  # noqa: S603
        subprocess.run([git, "-C", str(root), "add", "."], check=True)  # noqa: S603
        return root

    return make


@pytest.fixture
def run_detect() -> Detect:
    def run(
        *roots: Path,
        language: LanguageName,
        include_tests: bool = False,
        min_behavioural: int = 0,
    ) -> tuple[Report, Accounting]:
        accounting = Accounting()
        settings = Settings(
            threshold=0.85,
            include_tests=include_tests,
            min_behavioural=min_behavioural,
            min_tokens=0,
            language=language,
        )
        report = detect(roots=list(roots), settings=settings, accounting=accounting)
        return report, accounting

    return run


def reported_names(report: Report) -> set[str]:
    return {
        location.split(" ", 1)[1]
        for group in report["groups"]
        for location in group["locations"]
    }


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        pytest.param(
            LanguageName.RUST,
            RUST_KINDS,
            {"a", "b", "impl Foo", "c", "T"},
            id="rust fns, impls and traits",
        ),
        pytest.param(
            LanguageName.TYPESCRIPT,
            SCRIPT_KINDS + " abstract class A { n() { f(); } }",
            {"a", "b", "C", "m", "x", "y", "p", "A", "n"},
            id="typescript functions, classes and named arrows",
        ),
        pytest.param(
            LanguageName.JAVASCRIPT,
            SCRIPT_KINDS,
            {"a", "b", "C", "m", "x", "y", "p"},
            id="javascript functions, classes and named arrows",
        ),
    ],
)
def test_every_fragment_kind_is_reported(
    make_repo: MakeRepo,
    run_detect: Detect,
    language: LanguageName,
    source: str,
    expected: set[str],
) -> None:
    suffix = SUFFIX[language]
    root = make_repo("repo", {f"a{suffix}": source, f"b{suffix}": source})

    report, _ = run_detect(root, language=language)

    assert reported_names(report) == expected


@pytest.mark.parametrize(
    "language",
    [
        pytest.param(LanguageName.RUST, id="rust"),
        pytest.param(LanguageName.TYPESCRIPT, id="typescript"),
        pytest.param(LanguageName.JAVASCRIPT, id="javascript"),
    ],
)
def test_renamed_copy_groups_and_a_bad_parse_is_unreadable(
    make_repo: MakeRepo, run_detect: Detect, language: LanguageName
) -> None:
    suffix = SUFFIX[language]
    root = make_repo(
        "repo",
        {
            f"a{suffix}": CLONE[language].format(name="first"),
            f"b{suffix}": CLONE[language].format(name="second"),
            f"bad{suffix}": "fn broken( {",
        },
    )

    report, accounting = run_detect(root, language=language, min_behavioural=3)

    assert [group["locations"] for group in report["groups"]] == [
        [f"a{suffix}:1-1 first", f"b{suffix}:1-1 second"]
    ]
    assert accounting.unreadable == [f"bad{suffix}"]


@pytest.mark.parametrize(
    ("include_tests", "expected"),
    [
        pytest.param(False, {"c"}, id="cfg(test) items skipped by default"),
        pytest.param(True, {"a", "b", "c"}, id="cfg(test) items kept on request"),
    ],
)
def test_rust_cfg_test_items(
    make_repo: MakeRepo, run_detect: Detect, *, include_tests: bool, expected: set[str]
) -> None:
    source = (
        "#[cfg(test)] fn a() { f(); } "
        "#[cfg(test)] mod tests { fn b() { g(); } } "
        "fn c() { h(); }"
    )
    root = make_repo("repo", {"a.rs": source, "b.rs": source})

    report, _ = run_detect(
        root, language=LanguageName.RUST, include_tests=include_tests
    )

    assert reported_names(report) == expected


@pytest.mark.parametrize(
    "test_file",
    [
        pytest.param("src/test-widget.ts", id="test- prefix"),
        pytest.param("src/test_widget.ts", id="test_ prefix"),
        pytest.param("src/widget.test.ts", id="dot test infix"),
        pytest.param("src/widget.spec.ts", id="dot spec infix"),
        pytest.param("src/__tests__/widget.ts", id="__tests__ directory"),
        pytest.param("test/widget.ts", id="test directory"),
    ],
)
def test_script_test_files_are_excluded(
    make_repo: MakeRepo, run_detect: Detect, test_file: str
) -> None:
    root = make_repo("repo", {"src/widget.ts": "f();", test_file: "f();"})

    _, accounting = run_detect(root, language=LanguageName.TYPESCRIPT)

    assert (accounting.tracked, accounting.excluded_tests) == (2, 1)


def test_cross_repo_groups_leave_shared_empty(
    make_repo: MakeRepo, run_detect: Detect
) -> None:
    clone = CLONE[LanguageName.RUST]
    service = make_repo("service", {"a.rs": clone.format(name="first")})
    library = make_repo("library", {"b.rs": clone.format(name="second")})

    report, _ = run_detect(service, library, language=LanguageName.RUST)

    assert [(g["repos"], g["shared"]) for g in report["groups"]] == [
        (["library", "service"], "")
    ]


@pytest.mark.parametrize(
    ("grammars", "kinds"),
    [
        pytest.param(
            [tree_sitter_rust.language()],
            FRAGMENT_KINDS[LanguageName.RUST] | RUST_BEHAVIOURAL,
            id="rust",
        ),
        pytest.param(
            [
                tree_sitter_typescript.language_typescript(),
                tree_sitter_typescript.language_tsx(),
            ],
            FRAGMENT_KINDS[LanguageName.TYPESCRIPT] | SCRIPT_BEHAVIOURAL,
            id="typescript and tsx",
        ),
        pytest.param(
            [tree_sitter_javascript.language()],
            FRAGMENT_KINDS[LanguageName.JAVASCRIPT] | SCRIPT_BEHAVIOURAL,
            id="javascript",
        ),
    ],
)
def test_configured_node_kinds_exist_in_the_grammar(
    grammars: list[object], kinds: frozenset[str]
) -> None:
    known = [
        {
            Language(grammar).node_kind_for_id(index)
            for index in range(Language(grammar).node_kind_count)
        }
        for grammar in grammars
    ]

    assert [kinds - names for names in known] == [set()] * len(grammars)
