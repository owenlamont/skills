---
name: rust-testing
description: Write and lay out Rust tests to this project's standards — unit tests beside the code versus integration tests through the public interface, property tests, snapshots, and what a coverage gate actually measures. Use when adding or restructuring Rust tests, choosing between an in-source test module and the tests directory, reaching for proptest or insta, testing a binary crate, or closing uncovered regions under a coverage gate.
---

# Rust Testing

Standards for testing Rust in this project. `rust-code-style` carries general Rust style
and `software-engineering` carries what counts as having verified a claim; this is the
test layer.

## Layout follows the boundary being tested

- **`#[cfg(test)] mod tests` beside the code for tests that need private access**;
  **`tests/` for behaviour exercised through the public interface.** An integration test
  compiles as a separate crate, so it can only reach what is `pub` — which is exactly what
  makes it the honest place to pin a contract.
- Don't migrate every test to one style for consistency. The boundary under test decides,
  and a codebase with both is the normal outcome rather than a mess to tidy.
- **A strict coverage gate can legitimately override that and force everything into
  `tests/`.** In-source test modules are compiled into the unit-test binary and
  instrumented with it (see *What a coverage gate actually measures*), so a
  zero-uncovered-regions policy pays a real cost for each one. Where a project has made
  that trade, it is a deliberate constraint to respect rather than a layout to correct —
  and the price it pays is widening visibility to `pub(crate)` for testability, which is
  then a reason for that visibility rather than a lapse.
- **A binary-heavy crate needs a decision here, not a default.** `tests/` can only reach
  the library target, so behaviour living in `main.rs` is untestable from there. Either
  keep `main` a thin shell over a library function, or drive the built binary as a
  subprocess — and pick one deliberately, because the second is much slower and the first
  shapes the crate.
- **Don't re-test a dependency crate's own guarantees** — `software-engineering`'s *Design
  judgement* decides what a test of your use of a dependency should assert.
- An in-memory transport, where the protocol library offers one, beats a real socket or
  stdio for loop and dispatch tests: the same dispatch path, no port, no timing.

## Property tests

- **proptest where generation needs constrained strategies and meaningful shrinking** —
  parsers, config, anything with a grammar. QuickCheck where a plain `Arbitrary` instance
  is genuinely enough. Don't carry both dependencies without a reason.
- **A property test supplements deterministic examples; it never replaces them.** A random
  run is not evidence that a particular branch executed, so anything a coverage gate must
  reach needs a named example test that reaches it every run.
- Shrink output is the deliverable when a property fails. If a failure reports an input
  nobody can read, the strategy is generating the wrong shape — fix the strategy rather
  than widening the assertion.

## Snapshots

- **`insta` where the complete rendered output is the contract under human review** —
  diagnostics, formatted output, help text. Not as a substitute for asserting one
  specific invariant, where a precise assertion states what you actually meant and a
  snapshot buries it.
- **Normalise before snapshotting: sort unordered output, redact machine-specific
  absolute paths (temp and home directories), unify line endings and path separators,
  and redact timestamps.**
  Otherwise parallelism and platform differences produce churn, and churn trains reviewers
  to accept snapshot diffs without reading them — which is the failure mode that makes
  snapshot suites worthless rather than merely noisy.

## What a coverage gate actually measures

- **`#[cfg(test)]` controls compilation, not coverage.** The unit-test binary is built
  with `cfg(test)` on, so in-source test helpers are instrumented like any other code.
  "Test modules don't count towards coverage" is the common and costly error here.
- **Keep in-source test helpers branch-free.** Every conditional in a `#[cfg(test)]`
  helper is another region the gate has to execute, and helper logic is the last thing
  anyone writes a test for.
- **`#[coverage(off)]` is not available on stable** — measured on both a pinned 1.97.1
  and the 1.98.1 stable of the day, which reject it as an experimental feature. Don't
  design a coverage policy that depends on it; re-check before assuming a later release
  changed that.
- Pass `llvm-cov` every instrumented binary whose regions form the gate — the unit-test
  binary, each `tests/` binary, the bin — as an `--object`. Don't infer that list from a
  plain `cargo test` run: a binary left out is silently absent from the report.
- Doctests need unstable rustdoc support to persist their binaries for `llvm-cov`, so
  don't count them towards a stable coverage gate unless CI has deliberately solved that.
- Use the LLVM tools shipped with the pinned toolchain (`llvm-tools-preview`). The profile
  data format can change between releases, so a mismatched system LLVM produces confident
  nonsense rather than an error.
- **A region a test cannot reach is a design signal before it is a coverage problem.**
  Prefer deleting the unreachable branch or restructuring so it is reachable, over
  contorting a test to touch it.
