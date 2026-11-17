# State

The product record: the backlog (what the user wants built, in priority order)
and the finished work, one line each, with the detail in `git log`, `README.md`
and `docs/ARCHITECTURE.md`. The live state of work in flight is in
`docs/state/now.md`, and rulings are in `docs/DECISIONS.md`; the `orchestrate`
skill reads those, not this file. Keep the backlog here true.

Updated: 2026-11-18

## Where things stand

The product is the session-isolated learning MVP (backlog 0, approved
2026-10-08), OpenStack-only since 2026-10-20 (Kolla-Ansible 2025.1 or later,
KVM recommended). The cloud holds two VMs: the platform VM `cr-platform`
(`m1.large`, a checkout of `dev` in `/opt/cr` that pulls every image from
GHCR) and the range host `cr-range` (`dba.range`, 6 vCPU, 16 GB), which runs
slot N as the compose project `sN`, eight slots (`compute.slots: 8`). The
range host pulls the range images at `CR_RANGE_IMAGE_TAG`, so a platform-only
`uv run bin/cloud up --replace` keeps it and takes about 10 min (25 min when a
new range host boots). Both hosts install from `mirror.kakao.com`.

Two courses of foundations, c1 (F1-F3) and c2 (F4-F6), and eleven timed
scenarios on live customer traffic run against two targets, the board
(`board.com`) and WordPress (`corp.com`). A slot is an edge router with one
public IP, the WAF, one Suricata sensor behind it on the web segment, a 관제망
with its log server, and the wargames; the learner map draws that wiring.
Every surface signs in; a learner signs up for an admin's approval and sees
only their own sessions. Answer-blind walk round 27's fixes are live on the
platform VM with the full `bin/verify` green; from round 29, interim rounds
re-check only the fixed items (`docs/DECISIONS.md` 2026-11-18). The live
state and the latest `bin/verify` numbers are in `docs/state/now.md`;
`bin/measure` prints the metrics against `metrics.json`.

## What exists now

The shape of the product; detail is in `git log` and `docs/ARCHITECTURE.md`.

- **Range**: per slot, an Internet segment (`internet`) with thirty declared
  origin countries on Kali, the DMZ (`estate`: the edge router's `lan` and the
  WAF), the web segment (`web`: the WAF and the web servers), each wargame's
  database network, and the 관제망 (`mgmt`: the sensor, the WAF's management
  interface and the log server). The edge router's `wan` holds one public IP,
  121.134.88.42/29; Kali resolves `board.com` and `corp.com` to it, the edge
  forwards tcp 80 to the WAF (DNAT, no SNAT) and from `wan` passes only
  replies and that forwarded port, so Kali reaches the targets only through
  the router's public IP and the WAF (`docs/ARCHITECTURE.md`).
- **Red team**: one Kali image, driven from the red console's terminal in a wargame or the
  blue console's Kali pane in a lesson or scenario; the
  cases stay for the API, the harness and the scenario engine's attacker; each
  case carries a Mandiant stage, ATT&CK/CAPEC ids, and what it takes.
- **Two targets.** A Django board on MySQL behind the WAF as `board.com`
  (Django 3.2.4, the `?sort=` order_by SQLi): `loot_verified`, the attacker
  submits exfiltrated `auth_user` hashes and the platform checks them against
  the snapshotted ground truth. A WordPress site behind the WAF as `corp.com`
  (three pinned-version CVEs, `wargames/corp/`): `effect_observed`, scored
  from `corp-db`'s own MySQL binary log. Each wargame is one folder,
  `wargames/<id>/`; the top `compose.yaml` does not include them but mounts
  `./wargames` read-only into the platform, and `range/rangehost.py`
  (`compose`) renders each wargame's `compose.yaml` into every slot's compose
  project. `board` holds the board and its MySQL, `corp` the WordPress site
  and its MySQL. `test_compose.py` holds the folders and the console's
  catalogue to each other.
