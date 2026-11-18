---
name: dependency-adoption
description: Decide whether to take on a new third-party dependency, and record the evidence in the pull request. Use before `uv add`, `pnpm add` or a new PEP 723 dependency; before adding or changing a workflow `uses:`, a Dockerfile `FROM`, a prek hook `repo`/`rev`, a Terraform module `source` or provider, or a `curl | sh`, `npx`, `pnpm dlx` or `uv tool install` command committed to a repo; and when choosing between candidate libraries or reviewing a diff that adds one. Covers the hard gates (cooldown, advisories, licence, pinning), the review triggers that need a written judgement, and how each surface is pinned.
---

# Dependency adoption

Every new dependency is code you run with your credentials. Admit it on evidence: the
bundled script collects the facts, you write the judgement, and both go in the PR body.

## What a change owes

- **A newly adopted third-party package, Action, image, hook, Terraform module or
  installer** owes every gate, the evidence record and the judgement lines below.
- **A changed version or `rev` of one already adopted** owes the hard gates, which the
  script checks for PyPI, npm and Actions, but not the judgement lines. Treat it as new
  when the package name, `owner/repo` or image name changes.
- **A dependency already adopted in another repo you maintain** owes the hard gates
  and a link to the earlier adoption PR —
  `gh search prs --owner <owner> "Dependency evidence: <PyPI|npm|action> <name>"` —
  or to a repo already using the dependency. Repeat the judgement lines only when the
  use differs: the dependency now ships to a browser or customer, or handles
  credentials.
- **The gates bind the references the PR adds or changes.** Leave existing references
  alone; add a missing repo-wide setting (`exclude-newer`, `minimumReleaseAge`,
  `trustPolicy`, a Dependabot `cooldown`) when the PR touches that ecosystem.
- Bypassing the uv cooldown for a security fix follows `python-uv-workflow`.

## Necessity first

- Apply `software-engineering`'s dependency trade before anything here: a dependency
  must shrink the code you maintain or solve a genuinely hard problem.
- **Copy the package name from the upstream project's own README or repository, never
  from memory or a model's suggestion.** A plausible package name that doesn't exist, or
  belongs to someone else, is how typosquats and slopsquats get installed.

## Collect the evidence record

The script covers PyPI, npm and GitHub Actions, reusable workflows included. **Lock
before you install, so no unreviewed code runs:** `uv add --no-sync --no-build <name>`;
for a PEP 723 script, `uv add --no-build --script <file> <name>` then
`uv lock --no-build --script <file>`, since the add alone writes no lock; or
`pnpm add --lockfile-only <name>`. Then assess the version the lockfile resolved, and
install only once it passes. Paste the output into the PR body; the output is a
collapsed `<details>` table, so the visible body carries only your judgement lines:

```sh
uv run --script <skill-dir>/scripts/assess_dependency.py pypi <name> --version <locked>
uv run --script <skill-dir>/scripts/assess_dependency.py npm <name> --version <locked>
GH_TOKEN=$(gh auth token) uv run --script <skill-dir>/scripts/assess_dependency.py action <owner/repo[/path]@ref>
```

- **`fail` is a hard gate**: don't adopt until it passes, or until an exception is
  approved (see *Exceptions*). The exit status is 1 when anything fails.
- **`review` needs a sentence in the PR** saying what you checked and why it is
  acceptable.
- **`--no-build` covers non-editable registry packages only**: it fails rather than
  build one that ships no wheel. uv still builds the project itself and its workspace
  members to read dynamic metadata, and refuses a local, editable or Git dependency
  with dynamic metadata, which runs its build backend once the flag is dropped. Review
  any of those as source before resolving.
- **The licence row grades code as bundled.** Ignore it for a tool run as a separate
  process; for weak copyleft that ships to a browser or a customer, its `review` is a
  `fail` until an exception is approved.
- Run the script on public packages only: it sends the name to PyPI, npm, OSV and
  GitHub.
- **New transitive packages in the lockfile diff owe the licence gate and the
  install-code line.** Run the script on each one.
- **Images, prek hooks, Terraform modules and installers** owe the pinning rule, the
  cooldown where the release date is published, and the judgement lines; the script
  does not cover them.

## Hard gates

- **Cooldown:** the selected version is at least 7 days old, or the PR cites the
  advisory it fixes. Pick the newest version past the cooldown rather than latest. An
  unknown release date fails the gate.
- **Advisories:** no OSV advisory against the exact version.
- **Withdrawn:** the dependency's release is not yanked or deprecated, and neither it
  nor its source repository is archived.
- **Provenance downgrade:** a release that drops provenance its predecessor had needs
  an approved exception stating why.
- **Publisher under another owner:** a PyPI release attested as published from a
  repository whose owner differs from its declared source's needs an approved
  exception. A different repository under the same owner is a review line.
- **Licence:** on the allow-list below for how it is used.
- **Pinning:** the reference meets its rule under *Pinning by surface*.

## Licences

- **These lists are a default for code distributed under a permissive or proprietary
  licence.** They are exactly `assess_dependency.py`'s `PERMISSIVE`, `WEAK_COPYLEFT`
  and `FORBIDDEN`. Where your organisation has a licence policy, it wins: change both
  together.
