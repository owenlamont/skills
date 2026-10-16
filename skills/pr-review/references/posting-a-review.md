# Posting a review

Read this before anything goes up on someone else's PR. It carries two things: what each
check in *Clear a higher bar than you would for your own code* costs to clear, and the
endpoints the review goes up through. The bar comes first deliberately — you are here for
the mechanics, and the mechanics are what put a wrong claim under the reviewing human's
name.

Every rule stays in `SKILL.md`. Nothing here relaxes one: this is what clearing them
looks like in practice.

## Clearing the higher bar

One entry per check in `SKILL.md`'s list, in the same order. The check is the rule; this
is what clearing it costs.

**Re-confirm the author hasn't declared the behaviour deliberate or dispositioned the
risk.** Read the surrounding docstring and comments, the PR body and the linked issue:
a finding can clear the evidence bar and still fail the intent one. The intent gate
under *Report on separate axes* owns that check and is where it belongs — this is the
last pass before spending the author's attention, not the first, and a finding
reaching here unchecked has already been written up and presented.

**Run the fix before you propose it.** Apply it in the head worktree — which exists so
there is somewhere to mutate — and confirm it does what the comment says: it builds, the
narrowest test covering it passes, and it doesn't break a neighbouring case. The asks that
turn out to be impossible fail in a small number of ways — the type won't permit it, the
helper doesn't exist, or the test it breaks is the one pinning the behaviour it was meant
to protect. This is the remedy's own bar, separate from the defect's, and both apply to
the same comment.

**Building and passing tests verifies nothing about a fix to configuration, defaults or
deployment surface.** Establish, per environment: which environments exist at all, whether
the variable is declared and passed there, and what the code falls back to where it isn't.
A default that looks inconsistent with its siblings is often the delivery mechanism for
the real value, and a sibling's unreachable placeholder is what a per-environment value
looks like.

**Never assert another person's access, environment or intent unless they stated it or you
verified it.** A command reporting which principal you are tells you about *your* session,
and attributing that to whoever ran a command in the PR puts a wrong claim about someone
else's privileges up under the reviewing human's name. `software-engineering` forbids
inventing an identifier for a thing; a person is the higher-stakes case, because the claim
is published about someone who has to work with the reader afterwards. State the weakest
claim that still carries the finding — usually one about the code, not about anybody.

**Separate correct from practical.** A remedy that is right but needs a refactor three
modules wide is a follow-up issue, not a review comment — and don't disguise the
second as the first.

**An ask that introduces a pattern your other repos don't use carries the highest bar
here.** The inconsistency is paid by everyone who moves between them, and it lands in one
whose author didn't choose it — so say why the shape is better, not merely different. This
governs a shape **no** standard mandates; where a specialist skill already requires it,
the added code is held to the skill instead.

**Weigh how the code has actually been running.** Reconciling that before posting is part
of the work, and it lands one of three ways: either the trigger is rarer than you think,
something upstream prevents it, or it has been failing quietly and that is the finding.

**Reproduce the defect before you post it.** A finding claims the code does something
wrong, and running it is the evidence that settles that. A docs-only finding carries no
signal that it might be wrong, which is what makes it expensive when it is. This covers
platform behaviour of every kind — services, libraries, CLIs, language runtimes — where
the real semantics sit a layer or two below where they appear to. Reading the platform's
own documentation first is what tells you what to reproduce and names the mechanism.

**Treat the barrier to reproducing as imagined until you have checked it.** The barrier
is usually a guess about what reproducing would require, made before anyone looked.
`reproducing-a-finding.md` alongside this file gives the shape for the awkward cases —
replicating a subject you cannot modify, an authorising call that executes nothing, the
control arm, and cleanup.

**Where you couldn't run the fix, say so in the comment.** An untested suggestion labelled
as one is honest; the same words stated as an instruction are not. The latitude covers the
remedy only: the finding itself is governed by *Reproduce the defect before you post it*,
whose fallback is the narrower of the two.

**Find the consumers before calling an interface change safe.**

```sh
gh search code --owner <owner> '<symbol>' --json repository,path \
  -q '.[] | .repository.nameWithOwner + "  " + .path'
```

`nameWithOwner`, not `name`, which comes back empty.

**Re-read the set as the author before it goes up.** Every false positive spends the
reviewer's credibility, and it is not yours to spend.

## Re-pinning: has the diff actually moved?

`compare` settles it from the OID pair you pinned and the pair you just fetched,
exiting 0 unchanged and 1 moved:

```sh
uv run --script <skill-dir>/scripts/review_scope.py compare --repo <checkout> \
  --pinned <base-oid>:<head-oid> --current <base-oid>:<head-oid>
```

