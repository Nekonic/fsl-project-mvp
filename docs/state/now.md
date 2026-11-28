# Now

The handover to the next session, kept short. The build record and backlog
are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md`; detail in `git log`.
The handover of the old tree up to 2026-11-18 is in this file's git history.

Updated: 2026-11-28.

## Where things stand

- 2026-11-28, the pvp demo day: `dev` holds the pvp check fixes
  (`docs/DECISIONS.md` 2026-11-28 "pvp demo check"). The Kali terminal no
  longer reloads itself while ttyd's page loads; terminal grants skip the
  round's log read and every other view reads on a thread of its own
  (`CR_READ_IN_BACKGROUND=1` in `compose.yaml`); corp's registration cases
  send the form's own field ids, so corp-rogue-admin creates an administrator
  and the objective falls; corp starts on its own IDS rules (corp-ids), which
  alert on it; the defence console opens on alerts and loads Kibana only on
  its tab; the starting WAF/IDS versions read '시작 룰'; learners see the slot
  as '1번'; both consoles show a waiting or starting notice; the WireGuard
  profile downloads as a `.conf` (vpn-download); problems 19 and 20 say
  '기업 사이트'. On the cloud after one replace, both pvp checks
  (`~/.cache/fsl-work/pvp-check/{board,corp}/results.json`) passed every
  step from sign-in to sign-out: the attack takes corp's objective, the IDS
  alert shows, the defender's WAF rule passes its test, goes live and the same
  attack gets 403; the board SQLi is refused by CRS and then by the
  defender's rule. Start still takes 25-40 s (posture 7.6 s, baseline 3.1 s
  measured, on a 2-vCPU platform VM). Times shown in the console are KST
  (`front/src/format.ts`); that change is on `dev` and reaches the cloud with
  the next replace.
- The tree is `ui-sweep` (2026-11-27, the evening before the pvp demo):
  `demo` with the Korean wording pass and the fixes of a UI sweep
  (`docs/DECISIONS.md` 2026-11-27 "Sign-out ends everything at once"). Sign-out
  and any 401 clear the console's session, so the page lands on the sign-in
  page once and every poll stops (before: 249 to 394 requests in 10 s, a
  401/429 loop between home and sign-in). An event follower starts at the
  newest event unless a listener replays the backlog, and asks only for the
  kinds its listeners want (`kinds=`, `tail=` on the feed); panes that ask for
  the same resource in one render share one read; the backlog no longer
  triggers refreshes. Also: the loot pane is off the corp attack console
  (`takes_loot`), each attack case keeps its last outcome and a tool case
  shows running until its run ends, terminals show a connecting notice and
  reload on a 5xx, the IDS pane re-reads the sensor's rules before a test,
  a running check or test says so, a kept pane stays laid out so Kibana is
  not rebuilt on a tab switch, 기권, 끝내기, 레인지 반납 and 다음 IP로 take a
  second press, the score is read again while pending, a player's result
  page no longer reads the allocation (`operated` on the round), learners
  see only published problems' rounds and records, objectives read
  달성 rather than 탈취, the debrief loads in about 3 s on a 57k-alert round
  and hides the bot's shell lines and English notes, a round's end marks its
  bot runs `round_ended`, the alert list is newest first, and the IDS/WAF
  pane strings and the local Suricata rule notes are plainer Korean. On the
  cloud: two replaces (both exit 0), then three Playwright sweeps of every
  route, button and form for both seats of a board and a corp 1:1 round and
  one Player vs AI round, 400, 351 and 328 actions pressed, the last with
  no defect (`~/.cache/fsl-work/ui-sweep/report.md`). Problems 16, 17, 19
  and 20 were imported again from their files and stay published. The IDS
  and WAF reload refusals are Korean in `deploy/roles/` but the slots run
  the baked English ones until the next infra and waf bake.
- Before that the tree was `demo` (2026-11-27, the evening before the pvp demo):
  `slot-fix` with `ingest-fix`, `no-baseline`, `problem-body` and
  `pvp-no-problem` merged. The bot-vs-bot rounds are dropped by their own
  migration (scoring 0002, run before training 0004) because on PostgreSQL
  the delete and the ALTER TABLE in one migration refused ("pending trigger
  events"); a store test migrates a PostgreSQL store with a running
  bot-vs-bot round and a detection from 0003. Dropping an allocation locks
  its rounds and forgets their detections again after the delete (the bot
  run claim answered 500 on a detection stored while its round was
  deleted). A pvp round's time limit is `CR_PVP_TIME_LIMIT_SECONDS`, 30
  min by default. The problem fold of a pvp round names the wargame in
  Korean; the pvp debrief has no opponent bot section. Ending a running
  round closes both sides and stops the customers before the final read
  (it took 44 s with both consoles open). Problems 18 and 21 (the old pvp
  problems) are deleted; the bot problems 16, 17, 19 and 20 are published.
  On the cloud: four replaces (12 min 48 s, 12 min 22 s, 12 min 58 s,
  13 min 38 s; the first came up at training 0003 because of the
  migration), every slot refilled, no bot-vs-bot round left. A two-person
  Playwright rehearsal of the demo (admin attacks, `pvp-defender` defends,
  board) passed every step in the last run: start 35 s, the defender's
  rule test 10 s, end 27 s. In a pvp round the slot's starting WAF
  already refuses every single-request board case (403 from CRS), so the
  defender's own rule refuses an attack CRS refused already; a 200-then-403
  story needs a start posture, which pvp no longer has. Acceptance from
  the platform VM (`bin/verify --changed --live` against the dev before
  the merge, which lists all 34 files): stopped at the one-hour limit,
  54 passed and 0 failed in the groups that finished, four groups unfinished.
- Before that the tree was `slot-fix` (2026-11-27): `review2` with the causes of the
  last full acceptance's failures fixed (`docs/DECISIONS.md` 2026-11-27):
  an IDS alert Elasticsearch indexed after a later WAF line is read (the
  alert cursor reads 30 s back), `defence_traffic`'s `next` names one
  timestamp (traffic 15 s behind), the defence watch sends its end feed
  and closes stdin when its round ends and on a 401, a staff-ended
  baseline round closes its allocation once judged. A loop left reading
  baseline 2 since 2026-11-25 was stopped. On the cloud: one replace
  (exit 0), the full acceptance from the platform VM 101 passed, 0
  failed, 0 errors in 1 h 38 min, in one run.
- Before that the tree was `review2` (2026-11-27): `review-fix` with the fixes of the
  second live review round (`docs/STATE.md` "Where things stand"): one
  ModSecurity alert per refused request, the debrief grouped by rule and by
  benign case, Korean case titles on every case line, Korean origin
  countries, objective names in the staff round editor, `left_of_round_s`
  on the player line and the debrief bot line, rule test calls that wait
  five minutes, the IDS rule test 56 s to 12.5 s locally. On the cloud: one
  replace (exit 0, 12 min 45 s), a new bot token, the full acceptance from
  the platform VM 87 passed, 3 failed, 11 errors, all on board slots
  (`ground_truth_unavailable`, `range_unavailable`) and one IDS apply check;
  those six modules alone 20 of 20. The IDS rule test on the range took
  7.9 to 35.8 s under the acceptance load.
- The first `pvp` round: round 372 (2026-11-27, board), `admin` against the
  new player account `pvp-defender`, no objective lost, TP/FP/FN/TN 4/0/0/72.
- Before that the tree was `review-fix` (2026-11-26): `bundle-1126` with the fixes of
  a live review round. The score pane shows each objective's difficulty and
  the points each lost one adds; the loot pane names every objective that
  fell; board and corp objective names are Korean; the VPN profile lists
  only the target of the round it is attached to; the runner keeps a
  command's bytes as sent; a Claude child that failed finishes as error and
  its run as failed; the kali command log stamps a command when it starts.
  On the cloud: one replace (exit 0, 13 min 43 s), then the full
  acceptance from the platform VM 101 of 101 in 1 h 36 min. Not on the
  range yet: the kali change (`deploy/kali/operator-log.sh`) needs a kali
  bake, deferred, so the slots still run `cr-kali-bake4`'s command log.
- Before that the tree was `bundle-1126` (2026-11-26): `defence-watch` with the bot
  polling the rule test as a detached job, the rule test replayed in one
  curl over one SSH call, the attack prompt rewritten to name the round's
  attack profile for the debrief, and the watch check timed from the last
  start and capped. On the cloud: one replace; rounds 309 (`atk_vs_bot`
  step 2, all three lost, detection O, response O, the bot's WAF version
  live 118 s after the first alert), 310 (`def_vs_bot` step 2 Sonnet 5.5,
  2 refusals, the bot went on, no objective lost) and 311 (step 3 Opus 5.5,
  2 refusals, no objective lost, 7/0/0/42) at once; the full acceptance
  from the platform VM 101 of 101.
- Before that the tree was `defence-watch`: `waf5` with the defence bot kept in the
  round until it ends, fed by the launcher every `watch_s` of its step
  (`docs/DECISIONS.md` 2026-11-25). It runs on the cloud since the early
  morning of 2026-11-26 (`docs/STATE.md` "Where things stand"): one
  replace (exit 0); two WireGuard `atk_vs_bot` rounds by the bare address
  with the attack held 200 s after the start (rounds 277 at step 2, 278 at
  step 1): both defence runs lasted the round, the feeds came 31 s and 75 s
  apart, both bots wrote a `deny` of the attack's origin, and in both the
  WAF rule test (6 min 36 s and about 3 min) went past Claude Code's 120 s
  Bash timeout into the background, so nothing was applied and all three
  objectives were lost, detection O, response X; `bin/verify --changed --live` from the platform VM: acceptance
  101 of 101, the unit and API suites green.
- Before that the tree was `waf5`: `integrate` (`bot-rounds`, the Player vs AI rounds
  cut from `restructure`, with `pg-store`, the PostgreSQL store, and
  `access-address`, the access page's target address, and the fixes of
  their reviews) with CRS 920350 removed at the WAF (`cr-waf-bake5`)
  and the attack bot's prompt rewritten as an engagement brief. `main`
  still holds the old product. `waf5` ran on
  the cloud from the evening of 2026-11-25 (`docs/STATE.md` "Where things
  stand"): one `bin/cloud up --replace` (exit 0, every slot on
  `cr-waf-bake5`); a WireGuard `atk_vs_bot` round by the bare address with
  no 920350 alert and no origin spent before the attack (round 245, all
  three objectives lost, detection X, response X: the step-2 defence bot
  ended its run 35 s in, with nothing alerting); acceptance 101 of 101 from
  the platform VM; the attack bot stopped by its safeguards in 4 of 4 runs
  (Sonnet 5.5 2 of 2, Opus 5.5 2 of 2), no fall back, no objective taken.
- Before that the cloud ran `integrate` (2026-11-25, `docs/STATE.md` "Where
  things stand"): `cr-waf-bake4` and `cr-target-bake3` baked from it, one
  `bin/cloud up --replace` that loaded the SQLite store into PostgreSQL
  with every row count equal, the console from the image with no hand copy,
  an `atk_vs_bot` round through WireGuard by the bare address (all three
  objectives lost, detection O, response X), corp by the bare address, and
  the full `bin/verify` from the platform VM: acceptance 101 of 101, every
  unit and API suite green.
- On 2026-11-25 the Player vs AI build ran live (`docs/STATE.md` "Where
  things stand", `docs/DECISIONS.md` 2026-11-25): `cr-kali-bake4`, two
  replaces from `bot-rounds`, rounds from a PC through WireGuard (an
  objective lost through the tunnel; an origin spent by the defence bot
  through it), the learner reach check (only the round's kali and WAF
  answered), a two-round baseline, four fixes, then acceptance 101 of 101
  from the platform VM.
- `restructure` carries out the 2026-11-21 and 2026-11-22 rulings; the table
  is in `docs/STATE.md` "What exists on restructure". The rulings recorded on
  2026-11-23 (five attack origins, more benign kinds, Internet scanners, the
  board's attack paths, the response replay of the attack's own logged
  requests) are not built.
- The first cloud check of `restructure` ran on 2026-11-23
  (`docs/DECISIONS.md`, same date):
  - images `cr-infra-bake2`, `cr-waf-bake3`, `cr-target-bake2` baked from
    `restructure`, and `cr-kali-bake2`, whose role files match
    `restructure`'s;
  - the platform VM replaced from `restructure` with a fresh database, as
    stack `cr-platform2`; the pool converged;
  - `docs/OPENSTACK.md` §3.7-§3.10 checks 39 of 39 passed;
  - probes recorded, board 18 of 18 and corp 7 of 7, committed;
  - the final full `bin/verify` with acceptance: 101 passed, 0 failed.
- On 2026-11-24:
  - `bin/cloud up --replace` ran end to end on `cr-platform2` (exit 0,
    12 min) after two fixes: it refuses before deleting a stack whose
    network holds another server's port, and the store restore stops the
    `rebuild` service too;
  - the third kali bake passed as `cr-kali-bake3`, from `restructure`; a
    second replace (exit 0, 29 min 32 s) put every slot on it;
  - probes recorded again on that range, board 18 of 18 and corp 7 of 7
    (not committed: the committed set of 2026-11-23 stays);
  - the full `bin/verify` with acceptance on that range: acceptance 99
    passed and 2 errors (`test/test_block_everything.py`, both at setup: no
    board slot came free within the 1800 s room wait while 15 processes
    shared three board slots), the unit and API suites green; that module
    alone then passed 2 of 2;
  - one Player vs AI round per matchup ran with Claude Code as the bot
    (round 143 `def_vs_bot`, round 144 `atk_vs_bot`, board): no objective
    lost in either, TP/FP/FN/TN 9/0/0/66 and 6/0/0/84; the defence bot
    applied two WAF versions, spent the attack's first origin by `deny` and
    reloaded the IDS from its terminal.
- The run's product fixes: the attack API's body limit 256 KiB, the
  traversal case's path, the offline IDS test's `--runmode single`, the jump
  host in terminal grants, the declaration file's path.

## Not live-verified

A captured learner walk, a live review round with zero countable findings,
a docs review, the edge sets after an infra reboot. The list is in
`docs/STATE.md` "Not live-verified".

## Blockers for the user

- **The name `cr-platform`.** Heat's abandon ran (an admin turned it on)
  and `cr-platform`'s network and router were renamed `cr-dev`, but the
  abandoned stack's record stays (`DELETE_COMPLETE`, with its four resource
  rows), so Heat refuses a new stack of that name and `bin/cloud up
  --replace` under it stops, naming `cr-dev` (`docs/OPENSTACK.md` §5.3).
  An admin removes that record from Heat's database; until then the
  platform runs as `cr-platform2`, which works.

## Next, in order

1. The blocker above, when an admin can.
2. An infra and a waf bake to carry the Korean reload refusals; the
   launcher should stop a bot's child process when its round ends (the
   platform marks the run ended, the child runs to `CR_BOT_RUN_SECONDS`).
   Left from the sweep's tester findings: the corp round starts with the
   board's IDS rules (no corp case alerts in the IDS test), the site pane
   is blank for about 6 s on first open, the Kali MOTD prints twice, the
   debrief and the result page can disagree on pending for a few seconds,
   a staff problem edit's leave warning does not cover the back button,
   Kibana's own English UI and its refused internal calls.
2. A kali bake for `deploy/kali/operator-log.sh`.
3. The attack bot still meets 2 refusals a run on Sonnet and Opus 5.5
   and goes on; it took no objective in rounds 310 and 311.
4. A platform read now and then takes over 5 s with three rounds at once
   (the watch skips that check); the ingest inside each read is the
   suspect (`docs/STATE.md` "Open points").
5. Round 406's `ground_truth_unavailable` (2026-11-27, slot 1) is not
   explained: the platform did not log why; it now logs the reason a
   round did not start, so the next one is readable.
6. A captured walk as a learner, a live review round with zero countable
   findings, a docs review.
8. External learners, the last task of the Player vs AI work: the
   public-IP forwards (UDP 51820-51919, TCP 2222, the console) and
   `CR_VPN_HOST`.
9. Gate 2.

## Open points

- The attack bot is Haiku, Sonnet and Opus 5.5 again (DECISIONS 2026-11-25:
  the 2026-11-24 Haiku-only ruling is superseded; those refusals came from
  runs without the range context). The defence bot was not refused on any
  model.
- The bot no longer runs in the repo: the `bots` service starts Claude Code
  from an empty directory with no setting sources, from an image holding only
  `bots/` and the schema (live on 2026-11-25).
- Four acceptance checks read Elasticsearch directly
  (`test/test_event_time.py`, `test_geoip_durable.py`,
  `test_origin_placement.py`, `test_waf_geolocation.py`); the seam scan
  lists them as named exceptions until they move behind `/api/`.
- A round no one calls on does nothing (the late judge included); a polling
  console or bot keeps it moving. The rest is in `docs/STATE.md` "Open
  points".

Written for a session that reaches the cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet.
