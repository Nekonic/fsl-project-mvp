# State

The product backlog and the record of where the build stands. The handover to
the next session is `docs/state/now.md`; rulings are in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; the current
design in `docs/ARCHITECTURE.md`, and the historical 2026-11-19 design in
`docs/specs/2026-11-19-side-split-design.md` (the spec, cited below by
section). The record of the old tree (`platform/api/`, the console
templates, the scenario course) up to 2026-11-18 is in this file's git
history.

## Where things stand

The product was rebuilt as a side split on `side-split` (user ruling
2026-11-19: no code is kept or migrated; the old code is reference only), and
then restructured on the branch `restructure` (ruling 2026-11-21,
"The platform is restructured into five units, KYPO-style"). The tree is
`defence-watch`: `waf5` (`integrate` (`bot-rounds`, the Player vs AI rounds, with
`pg-store`, the PostgreSQL store, and `access-address`, the access page's
target address) with CRS 920350 removed at the WAF and the attack bot's
prompt rewritten as an engagement brief) with the defence bot kept in the
round and fed by the launcher until it ends, and `bundle-1126` on top
(the bot polls the rule test as a detached job, the rule test replays in
one curl over one SSH call, the attack prompt names the round's attack
profile for the debrief, the watch check is timed from the last start and
capped), and `review-fix` on top (the fixes of a live review round: each
objective's difficulty and points in the score pane, every fallen objective
in the loot pane, Korean objective names, the VPN profile listing only its
round's target, the runner keeping a command's bytes as sent, a failed
Claude child finishing as error, the kali command log stamping a command
when it starts), and `review2` on top (the fixes of a second live review
round, below), and `slot-fix` on top (2026-11-27, `docs/DECISIONS.md`: alerts Elasticsearch indexed late are read, the traffic cursor names one timestamp, the defence watch ends with its round, a judged baseline round gives its slot back, a round that does not start logs why), and `demo` on top (2026-11-27: `ingest-fix`, `no-baseline`, `problem-body` and `pvp-no-problem` merged; the bot-vs-bot rounds dropped by a migration of their own; an allocation's drop forgets its rounds' detections after the delete; a pvp round limited to 30 min; ending a round closes both sides before the final read; `docs/state/now.md`), and `ui-sweep` on top (2026-11-27: the Korean wording pass and the fixes of a UI sweep and three tester rounds, `docs/DECISIONS.md` 2026-11-27 "Sign-out ends everything at once", `docs/state/now.md`), and `pvp-demo-fix` on top (2026-11-28: `corp-ids` and `vpn-download` merged; the Kali terminal no longer reloads itself while ttyd's page loads, round log reads run off the request thread, corp's registration cases send the form's own field ids, the defence console opens on alerts, starting rules read '시작 룰', learners see no stack name, both consoles show the starting state, times are shown in UTC+9; `docs/DECISIONS.md` 2026-11-28); and `sweep-fix` on top (2026-11-28: the role files under `deploy/roles/`, `cases/` in place of `redteam/`, names that say what they hold, dead code and fields removed, corp's probes recorded again with the form's `-5` field ids; `docs/DECISIONS.md` 2026-11-28); `main` holds the old product until gate 2. The cloud runs `dev` since the evening of 2026-11-28 on `cr-kali-bake5`, `cr-waf-bake6` and `cr-infra-bake3`, baked from it: one replace (exit 0, 30 min), then a board and a corp pvp Playwright check passing every step from sign-in to sign-out, both rounds 15 minutes long, corp's rule test replaying the `-5` `corp-rogue-admin` probe; the full acceptance from the platform VM stopped at the one-hour limit with 75 passed, 2 failed (the corp option flip also lost `corp-rogue-admin`; a spent origin with no `origin.switched`) and 11 not reached. Before that it ran `dev` since the afternoon of 2026-11-28 (UTC+9 times on screen, in logs and in backup names; English terms in English on the console; the pvp limit 15 minutes through the VM's `openstack.env`): one replace (exit 0, 16 min), then a board and a corp pvp Playwright check passing every step from sign-in to sign-out. Before that it ran `pvp-demo-fix` since the morning of 2026-11-28: one replace (exit 0, 14 min) and the same two checks passing. Before that it ran `ui-sweep` since the night of 2026-11-27: two replaces (both exit 0), and three Playwright sweeps of every route and button for both seats of a board and a corp 1:1 round and a Player vs AI round, the last finding no defect. Before that it ran `demo` since the evening of 2026-11-27: four replaces, a two-person Playwright rehearsal of a pvp round on board passing every step, and `bin/verify --changed --live` from the platform VM stopped at the one-hour limit with 54 passed, 0 failed and four groups unfinished. In a pvp round the starting WAF already refuses every single-request board case. Before that it ran `slot-fix` since the afternoon of 2026-11-27: one replace (exit 0), then the full acceptance from the platform VM 101 passed, 0 failed, 0 errors in 1 h 38 min. Before that it ran
`review2` since the morning of 2026-11-27: one replace (exit 0,
12 min 45 s), a new bot OAuth token on the VM, then the full acceptance
from the platform VM: 87 passed, 3 failed and 11 errors in 1 h 44 min, all
14 on board slots (`round_start` answered `ground_truth_unavailable`,
`allocations` answered `range_unavailable`) and one IDS apply check; the
six modules they sit in run again alone, 20 of 20. On the range the IDS rule
test took 7.9 to 35.8 s (5 tests, from the store's test and `rule.tested`
times, with up to 15 acceptance processes at once); locally it went from
56 s to 12.5 s. The kali bake for `deploy/roles/kali/operator-log.sh` waited
until `cr-kali-bake5` (2026-11-28).

The second live review round (2026-11-27) found, and `review2` fixes: a
ModSecurity refusal counted twice (as the blocked alert and as its access-log
403); the debrief listing every alert and every benign verdict as its own row
(now grouped by rule, and one row per benign case with a count, at the case's
firing time); the prefetch GET of a case counted as a free action;
corroboration with no alert shown as false (now unknown); English case names
(every case has a Korean title, shown in the case list, score lines, rule test
rows, verdicts and the debrief); English origin countries in the attack
console and on the map (now Korean in the declaration); the staff round editor
naming objectives by key (the staff wargame list now sends key and name); a
bot run that stopped before its round not said (the player line and the
debrief bot line carry `left_of_round_s`, set when a run ended over 60 s
before its round, and the console says the bot stopped); rule test calls cut
at the 90 s request timeout (now five minutes); unapplied WAF edits lost on
reload (now kept per round in the browser); the shipped IDS rule file and the
bot's notes in English.

The first `pvp` round ran on 2026-11-27: round 372, board, `admin` attacking
and the new player account `pvp-defender` defending, 20 min 41 s, ended by
the operator; no objective lost, TP/FP/FN/TN 4/0/0/72.

Before `review2` the cloud ran `review-fix` from the evening of 2026-11-26:
one replace (exit 0, 13 min 43 s), the full acceptance from the platform VM
101 of 101 in 1 h 36 min. Before that it ran `bundle-1126`: one replace; rounds 309 (`atk_vs_bot`,
step 2: all three objectives lost, detection O and response O, the bot's
WAF version live 118 s after the first alert), 310 (`def_vs_bot`, step 2,
Sonnet 5.5: 118 turns, 2 refusals, the bot went on, no objective lost) and
311 (`def_vs_bot`, step 3, Opus 5.5: 79 turns, 2 refusals, no objective
lost, TP/FP/FN/TN 7/0/0/42) at once; watch checks every 30 s, each 0.3 to
5 s, a read that timed out at 5 s skipped to the next check; the full
acceptance from the platform VM 101 of 101; on 2026-11-23 the first range of `restructure`
was built and checked (`docs/DECISIONS.md`, "The first cloud check of
`restructure`").

- **Images.** `cr-infra-bake2`, `cr-waf-bake3`, `cr-target-bake2`, baked from
  `restructure`, and since 2026-11-25 `cr-kali-bake4`, baked from `bot-rounds`
  (the learner tunnel: `wireguard-tools`, `ip_forward`, `set-peer`), and
  `cr-waf-bake4` and `cr-target-bake3`, baked from `integrate` (each slot's
  own wargame is the WAF's default server; corp's WordPress takes its address
  from the request), which replace `cr-waf-bake3` and `cr-target-bake2` on
  the range, and `cr-waf-bake5`, baked from `waf-920350` (CRS 920350
  removed), which replaces `cr-waf-bake4`, and since 2026-11-28
  `cr-kali-bake5`, `cr-waf-bake6` and `cr-infra-bake3`, baked from
  `sweep-fix` (the renamed role files and the kali command log's start
  stamps). `compute.images` holds `cr-kali-bake5`, `cr-waf-bake6`,
  `cr-infra-bake3` and `cr-target-bake3`.
  Two kali
  snapshots before it failed at about 10 minutes with Nova's
  `compute_snapshot_instance: Error`; Glance's file store had 7.9 GB free
  for the 14.1 GB image, and the third bake passed after five unused images
  were deleted. That cause is likely, not confirmed: no admin log was read
  (`docs/OPENSTACK.md` §3.6). The project quota is 24 instances, 32 cores
  and 80 GB of RAM since 2026-11-24 (§3.2).
- **Platform.** Replaced from `restructure` with a fresh database, as stack
  `cr-platform2`. The old stack `cr-platform` was abandoned on 2026-11-24
  and its network and router renamed `cr-dev`, which carry the development
  VM `cr-dev`; the abandoned record still holds the name, so the platform
  cannot move back to `cr-platform` until an admin removes it
  (`docs/OPENSTACK.md` §5.3). The old tree's store is kept in a backup off
  the cloud. On 2026-11-24 `bin/cloud up --replace` ran end to end on
  `cr-platform2` twice: exit 0 in 12 min 12 s after a fix to the store
  restore (the refill service, then named `rebuild`, is now stopped with the platform), with the
  slot stacks standing through; and exit 0 in 29 min 32 s with
  `cr-kali-bake3`, every slot built again. The pool (`board: 3`, `corp: 1`)
  converged. On 2026-11-25 it was replaced from `integrate` (exit 0, 25
  min): the first replace onto PostgreSQL took the old VM's SQLite store and
  loaded it with `load_sqlite_store`, every table's row count equal to the
  backup's; the console came from the image's `/srv/front` with no hand
  copy; the pool converged on the new waf and target images.
- **Ran live and passed.** The checks of `docs/OPENSTACK.md` §3.7-§3.10, 39
  of 39 (§3.7's unused-address check by hand, after flushing kali's source
  rewriting, which the procedure now says);
  probe recordings, board 18 of 18 and corp 7 of 7, committed under
  `wargames/<id>/probes/`; the final full `bin/verify` with acceptance from
  the platform VM: acceptance 101 passed, 0 failed, the unit and API suites
  beside it green. `front/` was built and its vitest passed on the
  development VM, since the platform VM has no npm. On 2026-11-24, on the
  `cr-kali-bake3` range: probes board 18 of 18 and corp 7 of 7 recorded
  again (the committed set stays); the full `bin/verify`: acceptance 99
  passed and 2 errors (`test/test_block_everything.py`, both at setup: no
  board slot came free within the 1800 s room wait while 15 processes shared
  three board slots), the unit and API suites green; that module alone then
  passed 2 of 2.
- **Player vs AI rounds**, 2026-11-24, board, Claude Code as the bot
  player through `bots/cli.py`: round 143 `def_vs_bot` (bot attacks; it
  fired all nine attack cases and 13 free requests; TP/FP/FN/TN 9/0/0/66, no
  objective lost) and round 144 `atk_vs_bot` (bot defends on Opus 5.5:
  two tested WAF versions, the first origin spent by `deny`, an IDS reload
  from its terminal; 6/0/0/84, no objective lost). The attack bot was
  refused on Opus 5.5 and Sonnet 5.5 (`[cyber]`, the account's Cyber
  Verification Program tier is Defense Access) and played on Haiku 5.5.
- **Player vs AI live check**, 2026-11-25, `bot-rounds` on `cr-platform2`
  (replaced twice that night from `bot-rounds`), the bots service on the
  user's Claude Code login. As the bot uid in `cr-bots`, reading the secrets,
  another bot's home, `/proc/1/environ` and `sudo` were refused, and a call
  to the platform without the relay was refused. Rounds, board, three at once:
  - `atk_vs_bot` from cr-dev as the learner PC through the account's
    WireGuard profile: the profile attached to the round's kali and detached
    at the end; sqlmap through the tunnel dumped `auth_user` and the loot
    took all three objectives (round 175: detection O, response X, weighted
    11.0, the 2,183 tunnelled requests under `free_actions` by origin); in
    round 177 the step-3 defence bot (Opus 5.5) spent the origin by `deny`,
    the open tunnel moved to the next origin, and nothing was lost; in round
    179 the step-1 defence bot (Haiku 5.5) answered too late and all three
    were lost. The SSH snippet's `DynamicForward` carried the same traffic.
  - What a learner reaches (ruling 2026-11-25), from the tunnel and from the
    kali shell, by TCP connect and ICMP: only the round's own WAF front and
    its own kali; the platform VM's ports and management address, Keystone,
    con01, the gateway and every other slot's management and LAN addresses
    did not answer. UDP was not checked.
  - `def_vs_bot`: the step-2 attack bot (Haiku 5.5) stopped after a refused
    command (round 174) and, after the fix, was refused by Haiku 5.5's
    safeguards (`[cyber]`, round 180); the attack side has no model that
    plays on this account tonight.
  - A two-round baseline (human side attack, step 1) ran to `current`, then
    went `stale` when the new bots image changed the launcher profile.
  - Fixed on the way: the bots service's Host name, answers past 30,000
    characters, a bot ending the round on a refused command, quadratic
    correlation (`docs/DECISIONS.md` 2026-11-25).
  - Then `bin/verify --changed origin/restructure --live` from the platform
    VM (it selected every acceptance module): acceptance 101 passed, 0
    failed, 0 errors in 5,885 s across 15 processes; unit and API 246 and
    268 passed.
- **`integrate` live**, 2026-11-25, on `cr-platform2` with the PostgreSQL
  store:
  - `atk_vs_bot` on board from cr-dev through the WireGuard profile, by the
    address the access page gives (`http://121.134.88.42/`, no hosts line,
    no Host header), against the step-2 defence bot (Sonnet 5.5): sqlmap
    through the tunnel dumped `auth_user` and the loot took all three
    objectives (round 216: detection O, response X, weighted 11.0; TP/FP/FN/TN
    0/0/0/36, benign only). The bot spent the first origin by `deny` after
    two plain `GET /`, before any attack: CRS 920350 alerted on the
    numeric `Host` (removed since, `docs/DECISIONS.md` 2026-11-25).
  - corp by the bare address on slot 4: `GET /` answered WordPress with its
    links on the address typed, `/wp-login.php` 200.
  - The full `bin/verify` from the platform VM: acceptance 101 passed, 0
    failed, 0 errors in 6,090 s across 15 processes; domain 99, seams 1,343,
    users 34, telemetry 23, scoring 50, training 366, contract 98; unit and
    API beside acceptance 294 and 245. `front/` built and its vitest (42)
    passed on cr-dev; the bundle it built is the one the console serves.
- **`waf5` live**, 2026-11-25 evening, on `cr-platform2`:
  - `bin/cloud up --replace` from `waf5` ran end to end (exit 0, 22 min),
    the store restored from PostgreSQL with the per-table row counts in its
    output; every slot's WAF booted `cr-waf-bake5`.
  - `atk_vs_bot` on board from cr-dev through the WireGuard profile by the
    bare address, against the step-2 defence bot (Sonnet 5.5), as round 216:
    no CRS 920350 alert in the round (216 had 2,204), and no origin spent
    before the attack. The bot read alerts, traffic and events, saw none,
    and ended its run 35 s after it started, so it spent nothing at all.
    sqlmap through the tunnel dumped `auth_user` and the loot took all three
    objectives (round 245: detection X, response X, weighted 11.0;
    TP/FP/FN/TN 0/0/0/18, benign only). Detection was X because the loot
    came 3 min 20 s after the last attack request, outside the 2-minute
    attribution window (the driver's `attack_state` call after sqlmap was
    slow).
  - `bin/verify --changed origin/dev --live` from the platform VM: it
    selected every acceptance module; acceptance 101 passed, 0 failed, 0
    errors in 5,940 s across 15 processes. Its unit step failed at import:
    the change reached `platform/tests/domain`, and `--changed` ran those
    files in a Django process, which their conftest refuses. Fixed
    (`bin/verify` runs them in their own process); the unit step again on
    the VM: 1,563, 764 and 2 passed. `front/` built and its vitest (42)
    passed on cr-dev.
  - The attack bot with the engagement brief (`def_vs_bot`, defence idle,
    board): Sonnet 5.5 at step 2 stopped by its safeguards in 2 of 2 runs
    (rounds 273, 274, after 20 and 18 tool calls, on `sort` probes), Opus
    5.5 at step 3 in 2 of 2 (rounds 275, 276, after 6 and 17, the first on
    the first declared SQLi case, the second when it turned to the card's
    password guessing); no run fell back to Opus 4.8, and no objective was
    taken.
- **`defence-watch` live**, 2026-11-26 early morning (UTC), on `cr-platform2`:
  - `bin/cloud up --replace` from `defence-watch` (exit 0, 14 min; the slot
    stacks stood through, every slot on the same images).
  - `atk_vs_bot` on board from cr-dev through the WireGuard profile by the
    bare address, no range request until 200 s after the round started, then
    sqlmap, against the step-2 defence bot (Sonnet 5.5, `watch_s` 30), round
    277: the bot's run lasted the round (9 feeds, 00:41:40 to 00:52:41, exit
    success, 27 turns, USD 0.55, no refusal); the first feed with alerts came
    34 s after the first alert; it wrote a `deny` of the attack's origin and
    ran the WAF rule test, which took 6 min 36 s, ran past Claude Code's
    120 s Bash timeout into the background, where the bot could not read
    it, so every apply was refused `409 not_tested` and nothing went live
    before the loss (2 min 39 s after the first alert). All three objectives
    lost, detection O, response X, weighted 11.0; TP/FP/FN/TN 0/0/0/36,
    benign only; no CRS 920350 alert.
  - The same at step 1 (Haiku 5.5, `watch_s` 75), round 278: run lasted the
    round (exit success, 42 turns, USD 0.16); feeds 75 s apart where the
    bot was idle, against 31 s at step 2, so the interval follows the step.
    No feed came between 00:58:13 and 01:03:48 while alerts flowed from
    00:59:17 (not measured why); its `deny` came after the loss, the rule
    test again went to the background (about 3 min), nothing applied. All
    three lost, detection O, response X; TP/FP/FN/TN 0/0/0/42.
  - `bin/verify --changed origin/dev --live` from the platform VM: it
    selected every acceptance module; acceptance 101 passed, 0 failed, 0
    errors in 5,798 s across 15 processes (`test_bot_rounds` 3 of 3); unit
    and API 1,560, 759 and 3 (domain) passed. No module errored on the
    room wait. No node on the VM, so `front/` was not built there.

## What exists on restructure

The side-split build (the spec's steps 1-17, recorded in this file's git
history) is carried into five units. The proofs named in each row run
against fakes; on 2026-11-23 the acceptance suite also ran the whole table on
a live range and passed.

| Stage | What exists | Proof that ran |
|---|---|---|
| Five units | `users/`, `sandbox/` (every file that knows an outside device), `telemetry/`, `training/` (one app: `content/`, `round/`, `traffic/`, `attack/`, `defence/`, `lessons/`), `scoring/`; `cr/`, `domain/`, `testing/` shared; fresh `0001` migrations (`users` keeps `0002_first_account`) | `platform/tests/seams/test_imports.py` (no import from a higher layer, unit surfaces), `test_isolation_seams.py` (the exception list is the one CLAUDE.md gives); `openapi/schema.yaml` regenerated byte-identical to the schema before the move |
| Names | Seat is `Player`, Lease is `Allocation`: models, fields, routes (`/api/allocations/`, `/players/<side>/join/`), events (`player.joined`), error codes, `CR_PLAYER_TOKEN`, `CR_ALLOCATION_IDLE_MINUTES`, tables in `bin/backup`, the console's 플레이어 | unit and API suite, `front/` vitest |
| No tick | round reads run on the round's API requests (`training/round/views_catch_up.py`, `lifecycle.catch_up`, one reader per round through `Round.reading_since`, `CR_READ_EVERY_SECONDS`); the `follow` service is now `refill` (`manage.py refill_slots`); `ended` is `min(now, ends_at)` and the score counts up to it; a round ended by the operator, a forfeit or allocation expiry reads the logs once more first, waiting for a read another request holds; a reader releases only its own claim and stops once the round has ended, and a request reads a round before it closes an expired allocation; with `CR_READ_IN_BACKGROUND=1` (set in `compose.yaml`) the read runs on a thread of its own, one per round at a time, and the request does not wait for it; terminal grants do not read | `tests/training/round/test_catch_up_and_score.py`, `tests/training/round/test_lifecycle.py`, `tests/training/round/test_read_behind.py` |
| Origin loss | HP is gone; an origin is spent by an nginx `deny` or a `limit_req` at or above the floor in the WAF error log (`training/attack/origins.py`, `telemetry/waf_log.py`, `domain/traffic.py`), judged by the WAF version in force when the line was written; `limit.below_floor` warns the defence, and a zone keyed by anything but the client address spends nothing and warns once (`limit.shared_key`) | `tests/training/attack/test_origin_loss.py`, `tests/domain/test_traffic.py`, `tests/telemetry/test_refusals.py` |
| WAF as files | the defender edits six WAF files (`crs-setup.conf`, the REQUEST-900 and RESPONSE-999 exclusions, `/etc/nginx/defence/{http,board.com,corp.com}.conf`); one read, check, test, write, reload, record flow for IDS and WAF (`training/defence/rules.py`); a terminal reload recorded on the next read from the snapshot the reload wrapper (`deploy/roles/waf/nginx`) copies into root-only `/var/lib/cr-reloaded/waf` and installs root-only for the reload, so nginx loads exactly the snapshot, or put back to the head version when that snapshot touches the platform's measurement (`rule.refused`); live files edited after a reload are left alone; `drift.py` and the JSON tuning gone | `tests/seams/test_crs.py`, `test_crs_scratch.py`, `tests/training/defence/`, `test_analyst.py`, `test_roles.py` |
| IDS on the sensor | the defence edits Suricata rules on the sensor (ruling 2026-11-22): a second terminal, `analyst` on the infra (`deploy/roles/infra/analyst.sh`: the rule file by ACL, `sudo suricata -T` and `suricatasc -c reload-rules`, loopback addresses only, so not the log relay on the host's own address), `GET defence/ids/terminal/` and `/vm-terminal/ids/<round>/`, the console's terminal pane switching WAF and IDS, the bots' `ids_shell`; a reload there recorded as the next IDS version from the snapshot the `suricatasc` wrapper copies into root-only `/var/lib/cr-reloaded/ids` before reloading, put back when a reloaded rule carries `config: logging` (a backslash-continued rule included); a rule file edited after a reload is left alone; the IDS check, apply and disable API, `DisabledRule` and the console form gone, versions and the rule test kept | `test_ids_analyst.py`, `tests/training/defence/test_ids_terminal_reload.py`, `test_terminal.py`, `test_apply.py`, `tests/seams/test_jump.py`, `test_bots.py`, `test_front.py`, `test_vm_terminal.py`; the acceptance tests through the IDS shell, live 2026-11-23 |
| Test required | a rule test passes only when the engine accepts the files, every benign case of the round was replayed (`untested_benign` empty, at least one) and none is refused (WAF) or alerted on (IDS) (`passed`, `failed_benign`); a pass lists the box's hash of those files in root-only `/var/lib/cr-reloaded/{waf,ids}.passed` through `sandbox/crs.py` and `sandbox/suricata.py`, cleared at the round's setup; the console WAF apply takes only the files of a passed test (`409 not_tested`) and the console offers apply only then; both reload wrappers refuse a snapshot not listed, and the IDS wrapper refuses `config: logging` before it loads; a terminal version is tied to its passed test | `tests/training/defence/test_required_test.py`, `test_analyst.py` |
| Response proof | detection and response O/X per lost objective (ruling 2026-11-22); response is a spent origin of the window's attack actions, or a WAF version live after their first alert (first action when none alerted) whose passed test replayed their own requests under fresh per-test markers (case recordings, the logged request of free requests, `rules.attack_requests`) and refused the attack among them (every replayed action that alerted, else every replayed case attack, else any one); IDS versions never count | `tests/domain/test_objectives.py`, `tests/training/defence/test_response_proof.py`, `tests/scoring/test_score.py` |
| Late judge | the request that ends a round answers at once; the first read `CR_JUDGE_AFTER_SECONDS` after the end ingests once more, settles, judges and logs `round.judged` (`Round.judged_at`, `lifecycle.judge_late`); the score says `pending` until then | `tests/training/round/test_catch_up_and_score.py` |
| Customers on the infra | benign traffic leaves from the infra VM (`sandbox/customers.py`, `cr-customers.service`, dummy link `customers`), never from kali; the edge `pool` holds only attack origins | `tests/seams/test_customers.py`, `tests/seams/test_stack_plan.py`, `tests/test_roles.py` |
| Random board secret | each round's start sets new board passwords (`set_passwords`, declared as `rotate` in `wargames/board/objectives.yaml`) and then reads the baseline | `tests/scoring/test_baseline.py`, `tests/test_board_db_ephemeral.py` |
| Verdict notices | each case is judged once during the round (`scoring.score.judge`, `Verdict` rows, `case.judged` to the defence); the console shows the newest three | `tests/scoring/test_judge.py`, `front/` vitest |
| Bots | the bots get the human's shell (`bots/shell.py`); no generated client: `bots/`, `test/` and `bin/` call the API by `operationId` through `bots/rest.py` | `platform/tests/test_bots.py`; the acceptance suite through `bots/rest.py`, live 2026-11-23 |
| Lessons | the lesson content is gone; `training/lessons/` is an empty package; `front/` builds again | `npm run build`, `npx vitest run` |
| Docs | README, ARCHITECTURE, OPENSTACK, this file and `now.md` describe `restructure` and the 2026-11-23 cloud check | this stage |
| Player vs AI rounds (branch `bot-rounds`, gate 1 of 2026-11-24; with `pg-store` and `access-address` on `integrate` since 2026-11-25) | three difficulty steps (`training/content/steps.yaml`; attack and defence bot Haiku/Sonnet/Opus 5.5 at steps 1/2/3); attack cards A1-A8 (`cards.yaml`, one ATT&CK id each, drawn at random per round, shown only in the debrief); the `bots` compose service launches Claude Code behind a per-run relay that holds the token, pace and allowance; bot runs, notes, round records kept 90 days, the debrief; one WireGuard profile per account attached to the human attack seat's kali (`sandbox/vpn.py`, kali `set-peer`); attribution by origin (WAF access-log requests from the round's attacker origins are the attacker's free actions); console: lobby step picker, debrief, records, access page, staff card and step choice | the unit tests of spec §17, `front/` vitest and build; live on 2026-11-25 ("Where things stand") |

## Not live-verified

What ran on the range on 2026-11-23 and 2026-11-24 is under "Where things
stand". Still not run on a range:

- a live review round with zero countable findings, and a docs review
  (three Playwright sweeps of every route, button and form for both seats
  ran on 2026-11-27, the last with no defect);
- the edge's `pool` and `spent` sets after a reboot of the infra
  (`docs/OPENSTACK.md` §3.10, last check);
- by hand: the IDS reload's refusal of `config: logging` and the WAF
  wrapper's refusal of an `access_log off` written during a reload
  (`docs/OPENSTACK.md` §3.10);
- `bin/cloud up --replace` under the stack name `cr-platform` (it ran as
  `cr-platform2`; under `cr-platform` it stops before deleting anything,
  §5.3); `bin/cloud down`;
- of the Player vs AI build: the learner's UDP reach from outside the
  range (three bot rounds at once on the PostgreSQL store and `def_vs_bot`
  rounds the attack bot played to the end ran on 2026-11-26, rounds 309 to
  311);
- the rulings of 2026-11-22 and 2026-11-23 not built yet (five attack
  origins, more benign kinds, Internet scanners, the board's attack paths).
  The response replay of the attack's own logged requests ran in round 309.

## Next steps, in order

1. **corp's probes recorded again** with the fixed `corp-rogue-admin` case
   (`bin/record-probes`), committed under `wargames/corp/probes/`.
2. **A deploy of `dev`** (`bin/cloud up --replace`), which carries the UTC+9
   display and the probes wording to the cloud.
3. **External learners** (the user, 2026-11-25: the last task of the Player
   vs AI work): the public-IP forwards of UDP 51820-51919, TCP 2222 and the
   console, and `CR_VPN_HOST`.
4. **Gate 2**: a live review round with zero countable findings and a docs
   review, then present what changed with the evidence; on approval, move
   the verified, tagged state onto `main`.

Beside these, when they can: **the name `cr-platform`** (an admin removes
the abandoned stack's record from Heat's database, then one replace under
that name, `docs/OPENSTACK.md` §5.3); **the platform under several rounds**
(three bot rounds at once on 2026-11-26, rounds 309 to 311: no round
stopped, a platform read now and then took over 5 s; free actions read from
Elasticsearch at scoring time stay).

## Record of the trees, one line each

- `pvp-demo-fix` (2026-11-28): one replace (exit 0, 14 min); a board pvp check (round 489) and a corp pvp check (round 490) passed every step from sign-in to sign-out after the fixes of `docs/DECISIONS.md` 2026-11-28 "pvp demo check".
- `ui-sweep` (2026-11-27): two replaces (both exit 0); three Playwright sweeps of every route, button and form for both seats of a board and a corp 1:1 round and a Player vs AI round, 400, 351 and 328 actions, the last with no defect.
- `demo` (2026-11-27): four replaces (12 min 22 s to 13 min 38 s; the first stopped at training 0003, TROUBLESHOOTING "pending trigger events"); a two-person pvp rehearsal on board passed every step; `bin/verify --changed --live` stopped at the one-hour limit, 54 passed, 0 failed.
- `slot-fix` (2026-11-27): one replace (exit 0); the full acceptance from the platform VM 101 passed in 1 h 38 min.
- `review2` (2026-11-27): one replace (exit 0, 12 min 45 s); the full acceptance 87 passed, 3 failed, 11 errors, all on board slots and one IDS apply check; those six modules alone 20 of 20.
- First `pvp` round (2026-11-27): round 372, board, no objective lost, TP/FP/FN/TN 4/0/0/72.
- `review-fix` (2026-11-26): one replace (exit 0, 13 min 43 s); the full acceptance 101 of 101 in 1 h 36 min.
- `bundle-1126` (2026-11-26): rounds 309 (all three lost, detection O, response O), 310 and 311 at once; the full acceptance 101 of 101.
- `defence-watch` (2026-11-26): rounds 277 and 278, both defence runs lasted the round, detection O, response X; acceptance 101 of 101.
- `waf5` (2026-11-25): round 245 with no 920350 alert; acceptance 101 of 101; the attack bot stopped by its safeguards in 4 of 4 runs.
- `integrate` (2026-11-25): the SQLite store loaded into PostgreSQL with every row count equal; acceptance 101 of 101.

## Open points

- **The attack bot and the model's safeguards.** The attack bot is Haiku,
  Sonnet and Opus 5.5 at steps 1, 2 and 3 again (`docs/DECISIONS.md`
  2026-11-25: the earlier Sonnet and Opus refusals came from runs without
  the range context and inside the repo, so they do not count). Haiku 5.5
  refused once (`[cyber]`, round 180) and played in the other runs. With
  the range context and the call file (rounds 211-215, 2026-11-25, defence
  idle): Haiku 1 of 1 played, no safeguard stop; Sonnet 5.5 stopped by its
  safeguards in 1 of 2; Opus 5.5 in 2 of 2, and in round 215 Claude Code
  fell back to Opus 4.8 on `[cyber]`, which took all three objectives.
  A run that falls back still counts as step 3 (`docs/DECISIONS.md` 2026-11-25).
  With the engagement brief (`waf5`, rounds 273-276): Sonnet 5.5 stopped
  in 2 of 2, Opus 5.5 in 2 of 2, none fell back, none took an objective.
  The brief did not lower the stop rate in these four runs.
- **The defence bot ended its run when nothing alerted** (round 245: the
  step-2 defence bot read an empty alert list and ended its run 35 s in, so
  the attack that followed met no defender). Resolved on `defence-watch`
  (`docs/DECISIONS.md` 2026-11-25): the launcher keeps the defence bot's
  Claude Code session open until the round ends and feeds it new alerts,
  refusals, new addresses and phase changes every `watch_s` of its step.
  On the range (rounds 277, 278) both runs lasted the round.
- **A platform read can take over 5 s under three rounds at once.** In
  rounds 309 to 311 a watch check's `defence_state` read now and then hit
  its 5 s cap; the launcher logs the check and the next one reads the same
  rows again. The ingest each read runs (`lifecycle.catch_up`) is the
  suspect; not measured. Since `pvp-demo-fix` that read runs on a thread of
  its own (`CR_READ_IN_BACKGROUND=1` in `compose.yaml`,
  `training/round/views_catch_up.py`), so no request waits for it; whether a
  read under three rounds still runs past 5 s is not measured on that path.
- **The acceptance room wait can run out.** On 2026-11-24 one module of the
  full run waited past `ROOM_WAIT` (1800 s, `test/plays.py`) for a board
  slot while 15 processes shared three, and errored at setup; alone it
  passed. On 2026-11-23 the same split passed. Whether the wait, the split
  or the slot refill time should change is not measured.
- **The bot inherited the repo** in the bot rounds of 2026-11-24 (run from
  the repository root, it read `redteam/cases/` and the wargame files). On
  `bot-rounds` the launcher runs it from an empty directory in safe mode
  with no setting sources, from an image holding only `bots/` and the
  schema; live on 2026-11-25 every file read the bots tried (`cat`, `grep`,
  a `python3` script) was denied.
- **The platform under several rounds** (2026-11-25, three board rounds and
  a tunnelled sqlmap): `database is locked` past the 30 s busy timeout
  (bot notes, the judge, `bot_run_finish`), reads of a round longer than
  15 minutes until correlation was indexed, the store from 3 MB to 253 MB in
  four hours. `telemetry/alerts.joined_later` ran one JSON-filtered UPDATE
  per Suricata join; it now reads a page's flows once. The store is
  PostgreSQL and `apply_waf` and `apply_ids` reach the WAF or the sensor
  outside the write transaction; both run on the range since 2026-11-25,
  and under three bot rounds at once on 2026-11-26.
- **A past round's free actions live in Elasticsearch.** The score reads them
  at scoring time, so after a platform rebuild an ended round's live score
  drops them (round 175 read `detected: true` before the rebuild and `false`
  after); the round record keeps the score frozen at the end.
- **The jump host's key changes on every rebuild** (`/data/jump` is not
  carried over), so a learner's saved `known_hosts` refuses the next one.
- **Acceptance checks that read Elasticsearch directly.**
  `test/test_event_time.py`, `test/test_geoip_durable.py`,
  `test/test_origin_placement.py` and `test/test_waf_geolocation.py` query
  Elasticsearch's ingest pipeline, node settings and index on
  `localhost:9200` rather than through `/api/`. The seam scan lists them as
  named exceptions (CLAUDE.md); moving them behind an API route or into
  `telemetry/elastic.py` is open.
- **A refused key leaves a jump grant.** If the box refuses the per-player
  key, `sandbox.jump.open_access` keeps the platform sshd grant until the
  round ends. Without the box key it gives no access.
- **Mockup fields the API does not send.** User names on players and the
  round bar, a past round's end and result, the allocation's opening time, a CRS preview, case and objective
  catalogs for the staff editor, and coded slot and server failures.
- **Screens not yet one file to change.** Verdict tones differ between
  `Score` and `RuleBench`; some cytoscape widths and margins in
  `panes/Map.tsx` and the SVG stroke widths are still numbers in code.
- **A round no one calls on does nothing.** The benign pass, origin loss,
  alert ingest, verdicts and the time-limit end wait for the next request
  for the round; a polling console or bot keeps it moving. The edge sets
  are not refilled mid-round, so a `slot-boot` reload of the table leaves
  them empty until the next round starts.
- **Verdicts are never revised.** A notice sent before a late alert can
  differ from the final score, which comes from the rows. The 30 s wait
  before a miss (`CR_JUDGE_AFTER_SECONDS`) is an estimate, not measured.
- **Two `restructure` placements left as they are**: the staff range views
  stay in `training/round` until the pool records which allocation holds a
  slot, and the score view stays there because it gathers both sides'
  actions; `scoring/` has no views.
- **The comment scan reads code only.** `test_no_comments.py` covers
  Python, shell and TS/TSX/JS; YAML data and config files may carry
  comments and are not scanned: `cases/board.yaml`,
  `wargames/board/traffic.yaml` and `deploy/openstack/cloud.example.yaml`
  carry them today.
- **A changed case needs its probe recorded again.** The board and corp
  recordings were made on the 2026-11-23 range; a case whose request changes
  needs a new recording, as `board-path-traversal-static` did.
- **A recorded 400 or 403 response.** The scratch WAF's upstream answers a
  replayed case with its recorded response, so a case whose recording is a
  400 or 403 from the site reads as refused by the WAF.
- **No route serves the probe recordings.** `training/content/probes.py` writes them to
  the platform's `CR_PROBES_OUT`; they are copied off the platform VM by hand
  before they are committed.

## Decisions left for a person

- **What the lessons and rounds teach.** The old lessons F1-F6, courses c1
  and c2 and scenarios 1.1-4.1 are deleted, and the side-split lesson code
  went with the restructure; `training/lessons/` is the empty place for the
  rewrite from both sides. Problems are authored as database rows through
  the staff API and page; which lessons come first and which rounds follow
  is not decided.
- **Who sees a verdict.** `case.judged` goes to the defence and staff only,
  since it shows the defender's coverage; whether the attacker should see
  TP/FN for its own cases is open.
- **Two licences behind the origins and the map.** MaxMind's GeoLite EULA
  asks for old databases to be deleted within 30 days of a new release and
  for the line "This product includes GeoLite Data created by MaxMind". For
  the MVP the user took the lightest path (2026-10-02): the `.mmdb` is not
  committed, `bin/fetch-geoip` pulls it and `deploy/elastic/ingest-geoip/README.md`
  carries the attribution. Whether to carry the database and that obligation
  into the production repo, and the 30-day refresh, is still open.
  Cloudflare Radar's shares are CC BY-NC 4.0, fine here, to be looked at
  before they move to the production repo.
- **Board secret between rounds on one allocation.** The board passwords
  now rotate at every round start, but `may_start_scored` still refuses a
  scored round on an allocation where an objective has fallen
  (`objective_fallen`, spec §17 risk 8); corp's ground truth does not
  rotate. Whether to lift the rule for the board is open.

## Open risks (spec §17)

Not measured yet; the 2026-11-23 range ran these paths but measured none of
them: offline IDS against the live sensor;
mapping `suricata -T` errors to a line; scratch CRS instance fidelity;
recorded sqlmap pcaps as an IDS preview; error-log loss on the UDP hop (an origin
the defender banned is not spent); spend lag of one read interval plus shipping; forged markers and
customer addresses on a root box; free-action attribution by window; the
background round read (`CR_READ_IN_BACKGROUND=1`) keeping up under four sqlmap runs; the first Preact build and
the SPA fallback order.

## Known gaps

- The range keeps time by the platform VM alone (chrony, `local stratum 10`;
  each slot VM's user data points systemd-timesyncd at the platform's
  `cr-mgmt` address): if the platform VM loses its upstream, the range follows
  the platform's clock, which is what scoring compares against, not true time.
- The platform holds the ssh key of the management user on every slot VM
  (passwordless sudo): whoever takes the platform container is root on every
  slot VM. The platform VM's own Docker socket is not mounted anywhere.
- ModSecurity's `Detection.raw` holds the rule message, request, host and
  place, not the whole audit record.
- The command log is lost when the attacker box is recreated, and a sudo
  learner can rewrite it; it feeds only `command.run` and the `kali` check.
- A slot is reused, so the Kibana space `soc-logs-N` also shows what an
  earlier allocation on that slot left in `logs-N-*`.
- OpenStack host keys are trust-on-first-use per generation, kept in the
  platform user's home (lost with the container) unless the deployment's ssh
  config says otherwise.

## Tried and thrown away

- **The scenario engine, triage and debrief** (removed 2026-11-19 with the
  side split), and then the side-split lessons (removed 2026-11-21): one
  kind of play remains, the live round.
- **The periodic tick, HP, the WAF JSON tuning and drift check, and the
  generated client** (removed 2026-11-21 with the restructure;
  `docs/DECISIONS.md`).
- **The ratchet** (`metrics.json`, `bin/measure`), removed 2026-11-19: time,
  effort and dependency counts are not criteria.
- **Replacing Django entirely.** It cost more lines than it saved.
- **Elasticsearch as the only store, 2026-09-22**, killed before any code:
  both event clocks are `keyword` and the read clock leads ModSecurity's by
  2.5 s median, 7.9 s p90, so 64% of WAF alerts would miss their 2 s window.
- **Asserting that no alert in a red team window is unmarked.** False: a
  window reaches a minute either side, so it holds whatever used the range
  just before.
- **Feeding window correlation the scorer's address.** It would measure the
  scorer instead of the defence; a zero with a stated reason is more useful.
