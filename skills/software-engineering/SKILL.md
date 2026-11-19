---
name: software-engineering
description: General engineering practice that applies in every language — verify a command or a claim by running it instead of trusting memory, diagnose before changing code, spike a risky assumption before building on it, and prefer changes that leave the codebase smaller and simpler. Load it alongside whatever language-specific skill fits, and on its own when none does. Use when writing, refactoring or debugging code in any language, including Go, shell, YAML and TOML, which have no other standards skill; when adding or changing a CI workflow, a build file, or a linter or tool config; when a tool, lint rule, hook or pipeline misfires and you need to work out why; when investigating a failure, documenting a command or asserting that something works; when double-checking whether a remembered behaviour or limitation of a library, language or tool still holds; when weighing a dependency or an abstraction, scoping a risky change, or deciding how to make progress while blocked on something else.
---

# Software Engineering

Engineering practice that isn't tied to one language or tool. The specialists own their
own rules — `python-*` for Python, `sql-data-modelling` for SQL and the schema under it,
`pr-review` for reviewing a change, `docs` for anything a human reads — so
this skill holds only what none of them covers, and points at them rather than restating
them.

## Verify, don't assert

An untested command, untested code, and a remembered behaviour are all claims, not facts.
Apply to your own output and your own recollection the scepticism you would apply to a
stranger's.

- Treat what you remember about a language, library, or tool as a stale cache rather than
  a source of truth. Ecosystems move quickly — versions ship, APIs change, limitations get
  lifted — so check the docs, the source, or the runtime for the version actually
  installed before asserting how it behaves or what it can't do. A confident "X doesn't
  support Y" is the claim most likely to have expired, and human and model recollection
  go stale the same way.
- Run a command and read its actual output before documenting it, shipping it, or saying
  it works. An untested command tends to break in precisely the situation it was written
  for.
- A regression claim needs a repro that brackets it. Run the *same* script against the
  last good version and the reported one, and make its exit code carry the result — `0`
  on the earlier, non-zero on the later. Asserting the boundary in prose while only ever
  running the broken version leaves the reader's first move untested. Guard any API the
  offending change introduced (`getattr(obj, "attr", None)`) or the script dies on the
  earlier version and reports the failure as the bug: a diagnostic line touching an
  attribute that shipped *with* the regression made a published repro exit non-zero on
  the version it was meant to clear.
- `--help` output and usage strings are evidence about syntax, not behaviour. A flag that
  appears in a usage line can still be rejected at runtime, and two options printed side
  by side may not be accepted together. Run the exact invocation you intend to document.
- Give a reviewer's proposed fix the same scepticism as the code it fixes, and verify it
  before applying it — an untested suggestion can introduce the very defect it claims to
  remove.
- Re-probe a claim inherited from someone else's comment, notes, or rule header before
  repeating it, most of all when it is labelled as measured. A "measured, not assumed"
  header in one repo carried two false claims about what a linter could enforce, and that
  label is precisely what stopped them being retested before they were written into shared
  guidance. Stated confidence is not evidence, and a claim copied into documentation
  outlives the context that made it plausible. You cannot introspect whether content
  helps a future agent session either: measure that too rather than asserting it.
- Check a hard constraint programmatically instead of by eye before presenting the result.
  When the requirement is a limit, a count, or a format, measure it.
- A search or list result sitting at its cap is *unknown*, not complete. Nothing in the
  response marks it as truncated, so a returned count equal to the limit is the only
  tell — page it, raise the cap until the count comes back under it, or report the figure
  as a floor, and say which of the three you did. An explicit limit is a ceiling, not a
  promise: a search spanning many containers can cap per container *and* rate-limit
  partway, so one call can cover a fraction of the set twice over. A count of zero from
  a paginated API is the same case — "unknown", not "none", until the pagination is
  exhausted or a rare-target control has been watched to succeed.
- Bound a measured conclusion to exactly what you measured, a positive as tightly as a
  negative. "The probe found nothing" is a fact about the forms that were in the probe,
  not about the mechanism: a bare-call probe showing that ruff's `banned-api` cannot ban
  `getattr` became "it cannot ban a builtin", which is false for every form written
  through an import. A positive generalises just as readily — measuring rigorously how a
  renderer displays one description, then asserting "all 19 sit on top-level models",
  which was never counted and was wrong. This is not the untested-claim failure above —
  the measurement was real every time, and the error was in the scope of the conclusion
  drawn from it. Report the forms you tried beside the result, so the untested ones stay
  visible instead of being generalised away.
