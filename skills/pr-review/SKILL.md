---
name: pr-review
description: Review a pull request or working branch end to end — resolve its exact head and base, inventory what the diff touches, load the specialist skills that cover it, then run the self-review and iterated Codex adversarial passes until nothing is left unactioned. Use when given a PR URL or number to review, when checking over your own PR or branch before asking for approval or merging, when asked to critique or look over another developer's PR, or when asked whether a change is ready to merge.
---

# PR Review

This skill orchestrates a review; it does not restate coding standards. The specialist
skills own the rules — the job here is making sure the right ones are loaded **before**
any conclusion is drawn, and that findings are grounded in the code rather than the diff
summary.

Read the repo's own guidance (`AGENTS.md` / `CLAUDE.md`) before reading the diff, so
repo-specific conventions frame everything after — the root file **and** any nested ones
in the directories the change touches, since a subdirectory's file can narrow or override
the root and is the one the author was working under. Read the root file straight away
and the nested ones once the changed paths are known, below; have them all in hand before
judging anything, not merely before finishing.

Where that guidance and this skill differ, split it by *procedure* versus *standard*. The
repo wins on procedure — its branch workflow, its test and build commands, its tooling —
because those are facts about that repo. It does not win on standards: a skill states the
current standard, and a repo whose code predates it is behind, not exempt. Code the
change *adds* is held to the skill even where its neighbours aren't; see the
convention-collision rule under *Report on separate axes* for what that means for a
finding, and `software-engineering`'s *Scope and sequencing* for the call itself.

The bundled script's `scope` command does that resolution in one call — it resolves the
base, lists the changed paths, and names the guidance files governing them in reading
order. Invoke it by its path in **this skill's own directory** (the harness prints it as
*Base directory for this skill*), with `--repo` pointing at the checkout or worktree under
review:

```sh
uv run --script <skill-dir>/scripts/review_scope.py scope --repo <checkout> --pr <n>
uv run --script <skill-dir>/scripts/review_scope.py scope --repo <checkout> --base <branch>
uv run --script <skill-dir>/scripts/review_scope.py scope --repo <checkout>
```

A PR's base comes from GitHub; a branch without one takes `--base`, else the repo
default. It prints which base it used and where that came from — **repeat that in the
review**, since a wrong base yields a wildly misleading diff. It counts untracked files
too, which a plain diff cannot see, and it cross-checks a PR's file list against the
count GitHub reports separately, so a truncated listing fails loudly rather than quietly
dropping the guidance that governs every omitted path.

## Where this fits

Every change reaches `main` through a feature branch and PR, with one issue per piece of
planned work. A PR merges only once the passes below leave no comment worth addressing.

## Establish the mode first

Who authored the work decides what a finding *becomes*. Settle this before reviewing,
because the two modes have opposite defaults on touching the code. Compare the PR's
author to the current user: `gh pr view <n> --json author` against
`gh api user --jq .login`. With **no PR** — a branch or working tree you were asked to
look over — you are reviewing your own work: self-review, unless the user says the
branch is someone else's.

