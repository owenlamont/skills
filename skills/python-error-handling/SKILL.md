---
name: python-error-handling
description: Handle errors in Python to this project's standards — custom domain exceptions, narrow catches, and failing fast. Use when raising or catching exceptions, writing try/except, designing an exceptions module, or deciding whether to swallow or propagate an error.
---

# Python Error Handling

Standards for raising, catching, and modelling exceptions.

## Custom exceptions

- Define domain exceptions in a dedicated `exceptions` module and raise those rather than
  bare `ValueError`/`RuntimeError`/`Exception`, so call sites can catch precisely.
- **A Pydantic validator is the standing exception**: raise `ValueError` (or
  `PydanticCustomError`) there, because those are what Pydantic collects into a
  `ValidationError` carrying the field path. A domain exception propagates raw out of
  validation and loses it — see `python-pydantic`.
- Subclass `Exception`, not a built-in like `ValueError` — inheriting from `ValueError`
  means existing `ValueError` handlers silently swallow your exception, which is rarely
  what you want.
- Keep the hierarchy flat — a handful of specific exceptions, optionally sharing one
  package-level base class, not deep chains you must trace to know what a catch catches.
- Name each exception for the failure it represents (`RequestTimeoutError`) and build
  its message from the offending values, so the logged event is self-contained.

## Catching exceptions

- Catch the narrowest exception type you actually handle. A broad `except Exception` is
  the `Any` of error handling — it swallows the unexpected and programmer errors (a
  `KeyError`, a `PermissionError`) that should propagate instead.
- A broad `except Exception` is only correct at a top-level entry point — a
  long-running loop or a CLI's `main` — as a last resort that reports and re-raises (or
  exits non-zero), so nothing is lost silently.
- Keep `try` blocks down to the line or two that can actually raise, so it's obvious which
  call is guarded.
- Write a deliberate swallow as `with contextlib.suppress(SpecificError):`, never an
  empty `try/except: pass` — the suppression is then visible at the call site, and the
  narrow-catch rule above governs what you name in it. Suppress only where the failure
  genuinely has no consequence; otherwise handle it or let it propagate.
- Don't catch an exception only to log it and carry on — either handle it (recover) or let
  it propagate. And don't log at an intermediate catch when it still bubbles to a handler
  that logs: log it once, where it's acted on.
- Where a caught exception is recorded, attach the exception itself (`logger.exception`,
  or `exc_info=True`), never `str(exc)` alone. For the transport errors that dominate an
  HTTP client, `str(exc)` is the **empty string** — measured on httpx: `ReadTimeout`,
  `ConnectTimeout`, `ConnectError`, `WriteTimeout`, `PoolTimeout` and
  `RemoteProtocolError` all stringify to `''` — so a log line built from it at an
  `except Exception` site carries no diagnostic content at all, and nothing warns you.

## Fail fast

- Raise on impossible or coding-error states instead of logging-and-continuing or
  returning `None`. A reached "can't happen" branch is a bug; make it fail loudly.
- Let library failure checks fire: `subprocess.run(..., check=True)`,
  `response.raise_for_status()`, and the like — don't discard return codes or statuses.
- When a 1:1 lookup could return zero or many rows, assert exactly one with
  `more_itertools.one()` rather than silently taking the first.
- Be consistent across sibling functions: a set of lookups should all raise on "not
  found" or all return `None`, never a mix. Prefer raising, so callers can't forget to
  check.
- Better still, model data so impossible states can't be constructed — see "make invalid
  states unrepresentable" in `python-code-style`.

## Log severity

- Calibrate severity to recoverability: reserve `critical` for unrecoverable failures that
  end the process, `error`/`exception` for failures needing attention, `warning` for a
  recovered or degraded path, `info` for normal events. Don't log at `error` for something
  you handled, nor bury a real failure at `warning`.
