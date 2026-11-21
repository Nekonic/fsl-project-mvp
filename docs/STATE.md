# State

The product backlog and the record of where the build stands. The handover to
the next session is `docs/state/now.md`; rulings are in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md` (the spec, cited
below by section). The record of the old tree (`platform/api/`, the console
templates, the scenario course) up to 2026-11-18 is in this file's git
history.

## Where things stand

The product is being rebuilt as a side split on the working branch
`side-split` (user ruling 2026-11-19: no code is kept or migrated; the old
code is reference only). `dev` keeps the old product deployable until gate 2.

The rebuild follows the spec's build order (§16). Steps 1-4, 6-11, 13, 14,
the repo side of 5, step 15 (`nginx.conf`, the terminals and `front/`) and
the code of 16 are built and pass the unit and API suite; `front/` is built
against its mock API only. The bake of 5, step 12 and the live parts of 15,
16 and 17 are not done. Nothing on `side-split` has run on a range.

## What exists on side-split

| Spec step | What exists | Proof that ran |
|---|---|---|
| 1 Ratchet removed | `metrics.json`, `bin/measure` and the ratchet steps are gone | `bin/verify --fast` |
| 2 Old tree cleared | `platform/api/`, `platform/console/`, the scenario and lesson modules and their tests are deleted | `platform/tests/test_old_tree_gone.py` |
| 3 `domain/` | scoring (correlate, metrics, corroborate, objectives), traffic (customer shares, the limit_req floor), verdicts, checks, problems, round_rules | `platform/tests/domain/`, no Django in the process; import rule 1 |
| 4 Seams | `cr/config.py`, `cr/errors.py`, `ingest/elastic.py`, `rules/suricata.py`, `rules/crs.py`, `range/*` (with `edge.py`, `jump.py`, `refill.py` rewritten), `attack/box.py`, `firing.py`, `tools.py`, `defence/kibana.py`, `referee/loot.py`, `effect.py` | `platform/tests/seams/` against fakes; import rules 2, 4, 14; `platform/tests/seams/test_isolation_seams.py`, `test_no_comments.py` |
| 5 Deploy (repo side) | `edge.nft` with `pool` and `spent` and the `spent` drop and the drop of every address outside `pool` before the established accept, the probe lease admitting the origin it wears; the WAF's JSON access log `access.json` shipped and relayed as `nginx-access`, ingested as `nginx_access`; `probe.conf`, `probe-upstream.py`, `analyst.sh`; `conntrack`, `tcpdump` and `/var/lib/cr-ruletest` on the infra; `bin/record-probes`; each round start empties both edge sets (`range.edge.restart`) and the round's end empties them again (`attack.close`); the access log keeps `request_id` only when it has a marker's shape | `tests/test_edge_sets.py`, `test_waf_scratch.py`, `test_access_log.py`, `test_analyst.py`, `test_record_probes.py`, `test_roles.py`, `test_filebeat.py`, `tests/seams/test_edge.py`, `tests/attack/test_spend.py`; structural only, no `nft -c` or `nginx -t` |
| 6 Django skeleton | `cr/` (DRF, spectacular, one handler, `strings.py`), `strings/`, `accounts`, `events` | `tests/accounts` (with the first account `admin` from migration `accounts.0002_first_account`), `tests/events`, the error-shape and no-admin tests |
| 7 `content` | catalog, `wargame.yaml` per wargame, problems as nested documents with revisions and export/import, postures, the learner read API | `tests/content` |
| 8 Round records, referee | `match.models`, `match.auth` (seat tokens hashed, `HasSeat`, `InRound`, `IsOperator`, `OnLease`), `referee` (baseline, loot, effects, objectives, redact, score) | `tests/referee`; import rules 4, 5, 11, 15 |
| 9 `defence` | IDS rules and WAF files read, check, test and apply across sensors, versions with text and hash, a terminal reload recorded on the next read, probes, disable, alerts, traffic, terminal, Kibana gate | `tests/defence` |
| 10 `attack` | state, cases, requests, async tools, loot, origins, terminal, origin loss from the WAF error log (deny and limit_req above the floor), spend at the edge, customer sends | `tests/attack` |
| 11 `match.service` | lease and round lifecycle, follower (`follow` compose service), customers and the benign schedule, site pane, terminal auth routes, score, probe recording, staff range routes | `tests/match`; import rules 6, 7, 9 |
| 13 `lessons` | lesson rounds, facts, judges, progress, hints, `step_locked`, staff try | `tests/lessons` |
| 14 Contract and clients | `openapi/schema.yaml` committed; `bin/gen-clients`; `test/` and `bin/` on the generated client; `bin/backup` and `bin/prune` on the new tables | `tests/contract`; import rule 12; no `/api/sessions` outside docs |
| 15 `nginx.conf` and terminals | per-seat `/vm-terminal/<side>/<round>/` through an uncached `terminal-auth`, the raw-path seat guard, the round passed to ttyd as its only argument, a refused check answered with the API's status and code (`@terminal-refused`, from `terminal-auth`'s `X-Error-Code`); `vm-terminal.sh` (kali as `kali`, cr-waf as `analyst`, only with a jump grant, closed within 15 s once the grant goes); `analyst`'s processes, crontab and `at` jobs ended when the round's defence grant is revoked (`range.jump.end_account`); `/signed-in` on `/api/me/`; the 8002 listener keyed by round, its `@sign-in` sending the learner to `CR_CONSOLE_ORIGIN`'s login with a `next` on `CR_SITE_ORIGIN` (rendered by `python -m cr.config` at start; unset, the asked host's 8000 and 8002 over http), which `Login.tsx` follows only onto that origin's `/site/`; refused Kibana routes answered by the gate; `/app/front/dist` served last, `/assets/` answering 404 for a missing hashed file, `index.html` uncached | `tests/test_front.py` (a config parser and nginx's path normalization replayed), `tests/test_vm_terminal.py` (fake `python`, `ssh`, `tmux`), `tests/attack/test_terminal.py`, `tests/defence/test_terminal.py`, `tests/seams/test_jump.py` (the end script run against fake `crontab`, `atq`, `loginctl`, `pkill`, `pgrep`); no `nginx -t` |
| 15 `front/` | Vite, TypeScript, Preact console in the v4 design: `theme/tokens.css` and `theme/components.css` hold every visual value and class; `ui/` dumb components; `panes/` per spec §13 plus `Loot`, `AttackCases`, `RuleVersions`, each fetching through `api/` hooks; pages as thin arrangements; the three consoles declared as data in `layouts.ts`, routes and top nav as one table each (`routes.ts`, `nav.ts`); text only through `t()` over `strings/console.json`; `api/client.ts` (CSRF renewal, 90 s timeout, slot wait), `api/follow.ts` (one events cursor reading the whole backlog, per-lease heartbeat); a dev-server mock API (`front/mock/`); the Dockerfile's node stage (`npm run types`, `npm run build`) and `front`, `strings`, `openapi` in `images.yml` sources; `bin/verify` builds and tests `front/` | `npm run build`, `npx vitest run` (client, follow cursor, panes, the lobby holding an open lease until it leaves, Korean guards, no `server.json` key in the bundle); every route captured at 1440 and 390 against the mock and compared with the v4 mockups; `docker buildx` of the platform image and `nginx -t` inside it, not pushed |
| 16 `bots/` (code) | `tools.py`, `calls.py`, `cli.py`, `play.py`, `provider.py`, `signin.py`, the side prompts and the README | `platform/tests/test_bots.py` |
| 17 Docs | README, ARCHITECTURE, CLAUDE.md, this file and `now.md` describe the new layout | this step |

## Not live-verified

Every row above ran against fakes only. In particular, none of these has run
on a slot:

- the rule test on a sensor and on cr-waf (`rules.suricata.offline_test`,
  `rules.crs.scratch_check` and `scratch_test`), and that it leaves the live
  alerts and ground truth unchanged (`test/test_rule_test_isolation.py`);
- apply across sensors with rollback; WAF files applied with nginx -t, reload and rollback, and a reload done in the terminal recorded as the next version
  files;
- the origin spend from the WAF error log after a defender's nginx deny, the
  drop at the infra edge cutting a keep-alive connection, customers surviving
  the spend, and a CRS 403 spending nothing (`test/test_origin_spend.py`,
  `test/test_block_everything.py`);
- jump grants on the platform sshd and the per-seat key in the box account,
  for kali and for `analyst` on cr-waf;
- the follower on a live range (refill, expiry, ingest, effects);
- `bin/cloud up` and `down` through the new staff range routes;
- one round of each matchup with Claude Code driving the bot seat
  (`test/test_bot_rounds.py` drives the seats through the generated client,
  not through a model);
- the ported acceptance suite as a whole (`test/`);
- `nginx -t` on `platform/nginx.conf` and `nft -c` on `edge.nft` (Docker was
  not running on the development machine), the ttyd `?arg=` handoff, the
  terminal's ssh running in the background beside its recheck loop with a
  real terminal, and the `analyst` account on a baked WAF.

## Next steps, in order

1. **`front/` on a range** (spec step 15): built in the approved v4 design
   against the mock API only. Left: run it against a live platform, with
   the per-seat terminals (`nginx.conf`, `vm-terminal.sh`), the 8002 site
   listener and the Kibana pane, none of which has run on a range.
2. **Cloud step 5, the rebake**: the repo side is written and tested
   offline: `edge.nft` with the `pool` and `spent` sets and the `spent` drop
   before the established accept; `board.com.conf` with one `$refused` map
   (400, 403) and the JSON access log of every request
   (`/var/log/nginx/access.json`); `log-shipper.conf` and `log-relay.conf`
   carrying it as `nginx-access`; `filebeat.yml` and `ingest-pipeline.json`
   routing it to `nginx_access`; `probe.conf`, `probe-upstream.py` and
   `analyst.sh` on the WAF role; `conntrack`, `tcpdump` and the offline rule
   test's scratch folder on the infra role. Left: bake `cr-infra-bake2` and
   `cr-waf-bake3`, name them in `compute.images`, `bin/cloud up --replace`,
   and the step's checks on a slot (`docs/OPENSTACK.md` §3.7).
3. **The customers' rebake**: benign traffic runs on the infra now
   (`cr-customers.service`, the dummy link `customers`). Left: bake
   `cr-infra` and `cr-kali` again, name them in `compute.images`,
   `bin/cloud up --replace`, and the checks of `docs/OPENSTACK.md` §3.8.
4. **The board secret's rebake**: each round's start sets fresh board
   passwords with the board's `set_passwords`. Left: bake `cr-target` at a
   commit whose `cr-board` image has the command, name it in
   `compute.images`, `bin/cloud up --replace`, and the check of
   `docs/OPENSTACK.md` §3.9.
5. **Cloud step 12, probe recordings**: `bin/record-probes board` and
   `bin/record-probes corp` through the staff route on a probe lease; copy
   the platform's `CR_PROBES_OUT/<id>/probes/` into `wargames/<id>/probes/`
   and commit it (`docs/OPENSTACK.md` §3.7). Until the board's manifest is
   committed, `test/test_rule_test_isolation.py` fails: it requires
   `board-sqli-search` to be replayed by both rule tests.
6. **Full live verify**: the full `bin/verify` with acceptance on the range,
   the Claude Code bot round of each matchup (spec step 16), a captured walk
   of every page as a learner, a live review round with zero countable
   findings, and a docs review.
7. **Gate 2**: present what changed with the evidence; on approval, move the
   verified, tagged state onto `dev` and then `main`.

## Open points

- **Acceptance checks that read Elasticsearch directly.**
  `test/test_event_time.py`, `test/test_geoip_durable.py`,
  `test/test_origin_placement.py` and `test/test_waf_geolocation.py` query
  Elasticsearch's ingest pipeline, node settings and index on
  `localhost:9200` rather than through `/api/`. The seam scan lists them as
  named exceptions (CLAUDE.md); moving them behind an API route or into
  `ingest/elastic.py` is open.
- **A refused key leaves a jump grant.** If the box refuses the per-seat
  key, `range.jump.open_access` keeps the platform sshd grant until the
  round ends. Without the box key it gives no access.
- **Mockup fields the API does not send.** User names on seats and the round
  bar (`SeatLine`, `Me`), a past round's end and result, a lesson's step
  counts, the lease's opening time, a CRS preview, case and objective
  catalogs for the staff editor, and coded slot and server failures.
- **Screens not yet one file to change.** The map icons
  (`panes/map-symbols/node-*.svg`) and `panes/Map.tsx`'s cytoscape style
  do not use the tokens; a layout cannot put two panes side by side in the
  main area; the aside's first pane takes the `aside-lead` look; verdict
  labels are repeated across several `console.json` values; verdict tones
  differ between `Score` and `RuleTestTable`.
- **Two runtime guesses in the rule test.** Whether `jasonish/suricata`'s
  entrypoint lets the offline `-r` run write to the root-owned scratch log
  folder mounted at `/scratch`, and whether the scratch ModSecurity
  instance's audit log is opened by the root master (its workers could not
  write it), are not known until a slot runs them.
- **The comment scan reads code only.** `test_no_comments.py` covers
  Python, shell and TS/TSX/JS; config and data files are not scanned, and
  `wargames/board/traffic.yaml` carries a comment block from before the side
  split.
- **`bin/carry-users` mid-load.** If `loaddata` fails after the migrated
  `admin` was deleted, the new store has no `admin` until the command is run
  again, which recovers it.
- **Generated clients outside `bin/verify`.** The platform Dockerfile's node
  stage generates only `front/src/api/schema.d.ts` (`npm run types`), not
  `bin/gen-clients`; the platform image needs no Python client.
- **No route serves the probe recordings.** `match/probes.py` writes them to
  the platform's `CR_PROBES_OUT`; they are copied off the platform VM by hand
  before they are committed.

## Decisions left for a person

- **What the lessons and rounds teach.** The old lessons F1-F6, courses c1
  and c2 and scenarios 1.1-4.1 are deleted with no replacement. Problems are
  authored as database rows through the staff API (and the staff page once
  `front/` exists); which lessons come first and which rounds follow is not
  decided.
- **Two licences behind the origins and the map.** MaxMind's GeoLite EULA
  asks for old databases to be deleted within 30 days of a new release and
  for the line "This product includes GeoLite Data created by MaxMind". For
  the MVP the user took the lightest path (2026-10-02): the `.mmdb` is not
  committed, `bin/fetch-geoip` pulls it and `config/ingest-geoip/README.md`
  carries the attribution. Whether to carry the database and that obligation
  into the production repo, and the 30-day refresh, is still open.
  Cloudflare Radar's shares are CC BY-NC 4.0, fine here, to be looked at
  before they move to the production repo.
- **Board secret between rounds on one lease.** Until it is known whether
  the board secret can rotate without a rebuild, `may_start_scored` refuses
  a scored round on a lease where an objective has fallen (spec §17 risk 8).

## Open risks (spec §17)

Unmeasured until a range runs them: offline IDS against the live sensor;
mapping `suricata -T` errors to a line; scratch CRS instance fidelity;
recorded sqlmap pcaps as an IDS preview; error-log loss on the UDP hop (an origin
the defender banned is not spent); spend lag of one read interval plus shipping; forged markers and
customer addresses on a root box; free-action attribution by window; the
follower's single loop under four sqlmap runs; the first Preact build and
the SPA fallback order; whether `analyst` can read the CRS files without
changing the live reload path.

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
  earlier lease on that slot left in `logs-N-*`.
- OpenStack host keys are trust-on-first-use per generation, kept in the
  platform user's home (lost with the container) unless the deployment's ssh
  config says otherwise.

## Tried and thrown away

- **The scenario engine, triage and debrief** (removed 2026-11-19 with the
  side split): two kinds of play remain, a guided lesson and a live round.
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
