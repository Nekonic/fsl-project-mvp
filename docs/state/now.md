# Now

The live state of the work in flight. Small on purpose: the orchestrator keeps
its own context, so this is the handover across compaction, not a full history.
The product backlog and the finished record stay in `docs/STATE.md`; rulings
are in `docs/DECISIONS.md`; detail is in `git log`.

Updated: 2026-10-05

## In flight

Rebuilding the harness for single-session agent orchestration — branch
`claude/agent-orchestration-harness-e4de7c`.

- **Stage:** P1, the harness skeleton (no product code): new `CLAUDE.md`, the
  `orchestrate` skill, the `fsl-orchestrator` output style, `now.md` +
  `DECISIONS.md`, `.claude/agents/` roles, settings prune/extend. Written,
  self-reviewed by a fresh-context agent, six findings applied.
- **Awaiting:** gate-2 visual review of P1 before any push or merge.
- **Last feedback (2026-10-05):** review gates sit upstream (plan) and before
  anything outward (push/merge), autonomous between; keep the superpowers
  patterns but drop its auto session-start hook; the harness keeps docs matched
  to code; the gate-2 review is visual (diagram/table/UML), not prose.

## On merge to dev

- Retire or rewrite the user auto-memory `recursive-improvement-loop.md` (and
  its `MEMORY.md` line): it still describes the superseded loop (read only
  CLAUDE.md+STATE.md, one backlog item per session, three gated numbers). Do it
  only once the new `CLAUDE.md` is on `dev`, so memory and the repo agree.
- P2: run one real backlog item through the new loop end to end and compare its
  token cost and output against the old protocol.

## Decisions pending a person

None open.