- Show a harness can fail before trusting it to pass. A probe has to carry whatever
  context the rule under test needs in order to fire, and one that extracted a single line
  into a fresh file could not exercise an import-based lint rule at all — it reported seven
  working bans as holes. Run a known-bad case through first, and treat "zero hits" as
  evidence only once you have watched the harness produce a hit **on a case carrying that
  context** — a hit from a probe simpler than the real ones shows the harness runs, not
  that it reaches them.
- **A probe that deliberately breaks root or config-path handling runs against a
  throwaway environment, never the live one.** The override the script offers — a
  `--home`, a `--root`, a `--prefix` — is the very thing such a build stops honouring,
  so passing it while the real environment stays reachable isolates nothing. Redirect
  every root the program derives from the environment rather than the obvious one alone:

  ```sh
  scratch=$(mktemp -d)
  mkdir -p "$scratch/home" "$scratch/xdg"
  HOME="$scratch/home" XDG_CONFIG_HOME="$scratch/xdg" <command>
  ```

  Where the injected defect cannot reach path resolution — a broken output check, a
  wrong exit code — the override is isolation enough.
- **A tripwire watches where an escape would land, not where a correct run lands.**
  Asserting the throwaway paths were written is not one: the probe's own seeding
  guarantees that, so it passes against a deliberately broken root. Assert instead that
  the path an escape would land on is untouched — under the redirection above that is
  the sandbox's own fallback, and the real one stays unreachable throughout — and
  confirm the assertion can fail by running it against the broken arm before you trust
  it. A target that does not exist yet is still checkable: snapshot its absence and
  assert it stays absent. Resolve both sides first, since a symlink or a bind mount can
  make the two paths one file, and the throwaway write then reads as an escape.
- Run a control arm — a case the thing under test must allow — and read no result from
  the harness until that arm has passed. A broken harness does not have to look broken,
  and it does not have to look like success either: a probe that silently discarded the
  credentials it was built to test presented as round after round of "the permission
  hasn't propagated yet" — a plausible pending state, and one that argues for waiting
  rather than for suspecting the probe. The arm that must succeed is what separates the
  two. It is also what lets a reader who cannot audit your setup rule out "you
  misconfigured it", so report it beside the result rather than keeping it as a private
  check.
- Match the control arm to the target's rarity, not merely to its presence. A control
  that passes tests only the code path it exercises: filtering a log for a term present
  in most records returns on the first page and never touches the paging the real query
  depends on, so it confirmed the syntax and the credentials while a rare-target query
  came back empty from a store holding a thousand hits. A rare target needs a control
  that is also rare — a term known to occur a few times in the window — or a tool built
  for exhaustive counting rather than a tailer.
- A check that passes is evidence only once you know it ran on your code. A hook, linter,
  type checker or coverage gate configured for a layout the repo doesn't have reports
  success by checking nothing, and green is then indistinguishable from covered. Before
  trusting a gate you have never watched fail, break something it should catch — a
  deliberate type error, a failing assertion, a line the rule bans — and confirm it goes
  red. Make that broken case resemble the files you actually ship, or the probe confirms
  a gate that isn't covering them: a type checker skipping every standalone script in a
  repo still went red on a throwaway probe in the same directory, because what it skipped
  on was a header the throwaway didn't carry. The probe went red for the wrong file.
- Check the reason, not just the answer. A rule or a carve-out that reaches the right
  conclusion through false reasoning is still a defect, because whoever extends it next
  works from the stated reason rather than the list: an allowlist justified as "these are
  unreachable" survived review while its reason did not, and the next entry added on that
  basis would have been wrong.
- Confirm the end state before concluding. Don't call something stuck, working, or
  finished on partial evidence: a process that has emitted nothing yet is not the same as
  one that has died.
