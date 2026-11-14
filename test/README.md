# test

These tests check the acceptance criteria from section 9 of the design
document. They talk to the platform only over HTTP and never import platform
code. They see the system from the outside.

The range must be up before you run them. Run the suite on the OpenStack
platform VM, against that VM's own platform and its running range
(`docs/OPENSTACK.md` §7). `bin/verify` needs the checkout's `.venv`. The platform VM
makes `/opt/cr/.venv` itself at first boot and after a sideload checkout
(`docs/OPENSTACK.md` §7).

```bash
ssh ubuntu@<address> 'cd /opt/cr && CR_PLATFORM_URL=http://<address>:8000 bin/verify'
```

`bin/verify` runs these steps:

1. The unit suite, split by file size over up to four pytest processes (one per
   CPU; `CR_UNIT_JOBS` overrides). In a full run it starts first and runs beside
   the acceptance suite at the lowest CPU priority (`nice -n 19`); its result is
   printed after the acceptance suite.
2. The acceptance suite, through `bin/acceptance`, which runs `python -m pytest test/`.
3. The ratchet.

Before the acceptance suite, `bin/verify` opens one session, has the sensors
of that session's slot validate `deploy/suricata/rules/local.rules`, and
closes it. It does not wait for that slot's reset: each acceptance process
waits for a slot that is ready.

`CR_PLATFORM_URL` is the platform's address. The default is
`http://localhost:8000`. The platform VM does not listen on localhost, so always
set it there. The suite has no other way to reach the range: the docker
substrate was removed on 2026-10-21, so a laptop with Docker cannot run it.

`bin/verify --fast` skips the acceptance suite. `bin/verify --changed [BASE]`
runs only the unit tests the change reaches and lists the acceptance modules it
reaches. Add `--live` to run those modules too. The suite collects 92 tests;
`test_lesson.py`'s F1 map test runs once per course and skips for a course that
does not start with F1 (`c2` starts with F4), so a full run reports one skip.

If the range is down, these tests fail. They do not skip, because a skipped
acceptance check reads as "passed".

Tests that change the Suricata rules each use a session of their own. Closing
the session resets its slot (one copy of the range), which undoes the change.
Each of those that captures a baseline first checks that its sensor runs the
rule set this repo declares (`runs_the_declared_rules` in `conftest.py`); no
session is opened only for that check. `test_concurrent_sessions` is the
exception: it writes the repo's rule file plus a probe rule, so it captures no
leftovers.

Opening a session is the slow part of the suite: a close resets its slot,
43 s alone in the capacity measurement and 53 s in the 2026-11-14 acceptance
round (`docs/state/now.md`), and longer when several slots reset at once,
and the next open waits for a ready slot. Tests whose claims hold on the
same traffic therefore share one session. `shared_sessions.py` holds these
sessions as session-scoped fixtures. Each fixture does the following:

1. Opens its session.
2. Does every write the tests need (fire a case, tune, apply rules, loot) and
   every live read.
3. Closes the session.
4. Gives the tests the recorded answers.

No test body writes into a shared session, so the tests pass in any order.

These fixtures serve these tests:

