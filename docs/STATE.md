# State

The product record: the backlog (what the user wants built, in priority order)
and the finished work, one line each, with the detail in `git log`, `README.md`
and `docs/ARCHITECTURE.md`. The live state of work in flight is in
`docs/state/now.md`, and rulings are in `docs/DECISIONS.md`; the `orchestrate`
skill reads those, not this file. Keep the backlog here true.

Updated: 2026-10-08

## Where things stand

On 2026-09-20 the repo moved from proving the hypothesis to building the
smallest product that demonstrates it
(`docs/superpowers/specs/2026-09-20-product-flow-design.md`, all four phases
done). On 2026-10-08 the user approved the next direction, a session-isolated
learning MVP (backlog 0).

The range has two targets: the Django board (`board.com`, MySQL behind the WAF,
`loot_verified`) and the WordPress site `corp` (`corp.com`, `effect_observed`,
sub-project B, done 2026-10-04). Juice Shop, the internal wiki and the
`self_judged` objective model were removed on 2026-10-04 (objective-model
Phase 4).

`bin/verify` prints the scores; they and the baseline are in `metrics.json`,
not copied here.

The loop runs in a browser. Open `/`, start a session, and open the red and
blue consoles side by side. The red console fires cases and holds the Kali
terminal; an attack typed there between Start and Stop is attributed by time,
source address and the proxy's marker. The blue console is a sidebar that
frames the real tools (Kibana and a WAF terminal) and calls no
`/api/`. The UI has no rule editor; the session page's confirm-close calls
`/ingest/` once before closing, and also reads `/score/`. The acceptance suite
calls `/ingest/` too, and `redteam/run.py` prints the curl.

## The objective model (done 2026-10-04)

The attacker proves possession. The objective layer used to read Juice Shop's
self-flipped `solved` flag; it is now one target-agnostic model, carried by the
board, and Juice Shop is gone. Design:
`docs/superpowers/specs/2026-10-03-attacker-proven-objective-model-design.md`.
All four phases are committed and `bin/verify` is green.

- **The loot ladder.** `objective_model` is `loot_verified`,
  `effect_observed` (corp, sub-project B) or `none`; `judged` is derived
  (`!= none`). The board is `loot_verified`.
  `wargames/board/objectives.yaml` declares `board-auth-user-partial`,
  `-admin` and `-full`. `POST /api/sessions/<id>/loot/` (`platform/api/loot.py`)
  snapshots the ground truth onto `Session.baseline` at session start and
  verifies submitted rows against that snapshot by exact hash match only,
  never re-reading the target live. Credited tiers flow into the zero-sum game
  through the exfil case. `none` is reachable only by patching in tests.
