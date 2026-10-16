---
name: python-libraries
description: Reach for this project's preferred, well-supported libraries instead of hand-rolling. Use when choosing a library for HTTP, retries, JSON, or parsing, or whenever you are about to write something the standard library or a maintained package already does.
---

# Python Libraries

Prefer well-supported libraries (and the standard library) over hand-rolled code — it is
less to maintain and less to get wrong than reinventing a solved problem.
`software-engineering` states when a dependency is *not* the better trade.

## Choosing and maintaining a dependency

- Don't add a dependency for a task the standard library handles, or one with no
  maintainer or recent release.
- When a widely used library goes unmaintained, prefer a maintained drop-in successor over
  staying on the dormant one — but confirm on PyPI that the successor exists and is
  actively released before naming it in code or docs. Don't assume a `<pkg>2` exists
  because the pattern is familiar.
- Once a repo moves off a library, ban it in `ruff.toml` so it cannot creep back, naming
  the successor in the message: `"httpx".msg = "httpx is unmaintained; use httpx2"` under
  `[lint.flake8-tidy-imports.banned-api]`. The entry does nothing unless `TID251` is
  selected (`TID` covers it), so check `select` too. A module entry fails every import of
  it, aliased or `from` alike. It cannot see a PEP 723 `dependencies` line, so a declared
  but unimported package passes.

## Don't reinvent the wheel

- Don't hand-roll retry or backoff loops — use `stamina` (it wraps `tenacity` with sane
  defaults: capped attempts, jitter, and retrying only the exceptions you name). Set a
  timeout and exclude non-retryable errors, such as a 4xx that won't change on retry.
- Don't reimplement what `itertools` (stdlib) or `more-itertools` already provide
  (grouping, chaining, windowing, accumulating) — reach for them instead. See
  `python-code-style` for the broader "prefer stdlib idioms" rule.
- **Read a formal grammar with a real parser, never with `split`, conditionals or a
  regex.** Markdown goes to `markdown-it-py`; HTML and XML to `parsel` (XPath and CSS
  selectors), or the stdlib `html.parser` when you need a fragment's tag and text events
  rather than a query; TOML to `tomllib`, `uv.lock` included; YAML to `py-yaml12` (a YAML
  1.2 parser, so `yes` and `on` stay strings); dependency specifiers and versions to
  `packaging`; Python to `ast`; shell to `tree-sitter` plus `tree-sitter-bash`. Any other
  grammar goes to `tree-sitter` with that language's own grammar package — the runtime
  ships none, so check a maintained one exists before naming it, and where none does,
  writing a parser is the work, not a licence to split. A hand-rolled reader agrees with
  the real one on the constructs it was written against and diverges on the rest, so
  each review round finds a fresh one and the fixes never converge.
- **Text handling stays fine where there is no grammar to get wrong**: a line-oriented
  format with no nesting, quoting or escaping, or a fixed string match that never has to
  understand structure.
- **The tell is the second construct, not the first.** One input read differently from
  the reference tool is a bug worth fixing in place; a second means the grammar has more
  shapes than the code was written against, and the remedy is to swap in the parser
  rather than add another branch.
- **A regex the specification publishes as its own reference implementation is that
  parser, for the part it covers.** PEP 723's block-extraction regex is copied verbatim,
  and the block's contents still go to `tomllib`. Copying such a regex is not
  hand-rolling; extending it past what the specification defines is.

## Command-line interfaces

- Build a script's CLI with `typer`, not `argparse`, unless the script's own startup
  time is the constraint. Typer derives the parser from the function signature and its
  type hints, so each option is declared once instead of in an `add_argument` call and
  again in the body.
- `typer` is a deliberate exception to *don't add a dependency for a task the standard
  library handles*: `typer` buys declaring each option once, where `argparse` makes
  every script declare each option twice, rather than a capability `argparse` lacks.
  The exception holds for every CLI and does not generalise to other libraries.
