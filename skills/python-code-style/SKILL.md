---
name: python-code-style
description: Write Python source to this project's standards. Use when authoring or refactoring Python code and deciding on style, type hints, docstrings, comments, imports, or language idioms.
---

# Python Code Style

Standards for writing Python source in this project.

## Style guide and docstrings

- Follow the
  [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) for all
  code, including its Google-style docstrings, **with the exception that whether a
  docstring is warranted at all is decided by *Comments and docstrings* below** — Google
  requires a module docstring and expects a class one; that section overrides both.
- Wrap to the project's configured line length (88 characters in these projects) **as you
  type**, not after the hooks complain. `ruff-format` re-flows code but will not re-wrap
  a long string literal, comment, or docstring, so an over-long one fails the run rather
  than being fixed for you — and prose in a docstring is exactly where that bites. Check
  the file you just edited with `ruff check <file>` rather than waiting for the full
  gate; `python-lint-format` has the per-file commands and the Markdown equivalent.

## Type hints

- Type everything with the strongest type that still matches how the value is used —
  specific to its semantics/interface, which for an iterated-only parameter is
  `Iterable[X]` rather than `list[X]`.
- Don't convert a caller's container to satisfy an over-concrete parameter type (calling
  `df.columns.tolist()` for a `list[str]` parameter that only tests membership). Widen
  the parameter to the narrowest `collections.abc` interface the body actually uses —
  `Container` for membership alone, `Collection` if it also iterates or takes `len`,
  `Sequence` only if it indexes — and pass the native container through. Deliberate
  conversions at a serialisation or ownership boundary still stand.
- Use modern type-hint syntax: lowercase built-in generics (`list`, `dict`, `tuple`),
  `X | None` over `Optional[X]`, and `collections.abc` types (`Iterable`, `Sequence`,
  `Mapping`).
- Model categorical values as a `StrEnum` (or another `Enum`), not a bare `str`, so the
  permitted values are explicit and type-checked.
- When a dict's keys and value types are known ahead of time, use a `TypedDict` or a
  dataclass rather than a plain `dict`, or a Pydantic model when you also need runtime
  validation (`python-pydantic` covers how to write one).
- Type-hint module-level constants with `Final`, name them `ALL_CAPS`
  (`MAX_RETRIES: Final = 3`), and prefix module-local (non-exported) ones with an
  underscore (`_MAX_RETRIES`); values local to a function and attributes declared in a
  class body need neither `Final` nor `ALL_CAPS`. Give magic numbers a named constant
  rather than inlining them.
- Don't use `typing.cast()`; fix the underlying type error instead of suppressing it.
- Give values a specific type wherever one fits. For a genuinely untypable value, always
  prefer `Any` over `object` — `object` forces `isinstance`/casts before use and conveys
  no intent, so it is never the better choice. Don't reach for `object` to keep `Any` out.
- `type: ignore` should almost never be used — only for third-party packages with no
  typing or with dynamic typing.
- Don't use runtime reflection — `getattr`, `setattr`, `hasattr`, `delattr`, `vars`,
  `globals`, `locals`, `dir`, `__import__`, `operator.attrgetter`/`methodcaller`,
  `importlib.import_module`, 3-argument `type("N", (), {})`, and the object-graph dunders
  (`__dict__`, `__class__`, `__mro__`, `__subclasses__`, `__globals__`, `__code__`) — or
  `*args`/`**kwargs` passthrough; each defeats static type checking, autocomplete, and
  grep-based refactoring. Ruff cannot enforce most of it, so a green lint run is no
  evidence the code is clean: `python-lint-format` has which tool can reach which form.
  Where a repo ships the hook, it is a hard gate rather than a style preference.
- Extend that reflection ban to any name it doesn't list by asking whether the call
  *produces* or merely *reports*. Producing a namespace, a frame, the object graph, or
  an attribute-by-name is out — `dir()` returns names whose purpose is to be fed back
  into `getattr`, a frame carries its own `f_globals`/`f_locals` so `sys._getframe` and
  `inspect.currentframe` are `globals()` by another road, and `gc.get_referrers` reaches
  any live object at all. Returning a name or metadata is fine: `__name__`, `__file__`,
  `__qualname__`, `inspect.signature`, `inspect.getmembers` (it yields `(name, value)`
  pairs, so nothing has to be looked up afterwards), and a frame *consumer* such as
  `inspect.getframeinfo`, which hands back a filename and a line number rather than a
  live frame.
- Apply produce-or-report to the exact name in front of you, not to its family.
  `itemgetter` is item access and stays while `attrgetter` goes; one-argument `type(x)`
  stays while the three-argument form goes; `inspect` is permitted only in part, so
  "`inspect` is fine" is not the rule.