- Watch a background process by its PID, never by a pattern. `pgrep -f <pattern>`
  matches the shell running the check, `grep -v grep` discards any process whose command
  line mentions grep, and even a bracketed `grep '[c]odex'` matches the watch loop's own
  echo — each reported a finished run as live or a live one as finished. The PID can
  match nothing else, so capture it in the same shell that backgrounds the command and
  poll `kill -0`; a wrapper the harness backgrounds returns the wrapper's exit, not the
  tool's. Bound the wait and report what it was waiting on when it gives up, and read
  stderr a few seconds after launch: a CLI rejecting an argument dies in under a second
  and looks exactly like a run that has produced nothing yet.
- Capture an exit status on its own line, `RC=$?` immediately after the command, and
  report `$RC`. Inside a composed line `$?` is whatever finished last during expansion,
  not the command you meant: measured in bash, `false; echo "$(exit 3) rc=$?"` prints
  `rc=3`, because the substitution runs before the `$?` beside it is expanded. A check
  written that way reports on its own scaffolding and reads as a pass.
- A pipeline's exit status is its **last stage's**, so never gate an action, or print an
  all-clear, off one whose last stage is a filter. `tail`, `head` and `grep -v` succeed
  on any input, so `cmd | grep -v Passed | tail -3 && echo CLEAN` prints `CLEAN` whether
  or not `cmd` failed; `cmd | grep -c Failed && commit` inverts the same defect, running
  the action only when `cmd` *did* fail. Across 11,508 recorded shell calls, 82
  self-declared all-clears were printed by chains that could not fail, with real failures
  masked under them. `set -o pipefail` fixes the status but not the habit, and is off by
  default in bash; run the command on its own line, capture `RC=$?`, test that, and
  filter the saved output afterwards.
- Anchor a text replacement on whole lines, ending included, and assert the match count
  is exactly one before writing. A pattern starting or ending mid-line leaves the rest of
  that line attached to the edit, so the tail is silently joined onto the replacement —
  and the file still parses, so nothing downstream reports it.
- A subagent's output file appearing is not the signal that it finished — the file
  exists before the agent has finished writing it. Wait for the completion notification,
  then read.
- Never invent an identifier for something you claim to have created or found — an issue
  or PR number, a commit SHA, a URL. Report a side effect only after the call that caused
  it has come back, and quote the identifier that call returned. Repeating one the user
  gave you, or building a link from parts a tool did return, is not the failure this
  guards against; asserting a number for work you haven't confirmed happened is.

## Diagnose before you change

- Reproduce the failure, or instrument the code until you can observe it, before changing
  anything. A fix aimed at a symptom you never actually saw is a guess.
- Fix the cause rather than the place the symptom surfaced. A spot-patch that leaves the
  cause in place buys time and returns later, usually somewhere less convenient.
- Enumerate the family rather than patching the instance you were handed. When a review
  or a report names one member of a class of problem, derive the whole surface and test
  every member of it: eleven of twelve review rounds each finding a fresh instance is the
  signature of fixing reported rows one at a time, and switching to enumeration — deriving
  the candidate list programmatically instead of widening it by hand — both converged the
  work and turned up five members nobody had reported.
- Read the documentation or the upstream source when a library, framework, or remote
  service behaves opaquely, rather than trial-and-error patching around it.
- Capture the actual state when something fails — the response body, the event stream, the
  effective config — rather than theorising from the symptom.
- Treat the absence of an expected artifact as a signal that localises the fault: a run
  that produced no log, no transcript, or no output file failed before the step that
  writes it, which narrows the cause faster than reasoning about the symptom does.
- Send diagnostics to a file rather than piping them through `tail` or `head`, which
  buffer until the producer exits — so killing a stalled process discards exactly the
  output you were trying to read.

## Make a long run observable

A process that takes minutes or hours is watched by someone who cannot see inside it.
Build the reporting into the loop while you are writing it, rather than adding it after
the first run has already gone quiet on someone.

- Report progress while the run is still in flight, not only once it finishes. Whoever
  is watching should be able to answer "is it alive, how far in, how much longer" from
  the log alone, without attaching a debugger or watching the output file grow. A run
  that announces its plan and then says nothing for an hour is indistinguishable from
  one that hung on its first item. A periodic line carrying units done against the
  total, the percentage, and the elapsed time answers all three at once.
