---
name: rust-code-style
description: Write Rust source to this project's standards — errors, ownership and borrowing, iterators, traits, visibility, module layout, naming, and the unsafe boundary. Use when authoring or reviewing Rust, and when choosing an error type, deciding what a signature borrows or owns, weighing a trait against an enum, setting visibility, placing a module, naming an item, or reaching for unsafe.
---

# Rust Code Style

Standards for writing Rust source in this project. `software-engineering` carries the
language-neutral half and `docs` sets the bar for whether a comment is warranted at all;
this skill is what those two leave to Rust.

## Read the toolchain before writing against it

- **`Cargo.toml`'s `edition` and `rust-version` are the ceiling, not the toolchain you
  happen to have installed.** Read both before writing anything. A local build proving
  your code compiles says nothing about the MSRV gate, because the installed stable is
  routinely newer than the pin. Rules below that depend on an edition say which.
- **Set `rust-version` in `Cargo.toml`.** Clippy reads it as the default MSRV for
  MSRV-sensitive lints, so it is load-bearing rather than documentary. Where a
  `clippy.toml` carries an `msrv` key that merely restates the pin, delete the key — two
  places to keep in step is one too many, and Cargo's is the one Clippy prefers.
- Keep `rust-version` in step with the channel pinned in `rust-toolchain.toml`.

## Errors

- **A concrete error enum at every subsystem or library boundary**, normally derived with
  `thiserror`. Reserve `anyhow::Result` for top-level binary orchestration whose callers
  only report and propagate. The split is the settled ecosystem position, not a
  preference: typed errors preserve what a caller would branch on, and erasure removes it.
- Don't return `anyhow::Error` from an API whose callers could reasonably recover
  differently from different failures — that is precisely the information erasure throws
  away. Don't use `Box<dyn Error>` as the routine application error type either.
- **Preserve the cause chain through `Error::source()`, and make the wrapper's `Display`
  add context rather than restate the source's message.** A reader who walks the chain
  sees both, so a wrapper that repeats its source reads as the same failure twice.
- `#[from]` only where the source type alone determines the variant. The moment a path,
  span, URI or rule id belongs on that variant, construct it explicitly or use `map_err`:
  a `#[from]` variant holds the source and an optional backtrace, and cannot carry the
  context that makes the error diagnosable.
- `#[error(transparent)]` marks a deliberate pass-through wrapper — it delegates both
  `Display` and `source()`. It is not a way to skip writing a message.
- Error `Display` text starts lowercase and ends without punctuation, so it composes into
  a caller's larger message.
- **An expected in-domain outcome is not an `Err`.** Lint findings, diagnostics, misses
  and "not found" that callers routinely handle are values in the success type. `Err`
  means the computation could not be performed at all.
- `Result` for anything recoverable from input, the filesystem, or a peer; panic only for
  a violated internal invariant. Write an `expect` message as the invariant that makes it
  unreachable, not as "should not happen".
- An error crossing a thread, channel or rayon boundary needs `Send + Sync + 'static`.
  A bare `dyn Error` promises neither, so erased errors there are
  `Box<dyn Error + Send + Sync + 'static>` or an error type that already requires both.
- Stale, and still common in generated code: `Error::description()` and `Error::cause()`
  are deprecated — write `Display` and walk with `source()`. `Error::provide` and
  `dyn Error::sources()` are **not** stable; confirm against the std docs for your pinned
  version before writing against either.

## Ownership and borrowing

- **`&str` when a function only reads the text for the duration of the call; `String`
  when it stores or consumes it.** The signature is where ownership is documented, so an
  owned parameter the body only reads is a false claim, not a harmless one.
- `impl Into<String>` belongs at a constructor or public edge that genuinely takes
  ownership. Internally take `&str` or `String`. It is an anonymous generic parameter,
  not free ergonomics, and it hides where the allocation happens.
- `impl AsRef<Path>` or `impl AsRef<str>` at a convenience boundary accepting several
  reference-like forms. Don't thread `AsRef` down internal call chains.
