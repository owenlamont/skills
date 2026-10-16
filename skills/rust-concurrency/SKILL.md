---
name: rust-concurrency
description: Write concurrent Rust to this project's standards — picking between rayon, threads, channels and shared state, keeping a dispatch loop responsive, and getting atomic orderings right. Use when parallelising work with rayon, spawning threads, passing values over channels, reaching for Arc and Mutex or an atomic, deciding a memory ordering, keeping parallel output deterministic, or diagnosing a deadlock, a stale result or an ordering flake.
---

# Rust Concurrency

Standards for concurrent Rust in this project. `rust-code-style` carries general Rust
style; this is what changes once more than one thread is involved.

## Pick the mechanism from the shape of the work

- **Rayon for finite, CPU-bound, data-parallel work over a collection** — parallel
  iterators, `map`/`filter`/`collect`, and reductions. Its pool assumes jobs finish.
- **`std::thread` for a long-lived service loop, or for blocking ownership of a
  resource.** Parking such work on rayon's shared pool starves every other job on it, and
  a lifetime that outlives one data-parallel job wants an explicit thread and an explicit
  owner.
- **Channels where a worker can own its input and send an owned result back.** Message
  passing transfers ownership, which is by a wide margin the cheapest concurrency to
  reason about — there is no shared state to get wrong.
- `Arc<Mutex<T>>` only where several threads genuinely mutate one shared object. Keep the
  critical section to the mutation itself, never around the work that produced the value.
- **Don't accumulate independent parallel results into an `Arc<Mutex<Vec<_>>>`.** Use a
  parallel `map`/`collect` or a reduction: serialising the writes puts contention back
  into work that had none, and it is the most common way a rayon speedup disappears.
- One intentionally configured pool, not several CPU-sized worker sets that oversubscribe
  each other. Where the global rayon pool is wrong for the workload, configure it rather
  than building a second one beside it.

## Keep the dispatch loop responsive

- **A thread that owns a request, protocol or event loop must not run expensive work
  inline.** Every message behind it waits, and the symptom is latency on unrelated
  requests rather than on the slow one. Hand the work to a pool and deliver the result
  back through a channel or an event queue.
- **Mutable session state stays owned by the coordinator; workers get owned inputs or
  immutable snapshots and return values.** That is a sharper rule than "message passing
  versus `Arc<Mutex<_>>`", and it decides most of the design on its own.
- **Tag background work with the generation or version of the state it read, and discard
  a result that is stale when it lands.** Concurrent work legitimately finishes out of
  request order, so publishing whatever arrives last is a correctness bug that only shows
  up under load.
- Holding a lock or guard across an `if let` and its `else` is worth re-reading under
  edition 2024, which drops the scrutinee temporary *before* the `else` branch — the
  guard's lifetime differs from edition 2021 with no diagnostic.

## Determinism is part of the contract

- **Parallelism must not reach user-visible ordering** — but know which paths already
  guarantee it before adding a sort. Rayon's `collect()` into an ordered container
  preserves *input* order, `filter_map` included, so a `par_iter().collect()` needs no
  re-sort and adding one hides that the guarantee was there.
- **What loses order is completion order**: `for_each`, pushing into a shared sink,
  `par_bridge`, and collecting into a `HashSet`/`HashMap` and iterating it. On those
  paths, carry an index through the parallel stage and sort by it at the end, or collect
  and reorder — before printing, snapshotting, or publishing anything a person or a test
  will compare.
- A test asserting on parallel output asserts on the sorted form. An ordering test that
  flakes is the design leaking into the test, not a flaky test to retry.

## Atomics

- **Prefer a mutex or a channel over atomics for anything with more than one field, or
  any state machine.** Ordering controls memory visibility between threads; it does not
  protect a higher-level invariant that spans two values.
- `Relaxed` only where the atomic value is the entire fact being communicated — an
  independent counter, a cancellation hint — and publishes no other memory.
- `Release` to publish other memory and `Acquire` to consume it; `AcqRel` for a
  read-modify-write that does both; `SeqCst` where the algorithm genuinely depends on one
  global order, or where its stronger model makes a small protocol provable.
- **Every non-trivial atomic protocol carries a comment saying what synchronises with
  what.** Correctness follows from the happens-before requirement you can state, so
  "weaker is faster" is not a justification for weakening one — and an ordering nobody can
  explain is one nobody can review.

## Threads change what is safe elsewhere

- `std::env::set_var` and `remove_var` are unsafe in edition 2024 precisely because a
  process environment cannot be mutated soundly while other threads run. Set the
  environment at process launch, or thread the value through as a parameter. Where tests
  need to vary it, inject an environment abstraction rather than mutating the real one.
- An error crossing a thread, channel or rayon boundary needs `Send + Sync + 'static`.
  Design the error type for that at the boundary rather than discovering it at the call
  site and erasing to `String` to get past the compiler.
