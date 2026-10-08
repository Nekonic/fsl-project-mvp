# Orchestrate reference

Detail pulled out of `CLAUDE.md` and this skill's hot path. Read it when a
change touches the measured numbers or the substrate seams.

## The ratchet numbers

`bin/measure` prints them; `metrics.json` holds the baseline; `bin/verify`
refuses a change that grows a gated number or shrinks the floor.

| number | ratchet | what it counts |
|---|---|---|
| `core_loc` | down only | the surviving hypothesis: `platform/scoring/`, `platform/ingest/`, `platform/rules/`, `redteam/harness.py` |
| `dependencies` | down only | direct pip packages |
| `services` | down only | the platform's own compose services |
| `tests` | up only | module-level `test_*` functions in `test_*.py` |
| `product_loc` | reported | the disposable shell: UI, API surface, compose, deploy |
| `wargame_services` | reported | a wargame's own compose services |

The split follows what the repo is for. `core_loc` is what would be worth
carrying to the production repo, so it stays small and keeps shrinking.
`product_loc` is where things are tried, so it grows — that is what building one
looks like. Anything that stops being disposable earns its way into `core_loc`
or out of the repo. Docs and `bin/` are not counted; tests are not counted as
production code, so growing the suite never reads as a regression.

A gated +1 that is small and obviously correct (a missing one-line capability
in a tool, say) may just be made and recorded in `DECISIONS.md` — not staged as
a multi-turn decision. Editing `metrics.json` by hand to pass is a last resort;
when you do it, the reason goes in `DECISIONS.md`.

Gaming to watch for, because the number alone will not show it: logic moved
into an uncounted path to drop `core_loc`; lines joined to the same end; a test
deleted and another renamed to hold the floor. The number can be honest only if
the change behind it is.

## The substrate seams

Each is the only file allowed to know its thing; keeping them the only ones is
what lets a piece be swapped without touching the rest.

- `platform/ingest/elastic.py` — Elasticsearch.
- `platform/rules/suricata.py` — the Suricata process (a runner; it does not
  import `subprocess`).
- `platform/attacker.py` — the attacker box and its marker.
- `platform/api/loot.py` — the board: reads the target's own records and
  matches submitted stolen data against them.
- `platform/api/effect.py` — corp: reads corp-db's own records (snapshot and
  binary log) through the substrate runner.
- `platform/scoring/`, `platform/scoreboard.py` — pure functions, no I/O, no
  Django.

Known exceptions in code today are listed in `CLAUDE.md` and in the isolation
seams table of `docs/ARCHITECTURE.md`, which also has the declaration/substrate
seam.
Why one case is one decision, and the `expect`/`corroborated` rule, are in
`CLAUDE.md` ("How the score works"); they are not copied here, so they cannot
drift.
