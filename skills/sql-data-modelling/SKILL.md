---
name: sql-data-modelling
description: Write SQL and design the schema under it so results stay correct as rows change, in any dialect — NULL semantics in constraints and aggregates, identity keys that don't drift, grouping and joins that don't multiply totals, comparisons matched to the source's precision, and where a statement belongs once it outgrows a string literal. Use when writing, reviewing, or debugging SQL or a query embedded in application code; deciding whether a statement belongs in a .sql file or inline in host-language source; designing or migrating a table; choosing a primary key, unique constraint, or dedupe hash; writing an upsert or ON CONFLICT clause; aggregating with GROUP BY, SUM, COUNT, or AVG; or chasing rows that duplicate on re-run, stay unlinked, or double-count.
---

# SQL and Data Modelling

Correctness rules for SQL and the schema beneath it, in any dialect, and where a
statement belongs once it outgrows a string literal. Each correctness rule describes a
failure that survives a green build and a passing test suite: the query runs, returns
rows, and the numbers are wrong. The bugs surface on the second load rather than the
first, which is why review catches them more often than tests do.

Examples below were run against SQLite; the one place engines genuinely disagree is called
out as such.

## NULL is not a value

- A `UNIQUE` constraint over a nullable column does not prevent duplicates. The SQL
  standard treats two NULLs as distinct, so the constraint is never violated,
  `ON CONFLICT` never fires, and every re-run inserts another row — three upserts into
  `UNIQUE (term, asset_id)` with `asset_id` NULL leave three rows, not one. Make every
  column in a uniqueness key `NOT NULL`, or move the uniqueness onto an expression that
  maps the absent case to a real value and use that same expression as the conflict
  target:

  ```sql
  CREATE UNIQUE INDEX asset_term ON t (term, COALESCE(asset_id, -1));
  INSERT INTO t (term, asset_id) VALUES ('a', NULL)
    ON CONFLICT (term, COALESCE(asset_id, -1)) DO UPDATE SET n = n + 1;
  ```

- Confirm the uniqueness key actually holds by running the same insert twice and counting
  rows. This is the one rule here that is genuinely dialect-dependent: PostgreSQL 15+ can
  declare `UNIQUE NULLS NOT DISTINCT`, SQL Server treats NULLs as equal and so permits
  only one, and SQLite and MySQL offer no such switch — identical DDL, different
  behaviour, so test rather than port an assumption between engines.
- Use `IS` / `IS NOT` (or `IS [NOT] DISTINCT FROM`) rather than `=` / `<>` on any column
  that can be NULL. A comparison against NULL yields NULL rather than true or false, so
  the NULL row is excluded from both halves of what reads like an exhaustive split: of
  three rows, `x = 2` matched one and `x <> 2` matched one, and the third appeared in
  neither result.
- Record what NULL means for each nullable column — "not measured" or "not applicable" —
  alongside the DDL. An aggregate can only be honest about a distinction someone wrote
  down.
- Don't `COALESCE` a NULL away inside an aggregate when NULL means "not measured".
  `SUM(COALESCE(v, 0))` reports a confident `0` for a column nothing has ever populated,
  where `SUM(v)` returns NULL and tells the truth; aggregates skip NULLs already, so on
  a sum the `COALESCE` buys nothing but the wrong answer. `AVG` is worse than `SUM` here,
  because the substituted zeros join the denominator and drag the mean down. When a caller
  has to tell "no data" from a measured zero, return `count(v)` beside the aggregate.

## Row identity

- Never put a mutable field in a primary key, a unique constraint, or a dedupe hash. When
  the value changes upstream the same entity hashes to a new identity, so the next load
  inserts a second row instead of updating the first, and quantities and money multiply:
  one order line carrying its `status` and `ship_date` in the row hash became three rows
  as those two fields progressed, tripling the cost it reported.
- Build the identity from fields that hold for the row's whole lifetime — the source's own
  id, or an event's immutable coordinates such as order id plus line number plus
  occurred-at — and carry everything that can change as ordinary columns the upsert
  updates.
- Hash only the immutable subset when the source gives you no stable id. A hash over the
  whole row is a change detector, not an identity, and using one as a key guarantees a
  duplicate on the first edit upstream.
- Test identity with a second load rather than by reading the key definition: load the
  same source twice with a mutable field edited in between, then assert the row count is
  unchanged. A row-identity bug is invisible on a first run and unmissable on a second.

## Aggregates and grouping

