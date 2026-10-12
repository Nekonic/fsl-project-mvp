# test

Checks the acceptance criteria from section 9 of the design document. Speaks
only HTTP and never imports platform code: it sees the system from outside.

The stack must be running.

```bash
docker compose up -d --build
python -m pytest test/ -v
```

If the stack is down these fail rather than skip. An acceptance check that
quietly skips reads as "passed".

Tests that change the Suricata rules do it in a session of their own; closing
the session ends the change (docker drops the stack at an open three minutes
or more later, OpenStack resets the slot).

Opening a session is the slow part of the suite, so tests whose claims hold on
the same traffic share one. `shared_sessions.py` holds those sessions as
session-scoped fixtures: each opens its session, does every write (fire, tune,
apply rules, loot) and every live read the tests need, closes it, and hands
the tests the recorded answers. No test body writes into a shared session, so
the tests pass in any order. The red-team run (`full_run`) also serves
topology, evasion, strategy honesty, the board attack and the before-silencing
check; `rules_session` the four rule tests; `board_session` loot, objectives,
score reveal, the empty-objectives check and the canary; `origins_session`
origins, rotation and the tool case; `tuned_session` the map and the probe past
the WAF; `terminal_session` the operator log and the attacker box; the corp
rogue-admin and option-flip exploits one session each for the two corp scoring
modules and the two corp exploit checks.

## Running in parallel

`bin/verify` runs the suite through `bin/acceptance`, which starts several
pytest processes over disjoint sets of modules and prints one summary line
with the totals of all of them (from each process's JUnit report).
`bin/acceptance --plan` prints the split without running it;
`--workers N` overrides the count, and any other argument goes to pytest.

- **Workers.** N is `max_sessions` from `GET /api/range/ready/`: docker 2
  (`FSL_MAX_SESSIONS`), OpenStack the range's slot count (`compute.slots`,
  two on the test cloud since 2026-10-12). With N = 1 one
  worker runs every session module in the order `pytest test/` would.
- **Idle.** `test_fabric`, `test_geoip_durable`, `test_origin_placement` and
  `test_waf_geolocation` read only the platform's fabric answer,
  Elasticsearch and repo files, so they run in a process of their own beside
  the workers, without waiting out a range reset. Everything that runs a
  command on a range host needs the range standing and stays in a worker.
- **Balanced.** For N > 1 the modules that share a session-scoped fixture
  (from `shared_sessions.py` or `conftest.py`, read statically) are one group
  and stay in one process; groups go to the least-loaded worker, heaviest
  first, by the seconds in `durations.json` (`--save-durations` writes the
  measured ones back).
- **Standing stack.** Beside another worker, a call that names no session
  cannot use "the newest stack": on docker another worker's open takes down
  stacks of closed sessions, and on OpenStack the newest session may hold the
  other slot. The modules that need a stack but open no
  session (`STANDING_STACK` in `bin/acceptance`) share one process, run
  first, and get a session that worker holds until it opens its own.
  `range.py` defaults a call without `session=` to it, and fails a call that
  names no session while the worker has one of its own open.
- **Solo.** `test_concurrent_sessions` and `test_lesson` hold two sessions at
  once, so they run alone after the workers.
- **Room.** An open refused because the range is full or resetting (409)
  waits for room and is retried; so is the red-team run.

The same suite runs on both substrates. `conftest.py` asks
`/api/range/ready/` which one the platform drives; on openstack,
`range.py` runs a role's command through the platform container's own range
adapter (`manage.py run_on_role --session <id>`, so it reaches the slot that
session holds) instead of `docker exec` into a compose container. Beside
another worker on OpenStack the per-test wait for a range reset is skipped:
every call reaches a slot its worker holds, and the other slot's reset does
not touch it.