- **The licence gate covers code imported, linked or bundled into what you build and
  ship.** A tool executed as a separate process — a CLI, an Action, a prek hook, a
  base image's userland, Terraform itself — is outside it.
- **Permissive** — `0BSD`, `Apache-2.0`, `BlueOak-1.0.0`, `BSD-2-Clause`,
  `BSD-3-Clause`, `BSL-1.0`, `CC0-1.0`, `HPND`, `ISC`, `MIT`, `MIT-0`, `PSF-2.0`,
  `Python-2.0`, `Unicode-3.0`, `Unicode-DFS-2016`, `Unlicense`, `X11`, `Zlib`: allowed.
  Code that ships to a browser or a customer needs its notices shipped with it — a
  generated third-party licences file, linked from the app.
- **Weak copyleft** — any `LGPL-`, `MPL-`, `EPL-` or `CDDL-` identifier: allowed in
  code that never ships to a browser or a customer. Code that does ships only with an
  approved exception.
- **Forbidden, with no exception:** any `GPL-`, `AGPL-`, `SSPL-`, `BUSL-` or
  `CC-BY-NC-` identifier, any other non-commercial licence, and no licence at all.
- **Anything else** — a licence on none of these lists, `BSD-4-Clause` among them, or
  a forbidden one `WITH` an exception — needs an approved exception.
- **A trove classifier names a family, not a licence.** A `BSD License` classifier is
  a review until the LICENSE file shows which clauses apply.
- **Read an expression, not a word:** `OR` lets you choose, so `MIT OR GPL-2.0` is
  allowed under MIT; `AND` binds you to all, so `MIT AND LGPL-3.0` is weak copyleft.
- **Missing or free-text registry metadata, or a `LicenseRef-` identifier, is not a
  verdict.** Read the LICENSE file
  in the source repository at the adopted tag, quote its first line in the PR, and
  apply the lists above to it.

## Judgement the PR records

Write one line for each that applies. None is a reason to reject alone.

- **One human registry account, or no release for a year.** The script lists the
  accounts and marks likely bots by name; check the list, since registries mark none.
  Say why it is acceptable: a small finished library is fine; an unmaintained parser of
  untrusted input is not. Stricter for anything handling auth, crypto or credentials.
- **Install-time code** — an npm `preinstall`/`install`/`postinstall` script, a
  `uv.lock` entry with no `wheels`, a package `pnpm install` lists as having ignored
  build scripts. Read what runs before approving it; with pnpm, approve it with
  `pnpm approve-builds`.
- **Privileges.** An Action that receives secrets, an OIDC token or write permissions;
  an image that runs as root or uses `ONBUILD`; a Terraform module with `local-exec`
  or a new provider. Read the pinned code, not the README.
- **No provenance published.** Note it. Valid provenance proves where an artifact was
  built, not that its code is safe.

## Pinning by surface

- **PyPI project:** a `uv.lock` committed and checked with `uv sync --locked`;
  `[tool.uv] exclude-newer = "1 week"` in `pyproject.toml`.
- **PEP 723 script:** the same `[tool.uv] exclude-newer = "1 week"` inside the
  script's metadata block. Keep the `<file>.lock` that `uv lock --no-build --script`
  wrote for the assessment, commit it beside the script, and run the script with
  `uv run --locked --script <file>`.
- **npm/pnpm:** `pnpm-lock.yaml` committed and installed with `--frozen-lockfile`;
  `minimumReleaseAge: 10080` (minutes) and `trustPolicy: no-downgrade` in
  `pnpm-workspace.yaml`.
- **GitHub Actions:** each `uses:` the PR adds or changes, reusable workflows
  included, pinned to a full 40-character commit SHA with the version as a comment —
  `actions/checkout@<sha> # v4.2.2`. The script prints the SHA for a tag.
- **Container images:** `FROM <image>:<patch tag>@sha256:<digest>` — the tag for the
  reader, the digest for the build. Prefer official or verified-publisher images.
- **prek hooks:** `rev` is a commit SHA, refreshed with
  `prek update --freeze --cooldown-days 7`. A hook's `additional_dependencies` are
  packages: assess them as PyPI or npm adoptions.
- **Terraform:** registry modules at an exact `version`, Git modules at a commit
  `ref`; `.terraform.lock.hcl` committed with hashes for every platform that runs
  `terraform`.
- **Registry CLIs committed to a repo** (`npx`, `pnpm dlx`, `uvx`, `uv tool install` in
  CI, scripts or docs): an exact version. An interactive one-off at your own prompt is
  not covered.
- **Downloaded installers:** an explicit version and a checksum or signature check;
  never pipe an unpinned URL to a shell.
- **Dependabot:** `cooldown: default-days: 7` on each ecosystem it updates.

## Exceptions

- **The approver is the repository's code owner, and the exception exists only once
  they approve it** in a PR review or comment of their own. You cannot approve your own.
- The request is a PR comment naming the gate, the reason, and an expiry date or the
  condition that ends it.
- A cited advisory clears the cooldown without an exception; the forbidden licences
  above have no exception route.

## Firing this without being asked

Frontmatter alone does not reliably load this skill; the bundled `adoption_hook.py`
does, by blocking package adds until the skill is loaded. If `adoption_hook.py` is in
neither `~/.claude/settings.json` nor `~/.codex/hooks.json`, tell the user and install
it on their go-ahead, per `references/hook-setup.md`.