- **The ground truth** (the target's own records). `/internal/auth-users` on
  the board returns the `auth_user` username/hash map on the `estate` network
  and answers 404 through the WAF (the Docker default vhost 404s `/internal` for
  any Host; the cloud's `range.conf` does too). Only the platform reads it; the
  red team cannot reach it, and it does not pass the sensors.
- **READY** reads "ground truth readable" where it used to read "nothing
  solved on the target" (`_ground_truth_readable` in `platform/api/views.py`).
- **The realistic exfil is the `?sort=` order_by SQLi.** The board is pinned to
  Django 3.2.4 (CVE-2021-35042) on `python:3.9-slim`; `post_list` passes
  `?sort=` straight to `order_by()`. A `.`-containing value bypasses field
  validation and reaches the raw `ORDER BY`; the board runs `DEBUG=True`, so
  MySQL errors surface, and error-based extraction leaked live data
  (`extractvalue(1,concat(0x7e,version()))` -> `~8.4.11`). sqlmap's
  off-the-shelf payloads do not auto-complete the dump through this ORM
  injection (they are not shaped for the dotted-column prefix), so
  `board-sqli-orderby-sqlmap` (`redteam/cases/board.yaml`) is a loud, detected
  probe. The planted `/members.json` `values()` leak was removed: no real app
  would expose it. Salts rotate per rebuild because
  `board-db` keeps no persistent volume (`test_board_db_ephemeral.py` guards
  it). Full automated extraction through the order_by sink and a live-cloud
  rebuild stay manual checks.
- **Proven on the live stack** (`test/test_board_loot.py`): the ground truth
  read over the internal channel and submitted credits all three tiers at
  coverage 1.0; fabricated hashes are refused.
- **Removed:** Juice Shop, the internal wiki and its lateral-movement
  objective, `platform/objectives.py`, the `self_judged` value and its three
  view branches, `members.json`, `wargames/juice-shop/`. Sessions stored with
  `scenario: juice-shop` keep their rows (migration 0013 only moves the
  default to `board`).
- **The `tests` floor was lowered 1252 -> 1196 under the user's Phase 4
  authorisation** (one of several authorised reductions, each recorded in
  `docs/DECISIONS.md` and `metrics.json`; this one is itemised in its commit
  message): about 64 Juice/wiki-only tests were deleted, one more
  with `members.json`, 15 were repurposed onto board loot behaviour
  (count-neutral), and removal/prerequisite guards were added. `core_loc` held
  at 461, `services` 7, `wargame_services` 4 -> 2, `product_loc` 8580 -> 8040,
  `dependencies` 6.

## Sub-project B: the WordPress authz target `corp` (done 2026-10-04)

The range's second target. Design in
`docs/superpowers/specs/2026-10-04-wordpress-authz-objective-design.md` (task
brief/report trail under
`.superpowers/sdd/2026-10-04-wordpress-authz-objective/`). `corp`
(`wargames/corp/`) is `effect_observed`, not `loot_verified`: nothing is
instrumented on the WordPress app itself (the user's explicit choice). Both the
session-start baseline snapshot and the ongoing observe read `corp-db` only,
through a substrate runner (`docker exec` or ssh running `mysql`/`mysqlbinlog`,
`views.py:188,408`), by reading its own MySQL binary log (`binlog_format=ROW`,
`corp-db`'s build layer adds `mysqlbinlog` on top of the stock MySQL 8.4
image). A committed ROW-event insert/update is ground truth; the target's own
data still decides what was taken, as with the board's `loot.py`.

Three real, unauthenticated CVEs, none detected by the default OWASP CRS, so
the blue team has to write its own detection; each is pinned to a vulnerable
plugin version:
- `CVE-2023-3460` - Ultimate Member 2.6.6, the accent-bypass `wp_capabilities`
  key -> `corp-rogue-admin` (`rogue_admin`).
- `CVE-2018-19207` - WP GDPR Compliance 1.4.2, an option flip to admin
  self-registration -> `corp-self-registration` (`option_flip`).
- `CVE-2026-4431` - Easy Post Submission 2.3.0, an unauthenticated `postId`
  overwrite of an existing post -> `corp-content-overwrite` (`content_write`).

The scripted cases in `redteam/cases/corp.yaml` are detection probes only
(each real exploit needs a per-page nonce the harness cannot bake statically,
so they cannot be scripted into a repeatable crediting case); the real
objective credit is proven by the live two-step acceptance tests
(`test/test_corp_authz.py`, `test_corp_observe_live.py`,
`test_corp_cve_content_write.py`): fetch a fresh nonce, then exploit, inside a
recorded session window, then `POST /objectives/` reads the credit from the
committed binlog rows.

`redteam/harness.py` gained form-body (`data=`) support alongside
params/json, by the user's explicit authorisation during B, so `$_POST`
attacks (the GDPR option flip, the postId overwrite) are scriptable as cases
too. That was sub-project B's only `core_loc` increase, 461 -> 462.
`wargame_services` grew 2 -> 4 (`corp-wp` + `corp-db` beside the board's own
two).

Audit cleanup committed (2026-10-02). A 10-slice over-reach
audit (a workflow, each finding adversarially re-verified) flagged 26 items;
the user asked for all. 23 were removed, test-first, `bin/verify` green:
`core_loc` 472 -> 461, `product_loc` 8235 -> 8142, the `tests` floor 1201 ->
1183 (`metrics.json` records the authorised test removals). Gone: the
sketch-era `unimplemented`/`CALLS`; the per-command `ssh -G` key-pinning probe
and `PINNING`; proactive token renewal (the 401 retry stays); the unused
`FSL_OPENSTACK_SSH_CONFIG` knob and the env-overridable attacker paths;
`DetectionRecord.source/signature`; `Session.truncated` (migration 0012);
`reachability.forget`; the single-tool `SUPPORTED_TOOLS` registry; `run.py
--origin`; `Origin.share/country`; `pfsense.home_net`; `_parse_time`'s dead
ctime-fraction and Z/offset paths (Py3.13 `fromisoformat` covers them);
`fetch`'s unused `timeout`; the `board.com` aliases on the non-default edges;
the duplicate `deploy/elastic` mount (`register_pipeline` reads `FSL_SOURCE`);
two `suricata.yaml` blocks that restated defaults; and tests that pinned
implementation letter (JS source-greps, a re-coded Hamilton, `CALLS`/field
source-greps). Three were not taken:
- **O1 only in part:** the clear over-reach is gone, but the deployment ssh
  config Include stays: the ssh test harness uses it to point ssh at the test
  sshd's port, so a full removal needs a harness redesign.
- **B11 skipped:** collapsing `confirmedOrigin`/`describedOrigin` into one
  `ready` flag would wrongly disable the terminal toggle after a reverted POST
  failure; the two encode a real partial-failure state.
- **B7 resolved by redefining `services`; the board stayed.** The board's
  MySQL belongs to the board wargame; the audit read it as removable because
  the gated `services` metric counted platform and wargame services together.
  Since 2026-10-02 `bin/measure` splits them: the gated `services` counts the
  platform's own compose services, and a wargame's services under
  `wargames/<id>/` (its app, its database, later its own attacker) count as
  `wargame_services`, reported, not gated, so adding a scenario is not a gated
  regression. `board-db` stays, on MySQL.

Backlog 2, steps 4 and 5 (pfSense edge + Kali attacker on OpenStack) are done
end to end (2026-10-02). The whole chain is proven on the cloud:
a case fired from the Kali box leaves as a chosen country, crosses
pfSense -> WAF -> the target, both sensors detect it, the logs reach the
platform's Elasticsearch geolocated, and the platform scores it.

Backlog 2 step 6's in-scope part is done (2026-10-02): the target port is
no longer published and the acceptance suite and command-line cases reach the
target from inside the range. **Step 7 is done (2026-10-03):** evidence by
event time, GeoIP's durable home, and now the session Start/Stop lifecycle -
Start takes a READY slot, Stop kicks off the rebuild, and READY is a three-check
gate (VMs ACTIVE, the target's ground truth readable, rules at baseline); the
canary (an alert corroborated by both engines with their clocks in sync) is a
separate check the landing page offers. The two blue-screen panes held out of backlog 2 (Kibana and the pfSense
GUI) were built on 2026-10-05/06; the 2026-10-08 ruling drops the pfSense pane
again, and it was removed the same day. The board's user-database objective is done (see "The
objective model").

**Committed (step 6, the acceptance/CLI move; the figures predate Phase 4):**
- `compose.yaml` drops the WAF's `127.0.0.1:8080:80` publish; the target is
  reached only from inside the range. (Host port 8080 was reused on 2026-10-05
  for the platform's pfSense proxy; that publish was removed on 2026-10-08.)
- The acceptance suite reaches the target through `test/range.py`'s runner:
  `conftest.target_code()`/`target_answers()` curl `http://board.com` from the
  attacker box (so `stack_is_up`, `reset_target` and `test_criterion_1` no
  longer need a host port), and `test_front_door`'s probe fires through
  `from_attacker`.
- The command-line harness runs inside the range: `run_redteam()` execs
  `redteam/run.py` on the `scorer` host (the platform container) with
  `--target/--tool-target http://board.com`, the way the console fires. A fresh
  run scored TP 8 / FP 0 / FN 2 / TN 6, both engines.
- `test_judge_isolation` drops 8080 from its published-port set; `README.md`
  shows the in-range invocation.

**Committed (step 7):** evidence selected by event time (Filebeat's read time
ran 0.8-8.6 s late here), GeoIP in a bind mount, and the session Start/Stop
lifecycle with the three-check READY gate; detail under backlog 2, step 7.

- **Re-configure must follow a rebuild.** A rebuild wipes pfSense's and the
  WAF's ssh-pushed config (`configure_slot`); the targets are baked. The console
  calls `POST /api/range/configure/` once the VMs are ACTIVE; until then the
  slot reads REBUILDING, then CHECKING, and the edge denies range traffic.

**Committed (`4ec543b..`):**
- **Left 1 - the WAN sticks.** `POST /api/range/configure/`
  (`configure_slot` -> `configure_edge`) plays `deploy/pfsense/configure.php`
  back on pfSense over mgmt ssh (settings as a base64 JSON line ahead of the
  static script, on stdin). WAN static at the first origin `.1`, the other 29
  as `ipalias` VIPs, IPv6/dhcp dropped, outbound NAT off, one WAN pass rule,
  the WAN's dhclient killed; it refuses unless pfSense then holds all 30.
  Survives a reboot (the stray DHCP dhclient was what wiped the hand-set
  address before).
- **Left 2 - Suricata on the WAN.** The same playback configures the pfSense
  package (visible in its GUI): `fsl_home` (`pfsense.home()`) as HOME_NET,
  `fsl_anywhere` (0.0.0.0/0) as EXTERNAL_NET, legacy mode, no blocking, EVE to
  syslog, `guess-applayer-tx` and `dump-all-headers: request` merged as dotted
  passthrough keys (the `types.N` index read back from `suricata
  --dump-config`), the shipped `local.rules` as a new sensor's custom rules.
  Refuses unless the sensor is running after.
- **Left 3 and 4 - the log pipeline, codified.** `configure_slot` also: starts
  the edge's remote syslog to the scorer (`:5140`, RFC 5424, logall); gives the
  WAF an rsyslog `imfile`->`omfwd` drop-in for its ModSecurity audit log
  (`range/waf.py`, sudo, `rsyslogd -N1`-checked); opens `fsl-reach` to exactly
  the edge and WAF on UDP 5140 (`fabric.hearing`); and Filebeat gains a UDP
  syslog input that parses every line and decodes Suricata/ModSecurity JSON so
  ingest normalizes them as before. GeoIP rides filebeat's per-request
  `output.pipeline: fsl-geoip` (works on Docker) and, as reinforcement, the
  `fsl-logs` template's `index.default_pipeline: fsl-geoip` (filebeat writes
  that into the template when it first creates it, proven by `filebeat setup`).
- **Left 5 - one attacker wears any origin.** The slot gives the attacker's one
  Internet port the ~100 per-country addresses (`slot.origin_addresses`), which
  the existing gateway `bootcmd` spreads onto the NIC; the proxy/terminal run on
  the Kali box (`proxy: fsl-kali`); `attacker.origins()` reads the edge as the
  way in and the target by name; choosing an origin runs
  `/usr/local/sbin/fsl-origin` to SNAT the box's outgoing source
  (`ATTACKER_ORIGIN_MODE=snat`), so every tool leaves as that country.

**Left 6 - the scored end-to-end run (cloud-verified 2026-10-02).** From a
fresh session, origin `tw` (SNAT source 120.96.0.10), a benign request and the
canonical SQLi fired from Kali through pfSense to the target: the platform
scored TP 1, FP 0, FN 0, TN 1, the attack corroborated and credited to
both engines (pfSense Suricata `FSL SQLi attempt - URI` + ModSecurity CRS).
`objectives` read 0: the probe was detected but did not take anything, and the
objective check reads the target, not the detector. `game.balance` appeared
on close.

Re-verified 2026-10-02: Left 1, 2, 3/4 and 6 each held up under an independent
read-only check against the live cloud and the committed code. Left 5 was
proven from a bare slot+image rebuild (below), which exposed and fixed the
WAN-pass-rule bug.

**Findings to carry:**
- **Syslog loss happens on pfSense's send side under bursts; paced traffic
  loses nothing** (measured). Fire the SQLi 30x at 0.5-1s spacing: pfSense
  detects 30, Elasticsearch indexes 30 - 0 loss, both engines. Fire 50
  concurrently: pfSense detects 50, ES indexes 44 then 13 on a repeat (12-74%,
  variable). A dual tcpdump showed the dropped datagrams never reach the
  platform NIC and NIC-arrivals == ES-indexed, so the loss is at pfSense's
  FreeBSD syslogd under a burst, not the virtual network and not the receive
  buffer (raising `rmem_max` 80x to 16 MB changed nothing). Re-ingest recovers
  a late datagram but not a dropped one. Impact: the console fires cases one at
  a time (paced) -> 0 loss; a bursty tool (sqlmap, 94 requests) loses a
  fraction of its many alerts but the case still scores TP (>=1 survivor across
  two engines). Only per-alert fidelity of bursty tools degrades. Session 3's
  FN earlier was this (one firing, one dropped alert). pfSense offers no
  non-UDP remote-syslog transport, so this is accepted.
- The config-push is idempotent and keyed on the WAN Suricata instance / the
  VIP descr `fsl origin <id>` / the WAN pass rule descr / the `fsl_home` and
  `fsl_anywhere` pass lists, so a second `configure` changes nothing.

**Left 5/6 reproduced from a clean boot (2026-10-02), and it exposed a real
bug.** The whole slot was torn down, the Kali image rebuilt (its `setup.sh`
ships `/usr/local/sbin/fsl-origin`), and the slot re-booted and re-configured
through the API alone (`DELETE /slot/`, `DELETE`+`POST /images/` until clean,
`POST /slot/`, `POST /configure/`). The fresh Kali came up with 100 eth0
addresses from the slot `bootcmd` and `fsl-origin` from the image, with no
hand steps, and `POST /api/attacker/origin/` SNATs it per country. A fresh
scored session then read TP 1, FP 0, FN 0, TN 1, the SQLi corroborated
across both engines (ModSecurity 16 + Suricata 4 detections), src 120.96.0.10
geolocated TW.
- **The bug the rebuild found:** on a fresh pfSense, `configure.php` added the
  WAN pass rule and reloaded pf, but the Suricata package sync that runs
  afterwards reloaded the filter and dropped it, so the edge denied all range
  traffic (Kali could not reach the WAF; every case was an FN). The earlier
  slot only worked because a hand-run playback had loaded a pass rule. Fixed:
  `configure.php` runs a final `filter_configure_sync()` after the sensor is up
  and prints `wanrule <count>`; `configure_edge()` refuses unless the rule is
  in pf (`pfsense.wan_rule_loaded`). Re-verified from the bare rebuild above.
- Still proven from `config.xml`, not an actual reboot: that the 30 WAN
  addresses + VIPs survive a pfSense reboot (a reboot was not performed).

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
  not that it worked, so `suricata -T` first still catches a bad rule. On
  OpenStack set `FSL_SENSOR_RELOAD="suricatasc -c reload-rules
  /run/suricata/suricata-command.socket"`, with `sudo -n` in front if needed.
- **Rules are written, validated and reloaded as commands through `runner`**
  with stdin, so the port has no rule verbs. Validation reads `/dev/stdin`,
  never a shared file. Rule changes take one process lock: enough for
  waitress's single process, not for two.
- **A rules apply cannot overwrite a newer file.** `GET /api/rules/` returns a
  `version`; an apply whose `base` is not the live version, `null` included,
  is a 409. One with no `base` is unchecked, so the console always sends it.
- **`$HTTP_PORTS` is `[80,8000]`**, the ports on the WAF's wire. Docker
  translates `8080` before the sensor sees it (same rule A/B: `8080` 0 alerts,
  `[80,8000]` 2, `any` 4).
- **A rule experiment writes to the shipped rules file**, the live artifact,
  so it uses sids at or above 9009000 and `test_sensor_rules.py` refuses those.
  Before each half of an A/B, check the loaded config inside the container: a
  12-second wait that missed the sensor's start nearly buried the one above.
- **Filebeat identifies files by fingerprint**: inodes are renumbered when the
  Docker host restarts, and inode identity re-shipped both logs. 8.15
  does not migrate the registry, so changing identity again re-ships once.
  Ingest drops an alert whose event time is outside the window, as `stale`.
- **The ingest pipeline is registered at bring-up** (`entrypoint.sh:50` runs
  `register_pipeline.py`) and geolocates `src_ip` and ModSecurity's
  `transaction.client_ip`. Two ways carry it to a doc: filebeat's
  `output.pipeline: fsl-geoip` per request (the Docker path), and the
  `fsl-logs` index template's `index.default_pipeline`, which filebeat writes
  in only when it first creates the template; a long-running ES whose template
  predates the setting keeps a template without it, so set
  `index.default_pipeline` on the live data stream's write index there (the
  cloud needed this; a fresh VM does not). Do not add
  `setup.template.overwrite: true` to force it: filebeat 8.15 then fails every
  write with "no matching index template found for data stream [fsl-logs]".
  Acceptance fails if the live pipeline or the sensor's `local.rules` differ
  from the committed ones.
- **The WAF's health check asks `/healthz`**, which the WAF answers itself;
  sent through to the target it alerted every ten seconds and used up a
  session's 5,000-document read in about 14 hours.
- **Bring-up is a single `docker compose up -d --build`.** The platform's
  entrypoint reads the docker socket's group from the socket at start, adds
  `fsl` to it, drops root with `gosu`, and registers the `fsl-geoip` ingest
  pipeline itself, so a fresh host needs no build argument and no manual PUT.
- **The store is the named volume `fsl_platformdata`**, not `./data` of
  whichever checkout ran `compose up`; `./data/label` is still a bind mount.
  `bin/backup` copies the store live; restore (README) has never been run.
- **Published ports.** By default 8000 (platform), 9200
  (Elasticsearch) and 5140/udp (syslog) are on `127.0.0.1`. On the platform VM
  cloud-init sets `FSL_PUBLISH` to the VM's address, so 8000 opens to
  any address with no login (the user, 2026-10-01), and `FSL_SYSLOG_PUBLISH` to
  `0.0.0.0` for 5140/udp (`platform.yaml:145`); 9200 stays on loopback. Django
  answers to the floating IP. Before, each segment's gateway
  forwarded 8000, 9200, 7681 and 8080 into the platform from inside the range
  (8 of 8 reached). `DJANGO_DEBUG=1` is safe only because of this. Another
  machine needs a tunnel, not a wider `ALLOWED_HOSTS`: it is
  `localhost,127.0.0.1,[::1]` (`DJANGO_ALLOWED_HOSTS` overrides) because at `*`
  DNS rebinding passed the same-origin check, which trusts the request's Host.
- **nginx inside the platform's image owns 8000.** waitress listens on
  `127.0.0.1:8001` and takes the client from `X-Forwarded-For`, which nginx
  sets to `$remote_addr` and waitress trusts only from `127.0.0.1`; anything
  that reads `REMOTE_ADDR` sees the real client. `/terminal/` goes to ttyd
  only after `auth_request` to `/api/attacker/` answers 2xx; a 403 passes
  through, and any other answer (Django's 400 for a Host it does not allow)
  becomes nginx's 500, still refused.
- **The platform refuses any address standing in the range** (403;
  participants cached 30 s). The operator arrives from a segment's gateway
  (`5.188.10.1`), the attacker box as a node (`5.188.10.2`). The rule reads
  `segments()`, which needs no sensor. If that raises `RangeUnavailable` it
  fails open for the 30 s the empty answer is cached; any other error is a 500.
- **Same-site writes are refused too**: `:8080` and `:8000` are one site.
  `:8080` served the target until 2026-10-02 and the pfSense proxy until 2026-10-08;
  a page there must not be able to write to the API. A write with a body must
  be `application/json`.
- **`bin/verify`** restarts the platform first (waitress never reloads), waits
  up to two minutes for the target (else TP 0 reads as a failed defence),
  refuses a stack another checkout brought up, and prunes only the sessions its
  run listed in `FSL_ACCEPTANCE_SESSIONS`.
- **The ratchet.** `bin/measure` counts `git ls-files -z`, so verify fails on
  an untracked file. It refuses a compose override, follows a block-style
  `include:` of plain paths (each wargame's file), counts only
  tests pytest collects and refuses duplicate names. It counts physical lines,
  so joining a wrapped line "shrinks" core: never do that.

## The substrate seam

Docker was the first substrate; OpenStack is the deployment target.
`platform/range/` is the port: `describe() -> Shape`, `segments()` (who stands
where, without the sensor), `runner(role, segment)` and `launcher(segment)`.
`range.substrate()` is the one place a name becomes an adapter
(`FSL_SUBSTRATE`, options keyed by substrate; a test refuses a second
`import_string`), and `redteam/run.py` uses it too. Core, `topology.py` and
`attacker.py` never call Docker. `test/range.py` is the acceptance suite's side
of the port.

`platform/range/declaration.yaml` declares per segment an id, a name and an
attack origin, a role table, and `watches: {sensor: gateway}`; the Docker
adapter, `fsl/settings.py` and `test/range.py` read it. Identity is declared,
allocation reported: a declared subnet that disagreed with the real one would
bin alerts by a subnet nothing lives on. `test_declaration.py` holds
`compose.yaml` to it. A segment is bound by its `fsl.segment.id` mark (Docker
label, Neutron tag), never by name: compose overrides, Heat stack suffixes,
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

**Deployed on the KVM cloud (2026-09-30).** `master@192.168.0.100` (ssh key
`fsl_claude`, passwordless sudo); its API endpoints are on `192.168.0.110`.
It runs kolla-ansible 2026.1 (Gazpacho, the 22.x series; the host has
22.2.1.dev9), Ubuntu images, ML2/Open vSwitch, inventory `/root/all-in-one`.
Tap-as-a-Service is on (2026-09-30, the user's go-ahead):
`enable_neutron_taas: "yes"` in `globals.yml` (the previous file is
`globals.yml.before-taas`), then `kolla-ansible reconfigure -i
/root/all-in-one -t neutron`. kolla-ansible 2026.1 has a bug here: it lists
`taas` in `service_plugins` for all three Neutron API services but writes
`neutron_taas.conf` only for `neutron-server`, so `neutron_rpc_server` and
`neutron_periodic_worker` exited ("No providers specified for 'TAAS'") and
every agent read as dead until fixed. The fix is kolla's own per-service
override: `/etc/kolla/config/neutron/neutron-rpc-server.conf` and
`neutron-periodic-worker.conf`, each a copy of `neutron_taas.conf`, then
reconfigure again. A later reconfigure keeps them. Checked as `fsl-range`: a
member creates a tap service and a `BOTH` tap flow on the target's port; the
flow goes ACTIVE, the service stays DOWN until its port is on a VM, and
`br-tap` exists.
The range lives in project `fsl-range` (id `64ffc2a247464ebdae21cfdae0f96d90`)
as user `fsl-range` with the `member` role, not admin. Its password is only in
`/root/fsl-range.password` on the host; `/root/fsl-range-openrc.sh` sources
it. A stand-in, `bin/openstack-range`, was the first range here, removed
on 2026-10-01 once the platform built its own (backlog 2, step 2); it made
keypair `fsl-claude` (which the platform stack still boots with), `fsl-sg`
(22/80/3000/icmp), six networks `fsl-<id>` tagged `fsl.segment.id=<id>` with
compose's subnets, and one target VM (ubuntu-24.04, m1.small, config drive)
on `fsl-estate`. Re-running `up` creates nothing. Through
`FSL_SUBSTRATE=range.openstack.connect` from the Mac, `describe()` returned
all six segments with their declared names and origins, the subnets, `.1`
gateways and network ids Neutron lists, the target VM at its fixed address
on `estate`, and no sensors (no gateway or sensor server stands);
`segments()` returned the same. That stand-in is gone; since step 3 of
backlog 2 the platform VM reaches the range's hosts over `mgmt` and
`runner()` has run on each of them (`launcher()` has not run on a cloud).

Left for OpenStack, as written on 2026-09-30. Since done: name resolution
(the slot appends every host's names to `/etc/hosts`; Kali reaches `board.com`
through the edge, step 5), where the sensor sits (Suricata runs as pfSense's
package, step 4), and one attacker for every origin (one Kali Internet port
holding the ~100 origin addresses, step 5). Not re-checked since:

4. **Roles are found by Nova server name**, which is not unique; segments are
   bound by tag for that reason, roles not yet. The slot marks its servers with
   metadata `fsl_host`, which `describe()` does not read yet. Credentials are
   settled: `FSL_SUBSTRATE=range.openstack.connect` and `FSL_OPENSTACK_*`, each
   refused by name when missing.
5. **Does the operator still look like an outsider?** The reachability rule
   works because Docker DNATs the published port to a gateway. A Neutron router
   presenting the operator's own address is fine; one presenting a node's
   locks the operator out and lets the red team in. Test this first on a cloud.
6. **Floating IPs and router SNAT.** The adapter keeps the fixed address. A
   router's SNAT makes Suricata see the router, not the attacker; the stamping
   proxy has no Neutron equivalent yet.

Settled since the sketch: the default origin, the sensor reload, whether a
sensor is a participant, subnets per segment, binding, and who starts a tool.

## Decided on 2026-09-30 (the user)

- **Blocking works as in practice**: the blue team turns the WAF's blocking
  mode and the IPS's drop rules on and off itself.
- **An IPS outage is an infrastructure fault**, not part of the exercise; it
  is neither planned for nor scored.
- **Objectives do not centre on one target.** The board's user database (Django
  `auth_user`: accounts and password hashes) is something the red team takes,
  and the attacker proves it by submitting the stolen hashes; the platform
  checks it against the target's own ground truth, never by its belief about
  what an attack did (done 2026-10-04, see "The objective model").
- **GeoIP is loaded once**, not refreshed: country ranges rarely move. It
  lives in a bind mount of `config/ingest-geoip` with the managed downloader
  off (done 2026-10-02; backlog 2, step 7). The downloader had failed at every
  Elasticsearch start (it runs before `.geoip_databases` has an active primary,
  then waits three days), one of its download addresses (`172.64.66.1`) does
  not connect through the VPN, and turning it off on 2026-09-30 deleted the
  downloaded databases.
- **Evidence is selected by event time (done 2026-10-02)**: the `fsl-geoip`
  pipeline sets `@timestamp` from Suricata's `timestamp` and ModSecurity's
  `transaction.time_stamp`, as ECS defines it and Elastic's own pipelines do,
  with every range VM's clock kept by chrony. It was Filebeat's read time, 5 s
  late median and 17 s worst.
- **The console shows Korean time** (UTC on hover), and an undefined
  precision or recall shows `-`.
- **ModSecurity severities stay** until the tutorial work tunes them to
  practice.
- **Origins**: 30 countries from a public ranking of Internet traffic (no API
  token), each wherever GeoIP places it, Hong Kong and Taiwan included; about
  100 addresses, more to bigger traffic, at least one each.
- **A tool's source address is set when it sends**: the attacker VM rewrites
  its outgoing packets to the chosen country's address, so every tool gets it
  whether or not it has a source option.
- **The terminal's moving WAF address** is a Docker artefact; on OpenStack
  addresses are fixed.
- **The platform VM lives inside OpenStack**: an Ubuntu 24.04 VM where
  `docker compose up` brings the whole platform up, cloud-native in feel;
  booting it should be all it takes (cloud-init runs the bring-up). It then
  reaches the OpenStack API from inside, and browsers reach it by a floating
  IP, which the loopback-only ports and missing login do not allow yet.
- **No Korean or commercial WAF**, to stay clear of licensing: the WAF is
  nginx + ModSecurity v3 + CRS (all Apache-2.0).
- **pfSense goes in** as the edge firewall, and Suricata runs as its package,
  managed in the pfSense GUI (placement spec, "pfSense"). Superseded in part on
  2026-10-08: pfSense stays as the OpenStack edge and Suricata host, but the
  firewall lesson and the pfSense GUI pane are out of scope.
- **The blue team reads alerts in Kibana** (the real ELK with full access)
  and the custom dashboard goes (done 2026-10-05). Kibana is in compose (a gated
  `services` 7 -> 8 the user's call justifies), reading the same Elasticsearch
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
  from 2026-10-05 until its removal on 2026-10-08, and 5140/udp takes the edge's syslog.
- **Session start/stop and the scoreboard stay on the landing page `/`**,
  outside the sidebar; the sidebar is only the work screen.
- **Tap-as-a-Service is dropped from the design**: it was there for a sensor
  the blue team could not tamper with, which is no longer assumed. It stays
  enabled on the cloud, off every path.

## Left to engineering (no decision needed)

Done 2026-10-07: `bin/verify` refuses to run while a session is open, and the red
console clears the attacker label on page load and at Stop (stale-attribution
guard).

Remaining:
- `no_marker` per engine, without warning on raw-TCP-only sessions. Needs an
  engine field on `DetectionRecord` and app-layer presence carried through the
  ingest seam, which raises gated `core_loc` and needs live-stack
  verification.
- A tool killed on the attacker when its timeout passes (touches the attacker
  seam).
- `fsl-logs-*` expire after 30 days, with a disk warning (an ES ILM policy;
  verify against the live stack).
- The ratchet counts statements with the baseline from `HEAD`, and
  `scoreboard.py` moves into core. This redefines the gate and raises
  `core_loc`, so it is a decision, not pure engineering.

Dropped: the rule editor's over-indent guard. The 2026-10-05 console rebuild
removed the rule editor, and the 2026-10-08 ruling drops the pfSense GUI pane
too; where a learner edits a Suricata rule or tunes CRS is not built yet
(backlog 0).

## Decisions left for a person

- **The tutorial**: designed and approved on 2026-10-08 as the learning MVP
  (backlog 0); not built yet.
- **Two licences behind the origins and the map.** MaxMind's GeoLite EULA
  asks for old databases to be deleted within 30 days of a new release and
  for the line "This product includes GeoLite Data created by MaxMind", which
  sits against "GeoIP is loaded once" (step 7 of backlog 2). For the MVP the
  user took the lightest path (2026-10-02): the `.mmdb` is not committed,
  `bin/fetch-geoip` pulls it and `config/ingest-geoip/README.md` carries the
  attribution. Whether to carry the database and that obligation into the
  production repo, and the 30-day refresh, is the part still left for a
  person. Cloudflare Radar's shares are CC BY-NC 4.0, fine here, to be looked
  at before they move to the production repo.
- The reasoning behind the placement and the WAF console is in
  `docs/superpowers/specs/2026-09-30-openstack-range-placement.md` and
  `docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`.

## What exists now

The shape of the product; detail is in `git log` and `docs/ARCHITECTURE.md`.

- **Range**: an Internet segment with thirty declared origin countries (Docker
  builds four: Russia, the default, Brazil, Hong Kong, United States), the
  internal network (`estate`) and management, crossed only at the WAF; two
  targets stand there, `http://board.com` and `http://corp.com`.
- **Red team**: one Kali image; cases fired from the console or a labelled
  shell; each case carries a Mandiant stage, ATT&CK/CAPEC ids, and what it takes.
- **Two targets.** A Django board on MySQL behind the WAF as `board.com`
  (Django 3.2.4, the `?sort=` order_by SQLi): `loot_verified`, the attacker
  submits exfiltrated `auth_user` hashes and the platform checks them against
  the snapshotted ground truth. A WordPress site behind the WAF as `corp.com`
  (three pinned-version CVEs, see "Sub-project B"): `effect_observed`, scored
  from `corp-db`'s own MySQL binary log. Each wargame is one folder,
  `wargames/<id>/`, whose `compose.yaml` the top one includes; `board` holds
  the board and its MySQL, `corp` the WordPress site and its MySQL. A test
  holds the folders, the includes and the console's catalogue to each other.
- **Score**: objectives (exfiltrated data or observed effect, checked against
  the target's own records) beside detection TP/FP/FN/TN with the
  `corroborated` gate; `platform/game.py` also computes a zero-sum balance,
  withheld until close (backlog 1, partly superseded).
- **Console**: the landing page `/` (sessions), a red console (cases, Kali
  terminal) and a blue console that is a sidebar framing Kibana and a WAF
  terminal; light theme, every value escaped. The blue dashboard, Live view,
  scoreboard tab, rule editor and world map were removed on 2026-10-05, and the
  pfSense GUI pane on 2026-10-08.
- **Stack**: every service `linux/amd64`; `docker compose up` is the whole
  bring-up (the platform entrypoint sets the socket group and registers the
  ingest pipeline).
- **Platform VM**: `deploy/openstack/platform.yaml` boots the whole stack on
  the OpenStack cloud as one Heat stack (backlog 2, step 1).
- **The range on OpenStack**: the platform builds the networks, the golden
  images and the slot (WAF and board as VMs) through
  `/api/range/fabric/`, `/images/` and `/slot/`, and reaches every host over
  ssh on `mgmt` (backlog 2, steps 2 and 3). pfSense (running Suricata) and the
  Kali attacker joined the slot on 2026-10-02 (steps 4 and 5).

## Backlog

The range is a web-entry range for now: attacks that come in through the
application, such as taking data out of a database. A foothold, privilege
escalation and persistence are a later goal, not this list's (decided
2026-09-28; `docs/THREAT-MODEL.md` already says so).

The deployment target (the user, 2026-09-30): the platform is an Ubuntu 24.04
VM inside the OpenStack cloud, brought up by `docker compose up`, and it
creates the range's VMs through the OpenStack API. Every product decision
behind the build is in "Decided on 2026-09-30" above and in
`docs/superpowers/specs/2026-09-30-openstack-range-placement.md`. More targets
(a WordPress site, a Java system) plug in where the board did.

### 0. The composable, session-isolated learning MVP (current, approved 2026-10-08)

Spec: `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`;
rulings in `docs/DECISIONS.md` (2026-10-08); build state in `docs/state/now.md`.
One session with two settings: guidance on/off, and baseline rules minimal or
full CRS. First lesson: tune CRS so the WAF blocks the board's `?sort=` SQLi
(CVE-2021-35042) while the benign O'Brien search passes, with Suricata sharing
the WAF's network namespace and detecting; completion is read from the target's own
records. Scope is WAF + IPS; the firewall lesson and the pfSense pane are out.
Build order, compose first and OpenStack later: (1) split compose into a shared
control plane and a per-session data plane (`docker compose -p fsl-<session>`);
(2) build each target image once, tagged, referenced by `image:`; (3) discover
scenarios from `wargames/<id>/scenario.yaml`, done in `81fb283`
(`board-easy`/`board-hard` and the defence fields wait for steps 1 and 7);
(4) declaration roles name compose services, resolved per project; (5)
`loot`/`effect` read the session's own target address; (6) a per-session index
`fsl-logs-<session>-*`; (7) the lesson (WAF `SecRuleEngine On` with CRS,
Suricata per session); (8) acceptance: two concurrent sessions, each scoring
only its own target and alerts (live gate, not yet run).

To do, found by the 2026-10-08 doc review (open until checked off):

- [ ] Build steps 1, 2, 4-8 on the OpenStack deployment; run the live
      acceptance there before the push (agreed 2026-10-08). Step 1 (control
      plane `compose.yaml`, per-session `session.yaml` as `fsl-<id>`) built
      2026-10-09; acceptance on substrate docker 138 passed, 0 failed.
- [x] On substrate openstack the board's ground truth was read from
      `BOARD_API_URL` (`http://board:8000`), the compose board on `estate`,
      not the OpenStack board VM. Readiness and the session baseline now read
      the board VM at the adapter's `address("board")` (management address);
      done 2026-10-09.
- [ ] The lesson's attack has to change the target's records: sqlmap's stock
      payloads do not finish the `?sort=` dump (only manual error-based
      extraction does). Settle the extraction before step 7 reads completion
      from the target.
- [x] Ingest from the console: the session page's confirm-close posts
      `/ingest/` before closing; done 2026-10-08.
- [x] CLI harness opens the session of the scenario matching the `--cases`
      basename; done 2026-10-08.
- [x] Remove the pfSense pane and the `:8080` proxy (`blue.html`,
      `nginx.conf:24-41`, `entrypoint.sh:16-40`, `pf_prime.py`,
      `compose.yaml:211`, the security group's 8080); dropped from scope
      2026-10-08 and removed the same day. pfSense itself stays as the OpenStack
      edge and sensor host.
- [x] Tool cases on OpenStack: the launcher ssh'd to Kali on the origin
      segment address, which collides with the platform's docker edge bridges
      (ru, br, hk, us) or times out (tw). It now ssh's over mgmt; sqlmap from
      ru and tw scored TP, alerts carry 5.188.10.10 and 120.96.0.10 (done
      2026-10-08).
- [ ] `POST /attacks/` does not wear the origin; the source country is the one
      last set by `/api/attacker/origin/` (the red console sets it when the
      origin is picked). An API caller that fires with another origin records
      an origin the traffic did not carry.
- [ ] Acceptance on substrate openstack (`FSL_PLATFORM_URL=http://192.168.0.210:8000
      bin/verify`, 2026-10-09: 23 passed, 78 skipped, 17 failed, 21 errors):
      session fixtures hold a session open while others POST a new one, and
      the single-slot range answers 409; `/api/rules/apply/` runs the compose
      reload (`suricatasc`) against the pfSense sensor because
      `FSL_SENSOR_RELOAD` is unset on the VM; the VM has no GeoLite2 database
      (`bin/fetch-geoip` never ran). The stale `blue.html` comparison test
      was removed 2026-10-09.
- [ ] Attacker image on OpenStack resolves from an env var (FSL_TOOL_IMAGE,
      set on the VM) rather than from the substrate in code; decide which.
- [ ] Seam exceptions: move the code or keep them recorded
      (`register_pipeline.py` for Elasticsearch, `range/pfsense.py` +
      `configure.php` for Suricata, `operator_log.py` + the `fsl-kali` terminal
      wiring for the attacker box).
- [ ] The red terminal and the blue WAF terminal (`/vm-terminal/`) do not
      connect on compose: Kali and the WAF have no `mgmt` address there.
- [ ] Spikes: Kibana highlight on stable `data-test-subj` selectors, and the
      CRS starting configuration (does default-PL CRS block the SQLi, does it
      false-positive on O'Brien).

### 1. The scoring redesign (partly superseded 2026-10-08)

Design in `docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`. One
zero-sum balance; the defence is a single score of four pillars (speed,
accuracy, coverage, response); revealed only when the session closes. The
target still decides which objectives fell.

Superseded on 2026-10-08 (`docs/DECISIONS.md`): the learner sees PASS/FAIL and
plain-language diagnostics derived from TP/FP/FN/TN, not the raw labels, the
four pillars or a balance, and there is no gamification. `game.py` and the
score API stay as built; the post-close scoreboard below is not planned for the
learner view.

Done: `platform/game.py` settles all four pillars against the attacker's take
into one balance (`GET /api/sessions/<id>/score/` carries `game`, withheld
until `ended_at`). Speed, accuracy and coverage are computed from data already
recorded; the response pillar's math is in place too (attacks blocked lift the
balance, benign blocked is an availability cost) and stays absent until a case
is actually blocked. A case carries its blocked disposition in `meta["blocked"]`.
Left:
- **Turn blocking on.** Nothing sets `meta["blocked"]` yet because nothing
  blocks. Decided: as in practice, the blue team turns on blocking itself, in
  the pfSense GUI (Suricata drop rules) and the WAF's mode (the pfSense GUI
  part is superseded: the pane was removed on 2026-10-08). Left: record which
  cases were blocked, read from the target side. Lands with item 2.
- **The scoreboard after close** on the landing page: the four pillars and the
  balance, with the declared weights visible. Superseded for the learner view
  (above). The live dashboard and rule editor were removed on 2026-10-05.
- **Weights and dwell** in `game.py` are v1 defaults (`WEIGHTS`, `FAST`/`SLOW`,
  `DETECTED_TAKE`); tune once the console shows them.

### 2. Build the range on OpenStack

The user's architecture, in this order (reorder if the user says so). Each
step ends with `describe()`/`segments()` and the acceptance suite reading it.

1. **The platform VM: done (2026-10-01).** `deploy/openstack/platform.yaml`
   is a Heat stack (a member may create stacks): network `fsl-platform`
   (`10.20.0.0/24`), a router to `provider`, a floating IP, a group opening
   only ssh and ping, and an Ubuntu 24.04 server whose cloud-init installs
   Docker, clones `repository` at `ref` into `/opt/fsl` and enables
   `fsl-platform.service`, which runs `docker compose up -d --build` on every
   boot. cloud-init writes every `FSL_OPENSTACK_*` setting but the password to
   `/opt/fsl/openstack.env` (0600, git-ignored), which compose gives the
   platform with `format: raw`; the operator appends the password over ssh
   (`README.md`). Checked on the cloud: a fresh stack
   went from create to all 11 services up in 3 min 20 s, and inside the
   platform container `FSL_SUBSTRATE=range.openstack.connect` returned the six
   `fsl-*` segments and the target VM from `describe()` and `segments()`.
   The platform itself stays on the Docker substrate until step 2. `bin/verify`
   on the VM: acceptance 126 of 126; the unit run fails only the 102 tests that
   need node, which the VM does not have.
   - **The tenant network's MTU is 1450** and Docker's bridges default to
     1500: TLS downloads from GitHub hung in the Kali build until curl timed
     out. The template writes the network's `mtu` attribute into
     `/etc/docker/daemon.json` (`mtu` and `default-network-opts`).
   - **Flavor** `m1.windows` (2 vCPU, 4 GB, 60 GB) is the largest a member can
     use; the stack takes about 2.4 GB, and cloud-init adds 4 GB of swap.
     Kibana (step 6) will need a bigger flavor, which only an admin can create.
   - **`ref` defaults to `dev`**, so the template clones this work only after
     it is pushed. The check above cloned a snapshot of this branch served
     from the operator's machine on the LAN.
   - **The password stays out of the user data.** The first version passed it
     as a hidden Heat parameter into cloud-init; Nova's metadata service
     answered from inside the Kali container (`meta_data.json`, 200), and the
     user data it serves would have carried the password.
   - **ModSecurity logged nothing on a Linux Docker host.** Its audit log was a
     bind mount of `deploy/nginx/logs`, which dockerd creates as root, and the
     WAF runs as nginx; colima's mounts hid it. It now sits on the named volume
     `waflogs` at the image's own `audit` directory, which belongs to nginx and
     which a fresh volume copies; Filebeat reads the volume read-only.
   - `FSL_OPENSTACK_SSH_KEY` names `/data/ssh/id_ed25519`, which nothing
     creates yet: step 2 makes it and registers it as a Nova keypair.
   - The kolla venv on the host has no Heat client; the stack was driven from
     a separate venv with `python-openstackclient` and `python-heatclient`.
   - Stack `fsl-platform` is still up, at floating IP `192.168.0.210`
     (server replaced on 2026-10-01 by a stack update; see step 3).
2. **Done (2026-10-01): the fabric from the platform, through the API**: one Internet network
   with a subnet per origin country (30, from a public traffic ranking, placed
   by GeoIP, about 100 addresses weighted by traffic), the internal (`estate`)
   and management networks. This replaces `bin/openstack-range`; the declaration
   gains a segment with many origin subnets.
   - **Done (2026-10-01): the thirty origins.** `declaration.yaml` has one
     `internet` segment whose `origins` list the top thirty countries by
     Cloudflare Radar's HTTP request share (frozen with its window), each with
     a /24 that GeoIP places there and its share of 100 addresses;
     `declared.read()` flattens each origin into a segment, so the port and
     its callers did not change, and `Declaration.origins` keeps the table.
     The default origin is `ru`, as before. Docker builds four (ru, br, hk,
     and us on 73.0.0.0/24 in place of North Korea, which the ranking drops).
     `bin/pick-origins` reproduces the table; legacy /8s are skipped so no
     origin is an institution's block. `test_origin_placement` checks all
     thirty through the live `fsl-geoip` pipeline.
   - **Done (2026-10-01): the fabric in code.** `range/fabric.py` is a pure
     planner: from the declaration and what the project holds it lists the
     networks (`internet`, `estate` 10.30.0.0/24, `mgmt` 10.31.0.0/24 with no
     gateway, off every compose and platform-VM subnet), the 32 subnets
     (DHCP off on the thirty origins), the keypair `fsl-platform`, and what
     drifted or is left over. The OpenStack adapter sends any verb (a 401
     re-signs and resends once), binds each origin to its subnet of the one
     Internet network by CIDR and keeps only hosts inside it, refuses a
     subnet no origin declares, and gains `plan_fabric`, `ensure_fabric`
     (create, then tag, deleting a network it could not tag; one bulk subnet
     POST; makes `/data/ssh/id_ed25519` and imports it) and `teardown_fabric`
     (refused while a server port stands). `GET/POST/DELETE
     /api/range/fabric/` exposes them; Docker answers 409, drift is a 409.
   - **Checked on the cloud (2026-10-01).** The stand-in range was removed
     (keypair `fsl-claude` kept), the platform stack rebuilt from the new
     template at floating IP `192.168.0.210`, where a browser opens the
     console on 8000 directly. Its platform, on `range.openstack.connect`,
     built `fsl-internet` with the thirty origin subnets, `fsl-estate`
     10.30.0.0/24 and `fsl-mgmt` 10.31.0.0/24 (DHCP on, no gateway) and the
     keypair `fsl-platform`; a second POST wrote nothing (32 present);
     `describe()` read back 32 segments from three networks; DELETE removed
     32 subnets, 3 networks and the keypair and left `fsl-platform` and
     `fsl-claude`; a POST rebuilt it clean. `bin/openstack-range` is gone.
     On the VM 8000 is bound to the VM's address, not loopback, so the
     acceptance suite's `localhost:8000` no longer reaches it there.
3. **Done (2026-10-01): targets and the WAF as VMs**: the board on MySQL and
   the WAF VM (nginx + ModSecurity + CRS). Golden images come from setup
   scripts in the repo, then snapshots. This step also built Juice Shop and
   the wiki as VMs; Phase 4 (2026-10-04) removed both from the declaration
   (see "The objective model").
   - **Done (2026-10-01): the images.** `declaration.yaml`'s `hosts:` names,
     per VM, a setup script and the files it needs (`deploy/waf/`,
     `wargames/board/image/` and the board's app). `range/images.py` packs
     each into a tar.gz whose digest is over paths, modes and contents; the
     platform boots a builder `fsl-build-<host>` from `ubuntu-24.04` on
     `FSL_OPENSTACK_BUILD_NETWORK` (the platform's own network, which has a
     router; the template writes it) with the bundle in its user data. The
     builder runs the setup and prints `fsl-image-ready <digest>` or
     `fsl-image-failed <digest>` to its console and stays up; the platform
     reads the console, stops a ready builder, snapshots it as `<host>` with
     the property `fsl_bundle`, and deletes the builder once the image is
     active. Every state comes from the cloud, so `POST
     /api/range/images/` is repeated until `clean`; `GET` reads, `DELETE`
     removes failed builders and images of another bundle. Versions match
     the Docker range: CRS 4.25.1,
     ModSecurity 3.0.16 compiled with connector 1.0.4 against Ubuntu's nginx
     1.24.0, each download pinned by sha256; the board runs Ubuntu's MySQL
     8.0 on the same VM.
   - **Checked on the cloud (2026-10-01):** the platform VM, given this tree
     and `FSL_OPENSTACK_BUILD_NETWORK`, built `fsl-waf` (4.8 GB)
     and the target images (2.3 to 3.2 GB, min disk 20) by repeated POSTs,
     each carrying the digest the Mac computes, with no builder left. Setup
     takes about four minutes for the board and seven for the WAF. The first WAF builds
     failed and said why on the console (CRS on 3.0.12, then a missing
     modules directory); `DELETE` cleared each and the next POST rebuilt.
   - **Ubuntu 24.04's libmodsecurity is 3.0.12**, which cannot parse CRS
     4.25's `XML://@*` targets (REQUEST-901 line 333); the OWASP image runs
     3.0.16. Hence the compile, about five minutes on one vCPU.
   - **Done (2026-10-01): the platform on management.** The fabric also
     makes two security groups, `fsl-range` (all IPv4 in, for every range
     port; anti-spoofing stays on) and `fsl-reach` (nothing in), and, when
     `FSL_OPENSTACK_PLATFORM` names the platform's own server, a port
     `fsl-platform.mgmt` in `fsl-reach` attached to it through
     `os-interface`. Teardown deletes that port first and still refuses any
     other server's. The template writes the server id at boot (`cloud-init
     query instance_id`) and a networkd file that DHCPs any NIC netplan does
     not claim, without its routes or DNS, then `networkctl reload`s. The
     runner reaches a host at its `mgmt` address unless a segment is named.
     Checked on the cloud: the live platform VM, given that file and its id,
     got `ens7` at `10.31.0.18/24` with its default route unchanged, the
     platform container connected to `10.31.0.1:53` through Docker's NAT,
     and a second POST read `clean`.
   - **Done (2026-10-01): the slot.** Each host in `hosts:` also declares
     its `segments` (every one includes `mgmt`) and its `names` on
     `estate`. `range/slot.py` plans a port `<host>.<segment>` per segment in
     `fsl-range` (Neutron picks the address where DHCP is on) and, for the
     host filling `gateway`, one Internet port holding every origin's
     gateway `.1`; it refuses a slot whose image is not ready, whose fabric
     lacks a segment, or whose non-gateway host stands on the Internet.
     The platform boots each host from its image with a config drive, the
     keypair `fsl-platform` and metadata `fsl_host`, and user data that
     appends every host's `estate` names to `/etc/hosts` and, on the gateway,
     a `bootcmd` adding all thirty addresses to the NIC with that port's MAC
     every boot. `GET/POST/DELETE /api/range/slot/`; `DELETE` removes the
     servers and the ports named for them.
   - **Checked on the cloud (2026-10-01, when the slot held four hosts):** one
     POST booted all four, all ACTIVE. Inside the
     platform container `describe()` returned `fsl-waf` on all thirty
     origins at each `.1`, the four hosts on `estate`, the five (the platform
     too) on mgmt, and no sensor. `runner()` over ssh to each mgmt address:
     MySQL and the board were active and answered 200, and the WAF held 33
     IPv4 addresses and proxied `board.com` (200) through the names in
     `/etc/hosts`. A request with a scanner's User-Agent was logged by
     ModSecurity 3.0.16 / CRS 4.25.1 (913100, 949110), the same producer
     line as the Docker WAF's.
   - **cloud-init applies only the first address of a port** that holds
     several (one per subnet), and adds a default route through each
     subnet's gateway, here the WAF's own address; hence the `bootcmd`.
     Without a config drive a guest gets no metadata at all: only its first
     NIC asks DHCP, and on the gateway that is the Internet, DHCP off.
   - **Checked end to end from the template (2026-10-01).** With the slot
     and the fabric taken down through the API (the platform's own port
     went first, then 32 subnets, 3 networks, the keypair and both groups,
     leaving only the stack and the images), a Heat `PATCH` of
     `fsl-platform` with this template and a clone of this branch served
     from the Mac on the LAN replaced the server (new id `7ed3db88...`) and
     kept `192.168.0.210`. cloud-init wrote `FSL_OPENSTACK_PLATFORM` and
     `FSL_OPENSTACK_BUILD_NETWORK`; after the password, one POST each built
     the fabric (the VM took `ens7`, `10.31.0.195`, by the template's
     networkd file), found the four images current, and booted the slot,
     and `describe()` and the runner gave the results above again. The
     range is left standing that way. Heat was driven by its REST API with
     `requests`; no Heat client was installed.
   - **The platform's ssh key lives on the VM** (`/data/ssh`, a named
     volume), so a replaced platform VM makes a new one and the fabric
     reports `fsl-platform` as drift; take the slot and the fabric down
     first (README).
   - **`README.ko.md` and `ARCHITECTURE.ko.md` mirror the English through
     step 7** (2026-10-03); the working-language rule now allows Korean in
     these two docs.
   - **Nova here answers 404 for the console of a guest that is off**
     ("Guest does not have a console available"), so a builder that powered
     itself off could never say how its setup went.
4. **pfSense CE** as the edge firewall with Suricata as its package; its logs
   by syslog to Elasticsearch.
   - **Done (2026-10-02): the image.** The user downloaded
     `netgate-installer-v1.2-RELEASE-amd64.iso` and agreed to its notice
     being accepted. Glance holds it as `netgate-installer` (with
     `hw_rescue_device=cdrom`, `hw_rescue_bus=scsi`) and the result as
     `fsl-pfsense`: pfSense CE 2.9.0-RELEASE on ZFS, WAN `vtnet0` by DHCP,
     LAN `vtnet1` 192.168.1.1/24, default admin login, qcow2, 1.7 GB, min
     disk 20, `hw_vif_model`/`hw_disk_bus` virtio, `os_distro=freebsd`. It
     was installed by hand (README, "The pfSense image"): a member cannot
     attach a blank disk here (no Cinder, no flavor with ephemeral disk), so
     a cirros server was rescued from the ISO, which Nova's stable rescue
     boots as a CD-ROM with the server's own disk still attached as
     `vtbd0`; the installer went onto that, and the server was unrescued
     and snapshotted. Installing CE asked for no account, only Internet
     (the `fsl-platform` network). A second server booted from the image
     came up to the console menu with its own device id.
   - **Done (2026-10-02, detail in "Left 1" to "Left 6" above).** The edge
     image `fsl-pfsense-edge` (base + Suricata 8.0.5 + sshd + MTU 1450 + OPT1
     mgmt) boots in the slot; `POST /api/range/configure/` plays
     `deploy/pfsense/configure.php` back over mgmt ssh and pfSense holds the 30
     origin `.1`s (static + 29 VIP aliases, IP up, IPv6/NAT off), runs Suricata
     on the WAN with the range as `HOME_NET` and EVE to syslog, and ships its
     syslog + the WAF's ModSecurity audit log to the platform's Elasticsearch,
     geolocated. The config-push is idempotent and the WAN pass rule survives
     the Suricata filter reload. The GUI pane is step 6 (dropped 2026-10-08).
5. **Kali VM** holding the country addresses, with the source rewritten as
   packets leave.
   - **Done (2026-10-02).** The `fsl-kali` image is built from
     `deploy/kali/setup.sh` on a `kali-rolling` base and boots in the slot on
     an origin + mgmt (the terminal/proxy/tooling baked in). Its one Internet
     port holds the ~100 per-country addresses (the slot `bootcmd` spreads them
     onto the NIC) and `/usr/local/sbin/fsl-origin` SNATs the box's source per
     country, so any origin fires. Proven from a clean image+slot rebuild.
6. **The sidebar and one port**: Kibana (the real ELK, reading the same
   Elasticsearch), the pfSense pane through a reverse-proxy on the platform's
   own `:8080`, and ttyd, all served by the platform image with no
   service or package added. **The terminal is done (2026-10-01):** nginx
   (from apt) runs inside the platform's image on 8000, `/` to waitress on
   `127.0.0.1:8001`, `/terminal/` to `kali:7681` (ttyd `-b /terminal`), and
   7681 is no longer published. waitress trusts only `127.0.0.1` for
   `X-Forwarded-For`, so the refusal of range addresses reads the real client
   as before; `/terminal/` asks `/api/attacker/` first (`auth_request`), and
   acceptance checks that a range host gets 403 there. **Done (2026-10-02):**
   the WAF's `:8080` publish is gone (host port 8080 then served the pfSense
   proxy, removed on 2026-10-08), and the acceptance suite and the
   command-line cases reach the target from inside the range through
   `test/range.py`'s runner (the attacker box for probes, the `scorer` host
   for `redteam/run.py`), not a host port. The same suite runs unchanged
   against the OpenStack range once `test/range.py` has its OpenStack adapter.
   **Done (the blue-console UI change, 2026-10-05/06):** the two
   blue-screen panes the earlier backlog held out, Kibana (in compose) and the
   pfSense GUI pane (a reverse-proxy on `:8080`, auto-logged-in), plus removing
   the custom console UI for the sidebar shell. See `docs/DECISIONS.md`. The
   2026-10-08 ruling drops the pfSense pane and the `:8080` proxy; both were
   removed the same day.
7. **Evidence by event time**, GeoIP in a durable bind mount, and the slot
   lifecycle (Stop rebuilds).
   - **Done (2026-10-02): evidence by event time.** The `fsl-geoip` pipeline
     sets `@timestamp` from Suricata's `timestamp` and ModSecurity's
     `transaction.time_stamp` (two date processors ahead of the geoip ones),
     so the ingest fetch window selects by event time, not Filebeat's read
     time. Core untouched; `test/test_event_time.py` is the guard.
   - **Done (2026-10-02): GeoIP's durable home.** The managed downloader is off
     and Elasticsearch reads `GeoLite2-City.mmdb` from a bind-mounted
     `config/ingest-geoip`; `bin/fetch-geoip` fills it (git-ignored, 63 MB),
     `config/ingest-geoip/README.md` carries the MaxMind attribution, and
     `test/test_geoip_durable.py` is the guard. Licence review for production
     still stands.
   - **Done (2026-10-02): the slot's Stop rebuild.** `rebuild_slot()` on the
     OpenStack adapter Nova-rebuilds every standing slot VM from its golden
     image (keeping id/flavour/ports/IPs), refusing before any write if the
     slot is not fully standing or an image is not ready; `POST
     /api/range/slot/rebuild/` (Docker 409s), unit-tested against the Nova
     fakes. A rebuild must be followed by `POST /api/range/configure/` once
     the VMs are ACTIVE (pfSense/WAF config is ssh-pushed, not baked).
   - **Done (2026-10-03): the session Start/Stop lifecycle and the READY gate.**
     `slot.Plan.active` (pure: clean + standing + every VM ACTIVE). `GET
     /api/range/ready/` is substrate-aware: compose answers `ready:true`,
     OpenStack answers the three read-only checks (active, ground truth readable,
     Suricata rules at baseline with no suppression in force) with a
     derived phase (NOT_STANDING / REBUILDING / CHECKING / READY). `POST
     /api/range/canary/` fires one known SQLi probe from the default origin
     (wear_origin + `harness.fire`), then
     reads Elasticsearch until both Suricata and ModSecurity alert on its marker
     and confirms the two engines' event clocks agree within `READY_SKEW` (5 s);
     it works on either substrate, so `test/test_ready.py` proves it end to end
     on compose. Session Start (`POST /api/sessions/`) refuses on a
     slot-bearing substrate if another session is open or the slot is not
     `_range_ready`; compose is unchanged (no slot), so the many-session tests
     stand. Session Stop (`close_session`) keeps observe -> stamp ended_at,
     then kicks off `rebuild_slot` (no ACTIVE wait); a failed rebuild leaves the
     session closed and says so. The console landing page polls `/ready/`,
     disables Start and shows the blocked reasons when not ready, and offers a
     canary button on the cloud; the close panel says the range rebuilds. No
     core line, no new Session field or migration, no new dependency or service.
   - **Not wired, by design:** Start does not itself fire the canary (that would
     leave an unattributed alert inside every session's ingest window); the
     canary is the between-sessions check the console runs after a rebuild, and
     Start's server-authoritative gate is the three read-only checks plus
     one-open-session. The minutes-long wait-ACTIVE -> `configure_slot` ->
     re-check after a Stop is sequenced by the console poll over the existing
     `/configure/` and `/slot/` endpoints, not inside `close`.
   - **Live-cloud verification is the user's to run** (the slot `active` check,
     the rebuild, and the canary firing through pfSense are proven against the
     Nova/ES fakes and, for the canary, end to end on compose; `test/range.py`
     has no OpenStack adapter, as for the rest of this backlog).

### 3. Sub-project B: the WordPress authz target `corp` - done 2026-10-04

The range's second target, after the board. See "Sub-project B" above for what
was built: three real, unauthenticated, pinned-version CVEs on `corp`
(`wargames/corp/`), scored `effect_observed` from the target's own MySQL
binary log via a substrate runner, proven end to end against the live stack.

## Known gaps

- The cloud was not touched by Phase 4. Juice Shop and wiki images or servers
  built there before 2026-10-04 are leftovers the declaration no longer names,
  and the live-cloud slot has not been re-checked as a two-host (WAF, board)
  slot.
- The first full `bin/verify` right after `docker compose up -d --build`
  (2026-09-30) failed 56 tests in `test_console_behaviour.py` that passed in
  `--fast` before it, alone, as a file, and in the next full run. The cause
  was not found; the output was truncated. It recurred on 2026-10-01 as two
  acceptance failures (one case of ten detected) that passed when rerun.
- `test_declaration.py` compares two files, never the running range.
- A slot host booted again on its own (its server deleted, then POST)
  takes a new `estate` address the others' `/etc/hosts` does not have; take
  the whole slot down and up instead.
- The platform mounts the Docker socket (non-root, via the socket's group): an
  escape path that goes away with the OpenStack adapter.
- The Kali terminal at `/terminal/`, and the ttyd terminals at
  `/vm-terminal/fsl-kali/` and `/vm-terminal/fsl-waf/`, are unauthenticated
  shells for whoever reaches the platform's port: loopback on compose, the VM's
  address (`FSL_PUBLISH`) on the platform VM.
- `elastic.fetch` reads at most 5000 documents per ingest, oldest first, `http`
  records included (a three-day window read 5000 of 42,231). Truncation drops
  the newest: the last cases fired become FN and the last benign ones TN, so a
  busier red team looks better defended. `Session.read_of` flags it and stays
  set after a later ingest that fits (`Session.truncated` was removed in
  migration 0012). Paging with `search_after` needs a monotonic write-time
  field; one `set: _ingest.timestamp` processor gives it.
- ModSecurity's `Detection.raw` holds the rule message, request, host and
  place, not the whole audit record.
- The operator log is lost when the attacker box is recreated, and its whole
  seconds let sessions under a second apart claim each other's commands.
- Two labelled windows under four seconds apart overlap (`WINDOW_SLACK` is two
  seconds each end), and the console does not say so.
- Nothing stops two people opening the same session in four windows. One user,
  one session was a deliberate scope decision.
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
