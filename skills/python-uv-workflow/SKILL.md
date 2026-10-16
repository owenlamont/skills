---
name: python-uv-workflow
description: Manage dependencies and run code in uv-based Python projects. Use when adding/upgrading dependencies, running Python code or scripts, bumping the project version, or bypassing the uv dependency cooldown for a security fix.
---

# Python uv Workflow

Standards for working in a [uv](https://docs.astral.sh/uv/) project. Prefer the uv CLI to
manage dependencies and the project version — let it edit `pyproject.toml` and `uv.lock`
rather than hand-editing them.

## Dependencies and running code

Never activate a venv or call `pip`/`python` directly. `uv add` and `uv run` keep deps in
sync across `pyproject.toml` and `uv.lock`; `uvx` touches neither, running a tool in an
environment of its own — so anything that has to import the project's code goes through
`uv run`, not `uvx`:

```bash
uv add httpx2       # add a dependency (uv add --dev for dev-only; uv remove to drop)
uv run pytest       # run a command in the project environment
uvx ruff check      # run a one-off tool, isolated from the project
```

Reach for `uvx --from <package> <command>` where the console script is named differently
from the package — `uvx --from skills-ref agentskills`,
`uvx --from datamodel-code-generator datamodel-codegen`. Plain `uvx <package>` fails there,
and its error lists the commands the package does ship, so read that rather than guess.

## Choosing dependencies

- Declare only packages your code imports directly as first-order dependencies — never
  lean on a transitive dependency.
- Keep linters, profilers, and locally-only tools (`uvicorn`, pytest plugins) in dev
  dependencies (`uv add --dev`), and keep heavy or specialised dependencies out of
  shared core packages so every consumer doesn't inherit them.
- Declare dev and other non-runtime dependencies in PEP 735 `[dependency-groups]` (what
  `uv add --dev`/`--group` write to), not `[project.optional-dependencies]`.

This section is about how a dependency is declared. Whether to take one on at all is
`python-libraries`' *Choosing and maintaining a dependency*.

## Updating and pinning

- Update one package at a time with `uv lock --upgrade-package <pkg>` rather than a
  blanket `uv lock --upgrade`, to keep lock churn reviewable. Other packages the lockfile
  moves alongside a targeted change are fine: don't raise them as a finding or ask for
  them to be reverted.
- Verify the lockfile is current in CI with `uv sync --locked` (or `uv lock --check`).
- Pin only lower bounds in `pyproject.toml` (no upper bound without a documented
  reason), and pin Docker base images to a patch-level tag (e.g. `python:3.13.1`, not
  `python:3.13`).

## Choosing the Python version

Run the latest stable CPython release, and move to a new one once everything you depend
on supports it — the packages, the deployment runtime and the tooling in CI. Confirm what
the current stable release is rather than assuming:
`uv python list` includes pre-releases, so the top line is not it.

Move a repo in one commit — the `requires-python` lower bound in `pyproject.toml`,
`.python-version` (via `uv python pin`), the Docker base image tag and any CI matrix all
on the same minor release, whatever patch precision each of them carries — then
`uv lock` and run the suite.

## Standalone and throwaway scripts

For a one-off script outside the project, declare deps inline with
[PEP 723](https://peps.python.org/pep-0723/); `uv run` builds an ephemeral env from them:

```python
# /// script
# dependencies = ["httpx2"]
# ///
import httpx2
```

```bash
uv run script.py                  # runs in an ephemeral env with httpx2
uv add --script script.py rich    # add a dep to the script's metadata
```

**A `requires-python` in that block does not reach `ruff`.** It sets the interpreter
`uv run --script` picks by default, which `--python` overrides with only a warning, and
it bounds what `uv lock --script` resolves against. What it does not do is set the
formatter's target: `ruff` reads the *project's* `requires-python` instead, so a script
pinned below the project's floor is rewritten with syntax its own interpreter cannot
parse. `python-lint-format` carries the measurement and the fix.

A throwaway with nothing to declare still goes through `uv`, never the system
interpreter. `--no-project` skips syncing whatever project the shell happens to be
standing in, and `--python` pins the interpreter where its version changes the result —
a benchmark, or version-specific behaviour:

```bash
uv run --no-project bench.py                # zero-dependency throwaway
uv run --no-project --python 3.13 bench.py  # pinned; downloads the interpreter if absent
```

## Bumping the project version

`uv version` reads or updates the version in `pyproject.toml` (and re-locks) — use it
instead of hand-editing:

```bash
uv version                 # read current version
uv version --bump patch    # 0.1.0 -> 0.1.1  (also: minor, major)
uv version 2.0.0           # set an explicit version
```

`--bump` also accepts `stable`, `alpha`, `beta`, `rc`, `post`, `dev` (stackable, e.g.
`--bump minor --bump rc` -> `1.1.0rc1`). Add `--dry-run` to preview.

**A branch bumped to `X.Y.0bN` sits below `X.Y.0` the moment the default branch releases
the stable version** — PEP 440 orders every pre-release under the release it precedes —
so merging it walks the version backwards, and a release job that skips when the tag
already exists does so silently. Treat an in-flight branch's bump as stale whenever the
default branch releases: take its `pyproject.toml` and `uv.lock` verbatim when resolving
the merge, and bump once at the end. A release *tag* existing is not evidence the version
reached the default branch either — a tag can point at a feature-branch commit — so ask
with ancestry, `git merge-base --is-ancestor <tag> origin/main`, never the release list.

## The uv cache when disk is short

uv hardlinks packages into the venv, so a cache entry whose only other link is in `.venv`
frees nothing when the cache goes: `uv cache clean` reports the bytes it removed, and the
`df` reclaim can be a small fraction of that. Before clearing a cache a scheduled
`uv run` depends on, run `uv sync --frozen --dry-run` — *Would make no changes* means the
venv already satisfies the lock and the next run fetches nothing — and validate afterwards
with `uv run python <entrypoint> --help`, which exercises the sync and the whole import
graph without starting the real job.

## Bypassing the dependency cooldown for security fixes

The cooldown (`exclude-newer` under `[tool.uv]`, e.g. `"1 week"`) holds back freshly
released versions. To take a newer version for a security fix, exempt only the affected
package(s) — one of the few settings with no CLI equivalent, so edit `pyproject.toml`
directly. A CLI-only `--exclude-newer-package "<pkg>=false"` is **not durable**: the next
`uv lock`/`uv sync` re-resolves and strips it back out.

1. Add or extend the exemption table under `[tool.uv]` (keep existing entries):

   ```toml
   [tool.uv]
   exclude-newer = "1 week"
   exclude-newer-package = { cryptography = false }
   ```

2. Force the upgrade — editing alone won't move an already-locked package — then commit
   `pyproject.toml` and `uv.lock`:

   ```bash
   uv lock --upgrade-package cryptography
   ```

Remove the entry and re-lock once the version is older than the cooldown window.