Take its verdict over your own reading of the two diffs. A raw text comparison trips on
the `index` blob OIDs, which move whenever a file changes anywhere; narrowing to the hunks
instead goes blind to a mode change and a binary payload, neither of which has any. It
also reports an OID it cannot resolve as moved. Usually that is a head you have not
fetched — a commit the author pushed is absent from your checkout until you do — and
only occasionally a force-pushed base. It resolves all four OIDs against the objects
you hold rather than through the API, so `git fetch origin pull/<n>/head` and re-run
before reading anything into that verdict; the PR ref covers a fork's head, which
`git fetch origin` alone does not. `self-check` runs it against all of those.

## Validating every anchor

The API accepts a `line` only where it falls inside a diff hunk. Parse the hunk
headers of the same diff the review was built from, collect the RIGHT-side line
numbers per file, and check every anchor against that set before posting — all of
them, since finding one bad anchor per round-trip costs a round-trip each.

Take the hunks from **GitHub's** patch for the PR rather than re-rendering the diff
locally: `git diff` answers to the checkout's own `diff.context`, rename detection and
`.gitattributes` diff drivers, and any of those yields a set GitHub disagrees with.

## The endpoints

| Move | Endpoint |
| --- | --- |
| the whole set, as one review | `POST /repos/{owner}/{repo}/pulls/{n}/reviews` |
| rung 1 — react on an existing inline comment | `POST /repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions` with `content: "+1"` |
| rung 2 — reply in an existing thread | `POST /repos/{owner}/{repo}/pulls/{n}/comments/{comment_id}/replies` |
| a lone follow-up inline comment, no review | `POST /repos/{owner}/{repo}/pulls/{n}/comments` |
| rewrite an inline comment in place | `PATCH /repos/{owner}/{repo}/pulls/comments/{id}` |
| delete an inline comment you are withdrawing | `DELETE /repos/{owner}/{repo}/pulls/comments/{id}` |
| rewrite a submitted review's body | `PUT /repos/{owner}/{repo}/pulls/{n}/reviews/{id}`, which takes `body` alone |

The review payload carries `commit_id` set to the head you pinned and
`comments: [{path, line, side, body}]`, with `event: "COMMENT"`.

Rung 2's `comment_id` has to be the thread's **top-level** comment; there is no
replying to a reply.

**GitHub doesn't document what deleting a top-level comment does to the replies under
it** — whether they go with it, survive orphaned, or block the delete. That is a second
reason the rule never deletes a thread anyone else has replied in, and it means the safe
path doesn't depend on which of those it turns out to be. Check the current API
documentation before writing any flow that does depend on it.

**A submitted review cannot be deleted**, so a finding that went in the review body comes
out by rewriting that body. Only the inline comments are individually deletable, whether
they went up inside a review or on their own.

**No CLI posts a review with its comments.** `gh pr review` posts a body and nothing else,
and `gh pr comment` writes to the Conversation tab, so the review endpoint is the only way
to thread findings on their lines under one notification. The lone-follow-up endpoint costs
one notification per comment — right for one, wrong for a set.

## Reacting to a thread and resolving it take different ids

Reacting takes the **REST comment id** (`databaseId`) and resolving takes the **GraphQL
thread id**. They are different values on different objects, so fetch both in one query
rather than discovering the mismatch halfway through:

```sh
gh api graphql -f query='{repository(owner:"O",name:"R"){pullRequest(number:N){
  reviewThreads(first:20){nodes{id isResolved comments(first:1){nodes{databaseId}}}}}}}'
gh api -X POST repos/O/R/pulls/comments/<databaseId>/reactions -f content='+1'
gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<id>"}){thread{isResolved}}}'
```

`first: 20` is a page, not a promise — a PR with more threads silently returns the first
20, which reads as "that was all of them". Copilot's review and the inline comments inside
it are authored by **different principals**: the review by
`copilot-pull-request-reviewer[bot]`, the comments by `Copilot`. Filtering the comments
endpoint by the review's author therefore returns nothing and looks like Copilot left no
feedback; filter on `Copilot`, or not by author at all.

## A PR can close an issue the body never names

`Closes`/`Fixes`/`Resolves` in a body is one of two ways a PR closes an issue. The other
is a manual link in the **Development** sidebar, which no keyword appears for, which the
body cannot contradict, and which closes the issue on merge just the same — so a body
saying `Refs #540` to keep an issue open can still close it. `closingIssuesReferences`
reports what will actually close, and the issue's timeline carries a `connected` event
only for a sidebar link, never for a keyword, so an event proves a human clicked:

```sh
gh pr view <n> --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'
gh api --paginate repos/<owner>/<repo>/issues/<n>/timeline \
  --jq '.[]|select(.event|test("connected|disconnected"))|"\(.event) by \(.actor.login)"'
```

A bare `#652` mention creates no reference at all, and a backticked keyword in prose is
not one either.
