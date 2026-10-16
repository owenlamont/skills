"""Exercise the non-Python fragment frontends through their grammar nodes."""

from pathlib import Path
import runpy
import shutil
import subprocess

import pytest


DRY = runpy.run_path(str(Path(__file__).with_name("dry.py")))
LanguageName = DRY["LanguageName"]
Settings = DRY["Settings"]


def fragments(source: str, language: str, *, include_tests: bool = False) -> list:
    """Parse a snippet and return its fragments without the git corpus layer."""
    selected = LanguageName(language)
    suffix = (
        ".rs" if language == "rust" else ".ts" if language == "typescript" else ".js"
    )
    data = source.encode()
    tree = DRY["_parser"](selected, Path("snippet" + suffix)).parse(data).root_node
    assert not tree.has_error, tree
    settings = Settings(
        threshold=0.85,
        include_tests=include_tests,
        min_behavioural=0,
        min_tokens=0,
        language=selected,
    )
    return list(
        DRY["_tree_fragments"](
            tree=tree,
            source=data,
            label="snippet",
            language=selected,
            settings=settings,
        )
    )


@pytest.mark.parametrize(
    ("language", "source", "names"),
    [
        (
            "rust",
            "fn a() { let x = f(); } impl Foo { fn b(&self) { f(); } }",
            {"a", "b", "impl Foo"},
        ),
        ("rust", "trait T { fn a() { f(); } }", {"a", "T"}),
        (
            "typescript",
            (
                "function a() { f(); } function* b() { yield 1; } "
                "class C { m() { f(); } x = () => f(); }"
            ),
            {"a", "b", "C", "m", "x"},
        ),
        (
            "typescript",
            "abstract class C { m() { f(); } } const x = function () { f(); };",
            {"C", "m", "x"},
        ),
        (
            "javascript",
            (
                "function a() { f(); } function* b() { yield 1; } "
                "class C { m() { f(); } x = () => f(); }"
            ),
            {"a", "b", "C", "m", "x"},
        ),
        (
            "javascript",
            (
                "const x = () => f(); const y = function () { f(); }; "
                "const z = {p: () => f()};"
            ),
            {"x", "y", "p"},
        ),
    ],
)
def test_fragment_kinds(language: str, source: str, names: set[str]) -> None:
    """Every configured fragment kind must yield a named site."""
    assert names <= {fragment.name for fragment in fragments(source, language)}


def test_rust_cfg_test_excludes_items_and_modules() -> None:
    """Rust test attributes exclude direct items and nested module members."""
    source = "#[cfg(test)] fn a() { f(); } #[cfg(test)] mod tests { fn b() { f(); } } "
    source += "fn c() { f(); }"
    assert [fragment.name for fragment in fragments(source, "rust")] == ["c"]
    assert {
        fragment.name for fragment in fragments(source, "rust", include_tests=True)
    } == {"a", "b", "c"}


@pytest.mark.parametrize("language", ["rust", "typescript", "javascript"])
def test_renamed_code_normalises_identically(language: str) -> None:
    """Identifier changes leave the body token stream unchanged."""
    if language == "rust":
        source = "fn a() { let x = f(); } fn b() { let y = g(); }"
    else:
        source = "function a() { const x = f(); } function b() { const y = g(); }"
    first, second = fragments(source, language)
    assert first.tokens == second.tokens


@pytest.mark.parametrize(
    ("language", "suffix", "body"),
    [
        ("rust", ".rs", "fn {name}() {{ let x = read(); process(x); save(x); }}"),
        (
            "typescript",
            ".ts",
            "function {name}() {{ const x = read(); process(x); save(x); }}",
        ),
        (
            "javascript",
            ".js",
            "function {name}() {{ const x = read(); process(x); save(x); }}",
        ),
    ],
)
def test_duplicate_group_and_unreadable(
    tmp_path: Path, language: str, suffix: str, body: str
) -> None:
    """A tracked clone pair groups while malformed source is accounted for."""
    (tmp_path / ("a" + suffix)).write_text(body.format(name="first"), encoding="utf-8")
    (tmp_path / ("b" + suffix)).write_text(body.format(name="second"), encoding="utf-8")
    broken = "fn broken( {" if language == "rust" else "function broken( {"
    (tmp_path / ("bad" + suffix)).write_text(broken, encoding="utf-8")
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)  # noqa: S603
    subprocess.run([git, "-C", str(tmp_path), "add", "."], check=True)  # noqa: S603
    accounting = DRY["Accounting"]()
    settings = Settings(
        threshold=0.85,
        include_tests=False,
        min_behavioural=3,
        min_tokens=0,
        language=LanguageName(language),
    )
    report = DRY["detect"](roots=[tmp_path], settings=settings, accounting=accounting)
    assert report["files"] == 3
    assert len(report["unreadable"]) == 1
    assert len(report["groups"]) == 1
    assert report["groups"][0]["size"] == 2


def test_language_test_paths() -> None:
    """Script language test naming conventions are excluded by default."""
    is_test = DRY["_is_language_test_path"]
    for language in (LanguageName.TYPESCRIPT, LanguageName.JAVASCRIPT):
        assert is_test(Path("test-widget.ts"), language)
        assert is_test(Path("widget.spec.ts"), language)
        assert is_test(Path("__tests__/widget.ts"), language)
        assert not is_test(Path("src/widget.ts"), language)


@pytest.mark.parametrize("language", ["rust", "typescript", "javascript"])
def test_configured_node_types_exist_in_grammar(language: str) -> None:
    """A misspelled grammar kind must fail instead of silently matching nothing."""
    selected = LanguageName(language)
    suffix = (
        ".rs" if language == "rust" else ".ts" if language == "typescript" else ".js"
    )
    grammar = DRY["_parser"](selected, Path("snippet" + suffix)).language
    kinds = {
        grammar.node_kind_for_id(index) for index in range(grammar.node_kind_count)
    }
    behavioural = (
        DRY["_RUST_BEHAVIOURAL"] if language == "rust" else DRY["_SCRIPT_BEHAVIOURAL"]
    )
    assert DRY["_FRAGMENT_KINDS"][selected] <= kinds
    assert behavioural <= kinds


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("rust", "fn f() {} impl X { fn m(&self) {} } trait T { fn d() {} }"),
        (
            "typescript",
            (
                "function f() {} function* g() {} class C { m() {} x = () => 1; } "
                "abstract class A {} const c = class {}; const q = function() {};"
            ),
        ),
        (
            "javascript",
            (
                "function f() {} function* g() {} class C { m() {} x = () => 1; } "
                "const c = class {}; const q = function() {};"
            ),
        ),
    ],
)
def test_every_fragment_kind_produces_a_fragment(language: str, source: str) -> None:
    """Each configured kind passes the extractor on a valid snippet."""
    selected = LanguageName(language)
    suffix = (
        ".rs" if language == "rust" else ".ts" if language == "typescript" else ".js"
    )
    data = source.encode()
    tree = DRY["_parser"](selected, Path("snippet" + suffix)).parse(data).root_node
    assert not tree.has_error
    settings = Settings(
        threshold=0.85,
        include_tests=True,
        min_behavioural=0,
        min_tokens=0,
        language=selected,
    )
    stack = [tree]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if (
            DRY["_tree_fragment"](
                node=node,
                source=data,
                label="snippet",
                language=selected,
                settings=settings,
            )
            is not None
        ):
            seen.add(node.type)
    assert seen == DRY["_FRAGMENT_KINDS"][selected]