- **`Borrow<T>` is not a fancier `AsRef<T>`.** Reach for it only where the borrowed form
  must hash and compare identically to the owned one — the property that lets a map be
  keyed by `String` and looked up by `&str`.
- `Cow<'_, str>` only where borrowing is the normal path and some branches genuinely
  produce owned text. Don't take a `Cow` parameter merely to accept both `String` and
  `&str`; a borrowed parameter says that more directly.
- Return `impl Iterator<Item = T>` and let the caller decide. Collect into a `Vec` only
  for indexing, sorting, repeated traversal, or to decouple from a borrow.
- Pass small `Copy` values by value rather than by `&T`.
- **Newtype a primitive where two values share its representation but not its
  meaning** — ids, units, offsets in different coordinate spaces — and could be swapped
  without the compiler noticing. The test is whether a mix-up is plausible and currently
  silent, not whether the representation happens to be a primitive. Don't newtype every
  integer; don't newtype where a library type already draws the distinction.
- **Edition 2024**: don't add `+ '_` or a capture-helper trait to make an `impl Trait`
  return capture input lifetimes. In-scope generics are captured automatically, and
  `use<..>` narrows it where you actually need less.

## Iterators and control flow

- Iterate elements rather than `0..v.len()` where the index exists only to index that one
  slice. `.enumerate()` when the position is genuinely needed, `.zip()` for lockstep over
  independent sequences, `windows` / `chunks` / `chunks_exact` for grouped runs.
- Keep explicit indexing where the index carries domain meaning, random access is the
  point, several structures share it, or **the borrow checker requires it** — iterating
  `self.items` immutably while the body needs `&mut self` is the common case, and a
  range loop is the honest fix there, not a lapse. "Never index" is not the rule;
  eliminating *incidental* indexing is.
- `let PATTERN = expr else { ... };` for a required pattern whose failure immediately
  diverges. It keeps the bindings in the enclosing scope, which a one-arm `match` cannot.
- **Edition 2024**: use a let-chain where each condition reads left to right off a
  binding made to its left. Break it into named locals or a `match` as soon as it stops
  reading as a single guard — the feature removes nesting, which is not a reason to
  merge unrelated decisions into one condition.
- `match` still owns genuine multi-way exhaustive decisions; `let ... else` and
  let-chains supplement it rather than replacing it.
- **Edition 2024**: an `if let` scrutinee temporary is dropped *before* the `else` branch
  runs, unlike edition 2021. Re-check any lock or guard held across that boundary — this
  is the change most likely to silently alter behaviour in ported code.
- Propagate recoverable errors with `?`.
- **Neither combinators nor `for` loops are inherently more idiomatic.** Combinators for
  transforming and composing data; `for` where the body is imperative control flow with
  breaks, early returns or side effects. `.for_each()` over a plain `for` loop is a
  downgrade, not a modernisation.

## Traits and generics

- **Start concrete.** A trait earns its place at a real abstraction boundary: several
  implementations, a generic algorithm over them, a seam for a substitutable external
  dependency, or deliberate type erasure. One implementation and no generic consumer
  means an inherent method or a free function.
- **Prefer an enum where the set of cases is closed and callers exhaustively branch.** A
  trait advertises open extension, and a closed set behind one is a contract you did not
  mean to offer.
- Generics and `impl Trait` where the concrete type is known at compile time; `dyn Trait`
  where implementations are heterogeneous, chosen at runtime, or where cutting
  monomorphisation matters. Dynamic dispatch is a tool, not a smell.
- **Check *dyn compatibility* against the current Reference before exposing `dyn Trait`,
  rather than recalling the old "object safety" rules.** The term changed and so did some
  of the detail; a method returning `impl Trait`, which includes any `async fn`, is not
  dispatchable.
- Seal a public trait that downstream crates must not implement, so it can still evolve.
- Use a GAT where an associated type is genuinely a family parameterised by a lifetime or
  type. Don't carry a pre-GAT workaround, and don't reach for one without that shape.
- `async fn` in traits being stable is not a reason to make a synchronous architecture
  async. If a public async trait is ever required and callers need the returned future to
  be `Send`, state that bound explicitly — bare `async fn` does not let them add it.
- Don't flip a public parameter between `T: Trait` and `impl Trait`. They are nearly
  equivalent inside the function and not equivalent to a caller passing explicit generic
  arguments.

## Public API and visibility

- **Private by default.** `pub(crate)` where the crate genuinely needs it, `pub(super)`
  where only the parent subsystem does, and plain `pub` only for a deliberate external
  contract. In a binary-heavy package, `pub` on an internal item hides dead code from the
  compiler as well as overstating the API.
- Keep public struct fields private unless literal construction is part of the contract
  you are offering. Private fields keep the representation changeable.
- **`#[non_exhaustive]` on a public enum goes on at creation, not later.** Adding it to
  an already-published exhaustive type can break downstream matches and construction,
  so it is a compatibility decision made once, up front, for enums expected to grow.
  Don't decorate crate-private enums with it — it does nothing inside its own crate.
