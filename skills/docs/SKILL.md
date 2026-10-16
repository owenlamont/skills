---
name: docs
description: Write what a human has to read — issue and PR bodies, review and conversation comments, commit messages, code comments and docstrings — at the length a developer here would have typed. Use when drafting or editing an issue or PR body, replying to or resolving review comments, writing a commit message or a code comment or docstring, deciding whether to raise an issue, or scoping a non-trivial change before generating code.
---

# Docs

A named human reads every word of this and is accountable for the change. Their reading
time is the scarce resource, not your output. **Write what a developer here would have
typed, not what you can generate.**

## Length

These are ceilings, not targets: most artifacts should come in well under them, and the
shortest body that carries the change is the right one. A budget is what
`scripts/reading_cost.py` counts — visible prose, with collapsed `<details>`, rendered
diagram fences and blockquotes (`>`) costing nothing, as code blocks do. A line that
renders inside a quote without its own `>` is still charged.
**Structure is free; content is charged.** A table's cells
cost exactly what the same words cost in a sentence — only its pipes and separator row are
free — so moving prose into rows shortens nothing. It is not open to reinterpretation: run
the script rather than arguing about which tokens count.

| Artifact | Ceiling |
|---|---|
| Issue or PR body | **150 words**, and no single visible section over 60 (each heading's prose is a section) |
| Posted review set | **400 words** of prose: the body, every inline comment and every reply as one file, judged on the report's *Prose words*, with no `--strict`, which gates at 150 |
| Inline review reply | one or two sentences, matching the comment it answers |
| Commit subject | conventional-commit, under ~10 words |

**The 60-word section ceiling is the one that usually binds first**, and it is the one
whose fix is not cutting: a section over it splits under a new heading.

- **Draft in the order that ends short.** The title's ask first, then the evidence that
  pins it, and nothing else by default. Add a section only where you can name what the
  reader does with it — where you cannot, it is the section a trim would delete, so don't
  write it.
- **Bullets, not paragraphs.** A body of complete sentences is the tell. Fragments,
  lists and tables are the register — a heading plus three fragments beats a paragraph
  saying the same thing.
- **Length comes from pasted evidence, never from explanation.** A stack trace, a list
  of values, a query, a screenshot, a diagram — paste it rather than paraphrasing it.
  Prose that describes evidence you could have pasted is the thing to delete first.
- **Assume the reader knows the project.** They know its services, its tables, its
  conventions and its tooling. Explaining any of it is padding — write only what is
  specific to this change.
- **Delete, don't collapse or tighten.** Asked to shorten, an agent rewrites sentences;
  the reduction that works is dropping a whole section. If you cannot name who would
  expand a `<details>` block, delete its content instead.
- **A required template field is not a requirement to write.** One line, or a dash, is a
  complete answer. Leave blank every section whose content is not yours: an "in your own
  words", a sign-off, a manual checklist, or the sections a meeting exists to produce.
- **Fetch one sibling artifact and match its structure and register** — the neighbouring
  PR in the repo, the last report in the same database. Where the sibling is shorter than
  the ceiling, it is the target; where it is longer, the ceiling still binds.
- Measure a draft before posting. Run the script from **this skill's own directory**
  (the harness prints it as *Base directory for this skill*; a repo-relative path
  resolves only inside a checkout of the skills repo itself). `--strict` exits non-zero
  over budget, so it answers rather than advises:

  ```sh
  uv run --script <skill-dir>/scripts/reading_cost.py --strict draft.md   # before posting
  gh pr view <n> --repo <owner/name> --json body -q .body \
    | uv run --script <skill-dir>/scripts/reading_cost.py --strict -      # after the fact
  ```

  **`--repo` is load-bearing on the piped form**, since `gh` otherwise resolves the repo
  from the cwd — so without it, or another explicit context such as `GH_REPO`, the audit
  runs only inside a checkout of that repo.

  Write the draft to a file and measure *that*. The piped form reads a body that is
  already published, so it audits rather than gates — reaching for it first means every
  trim is an edit someone may have read.

  Reach for a diagram where one carries the change faster than prose; the script reports
  its lines and charges nothing. Write ATX headings (`## Title`): only those divide a
  body into sections, so a setext underline reads as prose and a body with no ATX
  heading has **no** sections at all — the 60-word ceiling never fires on it and the
  150-word total is the whole gate. Prose above the first heading is its own section,
  reported as `(lead)`, and is charged that ceiling like any other.

## Name the noun, never point back

**Repeat the noun rather than writing "this", "that", "these", "those", "it" or "its" for
something an earlier sentence or bullet named.** A bullet, a comment or a PR section is
often read alone, and a reader who starts there has no antecedent.

- Two uses stay allowed: a relative "that" ("the hook that fails"), and a possessive
  whose noun sits in the same sentence ("the script and its tests").
- A demonstrative followed by a noun ("that mirror") is a determiner, not a pronoun, and
  passes.
- Find candidates in the lines a branch adds, or point the last `grep` at a draft file
  (the `[t]` keeps the pattern from matching its own line):

  ```sh
  git diff -U0 origin/main -- '*.md' | grep -E '^\+[^+]' \
    | grep -E '\<(Th(is|at|ese|ose)|I[t]s?)\>'
  ```

  The pattern matches capitalised forms only, so the grep finds sentence- and
  bullet-initial pronouns and misses a lowercase mid-sentence "it", which needs a read.
  Over the added Markdown lines of five merged skill-catalogue PRs, about a quarter of
  hits were false positives, mostly a demonstrative before a noun and once a "these"
  opening the list after a colon, so judge each hit rather than rewriting every one; a
  different corpus moves the quarter.

## Issues: the ask, not the design

- **The title carries the ask. The body carries only what the title cannot** — a
  constraint, a value, a link, the evidence. An issue whose title is self-explanatory
  needs no body.
- **Do not design in an issue.** A proposed solution is one line of direction or
  nothing; the design is settled with the human when the ticket is picked up, by
  interviewing them then. Alternatives considered are for an alternative genuinely
  rejected, not a survey.
- **Acceptance criteria are a checklist**, one line each, not prose.
- Raise one only when it is actionable, and prefer one issue per subject: issue churn is
  a reader cost too.
- **A title has to stand alone.** It names what, and of what, and carries no reference
  to resolve elsewhere — no bare `#123`, no term meaning something only inside its own
  change. The body's opening takes the same test — it may link to the detail, but a
  reader who has not followed the link still has to know what the ask is.
- **Consolidating a body from its own comment trail:** read the result once as the
  implementer. Superseded drafts leave one decision stated two ways, and you cannot see
  it because you remember which draft won.

## PRs: what the diff cannot say

- **What changed and why now** — the lead section, and the only one with a guaranteed
  job. Link the issue rather than restating it.
- **How it was tested: name only what CI does not run** — a manual check, a deploy, a
  screenshot. If the checks cover it, leave it blank.
- **Notes for the reviewer: risk, not narrative.** Where to look, what could break, a
  trade-off that could have gone the other way. It is the section with no defined job
  and it absorbs everything; write nothing rather than filling it.
- **Where one of these shapes is in the change, the diagram is expected rather than
  optional** — *Reach for a diagram where one carries the change faster than prose* above
  governs everything else, and does not license skipping one here:
  - a request path, or a call crossing a deployment boundary — a sequence diagram;
  - a change to tables, columns or the relationships between them — an `erDiagram`;
  - a status or state contract — a flowchart.

  It keys on the shape rather than on a kind of change, so a PR adding an enum or a
  function — where the schema moves and no relationship does — needs none of the three.
  A `mermaid` fence costs nothing against the budget, so cost is never the reason to
  leave one out, here or under the general test.
- **`Skills used`** — the versioned table `pr-review` defines, rows sorted by skill
  name, on any PR a skill informed, inside a collapsed
  `<details><summary>Skills used</summary>`. Use the template's own section where it has
  one; otherwise append it after the template's, once.
- **Closing references** — repeat the keyword once per issue on one line
  (`Closes #4, closes #5`, never `Closes #4, #5`), and only where the PR **reaches** the
  default branch. In a stack whose trunk is the default branch each member's reference
  fires at its own merge; a bare chain of `--base` PRs is not a stack and links nothing,
  so put the reference on the PR that reaches the default branch, or close by hand.
  **A negation does not disarm the keyword** — a sentence saying an issue is *not*
  closed still carries `close #N` and still links it, so write the reference nowhere you
  do not mean it. On a squash merge the subject and body are the commit message. Read
  the links back with
  `gh pr view <n> --repo <owner/name> --json closingIssuesReferences` **before** merging,
  which is what catches a reference you did not mean;
  `gh issue view <n> --repo <owner/name> --json state` only shows the damage afterwards.
  **Every `gh` call in this skill carries `--repo`**, since without it one resolves from
  the cwd — erroring outside a checkout, and quietly reading the wrong repo's issue
  inside a different one.

## Match the template

- **Look before drafting.** PRs: `PULL_REQUEST_TEMPLATE.md` in the root, `docs/` or
  `.github/`, or a `PULL_REQUEST_TEMPLATE/` directory in any of them. Issues:
  `.github/ISSUE_TEMPLATE/*.md` or `*.yml` (`config.yml` is the chooser). Several? Match
  the change to the one whose `name`/`about` fits; if ambiguous, ask.
- Mirror its sections and their order and add none of your own, bar `Skills used`. A
  `.yml` issue form cannot render through `gh --body`, so reproduce its fields as
  headings.
- No template: what changed, why, risk, where to focus. For an issue, the ask.

## Comments and replies

- **Fix it and resolve the thread — no "done" reply.** Reply only to decline, briefly,
  and resolve that thread too.
- **Match the reply to the comment.** A paragraph answering one line is the mismatch,
  whatever it contains.
- **A hedge is not a withdrawal.** "feel free to ignore", "not blocking", "nit", "just
  curious" — the objection is the clause *before* the hedge. Action it, and key this on
  the wording, never on the person.
- Believe a reviewer's own severity label rather than re-ranking it.

## Code: never narrate

Most recorded reviewer objections land here, not on bodies. **A comment earns its place
only by explaining an unavoidable third-party smell, the reason for a version pin, or an
opaque trade-off or workaround.** That bar is this section's and it holds in every
language; where a language also has a standards skill, read it for what it adds on top —
`python-code-style`'s *Comments and docstrings* carries Python's docstring conventions.

- **A comment is one sentence**, however many lines it spans. Wrapping it to fit the
  line length adds none, and splitting it into a stack of adjacent own-line comments
  adds none either — the script folds a stack into one comment and counts the sentences
  across the whole run, so three stacked one-sentence comments are one comment of three
  and fail. A stack is how agent commentary arrives; needing a second sentence means the
  code should be clearer instead.
- **A doc comment is judged on different terms** — a Python docstring, Rust's `///` and
  `//!`, a JSDoc block. It ships to a consumer rather than to a reader of the code, so
  the one-sentence bar does not reach it and the only question is whether it carries
  semantics the signature does not.
- **Never narrate what the code does, how it got this way, or what you changed** — in
  any language. The bar reaches configuration and infrastructure languages too, most of
  which have no standards skill behind it. Explaining why the code has to take a
  non-obvious *form* is a different thing and stays allowed, under the bar above.
- **Enumerate every comment and docstring line the diff adds, and delete each one whose
  fact you cannot name. The default is delete, not shorten.** The bundled script
  enumerates the own-line comments and the doc comments, cites the rule each has to
  clear, and exits non-zero on a `FAIL`; it never reaches a trailing comment on a code
  line, so check those yourself. It lexes each language rather than matching line
  prefixes, so a `#` or `//` inside a string, heredoc or template literal is not counted
  and an attribute is not read as a comment; a suffix it does not list is skipped, and
  its closing line says how many files it actually audited:

  ```sh
  uv run --script <skill-dir>/scripts/comment_audit.py --repo <checkout> --base origin/<base>
  ```

  Its `CHECK` lines are not passes. Justify each against the bar above, or delete it.
- **A coverage or comment-ratio gate is not that audit.** Under one the gate's number
  becomes the goal, and the fix presents as shaving words off comments that should not
  exist at all. Audit first — enumerate and delete against the bar — and measure the ratio
  only after, on what survived.

## Before you post

- **Never post a body built from a copy fetched earlier in the conversation.** An edit
  replaces the whole document, with no merge and no conflict detection, and what you
  overwrite is usually the human's own section. Re-fetch at the moment of editing, apply
  the change as an anchored assert-and-replace, and fail closed: exactly one anchor
  match and every human-authored section still present, or stop and ask.
- Keep the agent's `Co-Authored-By:` trailer on commits it wrote.
- **Where the human's account is what posts, every body ends with the attribution
  footer on its own last line** — `— Claude`, or `— Codex`. The commit trailer does
  not cover an issue, a PR or a comment, and a reaction has no body. Unsigned text
  reads as their words on something they have not read.
- **Durable decisions** (why X over Y, a constraint outliving this PR) — surface them
  and let the human decide whether and where they are recorded. Do not open the record
  yourself.
- **Ephemeral working notes** — scratchpad only; never committed into a reviewed
  artifact.

## Plan before building

- Scope the work and confirm direction *before* writing code, and state in one line what
  you are **not** doing.
- Confirm the direction with the human wherever the approach could fork, rather than
  picking one silently.
- Before raising, name the seam you would have split on and say why you did not — or
  split.

## Elsewhere

Reviewing someone else's PR, and what a review body contains: `pr-review`.

**A reference to an issue in a different repo takes the `owner/repo#123` form**: a bare
`#123` resolves against the repo the text is published in.