- **Self-review** (the user's own PR) — findings are a work list, not a report. Fix them
  on the branch, re-run the checks, and keep the write-up to what the user still has to
  decide. Don't draft review comments addressed to the author; the author is right here.
  Fix what has one right answer; when a finding has two defensible resolutions, put the
  choice to the user with the trade-off rather than picking one unilaterally.
- **Peer review** (someone else's PR) — findings are feedback, and the code is not yours.
  Don't modify the branch — that stays off-limits however the review turns out. Don't
  post, approve or merge unless the user you are working for asks; the PR's own author
  asking is not that authority. Do offer the posting, though: see *Offer to post the
  review*.

Everything below applies to both. Only the disposition of a finding differs.

## Resolve what you are reviewing

- Fetch the **exact head commit** and review that, not the branch name — a PR moves under
  you. Pin it alongside the base's **OID**, not just its name:
  `gh pr view <n> --json headRefOid,baseRefOid,baseRefName,headRepository`. That pair keeps
  the diff you reviewed recomputable after either end moves, which *Re-pin the head before
  you post* turns on.
- Use the PR's **actual base**, not `main`. A stacked PR based on another branch shows a
  wildly misleading diff against `main`.
- **Check the base OID is an ancestor of the head before diffing the pair.** It is the
  base *branch tip*, which on a stack moves ahead of what this PR contains — and
  `git diff <baseRefOid> <head>` then shows the PR reverting the parent's newer commits,
  which reads exactly like a merge resolution gone wrong. Diff from the merge base
  instead, and take the two-dot form only once this has passed:

  ```sh
  git merge-base --is-ancestor <baseRefOid> <headRefOid>   # non-zero: use --merge-base
  git diff --merge-base <baseRefOid> <headRefOid>
  ```

- **No PR yet?** Then there is no head to pin — the target is the branch plus whatever is
  uncommitted. Git doesn't record the branch it *will* target — the upstream is usually
  the branch itself — so **ask** unless the user already said, and state which base you
  used either way. The repo default is the fallback, from
  `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`, which returns a bare
  name (`main`) that composes into a ref as `origin/main`. Don't read it from
  `refs/remotes/origin/HEAD`: that already includes the `origin/` prefix, goes stale when
  the remote default is renamed, and is unset in a `--single-branch` clone. Then
  `git fetch`, and `git diff --merge-base origin/<base>` covers committed, staged and
  unstaged changes to tracked files in one diff. It cannot see **untracked** files, so
  read `git status --short` and open the new ones — an entire new module is otherwise
  invisible.
- Check whether the work has been merged before. A revert in the base's history, or a PR
  body citing an earlier attempt, means the informative comparison is against that
  attempt (`git diff <revert>^ <head>`) rather than the base — an empty one says the
  re-proposal is unchanged, which narrows the review to why it was reverted.
- **Read the PR conversation before any code.** The description carries the author's
  *intent*, which is a separate job from auditing its claims (below): a *Notes for the
  reviewer* or *design calls* section is them pre-empting review, so engage with it
  rather than re-raising it. Read the author's own comments the same way — a decision
  already considered, a known limitation, a deliberate deferral routinely lands in a
  comment instead of an edit to the description, and re-raising it wastes their attention
  and reads as not having looked.
- **Read the issues the PR closes, with their comments.**
  `gh pr view <n> --json closingIssuesReferences` lists what merging will close; the body
  and commits can point at others as the spec without linking them. Where such an issue
  specifies behaviour, it is the contract the diff is measured against — see *Report on
  separate axes*. Read each one's comments too, since an amended requirement usually lands
  as a comment rather than an edit to the issue body, and the amendment is the part that
  contradicts the diff.
- Enumerate what other reviewers have already said, before you form findings of your own.
  It takes three endpoints, not one — `gh api --paginate` on each, since without it a busy
  PR is silently cut off at 30:

  | Endpoint | Returns |
  | --- | --- |
  | `repos/{owner}/{repo}/pulls/<n>/reviews` | review bodies; skip `PENDING` drafts |
  | `repos/{owner}/{repo}/pulls/<n>/comments` | inline comments on lines |
  | `repos/{owner}/{repo}/issues/<n>/comments` | the Conversation tab |

  **The author's PR-wide comments live on the third one** — GitHub backs every PR with an
  issue, so conversation comments are issue comments and appear under neither `pulls/`
  endpoint. Query only those two and the author context you were told to read is
  invisible. Their inline comments and review bodies sit on the first two, as anyone's do.
- Filter all three endpoints' results by **content, not author** — review bodies, inline
  comments and Conversation-tab comments alike: drop automated status, coverage and lint
  reports, and keep substantive review feedback even when a bot wrote it. Copilot's
  findings are review context; a coverage delta is not.
- **A bot's inline comments can carry a different `user.login` from the review that
  contains them** (`Copilot` vs `copilot-pull-request-reviewer[bot]`), so filtering the
  comments by the review's author silently returns nothing and reads as "no prior
  feedback".
- Isolate whichever revision the mode needs. In peer review the **head** goes in a
  detached worktree so the user's checkout stays untouched — including when the PR
  branch already *is* their checkout, because the gate below mutates whatever tree it
  runs in, so the head still needs a worktree of its own. When you need to compare
  behaviour across the change, the **base** needs one too. Self-review's fixes belong on
  the **branch**: edit in place by default, and use a worktree of that branch instead
  where the repo's own guidance — which you have already read — says the clone is shared
  between sessions or forbids editing the checkout directly. You cannot observe another
  session, so that guidance is the only signal available; where it is silent and anything
  suggests a second session (a branch you didn't create, uncommitted changes that aren't
  yours), take the worktree. It costs a `git worktree add`, and the failure it avoids is
  destroying work you cannot see. Landing on the branch is the requirement; editing in
  place is only the usual way of meeting it.
- In peer review, don't touch **the tree in front of you** — the checkout belonging to the
  human who asked for the review, which is the one this session is running in, whoever
  authored the PR. It is not the author's tree you are protecting; it is your user's. Not
  even temporarily with the intention of putting it back. Verification writes to the tree:
  auto-fixing hooks reformat files (`prek run --all-files` will) and builds leave
  artefacts. Run those where mutation is expected — the worktree in peer review, the
  branch in self-review. Restoring afterwards is not the standard; never modifying it is.
- The authoring-side corollary: don't mutate the tree while a review of it is in flight.
  Editing a file mid-run forces the reviewer to stop and re-resolve its pinned head
  against a working tree that has moved. Finish the round, then act on it.

## Run the local gate on it

Once the revision is pinned and isolated, a change is not review-ready until these pass
on it — run them in the tree where mutation is expected, per the rule above:

- `prek run --all-files` — stage new files first, since prek only scans tracked files,
  and re-run if it autofixes. **Its autofixing hooks rewrite tracked files, so no diff
  you read may name the working tree while it could be running.** Name both ends —
  `git diff <base-oid> <head-oid>` — rather than comparing a commit against the tree. A
  diff taken mid-run reads as the PR deleting code it never touched, and the tell is
  that it disagrees with `git show <head>:<path>`.
- The repo's **own** test command, for any behaviour or code change — whatever its
  `AGENTS.md` or CI config defines; that command wins. Where it defines none, derive the
  command from what the project actually declares rather than assuming:
  `uv run pytest --color=no` for a uv project that depends on pytest, adding `-n logical`
  only when `pytest-xdist` is present, since without it pytest rejects `-n` outright. A
  repo that declares no test suite has no test gate to fail — say that, and don't
  manufacture one.

Where the repo has CI, that is the authoritative gate and the local run only its fast
proxy: a matrix across operating systems and interpreter versions fails on things one
local run cannot reproduce, so a green local gate does not stand in for it. Read the real
result on a PR — `gh pr checks <n>`, then `gh run view --log-failed <run-id>` on a failure
— rather than assuming red means flaky. A CI failure is a finding whichever way the local
gate went, and in peer review it is one for the report rather than for the PR:
*Nothing the machine already blocks goes up on the PR at all* says why. With no CI
configured, the local gate is the whole gate.

## Inventory, then load the specialists

Inventory what the diff actually touches — languages, imported libraries, frameworks,
tests, notebooks, config — and load every skill that materially covers it before
evaluating anything.

Two sit outside the diff and load on **every** review, and the rules below are written
against them rather than restating them, so a review that skipped either cannot apply the
gates it claims to. `docs` sets the budget the write-up is measured
against. `software-engineering` sets what counts as having verified a claim, diagnosed a
cause rather than guessed at one, and left the codebase simpler — the *Evidence* and
*Remedy* gates, the *what you verified* axis and the standards axis all resolve their
standard from it.

**Neither is the residue left once the specialists are loaded.** Loading eight specialist
skills leaves both of these unloaded, and a diff with no Python in it needs them exactly
as much as one full of it — a prose-only diff still gets claims verified and a write-up
budgeted. Diff contents drive the rest:

| The diff contains | Load |
| --- | --- |
| code, in any language | `software-engineering` |
| any Rust | `rust-code-style` |
| rayon, threads, channels or atomics | `rust-concurrency` |
| Rust tests | `rust-testing` |
| any Python | `python-code-style` |
| Python tests | `python-pytest` |
| any TypeScript; a tsconfig, `package.json`, `biome.json`, `.oxlintrc.json` or `.vscode-test.*` change; or a TypeScript linter failure | `typescript` |
| `import pandas` | `python-pandas` |
| `async def` / asyncio | `python-async` |
| raising or catching exceptions in Python | `python-error-handling` |
| Python datetimes or timezones | `python-datetime` |
| SQL, a schema or migration, or a query built in code | `sql-data-modelling` |
| hand-rolled Python helpers, or a new Python dependency | `python-libraries` |
| Python dependency or version changes | `python-uv-workflow` |
| prek hook or Python lint/format config, or a linter failure outside TypeScript | `python-lint-format` |
| a marimo or Jupyter notebook | the marimo skills, if installed |

The table is a floor, not a ceiling — load anything else the catalog offers that fits.

A row fires only when the diff **actually contains** its trigger. Where the trigger is
mechanical, check it (`git diff --name-only`, or grep the diff) rather than loading on a
hunch.

**Write the triage down before reviewing anything — every skill you loaded, and every one
you ruled out with its reason** ("no `models/` changes, so no migration to review").
Inventorying a trigger is not loading the skill, and once you are reading code nothing
distinguishes the two: a review that names the axes it covered while having loaded nothing
reads exactly like a thorough one. The two unconditional co-loads are the ones to check
the triage against first, since no trigger in the diff will remind you of either. Load
what fired, then begin.

On a refactor that claims to preserve behaviour, establish equivalence first (below): a
path proven identical cannot have changed domain semantics, so load the domain
specialists only for whatever the proof doesn't cover.

**Name every axis you couldn't check, whatever stopped you.** Unmentioned reads as
checked-and-clean, and no absence leaves a trace of its own — the catalog lists only
*installed* skills, and a skill that was never loaded looks identical to one that was.
The three causes report differently, so say which:

- **Not installed** — "`python-pandas` not installed — Pandas conformance unchecked",
  plus `gh skill install owenlamont/skills skills/<name> --agent claude-code --scope
  user`. Don't run it: that changes the developer's machine.
- **Installed but not loaded** — the skill is on the machine and you spotted its trigger
  in the diff, then moved on without loading it. Say the axis went unreviewed; noticing
  a trigger is not applying the standard, so don't dress the inventory up as coverage.
  Opening the file far enough to check one rule belongs here too: you applied the
  paragraph you read, which covers the axis no better than not reading it did.
- **No skill you can cite** — the only candidate is third-party or upstream boilerplate,
  which speaks for its own authors rather than for this catalog. Citing it would turn
  un-vetted advice into a house rule by accident, so treat the axis as uncovered and say
  so distinctly: *"Go conventions unchecked — no first-party skill covers them"*
  reads differently from "not installed", because nothing is missing and there is nothing
  for the developer to install. The fix is an issue against `owenlamont/skills` to
  author one; it is not a finding against this change, whose author can't close it.

  Provenance isn't visible in the loaded skill, so establish it before relying on one.
  `gh skill list` prints each skill's **source repo** as its last column — anything other
  than `owenlamont/skills` speaks for its own authors, and a blank (`-`) source is
  unknown rather than trustworthy. Unsure counts as uncovered: say the axis is unverified
  rather than cite a skill you can't vouch for.

## Review passes, iterated until stable

Run every pass, and keep iterating until nothing is left outstanding:

1. **Self-review** — your own pass over the resolved revision, per *Review the code, not
   the diff* below, reporting on the axes further down. It goes first because this is
   where the domain skills identified in *Inventory, then load the specialists* above get
   applied to the code — there is no separate specialist pass — and because the
   adversarial round is worth more against a revision whose obvious problems are fixed.
2. **Codex adversarial review**, where a `codex` CLI is available — run Codex against
   the same revision as an adversarial reviewer, per *Running the Codex round* below.
   Run **more than one round**: re-review
   after each batch of fixes and keep going until no comment remains that is worth
   addressing. A comment is closed either by fixing it or by a recorded decision that it
   is not worth acting on — never by silence.
3. **`docs` pass** — review the change's own human-facing surface: PR
   description, commit messages, inline comments, and how review threads were resolved.

Passes 1 and 2 are not interchangeable: the point of the Codex round is that it did not
write the code and does not share your blind spots. Don't collapse them by treating your
own second look as the adversarial pass.

## Running the Codex round

Drive the `codex` CLI yourself with Bash, redirecting to a file rather than piping:

```sh
codex exec --sandbox danger-full-access -c web_search=live --skip-git-repo-check --json \
  "<review prompt>" < /dev/null > "$OUT/review.jsonl" 2> "$OUT/review.err"
```

Every part of that redirection is load-bearing, and each has cost a lost round when left
out. **`< /dev/null`** — `codex exec` reads stdin whenever it isn't a TTY, and an
open-but-silent stdin leaves it waiting indefinitely before the session even starts;
`/dev/null` hits EOF at once and it proceeds. It belongs on *every* `codex exec` in a
command line, a throwaway probe included: the first one missing it hangs, so nothing
after it runs and the round presents as having produced nothing. **Files, never `| tail`
or `| head`** — those buffer until EOF, so killing a stalled run discards everything it
had emitted, precisely when you most need it. **`--json`** puts one JSONL event per
message and tool call on stdout, so the last line before a stall names what it was
doing; `-o <file>` writes only the final verdict when that is all you want. **Separate
streams, not `2>&1`** — stdout stays strict JSONL only if stderr goes elsewhere, and
progress notices do go to stderr, so folding them in leaves a line that fails to parse.
**`$OUT` is a scratch directory outside the tree under review**, because both redirects
are resolved by the invoking shell and not by `-C`: a bare `> review.jsonl` lands in
whatever checkout you launched from, which in peer review is the one you were told never
to touch.

Add `-C <dir>` when the revision under review sits in a worktree, so Codex reads that tree
rather than the checkout you invoked it from. `codex review` is the alternative entry
point, taking `--base <branch>` or `--uncommitted` for scope; neither flag combines with
a custom prompt positional, so use one or the other.

**Two things gate a round, and `command -v codex` settles only the first.** It says
whether the CLI is on `PATH`. Whether an installed CLI can actually serve one is the
Codex weekly window, and an exhausted window leaves you with no round just as surely as
no CLI — read it too before you spend a round finding out.
That is an availability check, separate from the cost check below.

**With no round available, report the PR as self-reviewed with the adversarial pass not
run, and carry on — it is not a merge gate.** Don't substitute a Claude model for it.
What makes pass 2 worth running is that it did not write the code and does not share
your blind spots, so a second Claude pass is pass 1 under another name — and presenting
it as the adversarial round is worse than reporting no round at all, because it retires
the pass without performing it. Name which half is missing and let the human choose
whether to wait for the window.

**A round is not free, so spend one only on what a round can see.** Two measured rounds
over mid-sized PRs cost 3% and 7% of a Codex weekly window — read the window before and
after rather than budgeting from either figure, since what a round reads and runs drives
it more than the diff's size does. Two things save a round without weakening the review:
name the previous round's retained probe directories in the next prompt, so it re-runs
those fixtures rather than rebuilding them; and where the only change since the last
round is a deletion, re-run every retained probe against the new tree yourself — a pass
on all of them closes the round on evidence already gathered.

**Drive the CLI yourself rather than delegating the round to a subagent.** Going idle
without ever reporting is the benign failure. The one that costs you is a subagent that
returns a long, substantive, plausible review it wrote *itself*: audited delegated
rounds were served end to end by a Claude model, several on days with no Codex session
at all. A verdict is therefore not evidence that a round happened — a real one leaves a
new rollout under `~/.codex/sessions/<year>/<month>/<day>/`, and the subagent transcript
at `~/.claude/projects/<slug>/<session>/subagents/agent-*.jsonl` records the `model`
that actually served it. If you do delegate and it hasn't reported by the time you need
it, run the CLI instead — and treat a late report as reviewing a stale tree until you
re-check its claims against the current one.

The prompt carries what Codex cannot work out for itself: which revision to diff, the
review angles that matter here, and the fixes applied since the previous round so it
doesn't re-raise them. End it by licensing a clean result — *report only defects worth
blocking merge; do not manufacture findings, and if the diff is clean say so plainly and
stop.* Without that, a reviewer asked for findings supplies some, and each invented one
costs a round to adjudicate.

**State the read-only expectation in the prompt, because nothing else does now.** Under
`danger-full-access` Codex is a reviewer that *can* edit, and a model asked to find
defects will readily fix one — leaving you unable to tell its finding from its repair, and
the round's diff no longer the revision you pinned. Say it outright: *review only; do not
edit, stage, commit, or revert anything. Running the suite and other read-only commands
is expected; report what you find rather than fixing it.* Naming the suite as permitted
matters, since a flat "change nothing" reads as forbidding the test run this sandbox
setting exists to allow.

**`--sandbox danger-full-access` is deliberate, and it removes a guarantee** — take the
two consequences seriously. Codex can now run the suite itself rather than reporting it
blocked, which is most of the point: under `read-only` anything needing a writable tempdir
(pytest among them) failed as a sandbox error that reads exactly like a failing suite. But
full access is not confined to the tree under review. `-C` sets where Codex *looks*; it
does not bound where Codex can *write*. In peer review the rule that the user's checkout
stays untouched was previously enforced by the sandbox and is now carried by the prompt
plus the after-check below — name the tree Codex should *work in* and verify afterwards
rather than assuming. No tree is writable: the prompt above forbids editing anywhere, so
there is no permitted-to-modify tree to name, and offering one would license exactly the
writes that prompt exists to prevent.

**Get the tree green, then fingerprint it, before you invoke.** Codex will very likely
run the repo's own gate, and an autofixing gate rewrites files as it runs — so the round
can mutate the tree while Codex is only trying to verify, through a command it is
entirely right to run. **Which hooks mutate is per-repo config, so read it rather than assuming**
— the same tool is a checker or a rewriter depending on one argument. Measured in this
repo: `ruff-check` carries `--fix` and `ruff-format` rewrites Python in place, `rumdl`
carries `--fix` and rewrites Markdown, and the trailing-whitespace and end-of-file hooks
rewrote a probe file on the spot with `git status` reporting it modified. A repo wiring
any of those without its fix argument only reports. Three consequences, all pointing the
same way:

- Run the gate to a **no-op**, not merely to green. `prek` fixes on the first pass, so the
  run that tells you anything is the second one, which changes nothing.
- Have the suite passing too, so the round is spent on the change rather than on a failure
  you already knew about.
- **Fingerprint the tree rather than requiring a clean one.** Tidying first is tempting,
  since an empty baseline is trivial to re-check — but demanding it contradicts two rules
  already settled above. With no PR the review target *is* the uncommitted work, so
  stashing it hands Codex a tree without the change in it and the round comes back clean;
  and in peer review the user's checkout must not be touched **at all**, tidying included.
  So take a content fingerprint before, and take it again after. Commit your own in-flight
  fixes if you can, though — see the recovery note below for why that is worth more than
  readability.

**Check both, afterwards, in every tree involved.** The prompt cannot be relied on alone,
so pair it with detection:

```sh
( cd <tree> && { git rev-parse HEAD
                 git status --porcelain
                 git diff HEAD
                 git ls-files --others --exclude-standard -z \
                   | sed -z 's|^|./|' | xargs -0 -r sha256sum --
               } ) | sha256sum
```

**Run it inside the tree, not with `git -C`.** `ls-files` prints paths relative to the
repository, but `sha256sum` resolves them against the *caller's* directory, so a `-C`
form silently hashes whatever sits at those paths where you happen to be standing.
Measured: fingerprinting one tree while standing in another hashed the other tree's
same-named file and reported a perfectly plausible digest. In the two-tree peer-review
case that makes both fingerprints agree no matter what changed. The subshell `cd` keeps
every part resolving in one place, and `-z` with `xargs -0` keeps filenames with spaces
intact.

The `./` prefix and the `--` are both load-bearing, and a stray `>` redirect is a
likelier way to get a file named `-` or `--foo` than anything adversarial. Measured on
all three: without them, `sha256sum` reads stdin for `-` and swallows `--` as its own
option terminator, so a file it should have hashed vanishes from the digest silently.
`--` alone is not enough — `-` is still stdin after it — which is why the paths are
prefixed rather than just terminated.

**A status line is not a content check**, which is why the diff and the untracked hashes
are in there. `git status --porcelain` reports a path and a state, not what is in the
file, so against an already-dirty baseline it cannot see a further edit to the same path:

```text
baseline    9a50173  M f.txt
after Codex 9a50173  M f.txt     # same HEAD, same status, different contents
```

Measured, and the detection was silent. The fingerprint above caught all four shapes it
has to: an edit to an already-dirty tracked file, a new untracked file, an edit to an
existing untracked one, and a commit.

In peer review that is **two** trees — the worktree under review, which is clean by
construction because you created it detached from a pinned commit, and the user's
checkout, which may be dirty and stays that way. The second is the one the rules protect,
so don't check only the one Codex was pointed at.

The round's own JSONL is the other half, and it is already on disk. It records every
command with its exit code, so it catches mutation Codex caused *indirectly* — an
autofixing gate it ran in good faith — and names what did it:

```sh
jq -r 'select(.type=="item.completed" and .item.type=="command_execution")
       | "\(.item.exit_code)  \(.item.command)"' "$OUT/review.jsonl"
```

This is detection, not prevention: full access reaches outside every tree you thought to
check, and a `git`-level check can only speak for the repos it was run in. Say what moved
in the review rather than quietly reverting it — a round that edited the tree may have
been reviewing its own repair.

**Recovery is only clean from a committed baseline**, which is the real reason to commit
before a round rather than merely to get a tidier fingerprint. `git reset --hard <sha>`
restores committed state and *destroys* uncommitted work along with it, so on a tree that
was already dirty it would take your own in-flight changes with Codex's. There, undo the
specific paths the fingerprint implicates — `git restore <path>` for a tracked file it
edited, deleting an untracked one it added — and reconstruct anything of yours it
overwrote from the reflog or from `git stash create`'s dangling commit if you made one.

**Don't edit anything while a round is in flight.** This was already true because the
reviewer's pinned revision moves under it; it now also corrupts work Codex is doing, since
it may be running the suite against the tree you are editing. A test failing on a
half-applied edit comes back as a finding that describes a state that never existed, and
adjudicating it costs a round. Queue the fixes, let the round finish, then apply them —
which is what *Review passes, iterated until stable* already asks for, and the reason it
batches fixes between rounds rather than during one.

**Web search needs no flag** — it is on by default for `codex exec`. The old
`--enable web_search_request` doesn't fail the run; it reports itself deprecated *because*
search is already on, and the round proceeds and searches anyway. The interactive
`--search` has no `exec` equivalent. `-c web_search=live` above is the current control
stated explicitly, so a machine whose `config.toml` sets `web_search = "disabled"` doesn't
silently review without it; the other values are `indexed`, `cached` and `disabled`.

When a run does hang, its own transcript localises the failure. Codex writes
`~/.codex/sessions/<year>/<month>/<day>/rollout-*.jsonl` at session start and appends as
it goes, non-interactive runs included, so its tool calls show where it stalled. **No
rollout at all means it never reached session start** — look at CLI setup and the prompt
read, not at the review.

**Adjudicate every finding against the source before acting on it.** The round is worth
running because Codex is not deferential, and that same independence produces false
positives: fixing one can introduce a real defect the next round then flags, and arguing
from its assertions rather than from the code turns the loop into ping-pong. It can read
outside the tree but rarely looks, so it may report an out-of-tree path — a machine-level
plugin, a user-scope skill — as non-existent; check the path yourself rather than taking
either its word or your own. Its findings clear the same bar as your own, below.

### Shaping the prompt

- **Pass the prompt from a file**, `"$(cat "$OUT/prompt.txt")"`, rather than inline: a
  backtick inside an inlined prompt is substituted by the invoking shell before Codex
  sees it, and a prompt full of code spans loses every one of them.
- **Scope it to the tracked files and the tool caches.** "Change nothing" read literally
  stops a reviewer running anything in place, since a suite writes caches; say that
  writing under `.pytest_cache`, `.ruff_cache` and a temp directory is expected, and
  that tracked files are not to be touched.
- **Tell it to leave temp directories in place and report the path.** Codex's tool
  router refuses `rm -f` and `rm -rf`, and the refusal takes the *whole* command with it,
  so a probe that builds a scratch repo under `mktemp -d` and cleans up at the end never
  runs at all. The model usually notices and retries without the cleanup; the capture
  never says so.
- **Reframe attack vocabulary.** The safety classifier aborts a round whose prompt reads
  as an exploit brief ("attack surface", "exploit", "bypass"); ask for a correctness
  review with the same scepticism and the round proceeds.
- **`codex features list` is the source of truth for feature names**, and never pin a
  `codex` version — the CLI moves weekly.

### Reading the round back

- **The check is "is the last event a `turn.*`", not "is it `turn.completed`".** Every
  finished capture ends in `turn.completed` or `turn.failed`; a capture whose last row is
  an `item.*` is still being written. Exit 0 either way. A `turn.failed` with *Selected
  model is at capacity* is a persistent condition: a retry minutes later buys little.
- **Findings are rows with `item.type == "agent_message"`, no wrapper around them** —
  and most of those rows are narration, not verdicts. Take the last `agent_message`
  before the terminal event and read it whole rather than assuming any single row is the
  answer. Read the narration too: it names the angles it was about to test, and an
  aborted round can still carry a finished finding in a `command_execution` row's
  `aggregated_output`.
- **A rejected tool call leaves no trace in the JSONL.** The router's refusal goes to
  stderr only — `grep 'tools::router: error=' "$OUT/review.err"` — with no
  `command_execution` row, exit 0, and a `turn.completed`, so a round that reports
  "verified by running" may never have run the probe. Read `.err` for anything other
  than the one healthy line, which is exactly `Reading additional input from stdin...`.
- **Do not declare a run truncated on a deadline.** A capture without a terminal event
  was, every time it was checked afterwards, still being written; the cost of calling it
  dead was re-running a finished review. Watch the PID and the file's growth, budget
  minutes rather than seconds, and never double-background — `run_in_background` plus a
  trailing `&` detaches `codex` from the wrapper, so the harness reports the shell
  finished while the review is still writing.
- **Two rounds landing on the same remedy is non-convergence**, not agreement: re-examine
  the previous fix before repairing it again. Stop when a round re-raises something
  already declined with a reason.
- **Resume only to verify a fix, never to redo the review**:
  `codex exec --sandbox danger-full-access resume <thread_id> "<follow-up>"` — the
  sandbox flag goes *before* `resume`, which accepts neither it nor `-C`, and it filters
  threads by the cwd they started in. Don't chain the `cd` into a backgrounded compound.

## Review the code, not the diff

- Read **in full** every file whose behaviour changes, then trace the runtime path out of
  it into the untouched code the change makes reachable — hunk context hides the caller
  that makes a change wrong. On a wide diff that means depth through the changed modules,
  not a skim across all of them.
- **Walk the PRs stacked above before calling code unused**, or before resting a finding
  on behaviour a later stage could change. A later stage is evidence, not out of scope:
  config one PR adds is often consumed in the next, and a docstring the finding leans on
  may be contradicted there. Follow `baseRefName` → `headRefName` up from this PR's
  head, reading each stage's diff:

  ```sh
  gh pr list --repo <owner/name> --state open --limit 1000 \
      --json number,baseRefName,headRefName \
    | jq -r --arg head "$(gh pr view <n> --repo <owner/name> --json headRefName -q .headRefName)" \
        'def above($b): (.[] | select(.baseRefName == $b)) as $p | $p, above($p.headRefName);
         if length == 1000 then error("list hit --limit 1000; raise both")
         else above($head) | "#\(.number) \(.headRefName)" end'
  ```

  The command prints nothing when no PR sits above.
- Check the PR body's specific claims — "adds tests for X", coverage numbers — against
  what the diff actually contains.
- Verify the author's claims yourself with the narrowest useful test, or by exercising
  the affected states directly, rather than running the full suite. Distinguish an
  environment setup failure from a real code failure; never report the former as the
  latter.
- **A refactor claiming equivalence needs differential evidence, not careful reading.**
  Compare the two trees first — a re-proposal is often unchanged — then run both
  revisions over the same inputs and compare observable results, normalising what is
  incidental: ordering, generated names, ids. Reorderings inside a compiler, solver or
  ORM produce diffs that look like correctness bugs and aren't, so confirm a suspected
  difference changes an observable result before reporting it. A fabricated bug against
  a correct PR costs more than the review returns.

## Report on separate axes

Keep these apart; conflating them buries the one that matters:

- **Correctness** — will it misbehave, and under what input or state.
- **Divergence from a specifying issue** — where the diff implements something other than
  what an issue it closes agreed, cited to that issue. Code can be correct and still
  deliver a different policy from the one signed off, which no amount of reading the diff
  alone surfaces.
- **Standards conformance** — what a loaded specialist skill requires, cited by skill.
  `software-engineering` is one of those skills on every review, whatever the language:
  whether the change leaves the codebase smaller and simpler is a standards finding held
  to its rules, not a matter of taste you can decline to have.
- **What you verified** — which paths you traced end to end, what test or differential
  run backed each, and what you could not check. This axis is for the user who asked for
  the review and never goes on the PR; *Split by where it lands* has the reason.
  `software-engineering`'s *Verify, don't assert* sets the bar a path has to clear before
  it goes in this list; reading it and finding it plausible is not tracing it. On a
  refactor this is usually the headline, and it is not the same thing as reporting zero
  findings. A test added for a
  fix counts as verified only once mutation-checked: revert the fix, confirm the named
  test fails, restore. One that still passes with the fix reverted pins nothing, so presenting
  it as coverage for the bug overstates what the change protects. Aim for a single failing
  test — parameterized cases of one test count once, and several distinct tests failing
  means their coverage overlaps.
- **Existing feedback** (peer review) — every prior comment left after that CI-noise
  filter, whether or not it overlaps a finding of yours, grouped by disposition. Give
  each group the one action it implies — a reaction, an in-thread reply, or nothing —
  using the rungs under *Offer to post the review*:

  ```text
  Already raised, nothing to add — would 👍:
    • Copilot loader.py:175 — a failing region is skipped instead of erroring

  Raised by a bot, and I have a delta or disagree — one line each in the review body:
    • Copilot report.py:185 — cap ordering / extra caps silently dropped
      (misses the equal-cap collapse, which blends nothing at all)
    • Copilot config.py:38 — wants the catch widened; I'd narrow it

  Raised by a person, and I have a delta — would reply in-thread with just the delta:
    • @teammate builder.py:88 — agrees the retry is unbounded; the ceiling also has to
      cover the scheduler path

  Raised, no view: Copilot builder.py:224 (docstring punctuation)
  ```

  Report this even when nothing will be posted. The user wants to know a prior reviewer
  already caught something regardless, and publicly disagreeing with another reviewer is
  a judgement not to make silently.
- **What to do about it** — in peer review, feedback for the author, ranked by severity
  and written to `docs`'s budget. In self-review, apply the fix on the
  branch, then report only the decisions the user still has to make — judgement calls
  left open, not commands for them to run.

Report in prose. Don't call `ReportFindings` — this skill is the active review
instruction, and it asks for prose. Carry the skill triage into the report — the written
record from *Write the triage down before reviewing anything*, naming each specialist
skill loaded and each ruled out with its reason, not a narrative listing the axes. The
standards axis means nothing without it, since the reader cannot otherwise tell which
standards were actually applied.

**Give each `owenlamont/skills` skill you applied its version**, so the triage records
which revision of a rule the review ran under and skill usage stays countable across
reviews. The transcript records every load, so don't write the list from memory: run
the bundled script from **this skill's own directory**, and it prints the table below
ready to paste:

```sh
uv run --script <skill-dir>/scripts/skills_used.py
```

It finds the current session's transcript from the harness's session id, and takes
`--harness claude-code` or `--harness codex` when one agent runs inside the other and both
ids are set. Each row's loaded-from path prints under the table, and every load whose
source is not `owenlamont/skills`, or cannot be read, goes to stderr and is left
out. A row is a load the transcript shows — a `Skill` call for Claude Code, and for
Codex a read of the installed `SKILL.md` whose output shows its frontmatter — so a skill
missing from it did not load, and a Codex read of a checkout copy or of a section below
the frontmatter is not a load either.

The version is the install stamp as it stood **when the skill loaded**, not what is on
disk now, so a `gh skill update` mid-session cannot relabel a load after the fact; where
one skill loaded at two versions, the script prints both as
`v0.22.0 (v0.23.0 mid-session)`. Claude Code strips the frontmatter from what it records,
so a Claude load reads `unversioned` unless a hook stamped it into the transcript at load
time — record it as printed rather than filling it in from `gh skill list`, which reports
what is installed now.

**Expect the numbers to differ across skills, and read staleness into neither a low one
nor a high one.** The version is the release at which that skill was last *installed or
content-updated*, whichever came later — not the release its content last changed in:
`gh skill update` compares `github-tree-sha` and relabels only content-changed skills,
while `gh skill install` stamps whatever release is current. So a skill sitting several
releases back is usually just one nobody has edited since rather than one that missed an
update, and a higher number can mean nothing more than a reinstall — a fully up-to-date
install spans many version numbers. Record each as it reads, and never report
one version for the whole set. Third-party and vendored skills stay off this list;
provenance comes from the source column under *No skill you can cite*.

**Keep the shape of this table unchanged, with the rows sorted by skill name**, so the
format stays consistent enough to count mechanically across many PRs, and so two reviews
of the same PR can be compared a row at a time. Load order carries no information and
differs between agents. The rows below illustrate it; the skills and versions in yours
are the ones you actually loaded and read:

```markdown
| Skill | Version |
| --- | --- |
| `docs` | v1.4.0 |
| `pr-review` | v1.4.0 |
| `python-code-style` | v1.4.0 |
| `python-pytest` | v1.1.0 |
| `software-engineering` | v1.2.0 |
```

Two columns and no more. It is a usage record, not the triage: a row means that skill was
loaded and applied, so keep it to those, and write the `+draft` bound above rather than
guessing a version you can't read.

**`pr-review` is a row on every review, and an example table is where it goes missing.**
A list of specialists reads as the whole shape, so the skill governing the review is the
one row nothing prompts you to write. It is also the row that matters most to a reader who
wasn't in the session: the table is the only record of which revision of the review
process itself ran, and nothing else on the PR carries it. The *Not installed* exception
cannot reach this row either — you are reading the skill, so it loaded.

**A row means you loaded the skill, not that you read part of its file.** Opening a
section to check a citation, or grepping it for one rule, is not loading it — you applied
the paragraph you read and none of the rest, which is what an unloaded skill looks like
from the inside. Where that is all you did, the axis belongs in the prose as unreviewed
under *Installed but not loaded*, and the row comes out. This is the distinction that
makes the table countable rather than a list of skills that felt relevant, and it is the
one an agent is most likely to get wrong in its own favour, which is why the rows come from
the transcript rather than from you. A Codex read that stopped partway through a
`SKILL.md` still shows its frontmatter, so the script prints it as a load: take that row
out and report the axis as the partial read it was. The two
unconditional co-loads are the exception, and it runs the other way: reporting either as
unreviewed is not open to you, so a partial read there means go back and load it.

**`docs` and `software-engineering` are rows on every review too**, since
nothing in a diff triggers either and the table is the last point at which their absence
is still visible. Reaching this table without one of them means the review skipped a pass
it is about to claim — go back and run it rather than adding the row. A skill that isn't
**installed** is the one exception, and *Not installed* already governs it: report the
axis unchecked and leave the row out, since a row means loaded and applied and there is
nothing here you are permitted to install. The skills you ruled out, and any axis nothing
covered, stay in the prose the rules above already ask for — they are reasoning a reader
has to follow, and folding them in here would make the rows mean two different things.

Where it lands follows the mode, and it is a *Skills used* section, pre-collapsed in a
`<details>` block, in both:

- **Peer review of someone else's PR** — in the posted review body, per *The versioned
  skill list always goes in the body*.
- **Self-review before raising or updating your own PR** — in the **PR description**,
  since a self-review posts no review to carry it. `docs` owns where in
  that body it goes, and what to do when the repo's template does or doesn't already
  provide the section.
- **A peer review you report but do not post** — in the terminal report, under the same
  *Skills used* heading. It is the only record of which revision of which rules the
  review ran under, and the posted body that would normally carry it does not exist, so
  it goes to the user who commissioned the review instead of being dropped. This is the
  one case where the table is not on a PR, and it is not licence to omit it.

Then, for every finding:

- Rank by severity and make each one actionable. Anchor a finding to a line **the change
  touches**; when the root cause sits in untouched code, anchor to the touched line that
  makes it reachable and name the real target in the body.
- State a failure scenario — concrete inputs or state, and the wrong result — rather than
  a general worry. Drop anything you can't ground that way.
- **Carry the ask, not just the problem.** Say what you want changed — the fix, or the
  choice between two when it is genuinely open. A finding that stops at the failure
  scenario makes the author reconstruct a remedy you already worked out, and reads as a
  complaint rather than a request. Where you can't name a fix, name what you need from
  them instead: an answer, a decision, a test. An ask is a claim like any other, so it is
  held to the same evidence bar as the finding — in peer review, *Clear a higher bar than
  you would for your own code* says how far that goes.
- **Hold each finding to the three gates below, as it forms** — Evidence, Intent, Remedy,
  and no others. They are gathered in one place deliberately: a gate you reach only once
  the report is drafted gets applied to something already written and presented. That is
  why the later section *Clear a higher bar than you would for your own code* is a set of
  re-checks rather than the first pass; it adds no fourth gate here.
  - **Evidence** — you have verified it is real, and it will be hit in practice. "Might
    be an issue, couldn't confirm" is not a finding; either verify it or drop it. Say
    what you suspected but couldn't confirm under *what you verified*, not as a finding.
    *Reproduce the defect before you post it* sets what verifying means for anything
    going up on someone else's PR.
  - **Intent** — the author hasn't declared the behaviour deliberate, and hasn't already
    stated and dispositioned the limitation. Read the PR body and their comments for this
    while the finding forms: a constraint you rediscover through your own investigation
    reads as your own finding even when you read it in the body thirty tool calls
    earlier. Where a finding overlaps something they stated, drop it or carry only the
    delta their statement doesn't cover.
  - **Remedy** — the fix is verified separately from the finding, and it addresses the
    cause rather than the line the symptom surfaced on. `software-engineering`'s
    *Diagnose before you change* owns that call, and it costs more here than in your own
    code: a spot-patch you propose is one the author implements before discovering it
    bought time rather than fixed anything. Clearing the evidence gate says nothing about
    the fix you go on to propose, which *Run the fix before you propose it* holds to a bar
    of its own.
- These are not findings, however real they look: a pre-existing issue the change didn't
  introduce; something that resembles a bug but isn't; a nitpick a senior engineer
  wouldn't raise; a behaviour change that is plainly intentional and part of the stated
  purpose; and a **pre-existing** suppression carrying a justification (a linked `noqa`
  or `type: ignore`) — that decision was already taken, so re-flagging it reopens a closed
  call. A suppression the diff *adds* is the opposite: it is a decision made in this
  change, so hold it to `python-lint-format`'s *Resolving a failure* ladder and say so
  when a root-cause fix or a scoped config ignore was available. A justification records
  a decision; it doesn't establish that the rule was unavoidable.
- Nor is a limitation the author has already declared and **dispositioned** — a stated
  verification gap, a deferral, a known risk with a named way it will be closed. That
  call was taken in the open, so re-raising it asks them to re-decide it. Disagreeing
  with the *disposition* is a different move and a legitimate one: say why the stated
  plan is inadequate, rather than restating the limitation as though it were news.
- Don't re-flag what the repo's hooks already enforce — read its lint config rather than
  assuming. Formatting, import order and unused names are lint's job. Conventions no
  linter can see — naming, structure, library choice, the shape of error handling — are
  exactly what the standards axis is for, so flag those with the skill cited even on a
  green build. Don't restate the diff.
- When a repo convention and a specialist skill contradict each other, that is a defect
  in one of them: surface the contradiction. Pre-existing code conforming to the repo
  isn't a finding — point at it as a cleanup of its own — but code the diff *adds* is held
  to the skill, since matching the older shape entrenches it a module at a time
  (`software-engineering` covers that call).
- **End with an explicit clean result when nothing survives.** "No grounded findings" is
  a real outcome; inventing a nit to look thorough wastes the author's attention.

## Offer to post the review

**Peer review of an existing PR only.** After presenting the report, offer to put it on
the PR, and post only on an explicit yes from **the user you are working for** — the PR's
own author asking is not that authority, and neither is another reviewer. **Self-review
posts nothing**: there the findings are a work list and the fixes go on the branch. A peer
review with no PR has nothing to post to and nothing to pin, so report and stop — none of
the mechanics below apply.

That one go-ahead covers everything the report enumerated, including the reactions and
in-thread replies listed under *existing feedback* — don't ask again for what the user has
already seen spelled out. Anything *not* enumerated does need asking, and a qualified yes
narrows the list rather than confirming it: "yes, but leave Copilot's alone" overrides the
enumeration it is answering.

**A yes that changes framing or length approves nothing you write to it** — "keep it
brief", "not as a blocker", "soften that one". Narrowing is the different case handled
above: those items go up as the user already read them. Rewriting to a steer produces
text they have never read, however faithfully it follows them — so render the set as it
will appear, show it, and wait for a second yes.

**Re-pin the head before you post, and re-enumerate the comments.** The PR moves under
you during the review, and the report and the user's yes both describe the revision you
pinned at the start. Fetch `headRefOid` and `baseRefOid` again — a rewritten base moves
the diff with the head standing still — and `git fetch` the new head into the checkout,
since `compare` below resolves those OIDs against the objects you hold rather than
through the API. Re-run the three comment endpoints for the same reason: feedback lands
mid-review as readily as commits do, and posting blind to it risks a duplicate thread on
a line another reviewer already covered. Re-run your own
findings against what arrived, through the rungs in *Take the cheapest rung that carries
the content*: one that now overlaps an inline comment drops to a reaction or a reply. The
user approved the enumeration, not that, so re-present the items that moved and ask again.

A moved head is not always a moved diff — on a stacked PR, the author merging the updated
parent branch in is the common case. The bundled script's `compare` command settles it
from the OID pair you pinned and the pair you just fetched, and its verdict beats your own
reading of the two diffs, which trips on things that are not changes at all. The
invocation is in `references/posting-a-review.md`.

Unchanged means the **anchors** still hold: re-validate them against the recomputed
diff, post with the new `commit_id`, and say in the report that the head moved and why
it did not matter. It does not mean the **findings** hold — the merge also brought the
parent's other changes into the tree, so re-check any finding that turned on code
outside the diff. A moved diff stops the post outright: the anchors were validated
against something that no longer matches, and GitHub marks comments carrying the old
`commit_id` outdated. Where the diff or a finding did change, read the delta, update the
report, and ask again.

### Clear a higher bar than you would for your own code

You post through the human's credential, so what goes up is spent from **their** standing:
in your own code a mistake costs a fix, here it costs someone else's credibility, and a
reviewer who has posted one impossible ask is discounted on every later one. Nearly every
false positive is an answer to a question the diff could not answer — how the thing is
deployed, how it has been running, what the rest of your other repos do, what the platform
guarantees — so clearing the bar is mostly a matter of widening the context.

These are the checks, each binding on its own. **Read `references/posting-a-review.md`
before you post**: it works through what each one costs to clear, and it holds the
endpoints you post through, so there is no posting without opening it. That file explains
the checks; it does not hold them — they apply whether or not you have read it.

- **Re-confirm the author hasn't declared the behaviour deliberate or dispositioned the
  risk** — the docstring and comments around the code, the PR body, the linked issue. A
  repro proves the behaviour, not that it is a defect.
- **Run the fix before you propose it**, in the head worktree: confirm it builds, that
  the narrowest test covering it passes, and that it doesn't break a neighbouring case.
  An ask that turns out to be impossible is worse than the finding was valuable.
- **Building and passing tests verifies nothing about a fix to configuration, defaults or
  deployment surface.** Establish what supplies the deployed value in **each** environment,
  from wherever that environment is actually declared.
- **Never assert another person's access, environment or intent unless they stated it or
  you verified it.** Inferring it from your own session is not verification. State the
  weakest claim that still carries the finding.
- **Separate correct from practical.** A remedy that needs a refactor three modules wide
  is a follow-up issue, not a review comment; say which one you are asking for.
- **An ask that introduces a pattern your other repos don't use carries the highest bar
  here.** Check what they actually do, name the ones you checked, and say why the shape
  is better rather than merely different. Where a specialist skill already requires the
  shape, *When a repo convention and a specialist skill contradict each other* applies
  instead.
- **Weigh how the code has actually been running.** A path that has served production for
  months without the failure you predict is evidence against you; say which way you
  reconciled that.
- **Reproduce the defect before you post it.** Running it is the evidence that settles the
  claim, and documentation never stands in for one however sound the reasoning built on
  it. Read the platform's own docs too, *before* raising the comment, and link the page
  you actually read rather than one from memory. With neither behind it, the claim is a
  question for the author rather than a finding.
- **Treat the barrier to reproducing as imagined until you have checked it.** Fall
  back to documentation alone only where reproducing would mutate production, needs
  access nobody has, or costs hours rather than minutes — then say in the comment that
  you didn't run it, and name the experiment that would settle it. A merge-blocking
  finding gets the least latitude, since it is the one asking the author to stop.
  `references/reproducing-a-finding.md` gives the shape.
- **Where you couldn't run the fix, say so in the comment.** An untested suggestion
  labelled as one is honest; the same words as an instruction are not. This latitude
  covers the remedy only.
- **Find the consumers before calling an interface change safe.** A signature, response
  shape or enum another repo reads is a cross-repo break the diff cannot show you, and "no
  consumers" is a finding worth stating rather than an absence worth assuming.
- **Re-read the set as the author before it goes up**, asking of each item: could I do
  this today, on this branch, as written? Anything that fails that question comes out.

Read from whatever context sources the session has — deployment config, error tracking,
runtime logs, a code search across your other repos — and don't write to any of them: a
go-ahead to post a review is not a go-ahead to touch infrastructure. Where reading is
free, just read; where a probe would create or cost something, ask first, and ask *before*
the finding goes up rather than posting it unreproduced with a caveat.

### Cut the set before it goes up

Everything above ranks and splits findings one at a time. The author pays for them all at
once, and nothing so far measures that — a review where every item passed each rule above
can still be 2,400 words and twelve minutes of their day.

- **Nothing the machine already blocks goes up on the PR at all.** A merge conflict git
  itself refuses, and a **required** check red on the PR — a failing test, a linter or a
  hook, whichever of them CI runs — stop the merge on their own, so the author is forced
  to them whether or not you say anything, and saying it spends their attention on a
  message they are already getting. Not as an inline comment, and not carried back in
  through the body either: the merge-readiness line does not itemise what the checks tab
  already reports. It goes to the user who asked for the
  review instead, with what it blocks.

  **What blocks is a question about the PR, not about your local run**, and the two come
  apart constantly. `gh pr checks <n> --required` is the answer — a non-required check
  forces nothing, and a suite CI never runs forces nothing whatever it did on your
  machine, so both stay findings and go up under the rules below. Where the repo has no
  CI at all, nothing here is covered: the local gate is the whole gate, and it gates
  nothing mechanically. Nor is a defect you found by reading the code covered — that a
  test nobody has written yet *would* have caught it is not the machine catching it.
- **Write everything you post blunt — the review body as much as each finding.** No
  opener praising the change, no hedges ("worth pulling on this", "fine either way"), no
  question softened into a suggestion when you need it answered. Verbose politeness
  isn't the kinder choice: it spends more of the author's time and buries the ask, which
  respects their attention less than a short direct comment does.
- Where a finding turns on a timeline, a time window or a data flow, an ASCII sketch or
  a mermaid block carries it in less of their time than a paragraph.
- **Assemble the whole set — review body, every inline comment, every reply — and read it
  once as the author rather than as its writer.** Measure that set with
  `docs`'s `reading_cost.py`, run from that skill's own directory; its
  *Posted review set* ceiling applies to the set, not to each item.
- Then cut. One finding stays one thread even when its fix spans several files — split
  across two, it is one finding the author reads twice. The converse binds too: two
  independent findings never share a thread, each anchored to its own offending line.
  Repeats of one violation take one comment on the first instance, asking for every
  repeat to be fixed. Drop narrative aimed at whoever *asked* for the review; that
  belongs in the report you already gave them. Trim any comment whose justification runs
  longer than its actionable ask.

### Take the cheapest rung that carries the content

Where a finding overlaps an **inline comment** already on the PR, take the cheapest rung
that carries the content. An agent's instinct is to write prose, so this needs saying
outright: **agreement alone is a reaction, not a comment.** A review body or a
Conversation-tab comment has no line thread to react to or reply in — engage with that
in your own review instead. Overlap with the **author's own** statements is not on this
ladder at all: the intent gate settled it while the finding formed, and anything
surviving that carries only the delta.

1. Agree, nothing to add → react on the existing comment.
2. Agree with a delta, *or disagree with what it says* → a reply in that thread carrying
   only the delta or the reconciliation. Disagreement belongs here rather than in a
   comment of its own, which would leave the author two disconnected threads arguing on
   one line.
   **On a bot's comment it is one line in the review body instead** — the bot won't read
   the reply or learn from it, so a thread apiece only charges the author a notification
   and a read each for a conversation they aren't in. Rung 1 still applies to a bot: a
   reaction costs them nothing.
3. Substance that answers no existing comment → your own inline comment on the review.

Everything else goes up as **one review, not N standalone comments** — each finding
threads on its line, and the author is notified once instead of N times. The endpoint for
each rung and for the review itself, with its payload, is in
`references/posting-a-review.md`.

- **Validate every anchor before posting.** The API accepts a `line` only where it falls
  inside a diff hunk, and it rejects the batch: one bad anchor 422s the whole request,
  with no partial post to inspect and no way to find the bad one incrementally short of
  posting the others for real. So check them all up front, against the hunks of
  **GitHub's** patch for the PR rather than a locally re-rendered diff — the algorithm,
  and why a local `git diff` yields a set GitHub disagrees with, are in
  `references/posting-a-review.md`. Added and context lines are both anchorable —
  GitHub accepts either — which makes "anchor a finding to a line the change touches" a
  rule about review quality rather than about what the API will take.
- **`event: "COMMENT"`, always.** Never `APPROVE` or `REQUEST_CHANGES` off the back of
  "post the review" — approving is a separate decision, and it is usually the thing a
  branch ruleset actually gates the merge on.
- **Say plainly which findings block, since nothing else will.** A `COMMENT` review
  leaves an existing `APPROVED` decision standing, so the PR stays mergeable however
  severe your finding — the word "blocking" in the comment is the whole of the signal,
  and a finding that needs one and doesn't say so reads as optional. The `(blocking)` /
  `(non-blocking)` decoration below is the form that word takes. State it in the report
  too, so the user knows what they are relying on the author to honour.
- **Prefer a committable `suggestion` block wherever the fix fits in one.** It is the most
  actionable form a remedy takes, since the author applies it from the diff view without
  retyping it. Its range constraint is tighter than a plain comment's: the replacement has
  to sit inside a diff hunk, so a restructure spilling past the hunk cannot be offered
  that way — a fix spanning lines 23-35 has nowhere to go against a `@@ -24,6 +24,7 @@`
  hunk. Carry that one as a fenced `diff` block with explicit `file:line` headers instead,
  and don't mix the two forms in one review. This is the remedy's *format* and is a
  separate choice from the `suggestion:` **label** below, which says what kind of comment
  it is — the two compose, and where the fix fits in a hunk you write both.
- **Sign it, in exactly this form.** You post through the human's `gh` credential, so
  GitHub shows them as the author. End the review body **and every inline comment** with
  a footer on its own last line, naming who wrote it and nothing else:

  ```text
  — Claude
  ```

  `— Codex` when Codex is the reviewer. That is the whole of the attribution: no "posted
  by an agent", no "on behalf of", no link, no per-comment variation. The account already
  carries who is accountable, and a reader here doesn't need telling what Claude or Codex
  is — every extra word is the author's to read. Left to their own wording, agents write
  a different attribution on each comment, which reads as several reviewers, not one.

  **Everything you post with a body takes it**: the review body, each inline comment, each
  in-thread reply, and any comment you go back and edit. Each carries its own because
  inline comments and replies are read in isolation from email notifications, where the
  body's footer isn't visible. A reaction has no body and a deletion leaves nothing, so
  neither takes one, and a self-review posts nothing at all.
- **Split by where it lands.** A finding anchored to a touched line goes inline;
  PR-description corrections, merge readiness and the skill triage go in the body. Both,
  always — a posted review carries a body. A finding that anchors to no touched line goes
  in the body too, rather than onto a line that doesn't carry it.
- **What you verified never goes on the PR.** It is the review's account of its own
  work — how you traced a path, what you ran, what you could not check — and the author
  is charged a full read for something that asks nothing of them. Report it in the
  terminal to whoever asked for the review, where the decision it informs is made. A
  verification that produced a finding is posted *as* that finding, and nothing else
  from the account goes with it.
- **The versioned skill list always goes in the body**, whether or not a summary does. It
  is the posted record of which rules the review was held to, and a reader who was not in
  the session has no other way to recover that. Post it as a **pre-collapsed *Skills
  used* section** — a `<details><summary>Skills used</summary>` block wrapping the table
  above — under the same name and in the same shape a PR description carries it, so the
  record is one thing a reader learns to find rather than two. Collapsed because it is
  provenance and not a finding: it belongs on the PR without spending the author's
  attention.
- **No CLI posts a review with its comments**, so the API is the only route — see
  `references/posting-a-review.md` for which endpoint carries what.

### Label every comment you post

Use these four labels and two decorations from
[Conventional Comments](https://conventionalcomments.org), and none of the others the spec
offers. Open each comment with one label and one decoration:

```text
<label> (<decoration>): <the comment>

issue (blocking): the retry has no ceiling, so a 500 from the scheduler path spins
```

The label comes first, the decoration in parentheses **after the label and before the
colon**, then the comment: `issue (blocking): ...`. That is the spec's own syntax and what
its parsers expect. Neither `issue: (blocking) ...` nor `(blocking) issue: ...` is the
adopted format.

**Posted peer-review comments only** — each inline comment, each in-thread reply that
carries an ask, and each finding the rules above route into the review body instead: one
anchored to no touched line, and the one-line delta on a bot's comment that rung 2 sends
there. A reply carrying no ask is the exception the closing paragraph names. The body's
other content is narrative rather than a finding and takes no label: the verification
summary,
merge readiness, the *Skills used* section. A PR-description correction falls either side
of that line — asking the author to fix a claim the diff contradicts is a finding and
takes a label, while recording what you checked is narrative. Rung 1 of the ladder above
is a reaction with no body, so there is nothing there to label. A self-review posts
nothing and so labels nothing, and a PR description carries no findings — that text is
`docs`'s.

| Label | Use it for |
| --- | --- |
| `issue:` | a defect in the change |
| `suggestion:` | a specific change you are asking for |
| `todo:` | a small, uncontentious change you expect done before merge |
| `question:` | something you need answered, asserting no defect |

- **The three gates hold whatever the label.** Evidence, Intent and Remedy are properties
  of the claim, not of the notation it is written in: a `suggestion:` or a `todo:` asks
  the author to change working code, so each clears all three exactly as an `issue:`
  does — including whatever latitude a gate already carries, which the label neither
  widens nor narrows. `question:` is the only one asserting no defect, and the bar below
  is its own rather than a lower one.
- **Every one of the four labels takes `(blocking)` or `(non-blocking)`.** An undecorated
  finding reads as optional, so the decoration is not reserved for the ones you think are
  contentious. It is the form *Say plainly which findings block* takes.
- **`question:` is not a route past the evidence gate.** It asks for something you need
  to know and asserts no defect. A defect you suspected but could not reproduce goes under
  *what you verified*, not up as a question with the claim intact — punctuating an
  unverified assertion differently still posts it, and posts it in a form the author
  cannot argue with.
- **A label is not a severity.** Rank by severity as *Report on separate axes* already
  requires; the label says what kind of response you want, and `(blocking)` says whether
  the author can merge without it.

**A new finding fitting none of the four labels is one the rules above already cut** — it
carries no ask, so it belongs in the report to whoever commissioned the review rather than
on the author's PR. That tests something you are about to raise, and not the two texts
that carry no ask by design: a reply that only reconciles with or disagrees with another
reviewer, and the one-line retraction left in place where *Revising what you already
posted* stops you deleting. Both go up unlabelled. A withdrawal that does delete writes
nothing, so there is nothing there to label either.

### Revising what you already posted

A later round supersedes findings that are already up. Amend those rather than posting a
second set the author has to reconcile against the first.

Its edits are writes to someone else's PR exactly as the first round's were, and the yes
you are holding covered what that report enumerated. So where this round would delete,
edit or rewrite anything, enumerate exactly that and wait for a yes on it — *Offer to
post the review* governs this round too. Where it would change nothing, say so and stop:
the approval is for the writes, not for having looked again. A delete is the one move
here that does not come back.

- An inline comment can be rewritten in place — same thread, no fresh notification — and
  so can a submitted review's body. `references/posting-a-review.md` has both endpoints.
- A finding on a line you have not already commented on needs a **new review** — a
  submitted review accepts no further inline comments. It goes up under the rules above:
  anchors validated against the current diff, `event: "COMMENT"`, head re-pinned.
- **Withdrawing a finding? Delete it — don't post a retraction.** A wrong finding has
  already cost the author a read; a reply saying so costs them a second one, to learn
  something they only needed to know because you posted it. Deleting takes it off the PR
  and leaves nothing to read. Two things stop a delete, and both mean editing **your**
  comment down to a one-line retraction, plus the attribution footer, in place rather
  than deleting the thread or replying under it:
  - **Anyone else has replied in the thread** — the author, another reviewer, a bot.
    Their words are not yours to remove.
  - **Something ties a change to the finding** — a commit message or a comment naming it,
    or the author saying they have pushed a fix for it. Deleting then leaves a change on
    the branch with nothing saying why it was made. Read what landed after you posted,
    not just the thread. A commit that merely touches those lines settles nothing, since
    it may be answering the finding or reaching the same code for its own reasons — and
    where you cannot tell which, keep the comment and edit it down. That costs two lines;
    deleting wrongly costs the record of why the branch changed.
- A finding you put in the **review body** doesn't come out this way, since a submitted
  review can't be withdrawn — only the inline comments are deletable. Rewrite the body
  without it, using the review-body endpoint the first bullet points at.

## Bar for merge

The local gate green — and CI too, wherever the repo has it — every available pass above
run and iterated to stable, and the only outstanding comments are ones explicitly judged
not worth addressing.

Reviewing is still not authorisation to act on the change: approving and merging stay off
the table in both modes unless the user asks. Posting is peer-review-only and needs the
explicit yes above. **A self-review posts nothing, and no instruction changes that** — not
a request to post, not one to publish the findings as notes; there the findings are a work
list for the user and the fixes go on the branch. Modifying the branch is the other
difference — expected in self-review, off-limits in peer review.
