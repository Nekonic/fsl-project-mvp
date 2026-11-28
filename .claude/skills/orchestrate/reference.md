# Orchestrate reference

Detail pulled out of `CLAUDE.md` and this skill's hot path. Read it when a
change touches the verify modes or the substrate seams.

## The verify modes

| command | runs | when |
|---|---|---|
| `bin/verify --changed [BASE]` | the unit test files the change reaches | by default while working |
| `bin/verify --changed [BASE] --live` | the same, plus the acceptance modules the change reaches, on the live range | a range-facing change, before it is pushed |
| `CR_FINAL_CHECK=1 bin/verify --fast` | every unit test | the final check, after a review round found nothing; CI runs it on every push to `dev` |
| `CR_FINAL_CHECK=1 bin/verify` | all of acceptance on the live range, with every unit test beside it at the lowest CPU priority | the final check before gate 2, after a review round found nothing |

Without `CR_FINAL_CHECK=1` the last two refuse to start, and so does
`bin/acceptance` without `--only`. `.githooks/pre-push` runs
`bin/verify --changed` on the merge of `origin/dev` and a commit pushed to
`dev`, and refuses the push when it is red.

The live modes run where the `cr-platform` container was brought up from the
same checkout (the platform VM's `/opt/cr`), refuse while a session is open,
restart the platform, and prune only the sessions the run made.

`BASE` is the merge-base with `dev` by default, plus uncommitted and untracked
files; `A..B` takes only the commits between. `bin/select-tests [BASE]` prints
the selection without running it. A test file is selected when it imports a
changed module (directly or through others, with `platform/` or `test/` as the
working directory), requests a URL whose view module reaches it, or names or
globs the changed file; reading a Python file as text does not pull in what it
imports. Docs (`*.md`, `docs/`, `.claude/`) select nothing.
The unit `conftest.py` and `__init__.py`, `pytest.ini`, `pyproject.toml`,
`uv.lock` and `cr/settings.py` run the whole unit suite, and so does any
changed file no test reaches. A range-facing change (`platform/` outside
`tests/` and `console/`, `wargames/`, `cases/`, `deploy/`, `test/` but
`test/durations.json`, `compose.yaml`, `bin/acceptance`) that no acceptance
test names needs all of acceptance. Because `api/views.py` imports
most of `platform/`, a change there still selects most of the API tests; a
change to `bin/`, `deploy/`, a template or a test selects a handful.

## The substrate seams

Each is the only file allowed to know its thing; keeping them the only ones is
what lets a piece be swapped without touching the rest.

- `platform/ingest/elastic.py` — Elasticsearch.
- `platform/rules/suricata.py` — the Suricata process (a runner; it does not
  import `subprocess`).
- `platform/rules/crs.py` — the CRS/ModSecurity configuration and the nginx
  reload.
- `platform/kibana.py` — the Kibana API.
- `platform/range/openstack.py` — the OpenStack API, and the read of the
  session stack's live wiring that the learner map draws (Neutron and the
  target VM's Docker networks; `range/wiring.py` parses it, `topology.py`
  names it for the learner).
- `platform/attacker.py` — the attacker box and its marker.
- `platform/api/loot.py` — the board: reads the target's own records and
  matches submitted stolen data against them.
- `platform/api/effect.py` — corp: reads corp-db's own records (snapshot and
  binary log) through the substrate runner.
- `platform/scoring/`, `platform/scoreboard.py` — pure functions, no I/O, no
  Django.

Known exceptions in code today are listed in `CLAUDE.md` and in the isolation
seams table of `docs/ARCHITECTURE.md`, which also has the declaration/substrate
seam. `platform/tests/seams/test_isolation_seams.py` scans `platform/`, `front/src`, `bots/`, `test/` and `bin/` for each
seam's marker strings and fails on a file outside the owner and its listed
exceptions; the wiring read has no row there.
Why one case is one decision, and the `expect`/`corroborated` rule, are in
`CLAUDE.md` ("How the score works"); they are not copied here, so they cannot
drift.
