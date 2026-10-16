---
name: python-async
description: Write asyncio Python to this project's standards — concurrent coroutines, async-all-the-way, and safe handling of errors from concurrent tasks. Use when writing async/await code, gathering coroutines, designing async FastAPI endpoints or clients, or handling failures from concurrent work.
---

# Python Asyncio

Standards for concurrency with `asyncio`.

## Run independent work concurrently

- Never `await` independent coroutines one at a time in a loop — that runs them serially
  and is a performance red flag. Schedule them together so they overlap.
- Use `asyncio.TaskGroup` for fail-fast semantics — the first error cancels its siblings.
  Plain `asyncio.gather` lets the siblings run on (the first exception still propagates),
  while `gather(..., return_exceptions=True)` returns every result, exceptions included.
  The choice is about error propagation — document it when it isn't obvious.
- Bound fan-out with an `asyncio.Semaphore`: unbounded concurrency usually exhausts host
  memory (the more common failure) and can open too many connections to a downstream
  service. Expose the limit as a service setting so it can be tuned without a new release.
- Sequentially awaiting paginated pages (each request needs the previous page's cursor)
  is the legitimate exception — keep it rare and flag it with a comment.

```python
import asyncio
from collections.abc import Sequence


async def fetch_all(record_ids: Sequence[str]) -> list[Record]:
    semaphore = asyncio.Semaphore(10)

    async def fetch_one(record_id: str) -> Record:
        async with semaphore:
            return await client.get(record_id)

    async with asyncio.TaskGroup() as task_group:
        tasks = [task_group.create_task(fetch_one(rid)) for rid in record_ids]
    return [task.result() for task in tasks]
```

## Async all the way down

- In FastAPI, mark an endpoint `async def` only if it awaits real async I/O (an async DB
  driver) — not if it makes blocking calls. A
  blocking call inside an `async` endpoint stalls the event loop; either make it genuinely
  async or leave the endpoint a plain `def` so the framework runs it in a threadpool.
- Don't mark a function `async def` if it never awaits — it gains no concurrency, misleads
  readers, and can be marginally slower.
- Create async clients, sessions, and connection pools once at startup and inject them;
  constructing them is costly enough to outweigh the gain from concurrency if done per
  request.
- Deploy asyncio services on `uvloop`, a faster drop-in event loop; the built-in loop is
  fine for local runs and debugging but slower in production.

## Errors from concurrent tasks

- `asyncio.TaskGroup` raises an `ExceptionGroup` on failure and cancels siblings — prefer
  it when you don't need to salvage the results of the siblings it cancels.
- With `gather(..., return_exceptions=True)`, inspect every result: immediately re-raise
  anything that is a `BaseException` but not an `Exception` (`asyncio.CancelledError`,
  `SystemExit`), and collect the plain `Exception`s into an `ExceptionGroup` to raise
  together. Never swallow a `BaseException` with a bare `continue`.
- Bound polling and retry loops with a max iteration count or an `asyncio.timeout`, so a
  loop can't run forever when its condition never becomes true.

See `python-error-handling` for catching the narrowest type and custom exceptions.