- **Score**: objectives (exfiltrated data or observed effect, checked against
  the target's own records) beside detection TP/FP/FN/TN with the
  `corroborated` gate; one case is one decision whatever its alert count; a
  scenario with `detected_by` (3.1-3.4: `suricata`) counts only that
  detector in its cases, objectives' detected flag and customer FPs;
  `platform/game.py` also computes a zero-sum balance, withheld until close
  (backlog 1, partly superseded).
- **Console**: the landing page `/` (sessions), a red console (objectives,
  loot submission, Kali terminal, Website pane) and a blue console that is a sidebar framing Kibana, a WAF
  terminal, a Website pane (site browser with developer tools), the Map
  pane (the slot's live wiring, drawn by the console) and, below a divider in lessons and scenarios, the Kali
  pane; the Alerts and IDS rules panes show where a scenario or F4 uses them;
  the course's coach steps through each foundation and stepped scenario, with
  a hint ladder whose last rung is Skip (it did the step for the learner until
  2026-10-17); light theme, every value escaped. The request-path view on the
  map was removed on 2026-10-16. The blue dashboard, Live view,
  scoreboard tab, rule editor and world map were removed on 2026-10-05, and the
  pfSense GUI pane on 2026-10-08.
- **Course**: `wargames/board/scenario.yaml` declares foundations F1-F6 in
  two courses, c1, log analysis basics (F1-F3), and c2,
  attack detection practice (F4-F6), each with a briefing and a reference
  column (47 steps; `platform/lesson.py` judges each
  step from range and request facts, with a ladder nudge, a hint and Skip) and
  eleven scenarios 1.1-4.1 (`platform/scenarios.py`, `api/scenario_run.py`: a
  scheduled automated attacker over customer traffic from `api/customers.py`
  and `traffic.py`, judged at a final check).
- **Stack**: every service `linux/amd64`. On the platform VM,
  `cr-platform.service` runs `docker compose pull` and `up -d` for the
  control plane (the platform entrypoint registers the ingest pipeline). The product is OpenStack-only since 2026-10-20; the
  docker substrate (`platform/range/docker.py`, `session.yaml`) was removed on
  2026-10-21.
- **Platform VM**: `deploy/openstack/platform.yaml` boots the whole stack on
  the OpenStack cloud as one Heat stack.
- **The range on OpenStack**: the platform builds the `mgmt` network and the
  range host `cr-range` through `/api/range/fabric/` and `/slot/`, and runs
  each slot on it as a compose project (Kali, the nftables edge, the WAF, one
  Suricata sensor, the log server and its shippers, and the wargames' GHCR
  containers) through `/configure/`,
  reaching the range host over ssh on `mgmt`. Until 2026-11-13
  each slot was four VMs (the OPNsense edge, the WAF, Kali and
  `cr-wargame-host`) built from golden images. Eight slots on the current cloud
  (`compute.slots: 8`) since 2026-11-15; four from 2026-11-13, two from 2026-10-21.
- **Monitoring per slot** (2026-11-16): one Suricata sensor per slot sniffs
  the web servers' segment behind the WAF (`web` on `sN-web`, `tc mirred`
  SPAN, no address) and stands on the slot's 관제망 `sN_mgmt`, where a log
  server takes the sensor's log and the WAF's two (ModSecurity's audit log
  and nginx's own refusals), each shipped from its own network namespace, and
  forwards them to the platform collector. An IDS alert is credited to the
  X-Forwarded-For address of its transaction. The live map draws the slot's
  real subnets, switches and interfaces.

## Backlog

The range is a web-entry range for now: attacks that come in through the
application, such as taking data out of a database. A foothold, privilege
escalation and persistence are a later goal, not this list's (decided
2026-09-28; `docs/THREAT-MODEL.md` already says so). More targets (a Java
system) plug in where the board and corp did. Items 2 (the range on
OpenStack) and 3 (the corp target) are finished.

### 0. The composable, session-isolated learning MVP (current, approved 2026-10-08)

Spec: `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`;
the course: `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`;
rulings in `docs/DECISIONS.md`; build state in `docs/state/now.md`.

- [ ] Scenario 4.2 (a person as the red team) is not declared; the engine
      accepts `red: person`. Needs a second person to run live.
- [ ] A corp scenario (what a WAF cannot see) is not built: corp's CVEs
      succeed but it has no customer traffic; it needs a generator for
      WordPress first.
- [ ] The intermittent `test_corp_*` nonce error (twice, passing on rerun):
      corp's healthcheck now waits for its forms and pages (2026-10-21) and
      every full run since passed without it, but an intermittent error is not
      proven gone.
- [ ] Acceptance run time: about 8-10 min on eight slots (488 s across 12
      processes on 2026-11-16; `docs/state/now.md` has the latest). The
      floor is ingest re-reading the whole window per `POST /ingest/` and the
      slot reset; more slots would shorten it.
- [ ] Suricata XSS coverage is URI-only: sid 9000003 inspects `http.uri`, so
      `board-xss-img-onerror-in-comment` (a form body) is WAF-only in the
      shipped rules. Decide whether to add a `http.request_body` XSS rule
      (changes the detection score) or keep it WAF-only; scenario 3.4 has the
      learner write that rule, which must match the URL-encoded body (`%3D`).
- [ ] Note, not a bug: `board-sqli-orderby-sqlmap` evades both engines on a
      clean exploit (the dotted ORDER BY payload has no SQLi grammar); only
      sqlmap's stock probes are caught. It is the "hard to detect" case.
- [ ] The attacker image on OpenStack resolves from an env var
      (`CR_TOOL_IMAGE`, written by the platform VM's cloud-init) rather than
      from the substrate in code; decide which.
- [ ] Seam exceptions: move the code or keep them recorded (the list is in
      `CLAUDE.md` and `docs/ARCHITECTURE.md`).

### 1. The scoring redesign (partly superseded 2026-10-08)

Design in `docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`.
Superseded on 2026-10-08 (`docs/DECISIONS.md`): the learner sees PASS/FAIL and
plain-language diagnostics, not the four pillars or a balance. `game.py`
settles the four pillars into one balance, withheld until close; the response
pillar stays absent until a case is blocked (`meta["blocked"]`).

- [ ] Turn blocking on: record which cases were blocked, read from the target
      side (the blue team turns blocking on itself, in the WAF's mode).
- [ ] Weights and dwell in `game.py` are v1 defaults (`WEIGHTS`,
      `FAST`/`SLOW`, `DETECTED_TAKE`); tune once the console shows them.

### 4. Left by the container range (2026-11-13)

- [ ] A real firewall product at the edge (OpenWrt with LuCI is the
      candidate), for a future corp or DMZ lesson that teaches a firewall's
      own screens; the edge is an nftables router container until then (the
      user's ruling, `docs/DECISIONS.md` 2026-11-13).
- [ ] The corp WordPress install sends its pretty-permalink loopback test to
      the real `corp.com`; the slot maps `corp.com` to 127.0.0.1 inside
      `corp-wp` because the slot has no egress. Make the image's install not
      depend on a request to its public name.
- [ ] MySQL `performance_schema=OFF`: the two MySQL containers are the
      largest share of a slot's memory, and memory is what caps the slots a
      range host holds.

### 5. Left by the hardening (2026-11-15)

- [ ] `admin` / `123456` is never forced to change (the user's ruling). The
      sign-in limits of 2026-11-16 slow guessing; they do not help against a
      default anyone can read. A password change is
      `manage.py changepassword admin` in the platform container.

### 6. Left to engineering (no decision needed)

- [ ] `no_marker` per engine, without warning on raw-TCP-only sessions. Needs
      an engine field on `DetectionRecord` and app-layer presence carried
      through the ingest seam, which raises gated `core_loc`.
- [ ] A tool killed on the attacker when its timeout passes (touches the
      attacker seam).
- [ ] `logs-*` expire after 30 days, with a disk warning (an ES ILM policy).
- [ ] The ratchet counts statements with the baseline from `HEAD`, and
      `scoreboard.py` moves into core. This redefines the gate and raises
      `core_loc`, so it is a decision, not pure engineering.

### 7. Decisions left for a person

- [ ] Two licences behind the origins and the map. MaxMind's GeoLite EULA
      asks for old databases to be deleted within 30 days of a new release
      and for its attribution line; for the MVP the `.mmdb` is not committed,
      `bin/fetch-geoip` pulls it and `config/ingest-geoip/README.md` carries
      the attribution (2026-10-02). Whether to carry the database and the
      30-day refresh into the production repo is left. Cloudflare Radar's
      shares are CC BY-NC 4.0, to be looked at before they move there.

## Finished

One line each; the detail is in `git log` and `docs/DECISIONS.md`.

- [x] 2026-10-01: the platform VM boots the stack as one Heat stack.
- [x] 2026-10-01: the fabric from the platform through the API: thirty origins, `estate`, `mgmt`.
- [x] 2026-10-01: the targets and the WAF as golden-image VMs, the platform on `mgmt`.
- [x] 2026-10-02: the pfSense edge with Suricata, and a Kali attacker wearing any origin, scored end to end.
- [x] 2026-10-02: the target port unpublished; acceptance and CLI cases fire from inside the range.
- [x] 2026-10-02: evidence selected by event time; GeoIP read once from a bind mount.
- [x] 2026-10-02: the over-reach audit: 23 of 26 items removed; `wargame_services` split from `services`.
- [x] 2026-10-03: session Start/Stop with the READY gate and the canary.
- [x] 2026-10-04: the objective model: the board is `loot_verified`; Juice Shop and the wiki removed.
- [x] 2026-10-04: sub-project B: WordPress `corp`, three pinned CVEs, `effect_observed` from its binlog.
- [x] 2026-10-05: the blue console is a sidebar framing Kibana; the custom dashboard removed.
- [x] 2026-10-07: `bin/verify` refuses to run while a session is open.
- [x] 2026-10-08: the pfSense pane and the `:8080` proxy removed.
- [x] 2026-10-08: the session page's confirm-close posts `/ingest/`.
- [x] 2026-10-08: the CLI harness opens the session of the scenario matching `--cases`.
- [x] 2026-10-08: tool cases on OpenStack ssh to Kali over `mgmt`.
- [x] 2026-10-09: `POST /attacks/` SNATs to the requested origin before firing.
- [x] 2026-10-09: corp cases fire real exploits through the harness's nonce `prefetch`.
- [x] 2026-10-09: readiness and the baseline read the board's ground truth from the board host.
- [x] 2026-10-10: MVP build steps 1-8, live acceptance green on the acceptance VM.
- [x] 2026-10-10: each session's sensor gets its own rule file.
- [x] 2026-10-10: the blue WAF terminal connects.
- [x] 2026-10-10: spikes closed: Kibana highlight on `data-test-subj`; the CRS starting configuration.
- [x] 2026-10-11: console redesign with the site browser and its Network panel.
- [x] 2026-10-11: the first cloud run of `bin/cloud up|down` and the images step.
- [x] 2026-10-11: OPNsense replaced pfSense at the edge.
- [x] 2026-10-11: the wargames on the range run as GHCR containers on one host image.
- [x] 2026-10-12: WAF tuning on OpenStack names the WAF layout per host.
- [x] 2026-10-12: management fenced from Kali; the edge passes tcp 80 to the WAF only.
- [x] 2026-10-12: two range slots; a sensor on the estate leg; full `bin/verify` on OpenStack.
- [x] 2026-10-13: scenario course P0-P4: foundations F1-F6, customer traffic, the scenario engine.
- [x] 2026-10-14: scenario course P5: every scenario failed a wrong defence and passed a right one, live.
- [x] 2026-10-14: scenario course P6: lessons 0-5 and 7, the rungs and `Session.mode` removed; Package 2 dropped.
- [x] 2026-10-15: UDP syslog drops fixed with a 32 MiB receive buffer.
- [x] 2026-10-15: the learner map as the company network the learner defends.
- [x] 2026-10-16: test audit: test functions 2,061 -> 1,051; `tests` reported, not gated.
- [x] 2026-10-17: every acceptance test runs on OpenStack, none skipped.
- [x] 2026-10-18: foundations run back to back in one session as attack and defence lessons.
- [x] 2026-10-18: the red console is Kali and a browser; the lesson's attack exfiltrates the board's accounts.
- [x] 2026-10-19: foundations review rounds 2-5; `/internal/auth-users` stays as is.
- [x] 2026-10-20: newcomer bring-up rewritten; the §9 one-VM trial ran end to end.
- [x] 2026-10-20: bring-up path fixes: resume checks the hand-over, `down` beside a stopped container, the digest ignores umask and the fixed IP.
- [x] 2026-10-20: `up` after `down` restores the newest backup that holds rows.
- [x] 2026-10-20: the product moved to the new cloud; the old cloud's floating IP dropped.
- [x] 2026-10-21: the docker substrate removed, proven live on the new cloud.
- [x] 2026-10-21: the platform VM rebuilt from GHCR images without `--sideload`.
- [x] 2026-10-21: corp's healthcheck waits for its forms; the corp cases post UM form 5.
- [x] 2026-10-21: found fixed: reachability walks every slot; two simultaneous session opens answer 409.
- [x] 2026-10-21: lesson auto-advance works; the walker was wrong.
- [x] 2026-10-22: a reset cut short by a platform restart resumes at boot.
- [x] 2026-10-22: PL4 and the Korean search measured: 920272 also needs `REQUEST_URI_RAW`.
- [x] 2026-10-22: F4-F6 re-walked, 28 of 28 steps.
- [x] 2026-10-23: tester reports: a root shell keeps the proxy; Kali steps say what is missing.
- [x] 2026-10-23: three lesson-check bugs from the tester report review.
- [x] 2026-10-23: the Kali and WAF terminals fit their pane.
- [x] 2026-10-23: a slot standing through a deploy is rebuilt onto the new images.
- [x] 2026-10-24: the stale-slot rebuild configures only after Nova shows each VM back.
- [x] 2026-10-24: slot reset 288 s -> 70-82 s (side-by-side start, pristine data restore).
- [x] 2026-10-24: the API's `suppression` renamed to disabling (`/api/rules/disabled/`).
- [x] 2026-10-24: F4 step 7 checks that the learner's rule fires.
- [x] 2026-10-24: F4 step 3's coach rings the row that holds the value.
- [x] 2026-10-24: a settling Kali run is not a failure; a long pass text waits for Next; four screen fixes.
- [x] 2026-10-24: `bin/platform-rebuild`'s ssh sends keepalives.
- [x] 2026-10-26: live review rounds 6-12 and their fixes; full `bin/verify` green.
- [x] 2026-11-13: live review round 14 found no countable finding; the loop converged.
- [x] 2026-11-13: the `fsl` names became `cr`, cut over live.
- [x] 2026-11-13: the range became one range host, a slot a compose project; OPNsense became an nftables edge.
- [x] 2026-11-14: answer-blind walks of rounds 16-18 and their findings fixed.
- [x] 2026-11-14: the acceptance suite cut from about 25 min to 12-13 min.
- [x] 2026-11-14: console text and UI slop removed.
- [x] 2026-11-15: answer-blind walks of rounds 19-22 and their findings fixed.
- [x] 2026-11-15: uv virtualenvs, the Nova keypair, `bin/cloud init` and `clouds.yaml`.
- [x] 2026-11-15: the learner map drawn from the slot's live wiring; GNS3 removed.
- [x] 2026-11-15: every surface signs in; eight slots.
- [x] 2026-11-15: a two-arm WAF: the web servers stand on `web` behind the WAF alone.
- [x] 2026-11-16: one Suricata sensor behind the WAF, reporting on the 관제망; nginx's refusals are WAF evidence.
- [x] 2026-11-16: gVisor and Elasticsearch security removed.
- [x] 2026-11-16: sign-up waits for an admin's approval; rate limits; a learner sees only their own sessions.
- [x] 2026-11-16: F4 and 3.4 run the WAF in DetectionOnly; 3.1-3.3 attack with `--random-agent`.
- [x] 2026-11-17: answer-blind walks of rounds 23 and 24 and their findings fixed.
- [x] 2026-11-17: staff delete an approved learner through the close path.
- [x] 2026-11-17: the edge router holds one public IP, port-forwards to the WAF and filters inbound.
- [x] 2026-11-17: the comment cases post with the board's CSRF token.
- [x] 2026-11-17: a zone box is its subnet; the IDS stands in the 관제망 box.
- [x] 2026-11-17: the range images are tagged by the last range-side change; a platform-only replace keeps the range host.
- [x] 2026-11-17: both hosts install from `mirror.kakao.com`; an apt try is judged by the install.
- [x] 2026-11-18: answer-blind walks of rounds 25-27; deployed live with the full `bin/verify` green.
- [x] Moot: the assessment's `REQUEST_URI_RAW` wording (no lesson runs at PL4); publishing the OPNsense image; the OPNsense update check.
- [x] Moot: the live walker as a repo tool; the answer-blind walks drive the browser from per-round scripts, not `walker/walk.py`.

## Measured mechanics a change can break

- **The marker is only on Suricata `http` documents**, never on `alert` ones
  (0 of 3,969 alerts carried `http.request_headers`). Filtering ingest to
  `event_type: alert` destroys correlation.
- **The marker join is keyed on `(flow_id, tx_id)`**, and Suricata writes
  `tx_id` only for rules that inspect an app-layer buffer. `detect:
  guess-applayer-tx: yes` fills it when only one transaction is live; without
  it a rule like `content:"UNION"` with no `http.uri` credits no case. An alert
  stored before its http event gets its marker on a later tick.
- **The sensor reloads over its unix command socket**: `suricatasc -c
  reload-rules` through the runner, not `kill -USR2 1`, which needed Suricata
  to be PID 1. `apply()` accepts only `"return":"OK"` (the 8.0 client exits 0
  on NOK) and rolls back otherwise. The socket needs `unix-command: enabled:
  yes` at startup; a sensor started without it answers "Unable to connect
  socket" and rolls back every change until restarted. OK means the reload ran,
  not that it worked, so `suricata -T` first still catches a bad rule. The
  reload command comes from the sensor host in `declaration.yaml`
  (`suricatasc -c reload-rules`); `CR_SENSOR_RELOAD` overrides it.
- **Rules are written, validated and reloaded as commands through `runner`**
  with stdin, so the port has no rule verbs. Validation reads `/dev/stdin`,
  never a shared file. Rule changes take one process lock: enough for
  waitress's single process, not for two.
- **A rules apply cannot overwrite a newer file.** `GET /api/rules/` returns a
  `version`; an apply whose `base` is not the live version, `null` included,
  is a 409. One with no `base` is unchecked, so the console always sends it.
- **`$HTTP_PORTS` is `[80,8000]`** (`deploy/suricata/suricata.yaml`), the
  ports on the web segment the sensor watches: the WAF proxies to the board on
  8000 and to corp on 80. Historical (the compose range, 2026-10): a rule A/B
  with `8080` in the list drew 0 alerts against 2 for `[80,8000]`.
- **A rule experiment writes to the shipped rules file**, the live artifact,
  so it uses sids at or above 9009000 and `test_sensor_rules.py` refuses those.
  Before each half of an A/B, check the loaded config inside the container: a
  12-second wait that missed the sensor's start nearly buried the one above.
- **Ingest drops an alert whose event time is outside the window**, counted
  as `stale`. The collector (Filebeat 8.15) takes UDP syslog on 5140 and reads
  no file; each slot's rsyslog shippers read the log files. Historical (the
  compose range, before 2026-10-21): Filebeat read the files itself, and inode
  identity re-shipped both logs after a Docker host restart until it
  identified files by fingerprint.
- **The ingest pipeline is registered at bring-up** (`entrypoint.sh:28` runs
  `register_pipeline.py`) and geolocates `src_ip` and ModSecurity's
  `transaction.client_ip`. Two ways carry it to a doc
  (`deploy/filebeat/filebeat.yml`): `output.pipeline: geoip` per request, and
  the `logs-sensors` index template's `index.default_pipeline`. Since
  2026-11-17 the collector overwrites that template at every start
  (`setup.template.overwrite: true`) with the ECS and beat field groups alone
  and a 1 s refresh. Acceptance fails if the live pipeline or the sensor's `local.rules` differ
  from the committed ones.
- **The WAF answers `/healthz` itself** (`deploy/waf/board.com.conf`); no
  probe may be sent through to a target. Historical (the compose range,
  2026-10): a health check that reached the target alerted every ten seconds
  and used up a session's 5,000-document read in about 14 hours.
- **Bring-up of the platform VM's control plane is `docker compose pull && docker compose up -d`** (`build:` is for local development). The platform's
  entrypoint drops root with `gosu` and registers the `geoip` ingest pipeline
  itself, so a fresh host needs no build argument and no manual PUT. No
  control-plane service holds the Docker socket (since 2026-11-15).
- **The store is the named volume `cr_platformdata`** (`/data` in the
  platform container), not `./data` of whichever checkout ran `compose up`.
  `bin/backup` copies the store live with `VACUUM INTO` and keeps the newest
  `--keep` copies (default 1; `cloud.yaml` `backups: {keep: 1}`);
  `bin/platform-rebuild` restores it on a new VM (`docs/OPENSTACK.md` §5.3;
  a 6 GB store twice on 2026-10-15).
- **Closed sessions are deleted after `CR_RETAIN_CLOSED_MINUTES`** (default
  60; `cr/settings.py`, `compose.yaml`): `platform/api/retention.py` runs at
  start and after every close, 2,000 rows per transaction; open sessions are
  never touched. SQLite transactions begin `IMMEDIATE`.
- **Published ports.** By default 8000 (the console and API), 8002 (the
  Website pane's site proxy), 9200 (Elasticsearch) and 5140/udp (the
  collector) are on `127.0.0.1`. On the platform VM cloud-init sets
  `CR_PUBLISH` to the VM's fixed address, so 8000 and 8002 open to
  `network.allowed` behind a sign-in, and `CR_SYSLOG_PUBLISH` to `0.0.0.0` for
  5140/udp (`platform.yaml`); 9200 stays on loopback. Django runs with DEBUG
  off. Another machine needs a tunnel, not a wider `ALLOWED_HOSTS`: it is
  `localhost,127.0.0.1,[::1]` (`DJANGO_ALLOWED_HOSTS` overrides) because at
  `*` DNS rebinding passed the same-origin check, which trusts the request's
  Host.
- **nginx inside the platform's image owns 8000 and 8002.** waitress listens
  on `127.0.0.1:8001` and takes the client from `X-Forwarded-For`, which nginx
  sets to `$remote_addr` and waitress trusts only from `127.0.0.1`; anything
  that reads `REMOTE_ADDR` sees the real client. `/vm-terminal/kali/` and
  `/vm-terminal/waf/` go to ttyd only after `auth_request /signed-in`
  (Django's `/auth-check/`) answers 204; a 401 becomes a redirect to the
  sign-in page, a 403 (a learner naming another's session, a range address)
  passes through.
- **The platform refuses any address a slot's segments list as a node**
  (403; `api/reachability.py`, every slot read side by side, cached 30 s), the
  scorer excepted. A slot whose read raises `RangeUnavailable` counts as
  empty, so the rule fails open for that slot for the 30 s the answer is
  cached.
- **Same-site writes are refused too**: `:8002` (the site proxy) and `:8000`
  are one site, and a page there must not be able to write to the API
  (`api/refusals.py`: a cross-site `Sec-Fetch-Site` or `Origin` is 403). A
  write with a body must be `application/json` (415 otherwise).
- **`bin/verify`** restarts the platform first (waitress never reloads), opens
  and closes one session to prove a session stack comes up (else TP 0 reads as
  a failed defence) and that its sensor reads the rule file, runs the unit
  suite beside the acceptance suite at the lowest CPU priority, refuses a
  stack another checkout brought up, and prunes only the sessions its run
  listed in `CR_ACCEPTANCE_SESSIONS`. `--changed [BASE]` (`bin/select-tests`)
  runs only the unit tests the change reaches and the ratchet, `--live` adds
  the acceptance modules it reaches, `--fast` runs every unit test; docs-only
  changes select nothing.
- **The ratchet.** `bin/measure` counts `git ls-files -z`, so verify fails on
  an untracked file. It refuses a compose override, follows a block-style
  `include:` of plain paths (each wargame's file), counts only
  tests pytest collects and refuses duplicate names. It counts physical lines,
  so joining a wrapped line "shrinks" core: never do that. `core_loc`,
  `dependencies` and `services` may only fall; `tests`, `product_loc` and
  `wargame_services` are reported, not gated (2026-10-16).

## The substrate seam

Docker was the first substrate and was removed on 2026-10-21; OpenStack is the only one.
`platform/range/` is the port: `describe() -> Shape`, `segments()` (who stands
where, without the sensor), `runner(role, segment)` and `launcher(segment)`.
`range.substrate()` is the one place a name becomes an adapter
(`CR_SUBSTRATE`, options keyed by substrate; a test refuses a second
`import_string`), and `redteam/run.py` uses it too. Core, `topology.py` and
`attacker.py` never call Docker. `test/range.py` is the acceptance suite's side
of the port.

`platform/range/declaration.yaml` declares per segment an id, a name and an
attack origin, a role table, and `watches: {sensor: gateway}`; the OpenStack
adapter, `cr/settings.py` and `test/range.py` read it. Identity is declared,
allocation reported: a declared subnet that disagreed with the real one would
bin alerts by a subnet nothing lives on. A segment is bound by its
`cr.segment.id` mark (a Neutron tag), never by name: Heat stack suffixes,
non-unique Neutron names and a project called `fsl_lab` broke name rules.

`platform/range/openstack.py` is unit-tested against fakes built from the
published API reference's responses and a local unprivileged sshd; Keystone
is simplified (domain `default`, project by id). It is loaded only by name, and
a test holds every field it reads to the reference. It reads endpoints off the
Keystone v3 token's catalogue (`public`, `RegionOne` by default), retries a
401 once with a fresh token (proactive renewal before `expires_at` was removed
on 2026-10-02), sends the Nova
microversion, follows `next` links (at most 50 pages), asks Neutron only for
tagged networks, and keeps fixed IPv4 addresses.

Open from the 2026-09-30 sketch:

- **Does the operator still look like an outsider?** The reachability rule
  reads `segments()`; a Neutron router presenting a node's address would lock
  the operator out and let the red team in. Not tested on a cloud.

Settled since: names resolve through each slot's hosts entries, the sensor
sits behind the WAF, one Kali holds every origin, the range host is found by
its `cr_host` metadata, and the edge forwards without SNAT, so the sensor sees
each client by X-Forwarded-For.

## Decided on 2026-09-30 (the user)

- **Blocking works as in practice**: the blue team turns the WAF's blocking
  mode and the IPS's drop rules on and off itself.
- **An IPS outage is an infrastructure fault**, not part of the exercise; it
  is neither planned for nor scored.
- **Objectives do not centre on one target.** The board's user database (Django
  `auth_user`: accounts and password hashes) is something the red team takes,
  and the attacker proves it by submitting the stolen hashes; the platform
  checks it against the target's own ground truth, never by its belief about
  what an attack did (done 2026-10-04).
- **GeoIP is loaded once**, not refreshed: country ranges rarely move. It
  lives in a bind mount of `config/ingest-geoip` with the managed downloader
  off (done 2026-10-02). The downloader had failed at every
  Elasticsearch start (it runs before `.geoip_databases` has an active primary,
  then waits three days), one of its download addresses (`172.64.66.1`) does
  not connect through the VPN, and turning it off on 2026-09-30 deleted the
  downloaded databases.
- **Evidence is selected by event time (done 2026-10-02)**: the `fsl-geoip`
  pipeline sets `@timestamp` from Suricata's `timestamp` and ModSecurity's
  `transaction.time_stamp`, as ECS defines it and Elastic's own pipelines do,
  with the range host's clock kept from the platform VM's chrony. It was
  Filebeat's read time, 5 s
  late median and 17 s worst.
- **The console shows Korean time** (UTC on hover), and an undefined
  precision or recall shows `-`.
- **ModSecurity severities stay** until the tutorial work tunes them to
  practice.
- **Origins**: 30 countries from a public ranking of Internet traffic (no API
  token), each wherever GeoIP places it, Hong Kong and Taiwan included; about
  100 addresses, more to bigger traffic, at least one each.
- **A tool's source address is set when it sends**: the attacker box rewrites
  its outgoing packets to the chosen country's address, so every tool gets it
  whether or not it has a source option.
- **The terminal's moving WAF address** is a Docker artefact; on OpenStack
  addresses are fixed.
- **The platform VM lives inside OpenStack**: an Ubuntu 24.04 VM where
  `docker compose up` brings the whole platform up, cloud-native in feel;
  booting it should be all it takes (cloud-init runs the bring-up). It then
  reaches the OpenStack API from inside, and browsers reach it by a floating
  IP (done: 8000 opens on the VM's address behind a sign-in).
- **No Korean or commercial WAF**, to stay clear of licensing: the WAF is
  nginx + ModSecurity v3 + CRS (all Apache-2.0).
- **pfSense goes in** as the edge firewall, and Suricata runs as its package,
  managed in the pfSense GUI (placement spec, "pfSense"). Superseded: on
  2026-10-08 the firewall lesson and the pfSense GUI pane went out of scope,
  on 2026-10-11 OPNsense replaced pfSense, and on 2026-11-13 an nftables
  router container replaced OPNsense; Suricata runs as the slot's own sensor.
- **The blue team reads alerts in Kibana** (the real ELK with full access)
  and the custom dashboard goes (done 2026-10-05). Kibana is in compose (a gated
  `services` 7 -> 8 on 2026-10-05; `bin/measure` has today's count), reading the same Elasticsearch
  the platform ingests from, reached at `/kibana/` through the one port.
- **The platform UI is a left sidebar with three panes shown inside the
  page**: pfSense, Kibana, a terminal. No new-tab buttons. Kibana is framed
  directly. pfSense sets `X-Frame-Options` and has no base-path setting, so its
  pane is the real GUI framed over a reverse-proxy on the platform's own
  `:8080` (a distinct origin, so pfSense's root-absolute URLs resolve); nginx
  strips the framing header, spoofs `Host` past the anti-DNS-rebind check, and
  injects a server-primed admin session so the pane opens auto-logged-in. The
  terminal pane is ttyd, as Kali's already is. Horizon is never shown to users.
  Superseded on 2026-10-08: the pfSense pane and the `:8080` proxy are dropped
  from scope and were removed the same day (`blue.html`, `nginx.conf`,
  `entrypoint.sh`, `pf_prime.py`, the 8080 publish and security-group rule).
- **One published port (2026-10-01)**: everything happens on the website, so
  the platform's port 8000 is the user-facing one. The terminal and Kibana are
  reached through it by path. 9200 stays published on loopback for the
  acceptance suite, which is all that uses it (the user, 2026-10-01). The WAF's
  8080 publish was removed on 2026-10-02: the command-line cases and the
  acceptance suite reach the target from inside the range, through
  `test/range.py`'s runner. Host port 8080 served the pfSense proxy
  from 2026-10-05 until its removal on 2026-10-08. Today 8000 is joined by
  8002, the Website pane's site proxy, and 5140/udp takes the slots' log
  servers' syslog.
- **Session start/stop and the scoreboard stay on the landing page `/`**,
  outside the sidebar; the sidebar is only the work screen.
- **Tap-as-a-Service is dropped from the design**: it was there for a sensor
  the blue team could not tamper with, which is no longer assumed. It stays
  enabled on the cloud, off every path.

## Known gaps

- The first full `bin/verify` right after `docker compose up -d --build`
  (2026-09-30) failed 56 tests in `test_console_behaviour.py` that passed in
  `--fast` before it, alone, as a file, and in the next full run. The cause
  was not found; the output was truncated. It recurred on 2026-10-01 as two
  acceptance failures (one case of ten detected) that passed when rerun.
- `test_declaration.py` compares two files, never the running range.
- The range keeps time by the platform VM alone (chrony, `local stratum 10`):
  if the platform VM loses its upstream, the range follows the platform's
  clock, which is what scoring compares against, not true time. A host whose
  time source does not answer within 30 s fails its configure step.
- The platform holds the ssh key that runs `sudo docker` on the range host:
  whoever takes the platform container is root on the range host. The
  platform VM's own Docker socket is no longer mounted anywhere (2026-11-15).
- `elastic.fetch` reads at most 5000 documents per call, oldest first, `http`
  records included. Since 2026-10-13 a full ingest pages by `@timestamp`
  (`api/views.py` `_fetched`, up to 41 reads, about 205,000 documents); past
  that, or when 5000 documents share one timestamp, the newest are still
  dropped and `Session.read_of` flags it. Each ingest re-reads the whole
  window. Paging with `search_after` inside `ingest/elastic.py` (a gated
  core file) would need a monotonic write-time field; one
  `set: _ingest.timestamp` processor gives it.
- ModSecurity's `Detection.raw` holds the rule message, request, host and
  place, not the whole audit record.
- The operator log is lost when the attacker box is recreated, and its whole
  seconds let sessions under a second apart claim each other's commands.
- Two labelled windows under four seconds apart overlap (`WINDOW_SLACK` is two
  seconds each end), and the console does not say so.
- A learner opens only their own sessions (one at a time); an admin opens
  any, and nothing stops one account using a session in four windows.
  Kibana shows a learner only their open session's slot (the platform's
  Kibana gate), but a slot is reused, so it also shows what an earlier
  session on that slot left in `logs-N-*`.
- A range host can send with another's address, and one recreated within the
  30 s cache keeps its old answer (`docs/THREAT-MODEL.md`).
- OpenStack host keys are trust-on-first-use per generation, kept in the
  platform user's home (lost with the container) unless the deployment's ssh
  config says otherwise. Reading them from `os-getConsoleOutput` is stronger,
  but libvirt returns only the last 100 KiB and the guest writes its console.

## Tried and thrown away

- **Replacing Django entirely.** It cost more lines than it saved.
- **Elasticsearch as the only store, 2026-09-22**, killed before any code:
  both event clocks are `keyword` and the read clock leads ModSecurity's by
  2.5 s median, 7.9 s p90, so 64% of WAF alerts would miss their 2 s window;
  re-querying turned one session's 66 detections into 98; 85 tests stand on
  `patch(elastic.fetch)`. The motivating 40 ms was a Docker call, not Django.
- **Asserting that no alert in a red team window is unmarked.** False: a
  window reaches a minute either side, so it holds whatever used the range
  just before. That is why `unattributed` is reported, not asserted;
  acceptance checks only for the stack alerting on its own traffic (loopback
  source or the numeric-Host signature).
- **Feeding window correlation the scorer's address.** It would measure the
  scorer instead of the defence; a zero with a stated reason is more useful.
