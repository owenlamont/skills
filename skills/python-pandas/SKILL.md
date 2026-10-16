---
name: python-pandas
description: Write or review Pandas code to this project's standards — vectorised operations, Pandas-native types, and Pandera schemas. Use when importing or using pandas, and when reviewing a diff that touches pandas — transforming DataFrames or Series, handling missing values, or type-hinting tabular data.
---

# Python Pandas

Standards for working with Pandas DataFrames and Series. Extends the "prefer library
idioms" rule in `python-code-style` with Pandas specifics.

## Vectorise

- Operate on whole Series and DataFrames; don't loop with `.apply`, `.iterrows`, or a
  Python `for` over rows. Reach for Series methods — `.where`/`.mask`/`.map`/`.clip`/
  `.str.*`, `.between`, `.isin` — and `df.eval`/`df.query` for arithmetic and filtering.
- Prefer `Series.map(mapping)` to `.apply(lambda x: mapping[x])`, and use `&`/`|` only for
  row-wise boolean masks — keep `and`/`or` for scalar conditionals.
- When you genuinely must iterate, use `.itertuples()` (named, typed, fast), never
  `.iterrows()`.
- Stay in Pandas types all the way to the function boundary — don't drop to Python lists
  or NumPy arrays mid-pipeline and convert back, and don't convert at a call site to
  satisfy an over-concrete parameter type (pass `df.columns`, not `df.columns.tolist()`;
  `python-code-style` has the general rule). The reason is usually performance: a Python
  container forces per-element work where a Pandas operation stays vectorised.
- Compute group statistics with a Pandas-native transform, not a dict round-trip:
  `images.groupby("source_dir")["source_dir"].transform("size")` filters on group size
  without leaving Pandas, where `value_counts().to_dict()` plus a row-wise `.map`
  allocates a Python dict per call.
- Name a DataFrame for what it holds (`images`, `upscaled_images`), never `df`, `data` or
  `tmp`. Add a `df_`/`_df` affix only where the type isn't obvious — most often when a
  DataFrame and a Series of the same concept sit side by side — and follow whichever
  affix the surrounding code already uses. Name Series for their contents too
  (`file_size_bytes`, not `s`).
- Time a performance claim on representative data before acting on it. Idiomatic Pandas
  usually wins, but both the size of the win and where it comes from move with the data:
  `transform("size")` beat `value_counts().to_dict()` plus a row-wise `.map` by 3.7–10×
  across group counts from 100 to 10k, while dropping the `.to_dict()` alone recovered
  anywhere from most of that to under a tenth — the cost is the per-element lookup rather
  than building the dict, so replace the lookup, not just the conversion.
  `groupby(...).filter(...)` was no faster than what it replaced.

## Don't mix NumPy into Pandas

- Use `pd.NA`/`pd.NaT` for missing values, not `np.nan`, and prefer the nullable
  extension dtypes (`Int64`, `boolean`, `string`) so missingness is first-class — NumPy
  float columns silently coerce `pd.NA` to `NaN`.
- Prefer Series methods over `np.*` functions on a Series (including via `.apply`), and
  never use `.values` (the `PD011` lint flags it) — reach for `.to_numpy()` only at a
  boundary needing a raw array.
- Don't store NaN as a sentinel; model "missing" explicitly with a nullable dtype.
- Keeping everything Pandas-native also keeps a future move to Polars tractable.

## Pandera schemas

- Lean on Pandera: type-hint every DataFrame parameter and return with `DataFrame[Model]`.
  The payoff is readability — the schema becomes explicit at every reference — so use it
  ubiquitously, not sparingly.
- A genuinely schema-polymorphic helper — one that works on whatever columns it is handed
  — takes a bare `pd.DataFrame` instead, and documents in its docstring the contract it
  does rely on (index levels, ordering, any required column). Don't invent a union model
  to force `DataFrame[Model]` onto it, and don't leave the contract implicit.
- Give each schema model its own module, and keep the raw (as-ingested) schema in a
  separate module from the processed (validated or derived) one.
- Back categorical columns with a `Category` dtype built from an `Enum`'s values (iterate
  the Enum to build the categories), and annotate timestamp columns as `pd.Timestamp`.
