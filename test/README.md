# test

These tests check the acceptance criteria against the live range. They talk to
the platform only through `bots/rest.py`, which sends each operation by its
`operationId` in `openapi/schema.yaml`, and never import platform code, so an
operation that is gone from the schema fails at its first call. Elasticsearch is read directly where a
test checks the ingest pipeline itself.

The range must be up before you run them. Run the suite on the OpenStack
platform VM, against that VM's own platform and its running range
(`docs/OPENSTACK.md` §7). `bin/verify` needs the checkout's `.venv`.

```bash
ssh ubuntu@<address> 'cd /opt/cr && CR_PLATFORM_URL=http://<address>:8000 bin/verify'
```

`bin/verify` regenerates the clients, runs the unit suite, and then the
acceptance suite through `bin/acceptance`, which runs `python -m pytest test/`.
Before the acceptance suite it opens one allocation, starts a round on it, has that
round's sensors check `deploy/suricata/rules/local.rules`, and closes the
allocation.

`CR_PLATFORM_URL` is the platform's address (default `http://localhost:8000`).
The suite signs in as `CR_ADMIN_USER` / `CR_ADMIN_PASSWORD`, a staff account.

If the range is down, these tests fail. They do not skip, because a skipped
acceptance check reads as "passed".

## How a test plays a round

`plays.py` holds every call the suite makes:

1. It keeps one staff problem per wargame, `Acceptance <wargame>`, written
   through the staff API on first use: a round problem whose posture is the
   committed `local.rules` and a CRS exclusion file that detects without blocking
   `/search/`, and every objective of the wargame.
2. `plays.play(wargame)` opens an allocation (`POST /api/allocations/`), creates a
   `def_vs_bot` round on it and starts it. The attack player is a bot whose token
   `plays` keeps; the defence player is the signed-in operator. A full range
   answers `503 range_unavailable`, and `play` waits and opens again.
3. The attack bot fires declared cases through `POST cases/`, sends free
   requests through `POST requests/` and runs tools through `POST tools/`.
   Every answer carries the action's marker, and `plays.marked` ties the alerts
   in `GET defence/alerts/` to it by `request_id`.
4. The platform fires the benign cases itself, every `benign_every_s`, so TN
   and FP come from the customers, never from the attack player.
5. The score is read as the operator (`GET /api/rounds/<id>/score/`,
   `?correlation=` for the strategy comparison). One declared case is one line
   of `outcomes.per_case` however many alerts it drew; free actions are
   reported apart in `free_actions` and never enter TP/FP/FN/TN.
6. `plays.close` ends the round and closes the allocation, which deletes the slot's
   stack and builds it again.

A test that needs another problem passes a `plays.Setup` (its own title,
posture, probe cases, side and matchups) to `plays.play` or
`plays.Round`, with `matchup="atk_vs_bot"` when the defence player is the bot.
`played.attack` and `played.defence` are the clients of the two players: a bot's
player token, or the signed-in operator. A `pvp` round passes `humans=`, a
second account per side from `plays.human_account` (signed up, approved and
disabled again by the test). `plays.in_shell` runs one command in a side's
terminal over the SSH grant a human's terminal uses (`bots/shell.py`). WAF
postures are file edits: `plays.appended` adds lines to a live WAF file
(`plays.paranoia`, `plays.RULE_ENGINE_OFF` for `crs-setup.conf`) and
`plays.tune_waf` applies them.

## Shared rounds

Opening an allocation is the slow part of the suite: a close replaces its slot's
stack, and the next allocation waits for an idle slot of its wargame. Tests whose
claims hold on the same traffic therefore share one round. `shared_sessions.py`
holds these as session-scoped fixtures; each one plays its round, does every
write the tests need and every live read, closes the allocation, and gives the tests
the recorded answers. No test body writes into a shared round, so the tests
pass in any order.

| Fixture | Tests it serves |
|---|---|
| `full_run` (every malicious case, one sqlmap run) | `test_acceptance`, `test_board`, `test_objectives`, `test_topology`, `test_strategy_honesty` |
| `board_session` | loot (one digest changed, the round's own, then the previous round's in the next), objectives and the score kept from a player while the round runs |
| `origins_session` | origins (the next origin's traffic arrives from it) and the tool case |
| `rules_session` | four rounds on one allocation: the invalid and the buffer-less rule; the noisy and the ported rule, where benign alerts show where benign traffic comes from; the catch-all rule of `test_indiscriminate_defence` with the WAF's rule engine off; a `generic probe` rule that catches the SQLi without naming it |
| `terminal_session` | the attacker box, the command feed and the front door |
| `terminal_windows` | `test_window_correlation` (a free tool attributed by source and time) and `test_strategy_comparison` |
| `rogue_admin_session`, `option_flip_session` | `test_corp_authz`, two corp allocations side by side; `rogue_admin_session` also serves `test_score_reveal` (the weighted objective number, an undetected loss) |

The red-team run fires every malicious case in `redteam/cases/board.yaml`
except the sqlmap variants other than `board-sqli-orderby-sqlmap`.
`CR_SQLMAP_VARIANTS=1` fires them all.

## Running in parallel

`bin/acceptance` starts several pytest processes over separate sets of modules
and prints one summary line with the totals of all of them.

- `bin/acceptance --plan` prints the split without running it.
- `--workers N` sets the number of slots to fill; by default it is the number
  of slots `GET /api/staff/range/` lists.
- `--only test_a,test_b` limits the run to those modules (`bin/verify --changed --live`).
- Any other argument goes to pytest.

The split follows these rules:

- **No slot.** `test_geoip_durable`, `test_origin_placement` and
  `test_waf_geolocation` read only Elasticsearch and repo files and run in a
  process of their own from the start.
- **Groups.** For N > 1, the modules that share a session-scoped fixture are
  one group and run in one process. Every other module is a group of its own.
- **Queue.** A group that holds two allocations at once (`TWO_ALLOCATIONS`:
  `test_concurrent_sessions`, `test_corp_authz`) takes two slots; every other
  group takes one. Two-slot groups go first, then the rest heaviest first by
  the seconds in `durations.json`.
- **Standing stack.** Some modules need a slot but play no round of their own
  (`STANDING_STACK` in `bin/acceptance`). Beside another process they share one
  allocation the group holds; `range.py` sends a call that names no allocation to it. The
  last containment test writes a file on that allocation's WAF, closes the allocation and
  checks that the slot's WAF is a new VM without the file.

## How the suite reaches the range's hosts

- `range.py` runs a role's command through the platform container's own range
  adapter (`manage.py run_on_role --allocation <id>`), which reaches the slot that
  allocation holds; a call may name a slot instead (`run(role, argv, slot=N)`), for
  a host read after the allocation closed. The `scorer` role runs on the platform
  container itself.
- It runs the attacker's command in a login shell, so the command gets the same
  `http_proxy` (the stamping proxy) as the terminal's login shell.
- `range.run_side_by_side(role, {key: argv})` starts several commands in one
  shell on one host; the containment checks send each host's probes in one call.
