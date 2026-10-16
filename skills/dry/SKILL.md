---
name: dry
description: Find deletable code as a refactor input — Python, Rust, TypeScript or JavaScript duplicated from itself, within a repo or across several, and hand-rolled Python a maintained library already does — with a bundled detector for each and the procedure for reading what they report. Use when asked to find duplicated or copy-pasted code, plan a DRY refactor, look for logic copied between services that belongs in a shared library, decide whether a duplicate should be deleted or promoted, size a refactor before scoping it, or hunt for hand-rolled retries, grouping, counting, chunking or memoisation a library replaces.
---

# DRY: duplication and library replacement

Two axes, one subcommand each of the bundled `scripts/dry.py`:

| Command | Language coverage |
| --- | --- |
| `dupes` | Python by default; Rust, TypeScript or JavaScript with `--language` |
| `shapes` | Python only |

- **Duplication** — `dry.py dupes` groups near-duplicate functions, methods
  and classes. Rename-insensitive, tolerates inserted statements, and scans several
  repos as one corpus.
- **Library replacement** — `dry.py shapes` matches a small catalog of
  hand-rolled shapes and names one candidate replacement for each. The candidate is a
  lead; whether to adopt that library is `python-libraries`' call.

Both commands list tracked files only and skip test code unless given `--include-tests`:
anything under a `tests/` directory, plus Rust `#[cfg(test)]` items, and TypeScript or
JavaScript under `test/` or `__tests__/` or named `*.test.*`, `*.spec.*`, `test-*` or
`test_*`. They print their file accounting on stderr, and exit 2 on a root that
leaves nothing to scan. Read the `unreadable` lines: a file that does not parse is
missing from the result, not clean.

## Which axis first

- **Run `dupes` across repos before `shapes`.** Measured over one estate,
  cross-repo duplication out-yielded the library-shape catalog many times over, and the
  catalog averaged about two hits per shape.
- **Before running `shapes`, check the repo's ruff selection.** Ruff's `FURB`,
  `SIM`, `PTH`, `C4` and `PERF` families catch single-expression stdlib reinvention; a
  missing family or a missing `preview = true` is the cheaper finding. The catalog only
  covers what ruff cannot see: multi-statement shapes and third-party replacements.
- **`explicit-preview-rules = true` keeps preview rules off even under `--preview`**,
  so a clean run on such a repo says nothing about them. Override it for the audit:

  ```sh
  ruff check --select FURB,SIM,PTH,C4,PERF --preview --config 'lint.explicit-preview-rules=false' <repo>
  ```

- **A low `shapes` yield is not a clean estate.** It shows only that the six
  reinventions the catalog can express are rare, not that nothing else is hand-rolled.

## Running the duplication pass

```sh
uv run --script <skill-dir>/scripts/dry.py dupes --min-behavioural 3 <repo> [<repo> ...]
uv run --script <skill-dir>/scripts/dry.py dupes --language rust --min-behavioural 3 <repo> [<repo> ...]
uv run --script <skill-dir>/scripts/dry.py dupes --min-behavioural 3 --cross-repo-only <repo> <repo> ...
```

- **Pass every repo that could share code as one invocation.** A per-repo run cannot
  see the copies that sit in different services, which are the ones most worth
  removing. `--json` emits the full report.
- **`--min-behavioural` has no default; treat 3 as a starting point, not a tuned
  value.** It is the number of calls, branches, loops and assignments outside type
  annotations a fragment needs, and it is what stops a class of field declarations
  matching every other such class. It was swept on one API-service corpus, where it
  turned at 3, then held at 8% false positives on a library repo it was not tuned on.
  On a new corpus, hand-score the first twenty groups before trusting the output, and
  move it if template-shaped matches dominate. The value was tuned on Python only.
