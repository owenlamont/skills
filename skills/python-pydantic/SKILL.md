---
name: python-pydantic
description: Write and review Pydantic v2 models to this project's standards — frozen models, Annotated field constraints, validators, aliases at the wire boundary, and pydantic-settings configuration. Use when defining or changing a BaseModel or BaseSettings, choosing field types or writing validators, serialising a model to JSON or a database row, or reviewing a diff that imports pydantic.
---

# Python Pydantic

Standards for Pydantic v2 models — wire formats, API schemas, database records, and
settings. `python-code-style` owns type hints and naming, `python-datetime` owns
timezones; this skill owns the model itself.

Reach for a Pydantic model when a value crosses a boundary and needs runtime validation.
Inside a boundary, a frozen dataclass is the lighter choice — see `python-code-style`.

## Model configuration

- **Freeze new models**: `frozen=True`. Models are values, not mutable records, and
  freezing enforces `python-code-style`'s rule against mutating an argument in place. It
  also makes a model hashable, though only if every field value is itself hashable.
- **`model_copy(update=...)` does not validate the update**, so it will happily build a
  model that violates its own constraints. Use it only for values already validated, and
  re-validate when they aren't: `Job.model_validate(job.model_dump())`.
- Set config as class keyword arguments — `class Job(BaseModel, frozen=True,
  extra="forbid")` — which keeps it visible in the class header. Use
  `model_config = ConfigDict(...)` instead when the config is long, when it carries a
  `json_schema_extra` example, or on a base class meant to be subclassed: subclasses
  inherit and merge it, so none of them has to repeat the shared settings.
- `class Config:` is the Pydantic v1 spelling and is deprecated — so are `@validator`,
  `@root_validator` and `orm_mode`. Replace them on sight with `ConfigDict`,
  `@field_validator`, `@model_validator` and `from_attributes`.
- **`extra="forbid"` wherever both ends of the wire are yours** — request bodies, query
  params, any payload you write and read. A misspelled field then fails loudly instead of
  being silently dropped. `extra="ignore"` is for a reader that must tolerate a producer
  deployed separately from it, such as a queue message written by a newer version of the
  service than the one reading it; say so in a comment, because the default is to forbid.
  Settings are the standing exception — see below.
- **`extra="allow"` is a third case, not a laxer `ignore`**: it *keeps* the unknown
  fields instead of dropping them, so reach for it only where carrying them is the
  model's job — a user-supplied record the model validates a few known keys on and
  passes through whole, to a frontend or another system that reads the rest. That makes
  the passthrough documented behaviour rather than an accident, so say so on the model;
  switching such a model to `forbid` doesn't tighten it, it breaks the callers that
  rely on the extras.
- `from_attributes=True` only on a model built from ORM instances.

## Published schemas

- **A request or response model's class docstring is published**: Pydantic emits it as the
  JSON Schema `description`, and a framework generating an OpenAPI spec copies it into
  `components.schemas.<Model>.description`, so it ships in the spec itself and a generated
  client can carry it into its own models. Write it for the API consumer in CommonMark;
  RST-only markup (a `:func:` role, a `` `text <url>`_ `` hyperlink) renders as literal
  text, while a double-backtick literal renders as code exactly as a single-backtick one
  does. This is the *shipping to a consumer* case that earns a class docstring under
  `python-code-style`'s bar.
- **Don't rely on a model-level description reaching the reader.** Documentation
  renderers differ in whether and where they show one, and a parameters model flattened
  into individual query parameters never becomes a component schema at all. Put anything
  a consumer must not miss in a per-field `Field(description=...)`, which every renderer
  shows.

## Fields carry their own validation

- **Pick a type that already validates before writing a validator**: `AwareDatetime`
  (never bare `datetime` — see `python-datetime`), `UUID4`/`UUID7`, `SecretStr`,
  `HttpUrl`, `PostgresDsn`, `EmailStr`, and a `StrEnum` for any categorical value.
- Every credential, token and password is a `SecretStr`, so it can't leak through a
  `repr` or a log line; call `.get_secret_value()` only where the value is used.
- **Put constraints inside the type — `Annotated[float, Field(ge=0.0)]` — not beside it
  as `x: float = Field(ge=0.0)`.** The constraint stays part of the type, so it survives
  being reused as a type alias and doesn't compete with the default.
- **Never pass a literal ellipsis as `Field`'s first argument.** `Field(...)` is the
  Pydantic v1 spelling of "required"; in v2 a field is required when it has no default,
  and an ellipsis alongside `Annotated` is redundant at best and contradicts an
  `X | None` annotation at worst.
- Constrain floats as `Annotated[float, Field(allow_inf_nan=False)]`: NaN and inf poison
  downstream arithmetic and have no JSON representation. **Not on a FastAPI request
  model** — the 422 echoes the rejected `input`, starlette renders with
  `allow_nan=False`, and the client gets a 500. Check `math.isfinite` in the handler and
  raise the 422 yourself.
- **`strict=True` turns on the wire contract, not on who wrote the producer.** Add it
  where a numeric string is invalid input, so a value that merely parses is rejected.
  Omit it wherever the producer may legitimately send one — including a service of your
  own, since a model serialising a `Decimal` field emits a JSON *string*. Measured on
  pydantic 2.13.5: `Decimal("0.9100")` serialises to `{"ratio":"0.9100"}`, which a strict
  float field rejects with `float_type` while the same field without `strict` parses
  `0.91`. It accepts a JSON integer either way, so that is not the half that bites.