- Derive the ETA from the rate the run is actually achieving, not the rate it was
  planned to achieve. Intended pacing leaves out latency, retries, and backoff — which
  is precisely what makes a run overrun — so an estimate built from the plan reads as
  authoritative and stays wrong for the whole run. Compute it from elapsed time over
  units completed, so it absorbs whatever the run is really encountering.
- Record the outcome of every unit of work, the successes as much as the failures.
  Isolating a failure so the rest of the run can continue is a legitimate recovery, but
  it is only half of one until the handler names which unit failed and why; unrecorded,
  that item is indistinguishable from one that was never attempted.
- Pace the progress reporting to the length of the run, so the routine lines don't bury
  the exceptional ones. A line per item across eight hundred items hides the three that
  failed — report once per interval or per batch instead, and let the failures stand out
  by being rarer.
- Persist the expensive artifact as it is produced, rather than only the conclusion
  drawn from it. Where the cost of a run is in the acquisition — API spend, rate-limit
  pacing, hours of wall-clock time — write each raw response to disk as it arrives and
  run the analysis against those, so a bug found afterwards costs a re-analysis instead
  of a second full run.

Which logging library, sink, and format to use is a project-level decision that the
project's own skill or docs should own; this section governs what has to be observable,
not the mechanism. `python-error-handling` sets the severity levels for Python, and
*Confirm the end state before concluding* above is the reader's side of this — a run
that reports nothing gives the reader nothing to confirm against.

## Scope and sequencing

- Re-triage which skills apply whenever the work changes medium — prose to code, one
  language to another, reviewing to authoring, application code to the infrastructure
  that deploys it. Whatever loaded at the start was chosen against the task as it was
  first described, and nothing re-runs that choice when the task turns into something
  else, so a session that began as documentation and ended up writing a parser stays
  under the documentation triage the whole way. Re-read the catalog against the work
  actually in front of you, and load what the new medium fires rather than assuming the
  opening triage still covers it.
- Spike a risky assumption at the smallest scale that could disprove it, before building
  on top of it — so a wrong assumption costs one throwaway experiment rather than a
  finished implementation.
- Take a feature in three passes — make it work, make it right, make it fast. The first
  pass only has to prove the approach, so don't slow it down polishing code you may
  throw away; the second pass is the one that lands, and it carries the tests, the
  naming, the edge cases and the current standard.
- Make it fast only once a measurement names the slow part. Intuition about where the
  time goes is unreliable, so a profile rather than a plausible story is what justifies
  an optimisation, and since speed usually costs readability the gain has to be worth
  that: a hot path can repay it where code that runs occasionally never will. This gates
  work that trades shape for speed — writing code in the form a standard already requires
  is not optimisation.
- Build the reusable tool rather than the throwaway script when the same need is likely
  to recur; a script used three times has earned a home and a name.
- Fix friction the moment you hit it, so long as it sits in the files the change already
  touches. Friction further out goes to the human as a cleanup of its own rather than
  widening the change in front of you, and anything too large to absorb now gets an issue
  capturing it rather than being left to slide.
- Write new code to the current standard even where its neighbours predate that standard
  and fall short of it. A briefly inconsistent repo is the better trade: consistency with
  code written before the rule existed is not a reason to keep breaking the rule, and
  matching the old shape entrenches it one module at a time.
- Don't convert those neighbours in passing either. When you find a body of code the
  standard now contradicts — the surrounding modules, a whole test suite — put it to the
  human as a cleanup of its own rather than absorbing it into the change in front of you,
  which keeps that change reviewable and settles the question instead of leaving it to be
  re-decided next session.
- When you are blocked, say so and stop, rather than speculatively changing the thing you
  are blocked on — an edit made to feel productive while waiting usually has to be
  unpicked. What to work on instead is the human's call.

Confirming the direction with the human before writing code is `docs`'s
*Plan before building*; this section is about de-risking once the direction is agreed.

## Design judgement

