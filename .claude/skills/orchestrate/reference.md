# Orchestrate reference

Detail pulled out of `CLAUDE.md` and this skill's hot path. Read it when a
change touches the measured numbers or the substrate seams.

## The ratchet numbers

`bin/measure` prints them; `metrics.json` holds the baseline; `bin/verify`
refuses a change that grows a gated number.

| number | ratchet | what it counts |
|---|---|---|
| `core_loc` | down only | the surviving hypothesis: `platform/scoring/`, `platform/ingest/`, `platform/rules/`, `redteam/harness.py` |
| `dependencies` | down only | direct pip packages |
| `services` | down only | the platform's own compose services |
| `product_loc` | reported | the disposable shell: UI, API surface, compose, deploy |
| `wargame_services` | reported | a wargame's own compose services |
| `tests` | reported | module-level `test_*` functions in `test_*.py` |

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
weakened or deleted to make a change pass. The test count is reported, not
gated (`DECISIONS.md`, 2026-10-16), so a removed test is justified in its
commit. The number can be honest only if the change behind it is.

## The verify modes

| command | runs | when |
|---|---|---|
| `bin/verify --changed [BASE]` | the unit test files the change reaches, then the ratchet | by default while working |
| `bin/verify --changed [BASE] --live` | the same, plus the acceptance modules the change reaches, on the live range | a range-facing change, before it is pushed |
| `bin/verify --fast` | every unit test; prints the metrics without gating them | before a commit that touches shared code |
| `bin/verify` | every unit test, all of acceptance on the live range, the ratchet | range-facing logic changed, and before a push |

`BASE` is the merge-base with `dev` by default, plus uncommitted and untracked
files; `A..B` takes only the commits between. `bin/select-tests [BASE]` prints
the selection without running it. A test file is selected when it imports a
changed module (directly or through others, with `platform/` or `test/` as the
working directory), requests a URL whose view module reaches it, or names or
globs the changed file; reading a Python file as text does not pull in what it
imports. Docs (`*.md`, `docs/`, `.claude/`, `metrics.json`) select nothing.
The unit `conftest.py`, `pytest.ini`, `requirements.txt` and `fsl/settings.py`
run the whole unit suite, and so does any changed file no test reaches. A
range-facing change (`platform/` outside `tests/` and `console/`,
`wargames/`, `redteam/`, `deploy/`, `test/`, the compose files) that no
acceptance test names needs all of acceptance. Because `api/views.py` imports
most of `platform/`, a change there still selects most of the API tests; a
change to `bin/`, `deploy/`, a template or a test selects a handful.

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
