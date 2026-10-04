# Decisions

Append-only. Every ruling and every rejected approach, with the reason, so the
same ground is not re-argued. Read before proposing; add when something is
settled. Newest last.

## 2026-10-05 — Harness rebuilt for single-session orchestration

The session is now a standing orchestrator: the user states a goal in plain
language and this one session scopes it, runs fan-out work as workflows,
reports, and stops only at defined gates. Replaces the old protocol of many
short sessions each doing one backlog item and handing off through a large
`STATE.md`. Grounded in current primary and practitioner sources (Anthropic
engineering + Claude Code docs, HumanLayer, Böckeler, Cognition), each cited
claim re-fetched and quote-verified before use.

- **Two review gates, upstream and before anything outward.** Gate 1 is plan
  approval (a wrong plan line multiplies into wrong code — HumanLayer ACE-FCA);
  gate 2 is before push/merge. Autonomous between them. Rejected: a gate at
  every phase (review fatigue — approving each step is not review, Anthropic
  auto-mode study: 93% approval), and plan-only with no final gate (misses the
  ~half of test-passing agent PRs that fail human review — METR).

- **superpowers: keep the patterns, drop the auto hook.** Its `executing-plans`
  (native execution, ~2x faster and half the cost of subagent-driven on a
  frontier model — Jesse Vincent) and `dispatching-parallel-agents` are the
  engine we want, but its `using-superpowers` SessionStart hook forces
  skill-invocation before any reply and brainstorming hard-gates a design
  approval, both of which fight the user's "do not over-ask" rule, and the
  "1% chance, ABSOLUTELY MUST" trigger is measured to misfire (obra/superpowers
  issue #2386). Platform constraint: an individual hook cannot be disabled, and
  `skillOverrides` does not apply to plugin skills, so the two cannot be
  separated while the plugin is enabled. Resolution: disable the plugin for
  this project and re-encode the two patterns in the `orchestrate` skill. The
  project-scoped disable is confirmed to stop the user-level hook — the plugin
  loading docs rank project settings above user settings, so the project
  `false` overrides the user `true` and neither the plugin nor its SessionStart
  hook loads. Consequence to accept: this also drops superpowers' other skills
  for the project (test-driven-development, systematic-debugging). They are
  patterns a frontier model largely follows anyway and the `orchestrate` skill
  carries the load-bearing parts; re-enabling the plugin is one settings flip
  if they are missed.

- **CLAUDE.md rewritten from scratch, 205 → ~110 lines.** Gotchas and
  invariants only; the session protocol moved to the `orchestrate` skill, the
  metrics table and seams to `reference.md`, the layout table dropped (it is in
  `ARCHITECTURE.md`). Emphatic wording (bold, caps, MUST) removed because
  Opus 4.5+ over-triggers on it (Anthropic prompting guide); reasons given
  instead. Target under 200 lines (Claude Code memory docs).

- **STATE.md demoted, not rewritten.** Live state moves to `docs/state/now.md`
  (re-injected after compaction by a SessionStart hook); rulings to this file.
  `STATE.md` stays as the product backlog and finished record — it is product
  state, not harness, so it was not rewritten here.

- **Anti-slop is mechanism, not prose.** A `fsl-orchestrator` output style
  (built on the Concise idea) leads with the result, names concrete tells to
  avoid rather than "avoid an AI look" (Fable 5.1 guidance), and makes reviews
  visual. The behavioural rules that must also reach subagents stay in
  `CLAUDE.md`, because an output style does not reach subagents.

- **Docs are kept matched to code inside the loop.** Before gate 2 a
  fresh-context reviewer lists doc-versus-code drift in the touched area and it
  is fixed. Prose copies of numbers were banned in favour of pointing at
  `metrics.json` / `bin/measure`, because prose copies went stale twice before.

- **researcher carries `omitClaudeMd`; reviewer does not.** researcher does
  external and bounded lookups and takes everything from its delegation prompt,
  so it skips CLAUDE.md (every non-fork subagent otherwise reloads it, ×16
  concurrent). reviewer deliberately keeps CLAUDE.md, because judging a change
  against the invariants — the target decides objectives, the isolation seams —
  requires knowing them.

- **Pruned:** clangd, rust-analyzer and gitkraken-hooks plugins disabled for
  the project. The LSPs do not fit a Python/HTML/compose repo; gitkraken-hooks
  runs an external binary on every lifecycle event, including every tool call,
  which is per-call latency on a dispatch-heavy session (user: disable,
  2026-10-05).

- **Working language tightened** (user, 2026-10-05). English in every repo file
  — code, commit messages, PR descriptions, documents, the state and decision
  files. Korean lives in exactly three places: `*.ko.md` documents for Korean
  readers (the English file is canonical; a `.ko.md` is added only on request),
  `strings.html`, and `docs/vocabulary.md`. When a change touches a document
  that has a `.ko.md` pair, both are updated together in the doc-code sync step.
  Reverts dev's looser "write Korean when the content genuinely calls for it",
  which was ambiguous.