- `GROUP BY` only on columns functionally dependent on the group's identity. Grouping on
  a mutable label — a title, a name, a status — splits one entity into a row per version
  of that label, and each of those rows counts the same children.
- Don't stop at the `GROUP BY` when a total looks wrong, because narrowing it hides this
  bug rather than curing it. If the parent table holds one row per label version, the join
  fans out and the total stays wrong: grouping by the stable id collapsed two rows back
  into one while the sum stayed at 4.80 against a true 2.40 — a single plausible-looking
  row carrying a doubled number, which is harder to spot than the two rows were. Cure the
  fan-out instead, either by giving the parent one row per entity (the identity rules
  above) or by aggregating the child side in a CTE and joining to that. Both return 2.40.
- Establish the grain of every join before summing across it — one row per what? — since
  any join that can match multiple rows on one side multiplies the other side's values.

## Comparisons

- Compare at the precision the data actually carries, which means deciding what a tie
  means before writing `>=` or `>`. A same-day row on a day-granularity source can't be
  ordered — nothing recorded says which came first — so `order_date >= bought_on`
  quietly rules that it *did* come later, while `>` quietly rules that it didn't. A
  precision mismatch is the same bug in disguise: where one side carries a time of day and
  the other is midnight, a same-day row lands on whichever side storage happens to put it.
  Truncate both sides to the coarser unit, then include or exclude the tie by decision
  rather than by default. (`python-datetime` owns the Python side of that boundary.)

## Upserts and write paths

- An upsert's insert branch and its update branch must leave the row in the same state.
  Enumerate the columns each branch sets and diff the two lists: a foreign key linked only
  on insert stays NULL forever on a row first seen before its parent existed, because
  nothing revisits it — the row exists now, so every later load takes the update path.
  `software-engineering` states the general path-symmetry rule this is an instance of.
- Backfill after fixing an asymmetric write path. Rows already persisted under the old
  path are still wrong, and a re-run won't correct them while their identity is unchanged
  — the update branch is precisely the one that skipped the column.

## Representing a closed set of values

- **A native enum is the default for a closed set, and an integer code is not the escape
  hatch it looks like.** The pressure to switch comes from "you can't remove an enum
  value", which is true and cheap to overstate. Measured on Postgres 17 at a million
  rows: `smallint` and the native enum are byte-identical in the heap, because the
  two-byte saving vanishes into alignment padding, so the integer's only advantage is DDL
  flexibility — which `varchar` plus a `CHECK` also has while staying readable to anyone
  querying the table directly. The integer adds a failure the enum cannot have: the
  name-to-number map lives in application code with nothing enforcing it, and an
  auto-numbered `IntEnum` renumbers on any reorder, silently relabelling every stored row.
- **Choose enum values that will not need removing**, and reach for `varchar` + `CHECK`
  only where the set is genuinely expected to churn. Removing a native enum value rewrites
  the table and **changes the type's OID**, and a connection pool that cached the old OID
  fails its next query casting to that type (`cache lookup failed for type ...`) until the
  pool cycles — the window is the deploy, not the migration. Adding a value with
  `ALTER TYPE ... ADD VALUE IF NOT EXISTS` keeps the OID and is safe under load.
- **A newly added enum value cannot be used in the transaction that added it**, so "add
  a value and backfill rows onto it" is two releases when migrations run in one
  transaction.

## Where a statement belongs

This section is about tooling reach rather than correctness: a statement in a file can be
linted and formatted, while one inside a host-language string literal is opaque to
everything but the database.

- Move a statement into a `.sql` file loaded at runtime once its expression runs past
  about five lines written one clause per line (`SELECT` / `FROM` / `JOIN` / `WHERE` /
  `GROUP BY` / `ORDER BY` …), or once it compounds: a CTE, a window function, a set
  operation, or a correlated subquery. Count the clauses it would take rather than the
  literal's own formatting — a statement squeezed onto one line is no simpler for it.
- Size and kind are separate tests, and failing either is enough to move a statement. A
  long-but-flat single-table statement stays inline however wide it gets, and a list
  binding — `json_each(?)`, `IN (?)` — is not compounding even though it nests a
  `SELECT`.
- Schema DDL belongs in a file whatever its size. A `CREATE TABLE` is the statement SQL
  tooling has most to say about, and the one a reader most often needs to find without
  reading application code to get to it.
- SQL already embedded in a string literal near yours, over this bar and left there,
  doesn't license a new one. Write yours into a `.sql` file, and raise the embedded
  statements as a cleanup of their own rather than converting them in passing or
  matching them (`software-engineering` covers that call).
