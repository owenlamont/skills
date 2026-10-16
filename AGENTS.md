# Skills

Agent skills in the [Agent Skills](https://agentskills.io/specification) format.

Cardinal rule: **the skills are the source of truth — don't restate their content here
or in code.** This file holds only what the skills don't: how this repo is laid out,
built and shipped.

## Layout

- `skills/<name>/SKILL.md` — one skill each; optional `scripts/` (standalone PEP 723
  tools) and `references/` (detail linked from the SKILL.md rather than carried in it)
  alongside it.
- `tests/` — repo-level checks over the bundled scripts.

## Toolchain

- Lint/format/type-check with `prek run --all-files` (ruff, ruff-format, ty, typos,
  rumdl, ryl, ast-grep). `prek` only scans git-tracked files — `git add` new files
  first.
- Every bundled script is self-contained: it declares its own dependencies in a PEP 723
  inline-metadata block and runs via `uv run --script`. There is **no installable
  package in this repo** — the root `pyproject.toml` is a *fake* project that exists
  solely so the `ty` hook can resolve the scripts' third-party imports. When you add a
  script, also add its third-party deps there, matching the PEP 723 minimum bounds.
- **The `ty` hook is a `local` hook running `ty check`, not the official mirror.** The
  mirror runs `uv check`, which skips any file carrying a PEP 723 `# /// script` block,
  so it would check none of the scripts here. Keep the version pinned in the hook's
  `entry` and bump it by hand, since a `local` hook has no `rev` for
  `prek autoupdate`.
- `uv run pytest` runs each script's own tests, and `tests/test_bundled_clis.py` runs
  every script's `--help` — the check that catches a severed
  `if __name__ == "__main__"`, which a unit suite that imports the module cannot see.
- Validate a skill against the spec with
  `uvx --from skills-ref agentskills validate ./skills/<name>`.
- **An unquoted frontmatter `description` ends at the first `#` that follows a space.**
  YAML reads the rest as a comment, and `agentskills validate` passes the truncated
  result. On any description change, parse the frontmatter with `yaml.safe_load` and
  compare it against the raw line; reword rather than quote, since `gh skill install`
  re-serialises the block.
- **Stage a probe before testing a hook, or pass `--all-files`.** Without it `prek run`
  stashes unstaged changes first, so an unstaged probe passes and proves nothing.

## Shipping a skill change

- Branch and open a PR — never commit to `main`.
- **A merged but untagged change is inert.** Installs resolve tags, so a change reaches
  agents only once a release tag exists and installs are updated. Skill-content changes
  need a semver tag (a new skill is a minor bump, fixes and additive guidance a patch);
  README-only changes don't.
- **A skill you invoke is the installed copy, not your working tree.** Dogfooding a
  skill you are editing silently applies the released rules, so read the branch's
  `SKILL.md`, follow that, and say which version you followed.
- **Renaming a skill orphans the old install**, and `gh skill` has no removal verb: the
  old directory keeps loading beside the new name until it is deleted by hand.

## Writing skill content

A skill is loaded mid-task and applied literally, which rules out two kinds of content:

- **Actionable items only — no backstory, no motivation.** Don't record which PR or
  incident prompted a rule unless knowing changes what the reader *does*.
- **Evergreen, not a snapshot of a repo.** Write the shape a rule applies to, never an
  inventory of where it currently applies. Counts, file lists and version numbers go
  stale silently. A point-in-time fact that matters becomes an instruction to check it.

**A measurement is evidence, not history.** Keep the number that makes a rule
actionable, attribute it to the shape it was measured on, and say what re-running would
move.

**A bullet moved between skills loses the neighbours that disambiguated it**, so restate
whatever referent its old context supplied.

**Between two skills, a rule lives in exactly one.** The other gets a one-line pointer
that names the owning skill and what it decides — naming a skill is what loads it.
