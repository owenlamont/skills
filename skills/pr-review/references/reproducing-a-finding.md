# Reproducing a finding

The shape a reproduction takes when the claim is about authorisation, configuration or
platform behaviour rather than about a pure function — the cases where "I'd have to touch
the live system" is the reflex that stops a finding being reproduced at all.

## The four moves

1. **Replicate the subject; don't edit it.** The thing whose behaviour you are testing
   is usually live, and mutating it to make it testable is both risky and no longer a
   test of the original. Stand up a throwaway carrying exactly the property under test —
   the same policy, the same config value, the same version — and probe that. Copy the
   property rather than paraphrasing it: anything you simplify is a difference between
   the probe and the subject, and it will be the difference that matters. Check first
   whether the platform will answer read-only, without your creating anything: a policy
   simulator, a validate or plan call, a dry-run endpoint.
2. **Choose a call that authorises without acting.** Many APIs expose a dry-run,
   validate-only or plan mode that runs the checks you care about and stops before the
   side effect. Finding one is what turns "this needs a production invocation" into a
   probe you can run in minutes.
3. **Run a control arm the subject must allow.** Point the same harness at a case that has
   to succeed. Until it does, a failure tells you nothing — it may be the defect or it may
   be the harness, and those are indistinguishable from the failing arm alone. Report the
   control beside the result: it is what lets a reader who cannot audit your setup rule
   out "you misconfigured the probe". `software-engineering` owns this rule in general;
   here it is the move that makes an awkward reproduction trustworthy.
4. **Clean up on an `EXIT` trap, then assert no residue.** Everything the probe created
   is deleted whether it passed, failed or was interrupted, and the last step is a query
   showing nothing is left.

## Why the control arm is the load-bearing one

A pending-looking failure is the trap. Freshly created permissions and configuration are
often eventually consistent, so an early denial can be genuine propagation lag — and a
probe that silently dropped the credentials it was built to test produces exactly the same
symptom, round after round. Both stories argue for waiting, which is why waiting never
resolves it. The arm that must succeed is the only thing that separates them.

## Traps

- **An explicit credential-selecting flag can discard credentials you exported into the
  environment**, rather than merely outranking them — narrower than a published precedence
  order usually reads. Left on, the probe runs as the wrong principal and its denials read
  as propagation lag. Where a tool offers a debug or verbose mode that names which
  credential source it used, assert on that line rather than trusting the flag.
- **A probe assembled from a simplified copy of the subject tests the simplification.**
  Diff the two before believing a result.