- **Check Cargo's SemVer compatibility chapter before changing a public signature, field
  set, trait, bound or trait impl.** "Adding things is safe" is wrong often enough to be
  dangerous: coherence, inference, exhaustiveness and construction all have hazards that
  look purely additive.
- A builder where construction has several independent optional settings; a plain `new`
  for two required values. Where `new()` takes no arguments and the empty value is an
  unsurprising default, implement `Default` too.
- Replace several positional `bool` parameters with a named enum or an options struct —
  at the call site `f(true, false)` carries no meaning.
- `#[must_use]` where discarding the value is very likely a caller bug, not on every pure
  function.
- A public `-> impl Trait` promises exactly the bounds you name and nothing else. Those
  bounds are API surface, so name the ones you intend to keep.

## Modules

- New modules are `foo.rs` beside `foo/bar.rs`, not `foo/mod.rs`. **`mod.rs` is
  supported, not deprecated** — don't churn existing modules or vendored layouts to
  match, and don't treat encountering one as a defect.
- Split a module when it holds separable responsibilities, or when its public boundary
  becomes hard to state. Not at a line count — Rust has no normative module size.
- No `extern crate` for ordinary dependencies.
- `crate::` for non-local internal paths; `self::` or `super::` where the relative
  position is itself meaningful.
- Re-export from a façade only where that path is the one callers are meant to name. A
  re-export is API surface like any other item.

## Naming

- `UpperCamelCase` for types and traits, `snake_case` for functions, modules and locals,
  `SCREAMING_SNAKE_CASE` for consts and statics.
- **Acronyms are words**: `YamlParser`, `LspServer`, `HttpClient` — never `YAMLParser`.
- `new` for the canonical constructor; `with_*` for variants that differ by configuration.
- Getters take the field's name — `name()`, not `get_name()`. `get` is for keyed or
  indexed lookup, where it means something.
- `as_` for a cheap borrowed view, `to_` for a converting copy that keeps the receiver,
  `into_` for a conversion that consumes it. The prefix is the caller's only signal about
  cost and ownership, so it has to be accurate.
- `iter` / `iter_mut` / `into_iter` for shared, mutable and owning iteration; name public
  iterator types `ThingIter`, `ThingIterMut`, `ThingIntoIter`.
- `Error` where a module has one obvious error type; `ParseError`, `ConfigError` and the
  like where several error domains meet in one scope.
- **Judge a type's name at the use site, not inside its own module.** `config::Error`
  reads right where callers path-qualify it; `ConfigError` reads right where they import
  the bare name into a scope that already holds other error types. Repeating the module's
  concept is a defect in the first case and correct in the second, which is the judgement
  `clippy::module_name_repetitions` cannot make.

## Unsafe

- **`#![forbid(unsafe_code)]` at every first-party crate root meant to stay safe.**
  `forbid` cannot be lowered by a local `allow`, which is the whole point — the boundary
  can't erode one exception at a time.
- **That is a claim about this crate, not about the dependency graph.** Safe abstractions
  over audited unsafe are what dependencies are for, so don't describe the crate, or let
  a review report it, as "no unsafe anywhere".
