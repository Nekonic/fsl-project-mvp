# fsl-project-mvp

A cyber attack/defence training range: a red team attacks a web app, a blue
team defends with Suricata and ModSecurity, the platform scores the defence.
This repo builds that product cheaply enough to throw away — the real one lives
in another repo — to find out which screens, scoring and stack it should have.
Build it, measure it, keep what survives, write down what did not. A Django
replacement was built in full, measured and discarded in a day.

## How work runs here

This session is the orchestrator. You state a goal in plain language; the
session scopes it, runs the stages (workflows, subagents), keeps docs matching
the code, and reports. The procedure is the `orchestrate` skill; invoke it when
work starts.

Two review gates, and only these two stop the run:

1. Before building — present a short plan or spec and wait for approval.
2. Before anything irreversible or outward (push, merge) — present what
   changed, visually (diagram, table, not walls of prose), and wait for
   approval.

Between the gates the session works on its own: report progress, do not ask
"continue?". Stop early only for a real blocker or a decision that changes what
the product does. Commit is local and needs no gate; push and merge are the
human's, and a push goes to `dev` as a fast-forward.

Replies are short — the result and the reason, no restatement, no analogy;
detail goes in the commit and `docs/DECISIONS.md`. Use the words practitioners
use and do not invent terms; when the field already names a thing, quote a
primary source rather than your own sense of the vocabulary.

## Working language

Reply to the user in Korean; write English in every repo file — code, commit
messages, PR descriptions, documents, the state and decision files — because
Korean costs about twice the tokens per line and every session re-reads them.
Code carries no comments in any language.

Korean belongs in exactly three places, nowhere else:

- `*.ko.md` — a document for Korean readers. The English file is canonical; add
  a `.ko.md` beside it only when the user asks (as with `README.ko.md` and
  `docs/ARCHITECTURE.ko.md`). When a change touches a document that has a
  `.ko.md`, update both together so the pair never drifts.
- `platform/console/templates/console/strings.html` — the console's `en`/`ko`
  string table, the only template allowed Korean, enforced by a test.
- `docs/vocabulary.md` — term translations and their sources.

Leave the last two unread unless you are editing them, and do not read the
archived `docs/superpowers/plans/`.

## How the score works

Two separate numbers; the first is the primary score.

What the red team took: the target flips its own ground truth when an objective
falls — for the board, loot that exactly matches the session-start snapshot of
its secret. That is the score: which objectives were lost, and whether the blue
team saw each one go; one lost and undetected counts double. The platform never
decides whether an attack succeeded — the target's own stored data does.

What the defence got wrong: TP, FP, FN, TN per attack case, from matching
alerts to the cases that caused them. Reported beside the first number, never
folded in — a defence that blocks everything scores perfectly here and loses
every objective.

One case is one decision however many alerts it drew (`board-sqli-orderby-sqlmap`
sends about 94 requests and draws many alerts, and counts once); say so when
reporting, because per-alert counting measures the alert threshold, not the
defence. A true positive must also
survive `expect`: the case names a substring its signature should match, and an
alert that does not mention the attack's mechanism is reported
`corroborated: false`.

## What must not break

- `test/` stays green, in particular TP > 0 and TN > 0 — attacks detected,
  benign traffic passes. That is the hypothesis.
- The benign cases in `redteam/cases/` stay; deleting them makes the score look
  good and the platform pointless.
- The target decides whether it was beaten; never mark an objective from the
  platform's own belief about an attack. The objective layer's value is that
  its ground truth is orthogonal to the detector.
- The isolation seams hold: `ingest/elastic.py` is the only file that knows
  Elasticsearch, `rules/suricata.py` the only one that knows the Suricata
  process, `attacker.py` the only one that knows the attacker box, and the loot
  path (`api/loot.py`, the board) and the effect path (`api/effect.py`, corp)
  the only ones that read the target's ground truth. Keep them the only ones.
  Known exceptions in code today; do not add more, and whether to move them is
  open (`docs/state/now.md`):
  `register_pipeline.py` PUTs the ingest pipeline to Elasticsearch at bring-up;
  `range/pfsense.py` stops and starts Suricata on pfSense (OpenStack);
  `operator_log.py` reads the attacker's command log, and the terminal wiring
  names `fsl-kali`. `docs/ARCHITECTURE.md` keeps the table.
- Fixed by the user: OpenStack, Docker, Suricata, nginx, Elasticsearch.
  Everything else may be replaced if it shrinks the project without breaking
  the above.
- Every UI action is a REST API first; console templates fetch `/api/`, never
  server-rendered data — this is what lets an agent take the human's place.

## The ratchet

`bin/verify` refuses a change that grows a gated number or shrinks the floor.
`core_loc` (`scoring/`, `ingest/`, `rules/`, `redteam/harness.py`),
`dependencies` and `services` may only fall. `product_loc` and
`wargame_services` are reported, not gated. `tests` (module-level `test_*` functions in
`test_*.py`, as `bin/measure` counts them) may only rise — deleting a test is the cheapest way to pass. `bin/measure` prints
them all; `reference.md` beside the `orchestrate` skill has the full table.
`metrics.json` holds the record; editing it by hand is a last resort, not an
escape hatch. A small, obviously-correct change that justifies a gated +1 may
just be made and recorded, not staged as a decision.

## Gotchas

- `platform/` is not a package — `platform` is a stdlib name; never add
  `platform/__init__.py`. Run Python with `platform/` as the working directory
  (same for `test/`).
- No comments or docstrings in code; name things so the code says what it
  does. Exceptions: `deploy/suricata/rules/`, where a commented-out rule is how
  suppression works, and the header Django writes into generated migrations.
- The target is not published; the harness fires from inside the range.
  Bring-up: build the session images once with
  `docker compose -f session.yaml build`, then `docker compose up -d --build`
  starts the shared control plane (it sets up the docker socket group and
  registers the Elasticsearch ingest pipeline); each session's stack starts
  when the session opens.
  `README.md` has the ports, `docs/ARCHITECTURE.md` the file map and the isolation seams,
  `docs/superpowers/specs/` the design.
