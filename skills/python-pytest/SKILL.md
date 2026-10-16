---
name: python-pytest
description: Write and structure pytest tests to this project's conventions. Use when authoring tests, parametrizing cases, handling warnings, deciding test coverage, or laying out the tests directory.
---

# Python pytest Conventions

Standards for authoring tests and laying out the test suite, which uses
[pytest](https://docs.pytest.org/).

## Writing tests

- Use test **functions** only — never test classes.
- Do most test setup with fixtures and parameters so the code under test is at, or near,
  the beginning of the test function.
- Prefer fixtures over module-level helper functions for test data and setup: a builder
  that takes no arguments should be a fixture (injected, not called), and a *parameterized*
  builder should be a **factory fixture** — a fixture that returns a callable the test
  invokes with its per-case arguments. Keep a plain module-level function only when the
  builder must be called inside a `@pytest.mark.parametrize(...)` decorator, whose
  arguments are evaluated at collection time, where fixtures can't be requested/injected.
  A suite that already standardises on module-level builders doesn't license another one:
  write the fixture, and raise the existing builders as a cleanup of their own rather than
  matching them or rewriting them mid-change (`software-engineering` covers that call).
- Compose fixtures from other fixtures rather than mutating fixture values, put shared
  fixtures in `conftest.py`, give each fixture a single purpose, and restore any global
  state you mutate after the `yield`.
- Use explicit `pytest.param(...)` instances in parametrized tests, each with a
  meaningful `id`. Param ids can contain spaces and should be written in a human-readable
  way.
- Don't parametrize a test that has only one case just to attach an id — keep it a plain
  test function.
- When a parametrized case needs more than about three values, wrap them in a small
  dataclass passed as one param instead of a long tuple.
- Don't use docstrings or comments in tests. Convey the test's purpose through meaningful
  function names, variable names, and param ids.
- Type-hint module-level constants in test modules with `Final`, exactly as in source
  (see `python-code-style`) — test modules are not exempt.

```python
import pytest


@pytest.mark.parametrize(
    ("celsius", "expected_fahrenheit"),
    [
        pytest.param(0, 32, id="freezing point of water"),
        pytest.param(100, 212, id="boiling point of water"),
        pytest.param(-40, -40, id="scales cross over"),
    ],
)
def test_celsius_to_fahrenheit(celsius, expected_fahrenheit):
    assert celsius_to_fahrenheit(celsius) == expected_fahrenheit
```

## Test design

- Mock at the boundary of services you don't own — outbound HTTP, third-party
  APIs; use real implementations for all internal code, including your own thin wrappers
  (mock the external call inside the wrapper, not the wrapper itself).
- **The database is the exception: don't mock it — run a real, ephemeral instance,
  session-scoped.** A fake diverges from the real engine exactly where the queries get
  interesting, so a passing test against one says little. Where standing that instance up
  needs something the machine may not have running, only the tests that touch it carry
  that requirement; the pure unit tests still run without it.
- For mocking use pytest-mock's `mocker`, not `monkeypatch` or `unittest.mock`.
  Patch the name in the namespace under test: `under_test.fn` when it does
  `from other import fn`, or `other.fn` when it does `import other`; pass
  `autospec=True` (or `spec=`) so signatures stay honest.
- One behaviour per test: assert as many facets of that single result as you need, but
  don't bundle unrelated behaviours into one test.
- Derive cases from the behavioural contract: parametrize over distinct observable
  outcomes, collapse input combinations that behave identically, and assert the whole
  result.
- Don't re-assert what the type system, framework, or DB constraint already guarantees.
- Test through the public API — it's the stable contract, whereas private
  (underscore-prefixed) functions are implementation details you should be free to
  refactor without touching tests. Don't import a private function to test it; cover it
  indirectly through its public callers (preferred), promote it to public if it
  genuinely needs direct testing, or drop the test if it adds no meaningful coverage.
- Don't put control flow (`if`/`for`/`try`) in a test, and don't assert on log output.
- Don't re-test a third-party library's own guarantees: `software-engineering`'s
  *Design judgement* decides what a test of your use of a dependency should assert.
- Use a raw string for `pytest.raises(match=...)` patterns that contain regex
  metacharacters.
- Make test data deterministic: freeze time (`freezegun`/`time-machine`) for any
  `now()`/expiry logic, and use fixed UUIDs (`uuid.UUID(int=N, version=4)`) — never the
  real clock or random UUIDs.

## Warnings

- Warnings are treated as errors in tests.
- Warnings emitted from code in this repo must be fixed at the source, not silenced.
- Warnings emitted from third-party packages may be ignored, using the most specific
  ignore practical.

## Coverage philosophy

- Aim for high branch coverage, but hold it in tension with test bloat — a goal, not an
  absolute. Every line of test code has a maintenance cost, so don't add tests that don't
  meaningfully exercise behaviour.
- **A test only its own fixture can construct pins nothing.** Where the fixture writes
  a state no real producer reaches — a value the API rejects, a row the database
  refuses — the test shows that the code reads that input and nothing more.
  Mutation-checking it closes no gap: reverting the code under test makes such a test
  fail exactly as a real one would. Establish the producing path first
  (`software-engineering`'s reachability rule), and delete the test where there is none.
- Watch the ratio of test code to source code. Past roughly 2:1 you're usually paying to
  maintain a lot of test code for diminishing returns — exercising ever-smaller slivers
  of source. When closing the last uncovered lines would push the ratio that high, prefer
  leaving them uncovered (with a justified `# pragma: no cover` where apt) over bloating
  the suite.
- Favour tests at public entry points — an API endpoint, a CLI command, a library's
  exported functions — over many unit tests of internals: they cover more code per
  test, survive internal refactors, and keep the test-to-source ratio low.
- Run coverage with `--cov-branch`. Cover new branches and error paths by default, but
  don't ratchet toward 100% at any cost: a deliberately uncovered path is fine when a test
  would cost more to maintain than it is worth.
- **A test body that never ran is a defect, not a coverage gap.** Point coverage at
  `tests/` as well as the source: a test nothing collected, a helper nothing calls, a
  body behind a marker scoped wrongly. Delete it, or fix what stopped it running. Read
  the deliberate non-runners out first — a platform `skipif` and an `xfail(run=False)`
  leave their bodies uncovered by design. Ruff's `F811` already catches the same-module
  duplicate whose second definition silently shadows the first, so this is for what a
  linter cannot see.
- Sanity-check the `src`/`tests` ratio with `software-engineering`'s
  `scripts/source_size.py`: it reports size per root and, with `--compare-to <ref>`, the
  delta a change adds. A suite outgrowing the code it covers is a prompt to consolidate
  rather than to add. That skill's *Design judgement* makes the same measurement a step
  on any non-trivial change, in any language.

## Test directory layout

- `/tests/` mirrors the `/src/` directory structure and stays in sync with it.
- Test modules are (in most cases) named after the src module they test, with a `test_`
  prefix. Rarer tests covering functionality spanning several src modules are the
  exception.
- Don't create sub-packages in the test directories — no `__init__.py` files (a
  `conftest.py` is fine). So no two `.py` files anywhere in the repo, source included,
  may share a name (`__init__.py` and `conftest.py` excepted): without packages, pytest's
  default `prepend` import mode imports each test file by its bare name, and because test
  modules mirror source names, two `utils.py` under `src/` become two `test_utils.py`
  that fail collection.

## Running tests

These are reference commands — run them when it suits your workflow:

```bash
# Run a single test file
uv run pytest tests/test_module.py

# Run the whole suite in parallel
uv run pytest -n logical --color=no

# Run an individual test (drop -n logical when running a single test)
uv run pytest tests/test_module.py::test_name
```