- Don't use `eval`, `exec`, or `compile` either. That is a separate prohibition from
  reflection — these execute a string rather than reach for an attribute — and ruff
  enforces only the first two (`S307`, `S102`), so `compile` is left to the `ast-grep`
  rule.
- Rewrite a reflection site rather than suppressing it, taking the first rung that fits:
  direct attribute access once the attribute is declared on the type; a typed accessor on
  a shared base class where only some subclasses carry it; `match` on an `Enum` rather
  than a string-keyed attribute lookup; an immutable module-level constant as a dataclass
  default rather than `object.__setattr__` in `__post_init__`; `try`/`except
  AttributeError` only for a third-party object you have confirmed is untyped. Reach for
  `default_factory` only where the default has to be mutable — `@dataclass` rejects a
  `list`/`dict`/`set` default but takes a `MappingProxyType` or `frozenset` as a plain
  one, so an immutable default needs no factory at all.
- "Third-party, therefore untyped" is a claim to check by importing the package, not a
  reason to reach for `getattr`. An attribute that reads as platform-specific is often
  present on every platform and merely returns `False`, and a *missing* type is fixed by
  declaring it rather than by reflecting past it.

## Functions and data modelling

- A class earns its place by owning state its methods read or change, or by being the
  unit of substitution behind a `Protocol` with several methods that have to be
  implemented together. Behaviour needing neither belongs in module-level functions — a
  method that never dereferences `self` is the tell. A dataclass or model that only
  carries data needs no such justification.
- Prefer pure functions: take every input as a parameter and return every result, rather
  than reaching around the call for module-level state or writing back to it. A pure
  function can be tested and reasoned about without first constructing the world it runs
  in.
- Prefer composition to inheritance, and keep any hierarchy you do write to a base plus
  one level — a subclass is coupled to every change its parent makes. `python-pydantic`'s
  *Inheritance* covers models.
- Make invalid states unrepresentable: model data so bad combinations can't be
  constructed — an `Enum` instead of several booleans, a sub-model instead of loosely
  related flat fields, one canonical representation of "empty" — and minimise
  optional/`None`-able fields. Prefer it to runtime validation that patches bad input.
- Don't mutate objects passed in as arguments; copy and return a new value (recreate
  Pydantic models). In-place mutation is a surprising side effect that hampers reasoning
  and testing.
- Make every parameter keyword-only with a leading bare `*` when any of these holds:
  three or more parameters, two or more of the same type, or any boolean parameter
  (prevents argument-order and boolean-trap bugs).
- Apply those same triggers — three or more fields, two or more of the same type, any
  boolean — to a `@dataclass`'s fields, with `kw_only=True`. Its generated `__init__` is
  a function with the same failure mode: transposing two same-typed fields positionally
  still type-checks. It composes with `frozen=True, slots=True`. A Pydantic `BaseModel`
  needs nothing — its `__init__` already refuses positional arguments.
- Group related values that travel together into a named dataclass/model rather than a
  positional tuple, and defer extracting a shared helper until the duplication is real.
- Never return a fixed-length tuple (`tuple[Foo, Bar, int]`, `tuple[float, float]`) — not
  even from a private one-off helper, since neither the call site nor the annotation says
  what each position means. Return a `@dataclass(frozen=True, slots=True)` with named
  fields instead, and annotate a collection of like values as `tuple[X, ...]`. Sort and
  comparison keys are the exception — a tuple is the idiom there.

## Dispatch

- Dispatch on a finite set of values with an explicit mapping or `match`/`case` rather
  than an `if`/`elif` chain.
- One switch is fine; the same switch in a second function is not. When several
  functions in a module branch on the same enum or the same `isinstance` test, pick the
  case once and pass the result: one `Protocol` implementation per case (the unit of
  substitution *Functions and data modelling* allows a class for), or — where the cases
  differ only in data or a single function — a mapping from the discriminator to that.
  Everything downstream receives what was picked and holds no branch of its own.
  The shape is a generic `Protocol`, one implementation per case, and a
  `Final[Mapping]` registry keyed by name. The switch spans the module, but each of its
  tells shows inside one function:
  - **A discriminator passed beside a value that already implies it** — a `message_type`
    parameter next to a `submission` whose type says the same thing, so one of the two
    goes unread or the pair can disagree. Drop it; once the case object exists it
    carries the discriminator as a property.
  - **A parameter only one branch reads** — `rows` threaded through every call, with
    `()` filled in for the case that ignores it. Make it a field of the implementation
    that needs it, and drop it from every shared signature.
  - **An annotated temporary that is only returned** — `verdict: Verdict = await
    send(...)` then `return verdict`, often one name per branch. Return the expression;
    where the annotation is what makes the type checker pass, type the value at its
    source instead.