- **Keep `-h` working when you convert one.** `argparse` accepts it for free and Typer
  does not, so a conversion checked by diffing `--help` passes while `-h` starts exiting
  2. `typer.run()` cannot carry context settings, so even a single-command script needs
  the app form:

  ```python
  app = typer.Typer(
      add_completion=False, context_settings={"help_option_names": ["-h", "--help"]}
  )
  ```

  Then `@app.command()` on the function and `app()` at the bottom, where `typer.run`
  would have gone.
- **A script that takes no arguments needs no CLI library at all.** Don't add one for a
  parser with nothing to parse. Know what that costs: with no parser `-h` and `--help`
  are not options — they are ignored and the script runs, so asking an unfamiliar script
  for help executes it.
- **A Typer command accepts keyword-only parameters**, so `python-code-style`'s bare-`*`
  rule reaches it like any other function.
- **Keep the command function `def`, not `async def`.** Typer accepts an `async def`
  command and never awaits it: the coroutine is discarded, the script exits 0, and the
  only sign is a `RuntimeWarning` (measured on typer 0.26.7 — re-check on a major bump).
  Call `asyncio.run(...)` inside a synchronous command instead.
- Importing `typer` costs tens of milliseconds more than `argparse`. How many depends on
  the machine, and on whether you time the import or the whole process, so measure it
  rather than quoting a figure. It decides nothing except where startup dominates — a
  script on a per-tool-call hook, where stdlib-only is the right trade: measured twice
  under `uv run --script`, importing `typer` alone added ~45 ms to startup, so a
  `PreToolUse` and `PostToolUse` pair pays ~90 ms of import on every tool call. Keep
  `argparse` there, and let the module docstring state the stdlib-only constraint that
  forces it. A single `stat` is microseconds, so "it does I/O" does not swamp a gap that
  size.

## HTTP

- Use `httpx2` (`import httpx2`) — the maintained, Pydantic-stewarded, drop-in successor
  to `httpx`. Async support is the baseline requirement either way, which rules out
  `requests` and `urllib`.
- In a repo already standardised on a different async client, use that one rather than
  importing a second alongside it; moving the repo onto `httpx2` is its own deliberate
  change, not a drive-by edit inside an unrelated one. Don't add another HTTP client as
  a (dev) dependency without a concrete reason.
- Set an explicit timeout on outbound requests; a single client-level default is fine,
  but never rely on the library default, which is often `None` (waits forever).

## JSON

- Use `orjson` over the standard library `json` for serialising and deserialising — it is
  faster and better-behaved.
- **Reach back for stdlib `json` only to keep a lenience `orjson` doesn't have**, and
  name the behaviour you are depending on in a comment at the call site. Nothing about
  the *shape* of the code qualifies: a standalone script carrying no other dependency
  doesn't, and neither does a payload being small. Of the differences below, only the
  two in bold qualify (measured on orjson 3.12 — re-check on a major bump):

  | Value | stdlib `json` | `orjson` |
  | --- | --- | --- |
  | `NaN` / `Infinity` | writes and reads the non-standard literals | **`dumps` writes `null`**; `loads` rejects the literals |
  | integer outside 64-bit range | exact, both ways | `dumps` raises `TypeError`; **`loads` returns a float** |
  | scalar non-`str` dict key (`int`, `float`, `bool`, `None`) | coerces it (`1` → `"1"`, `None` → `"null"`) | raises `TypeError` unless `OPT_NON_STR_KEYS` |

  The two in bold fail **silently**, which earns them a carve-out: a `NaN` becomes
  indistinguishable from a real null, and a large id loses its low digits. A
  `TypeError` announces itself, so fix the data at the call site — stringify the keys,
  or carry the big integer as a string — rather than swapping library for the whole
  payload.
- When a Pydantic model is involved, go straight to and from JSON bytes with
  `Model.model_validate_json(raw)` and `model.model_dump_json()` — one fast
  parse-and-validate pass.
- Don't call an HTTP response's `.json()` and hand the resulting dict to Pydantic: that
  parses twice (the client builds a dict, then Pydantic re-validates it). Pass the raw
  bytes (`response.content`) to `Model.model_validate_json(...)` instead.

See `python-async` for deploying on `uvloop`, and `python-datetime` for dates and times.
