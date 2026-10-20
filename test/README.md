# test

These tests check the acceptance criteria from section 9 of the design
document. They talk to the platform only over HTTP and never import platform
code. They see the system from the outside.

The range must be up before you run them. Run the suite on the OpenStack
platform VM, against that VM's own platform and its running range
(`docs/OPENSTACK.md` §7). `bin/verify` needs the checkout's `.venv`. The platform VM
makes `/opt/fsl/.venv` itself at first boot and after a sideload checkout
(`docs/OPENSTACK.md` §7).

```bash
ssh ubuntu@<address> 'cd /opt/fsl && FSL_PLATFORM_URL=http://<address>:8000 bin/verify'
```

`bin/verify` runs these steps in order:

1. The unit suite.
2. The acceptance suite, through `bin/acceptance`, which runs `python -m pytest test/`.
3. The ratchet.

`FSL_PLATFORM_URL` is the platform's address. The default is
`http://localhost:8000`. The platform VM does not listen on localhost, so always
set it there. The harness code still has a docker branch (the platform builds
the range on docker instead of OpenStack) until the docker substrate is removed
(`docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`). That
branch is not a way to run the product.

`bin/verify --fast` skips the acceptance suite. `bin/verify --changed [BASE]`
runs only the unit tests the change reaches and lists the acceptance modules it
reaches. Add `--live` to run those modules too. The suite collects 73 tests and
skips none.

If the range is down, these tests fail. They do not skip, because a skipped
acceptance check reads as "passed".

Tests that change the Suricata rules each use a session of their own. Closing
the session resets its slot (one copy of the range), which undoes the change.

Opening a session is the slow part of the suite. Tests whose claims hold on the
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
| `full_run` (the red-team run) | topology, evasion, strategy honesty, the board attack and the check before silencing |
| `rules_session` | the four rule tests |
| `board_session` | loot, objectives, score reveal, the empty-objectives check and the canary |
| `origins_session` | origins, rotation and the tool case |
| `tuned_session` | the map and the check that an attack passes the WAF to the inside |
| `terminal_session` | the operator log, the attacker box and the check that an attack through the published port arrives from the outside |

The corp rogue-admin exploit and the corp option-flip exploit each get one
session. `test_corp_observe_live` reads them from the target's binlog, and
`test_corp_authz` reads them from the target's own rows.

## Running in parallel

`bin/verify` runs the suite through `bin/acceptance`. It starts several pytest
processes over separate sets of modules. It prints one summary line with the
totals of all of them, taken from each process's JUnit report.

- `bin/acceptance --plan` prints the split without running it.
- `--workers N` sets the number of workers.
- `--only test_a,test_b` limits the run to those modules. This is what
  `bin/verify --changed --live` passes.
- Any other argument goes to pytest.

The split follows these rules:

- **Workers.** N is `max_sessions` from `GET /api/range/ready/`: the number of
  slots (`compute.slots`, two on the test cloud since 2026-10-12). With N = 1,
  one worker runs every session module in the order `pytest test/` would.
- **No range host.** `test_geoip_durable`, `test_origin_placement` and
  `test_waf_geolocation` read only Elasticsearch and repo files. They run in a
  process of their own beside the workers, so they do not wait for a range reset.
  Anything that runs a command on a range host needs the range up and stays in a
  worker.
- **Balanced.** For N > 1, the modules that share a session-scoped fixture are
  one group and stay in one process. The script finds these fixtures by reading
  `shared_sessions.py` and `conftest.py` as text. Groups go to the least-loaded
  worker, heaviest first. The weight is the seconds in `durations.json`.
  `--save-durations` writes the measured seconds back.
- **Standing stack.** When another worker is running, a call that names no
  session cannot use the newest session, because that session may hold the
  other slot. Some modules need a stack but open no session (`STANDING_STACK`
  in `bin/acceptance`). They share one process and run first. They get a session
  that this worker holds until it opens its own. `range.py` sends a call that
  has no `session=` to that session. It fails a call that names no session while
  the worker has one of its own open.
- **Solo.** `test_concurrent_sessions` and `test_lesson` each hold two sessions
  at once, so they run alone after the workers.
- **Room.** If the range is full or resetting, opening a session is refused with
  409. The test waits for room and retries. So does the red-team run.

## How the suite reaches the range

Every acceptance test runs on OpenStack and none is skipped. We deleted one
check of a compose-only mechanism instead of skipping it (2026-10-17).
`range.py` works like this:

- It runs a role's command through the platform container's own range adapter
  (`manage.py run_on_role --session <id>`), which reaches the slot that session
  holds.
- It runs the attacker's command in a login shell. The shell reads
  `/etc/profile.d/proxy.sh`, so the command gets the same `http_proxy` (the
  stamping proxy) as the terminal's ssh login.
- It reads alerts through the platform's API
  (`/api/sessions/<id>/detections/`), not from a sensor's log file.
- Beside another worker, it skips the wait for a range reset after each test.
  Every call reaches a slot its worker holds, and the reset of the other slot
  does not touch it.
