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

The rebuild follows the spec's build order (§16). Steps 1-4, 6-11, 13, 14 and
the code of 16 are built and pass the unit and API suite; steps 5, 12 and 15
and the live parts of 16 and 17 are not done. Nothing on `side-split` has run
on a range.

## What exists on side-split

| Spec step | What exists | Proof that ran |
|---|---|---|
| 1 Ratchet removed | `metrics.json`, `bin/measure` and the ratchet steps are gone | `bin/verify --fast` |
| 2 Old tree cleared | `platform/api/`, `platform/console/`, the scenario and lesson modules and their tests are deleted | `platform/tests/test_old_tree_gone.py` |
| 3 `domain/` | scoring (correlate, metrics, corroborate, objectives), ledger, verdicts, checks, problems, round_rules | `platform/tests/domain/`, no Django in the process; import rule 1 |
| 4 Seams | `cr/config.py`, `cr/errors.py`, `ingest/elastic.py`, `rules/suricata.py`, `rules/crs.py`, `range/*` (with `edge.py`, `jump.py`, `refill.py` rewritten), `attack/box.py`, `firing.py`, `tools.py`, `defence/kibana.py`, `referee/loot.py`, `effect.py` | `platform/tests/seams/` against fakes; import rules 2, 4, 14; `platform/tests/seams/test_isolation_seams.py`, `test_no_comments.py` |
| 6 Django skeleton | `cr/` (DRF, spectacular, one handler, `strings.py`), `strings/`, `accounts`, `events` | `tests/accounts` (with the first account `admin` from migration `accounts.0002_first_account`), `tests/events`, the error-shape and no-admin tests |
| 7 `content` | catalog, `wargame.yaml` per wargame, problems as nested documents with revisions and export/import, postures, the learner read API | `tests/content`; `test_no_hangul.py` |
| 8 Round records, referee | `match.models`, `match.auth` (seat tokens hashed, `HasSeat`, `InRound`, `IsOperator`, `OnLease`), `referee` (baseline, loot, effects, objectives, redact, score) | `tests/referee`; import rules 4, 5, 11, 15 |
| 9 `defence` | rules and posture read, check, test and apply across sensors, versions, probes, disable, drift, alerts, traffic, terminal, Kibana gate | `tests/defence` |
| 10 `attack` | state, cases, requests, async tools, loot, origins, terminal, HP from both sources, spend at the edge, customer sends | `tests/attack` |
| 11 `match.service` | lease and round lifecycle, follower (`follow` compose service), customers and the benign schedule, site pane, terminal auth routes, score, probe recording, staff range routes | `tests/match`; import rules 6, 7, 9 |
| 13 `lessons` | lesson rounds, facts, judges, progress, hints, `step_locked`, staff try | `tests/lessons` |
| 14 Contract and clients | `openapi/schema.yaml` committed; `bin/gen-clients`; `test/` and `bin/` on the generated client; `bin/backup` and `bin/prune` on the new tables | `tests/contract`; import rule 12; no `/api/sessions` outside docs |
| 16 `bots/` (code) | `tools.py`, `calls.py`, `cli.py`, `play.py`, `provider.py`, `signin.py`, the side prompts and the README | `platform/tests/test_bots.py` |
| 17 Docs | README, ARCHITECTURE, CLAUDE.md, this file and `now.md` describe the new layout | this step |

## Not live-verified

Every row above ran against fakes only. In particular, none of these has run
on a slot:

- the rule test on a sensor and on cr-waf (`rules.suricata.offline_test`,
  `rules.crs.scratch_check` and `scratch_test`), and that it leaves the live
  alerts and ground truth unchanged (`test/test_rule_test_isolation.py`);
- apply across sensors with rollback, and drift detection on the live CRS
  files;
- the HP charge from the WAF access log, the spend at the infra edge cutting a
  keep-alive connection, and customers surviving the spend
  (`test/test_hp_spend.py`, `test/test_block_everything_hp.py`);
- jump grants on the platform sshd and the per-seat key in the box account,
  for kali and for `analyst` on cr-waf;
- the follower on a live range (refill, expiry, ingest, effects);
- `bin/cloud up` and `down` through the new staff range routes;
- one round of each matchup with Claude Code driving the bot seat
  (`test/test_bot_rounds.py` drives the seats through the generated client,
  not through a model);
- the ported acceptance suite as a whole (`test/`).

## Next steps, in order

1. **`front/` in the design the user picks** (spec step 15): the typed
   console and the Dockerfile's node stage. `platform/nginx.conf` already
   serves `/app/front/dist` last with the `index.html` fallback, hands
   `/vm-terminal/<side>/<round>/` to the side's ttyd after `terminal-auth`,
   and keys the 8002 listener by round; `platform/vm-terminal.sh` opens kali
   as `kali` and cr-waf as `analyst` for a seat holding a jump grant. Neither
   has run on a range. The user chooses the design before it is built
   (gate 1).
2. **Cloud step 5, deploy changes and rebake**: `edge.nft` with the `pool`
   and `spent` sets and their drop rules before the established accept;
   `board.com.conf` with one `$refused` map (400, 403) and the JSON access log
   of every request; `log-shipper.conf` shipping it as `nginx-access`;
   `filebeat.yml` and `ingest-pipeline.json` routing it to `nginx_access`;
   `probe.conf`, `probe-upstream.py` and `analyst.sh` on the WAF role; then
   bake new infra and waf images (`docs/OPENSTACK.md`). None of these files
   is changed yet.
3. **Cloud step 12, probe recordings**: `bin/record-probes board` and
   `bin/record-probes corp` through the staff route on a probe lease; commit
   `wargames/<id>/probes/`. `bin/record-probes` does not exist yet.
4. **Full live verify**: the full `bin/verify` with acceptance on the range,
   the Claude Code bot round of each matchup (spec step 16), a captured walk
   of every page as a learner, a live review round with zero countable
   findings, and a docs review.
5. **Gate 2**: present what changed with the evidence; on approval, move the
   verified, tagged state onto `dev` and then `main`.

## Open points

- **Acceptance checks that read Elasticsearch directly.**
  `test/test_event_time.py`, `test/test_geoip_durable.py`,
  `test/test_origin_placement.py` and `test/test_waf_geolocation.py` query
  Elasticsearch's ingest pipeline, node settings and index on
  `localhost:9200` rather than through `/api/`. The seam scan lists them as
  named exceptions (CLAUDE.md); moving them behind an API route or into
  `ingest/elastic.py` is open.
- **Korean in `docs/DECISIONS.md`.** It quotes the user's rulings in Korean
  (about a hundred lines). `test_no_hangul.py` still allows it by name until
  those quotes are translated.
- **A refused key leaves a jump grant.** If the box refuses the per-seat
  key, `range.jump.open_access` keeps the platform sshd grant until the
  round ends. Without the box key it gives no access.
- **`bin/record-probes`** is in the spec's tree and not written.

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
recorded sqlmap pcaps as an IDS preview; access-log loss on the UDP hop (HP
undercharges); HP lag of one follower tick plus shipping; forged markers and
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