- **On Rust, try `--min-tokens 80`.** On one single-crate CLI repo the defaults gave 14
  removable groups out of 21, and 80 dropped only false positives — short `Option` and
  iterator chains — leaving 14 of 17. Unchecked on a second Rust repo; 100 lost real
  groups.
- **Expect cross-repo false positives at roughly double the within-repo rate**, from
  template-shaped matches multiplying across repos while genuine cross-repo clones stay
  rare. Measured at 31% against 12%.

## Reading a group

- **Score each group as one of three, and keep the second apart from the third:**
  duplication worth removing; real but deliberately kept; false positive. No detector
  can see the middle one — migration revisions, versioned API pairs kept apart so one
  can be deleted, sync/async client pairs — and folding it into false positives makes
  the tool look worse than it is.
- **Score a group as deliberately kept only on evidence of a decision to keep the
  copies apart**: git history, a comment at the site, or the owner saying so. The
  examples above are shapes to check, not an exclusion list; without that evidence,
  score the group as one of the other two on its merits.
- **The false-positive shape is a declaration block matching another declaration
  block**: two constant mapping tables over different enums, two models with disjoint
  fields, two router aggregators. Structure identical, nothing extractable.
- **A container and its contents come back as separate groups** when the members sit in
  different files. Act on the smaller one. A Rust `impl` holding one method lists both
  as locations of one site; count them once.
- **A group is transitively linked, not a clique.** `min_similarity` covers the pairs
  that were scored, so two members can be less alike than it suggests. The same property
  is what merges one rule spelled under two names, which a grep never finds.
- **A group whose copies have drifted apart is a question, not a defect.** Read each
  copy and the models it serves before calling the divergence a bug.

## Delete or promote a cross-repo group

Python cross-repo groups are classified from the roots' `pyproject.toml` dependency edges,
and a library counts only when its own repo is one of the roots — **pass the shared
library alongside the services**, or every group reads `unrelated`. Under any other
`--language`, `shared` stays empty.

| label | meaning |
| --- | --- |
| `delete` | one copy sits in a scanned library every other copy's repo declares |
| `promote` | every copy's repo declares one scanned library, and the code is in none |
| `unrelated` | no scanned library is common to them all; may be deliberate |

- **`delete` is a candidate, not a verdict.** A declared dependency does not show that
  the library's copy is public, present in the version the consumer pins, or
  behaviourally interchangeable. Check all three before replacing a copy with an import.
- **A function already parameterised on a shared library's type but living outside that
  library is an unfinished promotion.** Promote it.

## A detector names the shape; a grep sizes the family

**Size every family with a census before scoping a refactor.** A clone detector finds
what was copied recently: older copies drift below any usable similarity threshold, and
a small function falls under the size floor however many repos carry it. So take the
group as a pointer, find the API call, decorator or import that distinguishes the
shape, and count that across the corpus with `rg`:

```sh
rg -l 'logging.basicConfig' <repo> <repo> ...
```

- **Rank by copies × size, never by size alone.** A three-line helper copied thirty
  times outweighs a single forty-line pair; a size filter on the census discards it.
- **Lowering `--min-tokens` to catch small copies floods the report with idiom.** Use
  the `rg` census above for small functions instead.

## Library-replacement pass

```sh
uv run --script <skill-dir>/scripts/dry.py shapes <repo> [<repo> ...] [--shape <name>]
```

- **Every hit is a lead, not a replacement to apply.** A shape matches the common
  spelling of a reinvention, not every variant that would behave differently once
  swapped, so read the code and confirm the replacement is equivalent before making it.
- **Specify a new shape by its distinguishing clause, not its container.** A counter
  matched as "a subscript assigned from an expression containing `.get()`" was 1 real
  hit in 11; requiring the literal `+ 1` made it exact. Add a shape as a predicate in
  `SHAPES`.
- **Price in `retry-loop` as noisy.** A service main loop and a paginated fetch also
  sleep and catch an exception, and nothing structural says whether a loop re-runs the
  same call. Read every hit.
