# State

The product backlog and the record of where the build stands. The handover to
the next session is `docs/state/now.md`; rulings are in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md` (the spec, cited
below by section). The record of the old tree (`platform/api/`, the console
templates, the scenario course) up to 2026-11-18 is in this file's git
history.

## Where things stand

The product was rebuilt as a side split on `side-split` (user ruling
2026-11-19: no code is kept or migrated; the old code is reference only), and
then restructured on the working branch `restructure` (ruling 2026-11-21,
"The platform is restructured into five units, KYPO-style"). `dev` and
`main` still hold the old product until gate 2, but the cloud now runs
`restructure`: on 2026-11-23 its first range was built and checked
(`docs/DECISIONS.md`, "The first cloud check of `restructure`").

- **Images.** `cr-infra-bake2`, `cr-waf-bake3`, `cr-target-bake2`, baked from
  `restructure`, and since 2026-11-25 `cr-kali-bake4`, baked from `bot-rounds`
  (the learner tunnel: `wireguard-tools`, `ip_forward`, `set-peer`). Two kali
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
  restore (the `rebuild` service is now stopped with the platform), with the
  slot stacks standing through; and exit 0 in 29 min 32 s with
  `cr-kali-bake3`, every slot built again. The pool (`board: 3`, `corp: 1`)
  converged.
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

## What exists on restructure

The side-split build (the spec's steps 1-17, recorded in this file's git
history) is carried into five units. The proofs named in each row run
against fakes; on 2026-11-23 the acceptance suite also ran the whole table on
a live range and passed.

| Stage | What exists | Proof that ran |
|---|---|---|
| Five units | `users/`, `sandbox/` (every file that knows an outside device), `telemetry/`, `training/` (one app: `content/`, `round/`, `traffic/`, `attack/`, `defence/`, `lessons/`), `scoring/`; `cr/`, `domain/`, `testing/` shared; fresh `0001` migrations (`users` keeps `0002_first_account`) | `platform/tests/seams/test_imports.py` (no import from a higher layer, unit surfaces), `test_isolation_seams.py` (the exception list is the one CLAUDE.md gives); `openapi/schema.yaml` regenerated byte-identical to the schema before the move |
| Names | Seat is `Player`, Lease is `Allocation`: models, fields, routes (`/api/allocations/`, `/players/<side>/join/`), events (`player.joined`), error codes, `CR_PLAYER_TOKEN`, `CR_ALLOCATION_IDLE_MINUTES`, tables in `bin/backup`, the console's 플레이어 | unit and API suite, `front/` vitest |
| No tick | round reads run on the round's API requests (`training/round/views_catch_up.py`, `lifecycle.catch_up`, one reader per round through `Round.reading_since`, `CR_READ_EVERY_SECONDS`); the `follow` service is now `rebuild` (`manage.py rebuild_slots`); `ended` is `min(now, ends_at)` and the score counts up to it; a round ended by the operator, a forfeit or allocation expiry reads the logs once more first, waiting for a read another request holds; a reader releases only its own claim and stops once the round has ended, and a request reads a round before it closes an expired allocation | `tests/training/round/test_catch_up_and_score.py`, `tests/training/round/test_lifecycle.py` |
| Origin loss | HP is gone; an origin is spent by an nginx `deny` or a `limit_req` at or above the floor in the WAF error log (`training/attack/origins.py`, `telemetry/access.py`, `domain/traffic.py`), judged by the WAF version in force when the line was written; `limit.below_floor` warns the defence, and a zone keyed by anything but the client address spends nothing and warns once (`limit.shared_key`) | `tests/training/attack/test_origin_loss.py`, `tests/domain/test_traffic.py`, `tests/telemetry/test_refusals.py` |
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
| Player vs AI rounds (branch `bot-rounds`, gate 1 of 2026-11-24) | three difficulty steps (`training/content/steps.yaml`; attack and defence bot Haiku/Sonnet/Opus 5.5 at steps 1/2/3); attack cards A1-A8 (`cards.yaml`, one ATT&CK id each, drawn at random per round, shown only in the debrief); the `bots` compose service launches Claude Code behind a per-run relay that holds the token, pace and allowance; bot runs, notes, round records kept 90 days, the debrief, the bot-vs-bot baseline started from the problem editor and the percentile; one WireGuard profile per account attached to the human attack seat's kali (`sandbox/vpn.py`, kali `set-peer`); attribution by origin (WAF access-log requests from the round's attacker origins are the attacker's free actions); console: lobby step picker, debrief, records, access page, staff card and step choice and baseline panel | the unit tests of spec §17, `front/` vitest and build; live on 2026-11-25 ("Where things stand") |

## Not live-verified

What ran on the range on 2026-11-23 and 2026-11-24 is under "Where things
stand". Still not run on a range:

- one `pvp` round, and a round that loses an objective (neither bot round
  did, so the response mark and the double count have not run live);
- a captured walk of every page as a learner, against the live platform;
- a live review round with zero countable findings, and a docs review;
- the edge's `pool` and `spent` sets after a reboot of the infra
  (`docs/OPENSTACK.md` §3.10, last check);
- by hand: the IDS reload's refusal of `config: logging` and the WAF
  wrapper's refusal of an `access_log off` written during a reload
  (`docs/OPENSTACK.md` §3.10);
- `bin/cloud up --replace` under the stack name `cr-platform` (it ran as
  `cr-platform2`; under `cr-platform` it stops before deleting anything,
  §5.3); `bin/cloud down`;
- of the Player vs AI build: a `def_vs_bot` round the attack bot plays to
  the end (it was refused or stopped tonight), a loss with response O (the
  defence spent the origin before the loss), the learner's UDP reach, and
  three rounds at once without SQLite lock errors;
- the rulings of 2026-11-22 and 2026-11-23 not built yet (five attack
  origins, more benign kinds, Internet scanners, the board's attack paths,
  the response replay of the attack's own logged requests).

## Next steps, in order

1. **The name `cr-platform`** (an admin): remove the abandoned stack's
   record from Heat's database, then one replace under that name
   (`docs/OPENSTACK.md` §5.3).
2. **The platform under several rounds** (found 2026-11-25): SQLite locks,
   `joined_later`'s per-join UPDATE, rule applies holding the write lock over
   ssh, and free actions read from Elasticsearch at scoring time.
3. **One `pvp` round, and a loss with response O**.
4. **A captured walk of every page as a learner**, then a live review round
   with zero countable findings and a docs review.
5. **Gate 2**: present what changed with the evidence; on approval, move the
   verified, tagged state onto `dev` and then `main`.

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
  Whether a run that falls back is still step 3 is the user's call.
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
  per Suricata join; it now reads a page's flows once (not yet run on the
  range). Still open: `apply_waf` and `apply_ids` keep the write transaction
  open while they reach the WAF or the sensor over ssh.
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
  key, `sandbox.access.open_access` keeps the platform sshd grant until the
  round ends. Without the box key it gives no access.
- **Mockup fields the API does not send.** User names on players and the
  round bar, a past round's end and result, the allocation's opening time, a CRS preview, case and objective
  catalogs for the staff editor, and coded slot and server failures.
- **Screens not yet one file to change.** Verdict tones differ between
  `Score` and `RuleTestTable`; some cytoscape widths and margins in
  `panes/Map.tsx` and the SVG stroke widths are still numbers in code.
- **One case, many firings.** A benign case fires on every pass of the
  customers, and the score lists one line per firing, while CLAUDE.md counts
  one case as one decision. The acceptance harness reads a case as detected
  when any firing drew an alert. The user has not ruled
  (`docs/DECISIONS.md`, 2026-11-23).
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
  comments and are not scanned: `redteam/cases/board.yaml`,
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
  committed, `bin/fetch-geoip` pulls it and `config/ingest-geoip/README.md`
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
customer addresses on a root box; free-action attribution by window; reads
on request keeping up under four sqlmap runs; the first Preact build and
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