- A mutable default goes through `default_factory`, and so does any default that must be
  computed per instance (`Field(default_factory=lambda: datetime.now(UTC))`).
- Give a field a default only when that default is safe everywhere the model is
  constructed. A value whose absence is a deploy error stays required.
- When the same constraint recurs across models, make it a custom type with
  `__get_pydantic_core_schema__` rather than repeating a validator.
- Tag a field holding one of several model shapes with a discriminator —
  `Field(discriminator="kind")` — so Pydantic picks the variant from that tag instead
  of trying each in turn and reporting a union of every failure.

## Validators

- Write `@classmethod` directly beneath `@field_validator`. Pydantic applies it for you
  at runtime, so omitting it works and is exactly why it gets omitted — but the type
  checker then reads `cls` as an instance and types the whole validator wrongly.
- A `@model_validator(mode="after")` is an **instance method** returning `Self`, not a
  classmethod; writing it as one is deprecated and slated to break.
- Default to `mode="after"`, where the value is already parsed and typed. `mode="before"`
  is for raw input that must be reshaped before it can be typed at all.
- **Raise `ValueError` from a validator**, not a domain exception. Pydantic collects only
  `ValueError`, `AssertionError` and `PydanticCustomError` into a `ValidationError`
  carrying the field path — reach for `PydanticCustomError` when the caller needs to
  branch on an error code rather than read a message. Any other exception propagates raw
  and loses the field path with it. Catching it at the boundary is
  `python-error-handling`'s business.
- Stack `@computed_field` above `@property` for a value derived from other fields, so it
  serialises. Put any suppression on the `@computed_field` line itself, not the `def`,
  and link the tracking issue, per `python-code-style`.
- Prefer a `model_validator(mode="after")` over cross-field checks scattered through
  callers, and prefer making the invalid state unrepresentable over either.

## Aliases at the wire boundary

The consumer decides the alias, not the layer. Don't alias an internal model — a queue
payload, a service-layer value — for naming convenience.

**An alias that adapts a name already written down is load-bearing: never drop it.** A
field carrying `Field(alias="interval")` because that is the attribute name in the
records already stored is not a rename you can undo — removing it makes every existing
record fail validation with the field missing. The same holds for an upstream's own field
names. A model with such an alias needs `populate_by_name` so both spellings construct it.

- A model serialised for a **JavaScript or TypeScript frontend** gets camelCase, applied
  once as `alias_generator=to_camel` (from `pydantic.alias_generators`) with
  `serialize_by_alias=True` and `populate_by_name=True` — not a per-field `alias=`
  repeated down the class.
- Per-field `alias=` / `serialization_alias=` is for the names a generator can't produce:
  an upstream's own casing (`SITEID`, `URL`) or a unit suffix it would mangle
  (`totalBytesMB`, which `to_camel` renders `totalBytesMb`).
- Field names themselves stay snake_case whatever the alias — the alias is the wire
  spelling, not a rename.

## Settings

- Configuration is a `pydantic-settings` `BaseSettings` subclass, never a direct
  `os.environ` read. Subclass the project's own base — one that sets `frozen=True`,
  `env_nested_delimiter="__"` and the `.env` file — and scope each group with
  `env_prefix=`.
- Give every settings field a `Field` carrying a `description` — it is the only
  documentation an operator setting the environment variable gets.
- A new settings field also lands in the repo's `.env.example`, with a comment line
  carrying that same description. The `Field` documents it to whoever reads the model;
  the example file is what an operator copies, and a field missing from it is invisible
  to them. Where the repo keeps no `.env.example`, add the variable to whatever
  environment reference it does keep — and where it keeps none, say so on the pull
  request rather than creating a file as a side effect of an unrelated change.
- Nest a settings group as a field with `default_factory`, so `DATABASE__URL` resolves
  through the delimiter rather than needing a flat name per field.
- Settings are `extra="ignore"`, the one standing exception to `extra="forbid"`. A
  `.env` file is handed to the model whole, so every key in it that isn't a field of
  *this* settings group is an extra — under `forbid`, one shared `.env` across several
  groups fails them all at startup. Ambient environment variables are not the reason:
  the env source only reads names matching a field.
- Reach for `settings_customise_sources` when a value comes from somewhere Pydantic
  doesn't know about, such as a secret manager; ordering the sources is what decides
  precedence.

## Serialisation

- Dump with `model_dump()` / `model_dump_json()`; never hand-build the dict.
- Convert at the boundary with `@field_serializer`, keeping the field itself typed as the
  domain type — a store with no float type takes them through `Decimal`, for instance.
  Pass `when_used="unless-none"` on a serialiser for an optional field, or it gets handed
  a `None` it isn't typed for.
- Validate a non-model value with a module-level `TypeAdapter` (`TypeAdapter(EmailStr)`)
  rather than wrapping it in a single-field model or a `RootModel` — annotate the value
  with `Annotated` and let the adapter validate it. Build the adapter once; constructing
  one per call rebuilds the schema.

## Inheritance

- Subclass to share fields, and never redefine an inherited field — the redefinition
  silently wins and the two drift.
- Keep hierarchies shallow. Beyond a base plus one level, the fields of any given model
  stop being readable in one place.
- Don't build a Base/Create/Update/Response/InDB ladder. Name models for what they are on
  the wire, and let a request and a response model share a base only when they genuinely
  share fields.