- Don't reach for unchecked indexing, raw pointers or intrinsics on a speculative
  performance argument. Where safe Rust is *measured* too slow, change the algorithm,
  the data layout or the allocation pattern, or adopt an established safe abstraction,
  before treating the safety boundary as the thing to move.
- If a requirement genuinely needs unsafe, contain it in a separate minimal crate with
  its own audit policy rather than weakening this crate's `forbid`.
- **Edition 2024**: `std::env::set_var` and `remove_var` are unsafe, because concurrent
  environment mutation cannot be made sound. Material showing them as ordinary setup code
  predates that. Set the environment at process launch, or thread the value through.
- **Edition 2024**: direct FFI requires `unsafe extern`, and `static_mut_refs` denies
  references to a `static mut`. Both are boundaries to route around rather than open.
- Where unsafe is genuinely written: each operation goes in its own `unsafe {}` block
  **even inside an `unsafe fn`**, carries a `// SAFETY:` comment naming the invariant
  that discharges it, and the public item carries a `# Safety` section stating what the
  caller must uphold.

## Doc comments and suppressions

`docs` decides whether a comment is warranted; these are the Rust-specific parts it
leaves open.

- `///` for items, `//!` for the crate or module. **Whether a public item needs one is a
  judgement, not a quota** — a self-documenting signature often needs none, and enabling
  `missing_docs` converts that judgement into a requirement to write something. Turn it
  on only where a documented public API is genuinely the deliverable.
- `# Errors` on a public `Result`-returning function whose failure conditions are not
  self-evident, and `# Panics` where reachable caller input can panic.
  `clippy::missing_errors_doc` enforces the first mechanically — satisfy it minimally
  rather than padding it into prose.
- Make public examples runnable doctests, so they are compiled and executed rather than
  merely plausible.
- **Prefer `#[expect(lint, reason = "...")]` over `#[allow]`.** `expect` warns once the
  suppression stops being needed, so a fix elsewhere retires it instead of leaving a
  stale exemption behind; `allow` is silent forever. Keep `allow` only where the lint
  genuinely fires intermittently — a `cfg`-gated or feature-gated item, where `expect`
  would warn in the configuration that doesn't trip it.
- **Every suppression carries `reason = "..."` and sits on the smallest item that needs
  it.** A trailing `//` comment beside the attribute is not the same thing: it satisfies
  no lint and the next reader has no reason to trust it is still current. Enable
  `clippy::allow_attributes_without_reason` and `clippy::allow_attributes` — both are in
  the `restriction` group, so `pedantic` alone does **not** turn them on — and the rule
  becomes mechanical rather than remembered. An unexplained suppression is policy erosion
  no reviewer can weigh, and a crate-wide one silently covers code written years later.

## Lints and formatting

- **Clippy `pedantic` on, with a short explicit allow-list at the crate root** rather
  than suppressions scattered through the source. The usual candidates encode style
  preference rather than correctness signal — `clippy::module_name_repetitions` (whose
  judgement *Naming* above makes at the use site instead), `clippy::similar_names`,
  `clippy::too_many_lines` and `clippy::must_use_candidate`.
- **Don't allow away the cast lints, `needless_pass_by_value`,
  `trivially_copy_pass_by_ref`, `missing_errors_doc`, or the error-pattern lints.** Those
  carry real correctness signal — narrowing and sign-loss conversions especially, where
  the failure is a silently wrong value rather than a compile error.
- Don't enable `clippy::nursery` wholesale under `-D warnings`; name the nursery lints
  you want. Group membership changes between releases, and under `-D warnings` that turns
  a toolchain bump into a build break.
- **Under `-D warnings`, a toolchain bump is a lint-policy change.** Make it a deliberate
  step with its own review, not a side effect of a CI image moving.
- Accept rustfmt's output rather than hand-aligning around it, and keep `rustfmt.toml` to
  stable options — unstable ones require nightly, which a pinned stable channel rules
  out. Set `edition` there as well as in `Cargo.toml`.