- Prefer the change that leaves the codebase smaller, simpler, and more consistent.
  Maintenance cost is a first-class cost, and growth that isn't paying for itself is a
  design smell rather than progress. Measure that rather than judging it by eye:
  `scripts/source_size.py` walks whatever roots you name, and `--compare-to <ref>` reports
  the files, lines and bytes each gained. Run it from the repo root on any non-trivial
  change, passing `--ext` for another language — a suffix or a whole filename, so
  `--ext Dockerfile` works. It counts only what Git tracks, so nothing ignored skews the
  reading.

  ```sh
  uv run --script <skill-dir>/scripts/source_size.py --compare-to origin/main
  uv run --script <skill-dir>/scripts/source_size.py <dir> [<dir> ...] --compare-to main
  ```

  **The roots are positional and default to `src tests`**, so a repo laid out any other
  way has to name its own — there is no `--roots` option, and a run finding neither
  directory exits 1 having measured nothing.

  Where it shows growth, say what grew and what you considered deleting instead; whether
  to go back and shrink it is the human's call. There is no threshold to clear — a
  number to optimise gets met by deleting something load-bearing, and a rewrite demanded
  by a size reading buys premature abstraction.
- **A cleanup or a refactor is expected to come out net smaller**, so growth there is a
  result to report rather than a trade to absorb quietly. One can legitimately grow — an
  extracted helper, an explicit type, a case made explicit — but that is the argument to
  state, not to assume.
- **Establish that an input is reachable before guarding it.** Name the client, feed,
  code path or migration that produces the value; where you cannot name one, the guard,
  its exception, its handler and its tests are all surplus. Construct the value at the
  real entry point rather than weighing how plausible it looks — that is usually one
  command. Check the producer you actually have: two clients writing the same wire
  format can differ, one refusing the value outright and the next encoding it silently,
  so a result from one bounds nothing about the other. A mutation check settles nothing
  here either: it shows the code reads the input, not that anything sends it.
- **Reach for deletion before addition.** A defect is often best answered by removing what
  is wrong rather than replacing it with something right: the rest of the system usually
  covers the ground already, and a correct replacement for something that needn't exist
  is still surplus. The same holds for a carve-out answering an over-broad rule, and for
  bespoke logic that a smaller and more consistent shape would subsume.
- Add a dependency only when it shrinks the code you have to maintain or solves a
  genuinely hard problem; adding one to avoid writing ten obvious lines is a poor trade.
  The same measure cuts the other way, so it is not an argument for hand-rolling: a
  maintained library beats reimplementing a solved problem, and for Python
  `python-libraries` names which cases those are.
- **Use a maintained implementation wherever correctness depends on specialised
  knowledge, however short a hand-rolled version looks.** The tells: implementing an
  external standard and its compatibility rules (Unicode, time zones, a wire protocol);
  a security mechanism (cryptography, secure randomness, sanitising untrusted input); or
  an algorithm with subtle numerical, scaling or concurrency guarantees
  (arbitrary-precision arithmetic, floating-point summation, synchronisation). Reading a
  field from a format, or writing your own application's rules, stays ordinary code.
  "No new dependency" let through a hand-written big-integer conversion that ran about
  100× slower than `num-bigint` at 100,000 digits.
- **Test your use of a dependency, not the dependency.** Assert what your code does with
  the library's result — the call it makes, the value it passes on, the error it maps —
  and drop cases the library already guarantees, such as a big-integer type's sign,
  leading-zero or limb handling. Those tests only re-run the library's own suite.
- Don't special-case. Tune the policy or the configuration knob instead: dispatching on
  a capability or a category is fine, branching on one specific identity is not. Where
  the identity genuinely *is* the requirement — a contractual exception, a rule applying
  to one participant, a workaround for one upstream service — carry it as data the policy
  reads (a config entry, a lookup table) rather than a branch in code, and record why.
  That keeps the exception visible and revocable instead of buried in a condition.
- Two code paths that handle the same event or action — a create, a retry, a cancel,
  reached from a webhook and from a form — should behave identically by default. A
  deliberate difference, such as a different trust source, needs a stated reason.
- Never silence a type checker or a linter merely to make it pass. A suppression is a
  decision that needs a justification; the language's lint skill owns the mechanics
  (`python-lint-format`'s *Resolving a failure* for Python).

Comments, docstrings, and anything else written for a human to read are
`docs`'s, which already sets that bar for every language.
