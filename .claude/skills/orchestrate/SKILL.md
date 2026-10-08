---
name: orchestrate
description: The operating loop for this repo. Use at the start of any development goal the user states in plain language — a feature, a fix, a change, a measurement, a harness change — and whenever resuming one. Covers how to scope, when to run a workflow versus work solo, the two human-review gates, keeping docs matched to the code, and the visual review the second gate needs.
---

# Orchestrate

You run this repo as one standing session. The user states a goal in plain
language; you carry it from scope to a reviewable result, running fan-out work
as workflows and stopping only at the two gates. You do not hand off to another
session, and you do not make the user say "continue".

## The loop

1. **Scope.** Turn the goal into a short plan: what changes, which files, how
   you will prove it, what you will not touch, open questions. Read
   `docs/state/now.md` for where things stand and `docs/DECISIONS.md` for what
   was already ruled out — and open the canonical direction source they point to
   (the spec and the decided items of the living-doc artifact), not just `now.md`'s
   reconstruction or your memory. Scout before you plan — list the files, read
   the seam, scope the diff — so the plan is real, not a guess. Never overturn a
   recorded or decided item from memory or a re-derivation: quote the exact
   statement you would overturn and show where it fails; if a problem you hit is
   already resolved in the written design, apply that resolution instead of
   raising it as a new decision.

2. **Gate 1 — plan approval.** Present that plan and wait. This gate has the
   most leverage: a wrong line of plan becomes hundreds of wrong lines of code.
   Keep it short enough to actually read. Skip it only for a change small and
   obvious enough that a plan would be longer than the diff.

3. **Run the stages.** Work through the plan without pausing for approval.
   Report progress in a line or two as stages land; do not ask whether to go
   on. Use a workflow when the work fans out (see "When to run a workflow");
   otherwise do it yourself. Commit as coherent pieces land — commit is local
   and needs no gate.

4. **Match docs to code.** Before the result is reviewable, reconcile the docs
   with what you changed (see "Docs match the code"). This is part of the work,
   not a later chore.

5. **Verify with evidence.** The gate for every change is the unit and API
   tests (`bin/verify --fast`, per `DECISIONS.md` 2026-10-05); `--fast` prints
   the metrics without gating them, so compare `bin/measure` against
   `metrics.json` by hand. A change to the live stack (compose, the range,
   session isolation) is also run against the acceptance suite on the OpenStack
   deployment before it is pushed. Show the command and its output, not a claim
   that it passed. If it is red or a gated metric grew, fix it or `git reset --hard`
   and say what you learned — a reported failure beats a half-finished success.

6. **Gate 2 — visual review before anything outward.** Before a push or a
   merge, present what was done and what changed as a picture, not prose (see
   "The visual review"), with the verification evidence beside it. Wait. Push
   and merge are the user's; a push goes to `dev` as a fast-forward.

Stop between gates only for a real blocker or a decision that changes what the
product does — a new target's identity, a change to what the score means. An
exceptional condition you can resolve, you resolve; you do not bring
hypotheticals to the user as decisions.

## When to run a workflow

A workflow buys breadth (cover many files or angles at once), confidence
(independent and adversarial checks before you commit), or scale one context
cannot hold. Reach for one when the work splits into parts that do not depend
on each other: reviewing a diff across dimensions, researching several
questions, mapping subsystems, transforming many sites. Author the script per
the `workflow-authoring` reference.

Do not fan out writing that shares context. One agent writes a given file;
others review it, advise, or verify. Parallel writers on the same code
contradict each other and overwrite each other's fixes. The full `bin/verify`
drives the one live stack, so run it once at the end, not inside parallel
agents.

For work that touches files in parallel, give each agent its own git worktree
(`isolation: 'worktree'`); it is the established isolation unit here.

## Scope discipline

The model drifts toward doing more than asked, and that is the bulk of the
slop. Hold the line:

- Implement the most direct reading of the goal. A pre-existing bug you notice
  is a follow-up you report, not a fix you fold in.
- Commit roughly one focused test per behaviour the goal states. Do not turn a
  scratch check into a committed test, and do not add tests for behaviour
  nobody asked about.
- Do not add defensive layers, configuration, or abstractions for cases the
  goal does not name.

## Verification, and not gaming it

`bin/verify` is the gate, and the target decides whether it was beaten — those
two facts are what make a green run mean something. Protect them:

- Treat the tests and the benign cases as read-only. If a change seems to need
  a test deleted or weakened, that is a finding to raise, not a step to take.
  The `tests` floor and the benign-case rule exist because deleting them is the
  cheapest way to fake a pass.
- A green `bin/verify` is necessary, not sufficient: roughly half of
  test-passing agent PRs still fail human review on quality or breakage. The
  gate-2 review is where that is caught.
- Watch the ratchet for gaming, not just for the number: `core_loc` falling
  because logic moved into an uncounted path, or lines were joined, is not a
  real win. Record the real reason in `DECISIONS.md`.
- Opus-class models verify their own work without being told, so do not litter
  the run with "double-check" steps. Spend a separate reviewer where it earns
  its cost: a fresh-context agent reading the diff against the plan before
  gate 2, on anything beyond a trivial change.

## Docs match the code

When a change makes a document wrong, the document is part of the change. After
the code settles and before gate 2, check the docs the change touched —
`README.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`, the relevant `docs/` files —
against what the code now does, and fix the drift. When a touched document has
a `.ko.md` pair, update the English file and its `.ko.md` together, so the two
never diverge. On anything larger than a one-file change, dispatch a
fresh-context reviewer whose only job is to list doc-versus-code
contradictions in the touched area; apply what it finds. Prose copies of
numbers go stale — point at the source (`metrics.json`, `bin/measure`) instead
of restating it.

## The visual review (gate 2)

The user reviews the result as a picture, not a wall of text, so they can see
what happened and what changed at a glance. Lead with the visual, then a few
lines of plain language, then the evidence.

- Pick the form that fits: a before/after table for metrics and files touched;
  a `flowchart`/`sequenceDiagram` (Mermaid) or a small UML for a changed flow
  or structure; a diff summary for the shape of the change. Show state before
  and after, not just the end state.
- Render it inline (the `show_widget` or diagram tools), or send a rendered
  file; do not paste a long textual explanation in its place.
- Say plainly what you did, what changed, what you did not touch, and what is
  left or uncertain. Put the `bin/verify` evidence beside it.
- Keep it to what a reviewer needs to approve a push: no narration of how you
  got there.

## Files this loop keeps true

- `docs/state/now.md` — the live state: the goal in flight, the stage, what is
  awaiting review, the last feedback. Small; keep it current, drop finished
  detail into the archive or let `git log` hold it.
- `docs/DECISIONS.md` — append-only; every ruling and every rejected approach,
  with the reason. Read it before proposing; add to it when something is
  settled, so the same ground is not re-argued next time.
- `reference.md` (beside this file) — the metrics and ratchet detail, and the
  substrate seams, pulled out of the hot path. Read it when a change touches
  `metrics.json` or the measured numbers.