| Fixture | Tests it serves |
|---|---|
| `full_run` (the red-team run) | `test_acceptance` (criteria 3, both engines, the real rule set's credit), topology, evasion, strategy honesty, the board attack and the check before silencing |
| `rules_session` | `test_rule_changes` (criterion 4, the invalid rule), the buffer-less rule and the ported rule |
| `board_session` | loot, objectives (with the empty-objectives check), score reveal and the canary |
| `origins_session` | origins and the tool case |
| `tuned_session` | the map and the check that an attack passes the WAF to the inside |
| `terminal_session` | the operator log, the attacker box and the check that an attack through the published port arrives from the outside |

The corp rogue-admin exploit and the corp option-flip exploit each get one
session. `test_corp_observe_live` reads them from the target's binlog, and
`test_corp_authz` reads them from the target's own rows.

A module that would ask for two of these fixtures, or for one of them and a
session of its own, ties them into one process, so each test asks for one
fixture's session only: the check that the silenced rule fires with its rule
on lives in `test_board`, not `test_disabled_rule`.

### One sqlmap run per acceptance run

The red-team run (`full_run`) fires every case in `redteam/cases/board.yaml`
except the sqlmap variants: it keeps `board-sqli-orderby-sqlmap`, the dump,
and leaves out `-probe`, `-random-agent`, `-skip-waf`, `-tamper` and
`-versioned`, which took 50 s each and are not read by any test. The
filtered file is written inside the platform container
(`/tmp/cr-acceptance-cases/board.yaml`) and passed to `redteam/run.py
--cases`; the case file itself is not changed, and every benign case stays.
`CR_SQLMAP_VARIANTS=1` runs them all, for example
`CR_SQLMAP_VARIANTS=1 bin/verify`, to measure detection against every sqlmap
variant's real traffic.

### Probes side by side

`range.run_side_by_side(role, {key: argv})` starts several commands in one
shell on one host and returns each command's own output and exit code. Each
`range.run` call starts a Django process in the platform container and an ssh
to the range host, about 3 s before the command itself runs, so the
containment checks (`test_range_isolation`, `test_judge_isolation`) send each
host's probes in one call and the tests read their part of the answer.

## Running in parallel

`bin/verify` runs the suite through `bin/acceptance`. It starts several pytest
processes over separate sets of modules. It prints one summary line with the
totals of all of them, taken from each process's JUnit report.

- `bin/acceptance --plan` prints the split without running it.
- `--workers N` sets the number of slots to fill.
- `--only test_a,test_b` limits the run to those modules. This is what
  `bin/verify --changed --live` passes.
- Any other argument goes to pytest.

The split follows these rules:

- **Slots.** N is `max_sessions` from `GET /api/range/ready/`: the number of
  slots (`compute.slots`, four on the test cloud since 2026-11-13). `--workers N`
  overrides it. With N = 1, one process runs every session module in the order
  `pytest test/` would.
- **No range host.** `test_geoip_durable`, `test_origin_placement` and
  `test_waf_geolocation` read only Elasticsearch and repo files. They run in a
  process of their own from the start, so they do not wait for a range reset.
  Anything that runs a command on the range host needs the range up.
- **Groups.** For N > 1, the modules that share a session-scoped fixture are
  one group and run in one process. The script finds these fixtures by reading
  `shared_sessions.py` and `conftest.py` as text. Every other module is a group
  of its own. Each group is one pytest process.
- **Queue.** A group that holds two sessions at once (`TWO_SESSIONS`:
  `test_concurrent_sessions`) takes two slots; every other group takes one.
  Two-slot groups go first, then the rest heaviest first by the seconds in
  `durations.json`. A group starts as soon as the slots it takes are free, so
  N groups run at once and the next starts when one ends; there are no fixed
  workers waiting on each other. `--save-durations` writes the measured
  seconds back.
- **Standing stack.** Beside another process, a call that names no session
  cannot use the newest session, because that session may hold another slot.
  Some modules need a stack but open no session (`STANDING_STACK` in
  `bin/acceptance`: the reach, exfiltration, event-time and containment
  checks). They are one group and run in that order. They get a session the
  group holds until it opens its own; `range.py` sends a call that has no
  `session=` to that session and fails a call that names no session while the
  process has one of its own open. The last containment test plants links in
  that session's WAF and closes it to watch the reset.
- **Room.** If the range is full or resetting, opening a session is refused with
  409. The test waits for room and retries. So does the red-team run.

## How the suite reaches the range

Every acceptance test runs on OpenStack, and none skips because the range is
missing. The one skip is by design: `test_lesson.py`'s F1 map test runs once
per course and skips for `c2`, which starts with F4. We deleted one check of a
compose-only mechanism instead of skipping it (2026-10-17).
`range.py` reaches the range only through the platform and works like this:

- It runs a role's command through the platform container's own range adapter
  (`manage.py run_on_role --session <id>`), which reaches the slot that session
  holds. The only command it runs on the platform itself is the one for the
  `scorer` role, with `docker exec` on the platform container.
- It runs the attacker's command in a login shell. The shell reads
  `/etc/profile.d/proxy.sh`, so the command gets the same `http_proxy` (the
  stamping proxy) as the terminal's login shell (`docker exec ... bash -l`).
- It reads alerts through the platform's API
  (`/api/sessions/<id>/detections/`), not from a sensor's log file.
- Beside another process, it skips the wait for a range reset after each test.
  Every call reaches a slot its process holds, and the reset of another slot
  does not touch it. A call may name a slot instead of a session
  (`run(role, argv, slot=N)`), for a host read after the session that held the
  slot has closed.