## Comments and docstrings

**Whether a comment is warranted at all is `docs`'s call, in every language — load that
skill when you write one.** This section adds the Python docstring conventions on top of
its bar.

- Keep comments to an absolute minimum. Achieve readability through meaningful class,
  function, and variable names instead — and prefer extracting a well-named intermediate
  variable over a comment that explains a complex expression.
- Suffix variables and function arguments with their unit of measure where one applies
  (e.g. `timeout_ms`, `payload_size_bytes`, `duration_seconds`), so the name carries the
  unit. A unit is meaning, not type, so it belongs in the name even though a type doesn't.
- Name for meaning rather than implementation: don't encode a variable's type in its name
  (`id_to_name_dict`, `prices_df`) — the annotation already carries it, and the Google
  style guide lists type-in-name under *Names to Avoid*. Write boolean predicates
  positively to avoid double negation, don't use generic module names like `utils.py`,
  and keep acronyms fully upper-case (`HTTPClient`, not `HttpClient`).
- A module or class docstring earns its place only by carrying semantics the name and
  contents don't — a unit convention, an inclusive bound, a cross-field invariant, the
  reason for a representation — or by shipping to a consumer rather than to a reader of
  the code (`python-pydantic` covers the published-schema case). One that restates the
  name ("Configuration for the client") is narration:
  delete it rather than reword it. Most need none; put a CLI's usage narrative in its
  command/argument help (e.g. Typer), not a module docstring.
- Public functions should have docstrings. Parameters only need to be documented when
  the name and type hint don't convey their full semantics.
- Always document non-obvious side effects, the exceptions a function raises, and
  whether numeric range bounds are inclusive or exclusive, even when the parameters
  themselves are self-evident.
- Private functions (single-underscore prefix, per PEP 8) used within a module don't need
  docstrings, unless their names and type hints aren't sufficient to convey their
  semantics.
- A suppression is a last resort, not the first response to a warning: fix the root cause
  so the rule genuinely stops firing, and reach for `noqa`, `type: ignore`, or a coverage
  `pragma` only for a demonstrable false positive or a warning that isn't reasonably
  avoidable. `python-lint-format`'s *Resolving a failure* has the full ladder, including
  when a scoped config-level ignore beats an inline one.
- Link every suppression you do keep to a tracking issue or a one-line justification.

## Imports

- Keep all imports at the top of the module unless an import must be local to avoid a
  circular import.
- Use absolute imports only — no relative imports.
- Don't import private (underscore-prefixed) names across modules; if another module
  needs it, make it public and place it in the module its domain belongs to.
- Keep `__init__.py` files empty: no re-exports; import each symbol from the module that
  defines it. (Exception: deliberately curated public-API packages populate
  `__init__.py` to simplify import paths.)
- Don't add `from __future__ import annotations`; the project's Python version defers
  annotation evaluation already.

## Language idioms

- Use the most modern Python idioms and syntax allowed by the project's minimum
  supported Python version.
- Prefer immutable containers (`tuple`, `frozenset`) for fixed or read-only data,
  including module-level constants; use mutable containers only when the data changes,
  and `default_factory` for any mutable dataclass/Pydantic default.
- Use `pathlib.Path` (not `os`/`os.path`) for filesystem work and as path-argument
  types, and reach for stdlib helpers (`Counter`, `itertools`, `str.removeprefix`, `//`)
  over hand-rolled equivalents.
- Build collections with comprehensions or generator expressions rather than
  loop-and-`append`. Pass a generator (not a materialised list) to one-shot consumers
  like `str.join`, `sum`, or `pd.concat`.
- Use `with contextlib.suppress(...):` instead of an empty `try/except: pass`
  (`python-error-handling` covers when swallowing the exception is right at all).
- Use a float literal wherever a literal meets a float — in arithmetic, in a comparison,
  and in a constraint or default on a float field (`Field(gt=0.0)`, not `Field(gt=0)`),
  where a bare int reads as an int annotation at a glance. Never compare floats with `==`
  (use `math.isclose` or an explicit tolerance).
- Use a plain string literal, not an f-string, when there's nothing to interpolate.
- `sql-data-modelling` owns where a SQL statement belongs — a `.sql` file loaded at
  runtime versus a Python string literal — along with the SQL itself.
- Compare versions with `packaging.version.Version`, not string or tuple comparison
  (which sorts e.g. `0.10` before `0.9`).

## Testing

Test authoring and layout conventions live in the `python-pytest` skill.
