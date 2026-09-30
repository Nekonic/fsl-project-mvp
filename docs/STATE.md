# State

The handover between sessions. Keep it true; it is all the next session gets.
Finished work is one line each; the detail is in `git log`, `README.md` and
`docs/ARCHITECTURE.md`.

Updated: 2026-09-30

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md`; all four of its
phases are done.

`bin/verify` is green and prints the scores. Neither they nor the baseline are
copied here; read `metrics.json`. Copies in prose went stale twice.

The whole loop runs in a browser. Open `/`, start a session, open the red and
blue consoles side by side, fire cases from one, watch the score move in the
other, edit a Suricata rule and fire again. An attack typed at the red
console's Kali terminal between start and stop is scored by time and source
and by the proxy's marker. The blue console ingests on a timer, and any alert
opens its whole Elasticsearch record.

## In progress

Nothing half-finished. The last session left the tree green and committed.

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
- **`$HTTP_PORTS` is `[80,3000]`**, the ports on the WAF's wire. Docker
  translates `8080` before the sensor sees it (same rule A/B: `8080` 0 alerts,
  `[80,3000]` 2, `any` 4).
- **A rule experiment writes to the shipped rules file**, the live artifact,
  so it uses sids at or above 9009000 and `test_sensor_rules.py` refuses those.
  Before each half of an A/B, check the loaded config inside the container: a
  12-second wait that missed the sensor's start nearly buried the one above.
- **Filebeat identifies files by fingerprint**: inodes are renumbered when the
  Docker host restarts, and inode identity re-shipped both logs. 8.15
  does not migrate the registry, so changing identity again re-ships once.
  Ingest drops an alert whose event time is outside the window, as `stale`.
- **The ingest pipeline is installed by hand** (CLAUDE.md, Running it) and
  geolocates `src_ip` and ModSecurity's `transaction.client_ip`. Acceptance
  fails if the live pipeline or the sensor's `local.rules` differ from the
  committed ones.
- **The WAF's health check asks `/healthz`**, which the WAF answers itself;
  sent through to Juice Shop it alerted every ten seconds and used up a
  session's 5,000-document read in about 14 hours. The wiki's check asks
  `127.0.0.1`: its conf is read-only, so nginx adds no IPv6 listener.
- **Bring-up is a single `docker compose up -d --build`.** The platform's
  entrypoint reads the docker socket's group from the socket at start, adds
  `fsl` to it, drops root with `gosu`, and registers the `fsl-geoip` ingest
  pipeline itself, so a fresh host needs no build argument and no manual PUT.
- **The store is the named volume `fsl_platformdata`**, not `./data` of
  whichever checkout ran `compose up`; `./data/label` is still a bind mount.
  `bin/backup` copies the store live; restore (README) has never been run.
- **Every published port is on `127.0.0.1`.** Before, each segment's gateway
  forwarded 8000, 9200, 7681 and 8080 into the platform from inside the range
  (8 of 8 reached). `DJANGO_DEBUG=1` is safe only because of this. Another
  machine needs a tunnel, not a wider `ALLOWED_HOSTS`: it is
  `localhost,127.0.0.1,[::1]` (`DJANGO_ALLOWED_HOSTS` overrides) because at `*`
  DNS rebinding passed the same-origin check, which trusts the request's Host.
- **The platform refuses any address standing in the range** (403;
  participants cached 30 s). The operator arrives from a segment's gateway
  (`5.188.10.1`), the attacker box as a node (`5.188.10.2`). The rule reads
  `segments()`, which needs no sensor. If that raises `RangeUnavailable` it
  fails open for the 30 s the empty answer is cached; any other error is a 500.
- **Same-site writes are refused too**: `:8080` (the target) and `:8000` are
  one site, and making the target run script is what the red team is scored
  on. A write with a body must be `application/json`.
- **`bin/verify`** restarts the platform first (waitress never reloads), waits
  up to two minutes for the target (else TP 0 reads as a failed defence),
  refuses a stack another checkout brought up, and prunes only the sessions its
  run listed in `FSL_ACCEPTANCE_SESSIONS`.
- **The ratchet.** `bin/measure` counts `git ls-files -z`, so verify fails on
  an untracked file. It refuses a compose override or `include:`, counts only
  tests pytest collects and refuses duplicate names. It counts physical lines,
  so joining a wrapped line "shrinks" core: never do that.

## The substrate seam

Docker was the MVP shortcut; OpenStack is the target. `platform/range/` is the
port: `describe() -> Shape`, `segments()` (who stands where, without the
sensor), `runner(role, segment)` and `launcher(segment)`. `range.substrate()`
is the one place a name becomes an adapter (`FSL_SUBSTRATE`, options keyed by
substrate; a test refuses a second `import_string`), and `redteam/run.py` uses
it too. Core, `topology.py`, `attacker.py` and `objectives.py` never call
Docker. `test/range.py` is the acceptance suite's side of the port.

`platform/range/declaration.yaml` declares per segment an id, a name and an
attack origin, a role table, and `watches: {sensor: gateway}`; the Docker
adapter, `fsl/settings.py` and `test/range.py` read it. Identity is declared,
allocation reported: a declared subnet that disagreed with the real one would
bin alerts by a subnet nothing lives on. `test_declaration.py` holds
`compose.yaml` to it. A segment is bound by its `fsl.segment.id` mark (Docker
label, Neutron tag), never by name: compose overrides, Heat stack suffixes,
non-unique Neutron names and a project called `fsl_lab` broke name rules.

`platform/range/openstack.py` runs only against fakes built from the published
API reference's responses and a local unprivileged sshd, not a cloud; Keystone
is simplified (domain `default`, project by id). It is loaded only by name, and
a test holds every field it reads to the reference. It reads endpoints off the
Keystone v3 token's catalogue (`public`, `RegionOne` by default), renews the
token 30 s before `expires_at` and retries a 401 once, sends the Nova
microversion, follows `next` links (at most 50 pages), asks Neutron only for
tagged networks, and keeps fixed IPv4 addresses.

Left for OpenStack, in order:

1. **Name resolution.** Compose gives away `shop.com`, `wiki.internal`,
   `juice-shop:3000` and `proxy:8081`; Neutron does not. cloud-init writing
   `/etc/hosts` is the cheapest answer that keeps `shop.com`, and a target
   with no name is not the product.
2. **Where the sensor sits.** Docker shares the WAF's namespace and the adapter
   confirms `watches`; on Nova nothing confirms it. Either Suricata rides the
   WAF instance or Tap-as-a-Service mirrors its ports.
3. **One attacker, four origins (a decision).** Nova cannot boot a host per
   tool and hand back its output, so a tool runs over ssh on the attacker on
   that segment, and other segments are refused. Declare an attacker per
   origin, or accept one attacking position on OpenStack.
4. **Roles are found by Nova server name**, which is not unique; segments are
   bound by tag for that reason, roles not yet. Credentials are settled:
   `FSL_SUBSTRATE=range.openstack.connect` and `FSL_OPENSTACK_*`, each refused
   by name when missing.
5. **Does the operator still look like an outsider?** The reachability rule
   works because Docker DNATs the published port to a gateway. A Neutron router
   presenting the operator's own address is fine; one presenting a node's
   locks the operator out and lets the red team in. Test this first on a cloud.
6. **Floating IPs and router SNAT.** The adapter keeps the fixed address. A
   router's SNAT makes Suricata see the router, not the attacker; the stamping
   proxy has no Neutron equivalent yet.

Settled since the sketch: the default origin, the sensor reload, whether a
sensor is a participant, subnets per segment, binding, and who starts a tool.

## Decisions left for a person

- **GeoIP stops on about 2026-10-18.** The downloader has not succeeded since
  2026-09-18 (`_ingest/geoip/stats`: 0 successful, still so on 2026-09-25) and
  its databases expire after 30 days. Mount GeoLite2 `.mmdb` files (MaxMind
  account and licence) and disable the downloader, or let it lapse knowingly.
- **Which clock selects evidence.** Ingest uses `@timestamp`, Filebeat's read
  clock, with a one-minute tail; measured lag is 5 s median, 17 s worst.
  Rewriting it to event time in the pipeline removes the dependency, but the
  index then holds both meanings unless backfilled.
- **The terminal's origin file holds the WAF's address, which moves** across
  recreations (.4, .5, .4); the terminal keeps the old one until the red page
  reloads or an origin is chosen. Pin addresses (a reserved IPAM range, so the
  networks are recreated), or have the platform rewrite a stale file.
- **`no_marker` per engine.** It fires only when no detection has a marker, so
  a sensor that lost all of them is silent while the WAF keeps its own. Per
  engine it must not warn on raw-TCP-only sessions, and it costs core lines.
- **Whether verify may share a stack with a person.** It touches only its own
  sessions but resets the target, the rules and the attacker's origin.
- **The console's clock** (UTC like the server and operator log, or local), and
  whether an undefined precision or recall should be null, not 0.0.
- **How the ratchet counts:** statements instead of physical lines, the
  baseline from `HEAD` instead of the working tree, and whether `scoreboard.py`
  and parts of the views are core.
- **Defaults to confirm:** ModSecurity severity 0-2 is High (CRS's blocking
  rule carries 0, its attack rules 2); an OpenStack segment binds its single
  IPv4 subnet and refuses a second.
- **Not done, waiting on a call:** the terminal's label left after a page
  reload; a tool outliving its timeout (not killed on the host); a rule
  indented enough that Suricata skips it (waits on the ratchet question);
  retention for `fsl-logs-*` (nothing expires it; a full disk makes indices
  read-only and Filebeat stop silently; expiry deletes evidence).
- **45 of the store's 60 sessions are open**, all started 2026-09-23 between
  16:56 and 17:44 by acceptance runs. Nothing proves none is a person's. Count
  them in `/data/db.sqlite3`: `GET /api/sessions/` returns at most 25.
- OpenStack item 3 is a decision too.

## What exists now

The shape of the product; detail is in `git log` and `docs/ARCHITECTURE.md`.

- **Range**: three segments plus four Internet origin countries, crossed only
  at the WAF; target `http://shop.com`; an internal wiki reachable only by SSRF
  that judges its own reads.
- **Red team**: one Kali image; cases fired from the console or a labelled
  shell; each case carries a Mandiant stage, ATT&CK/CAPEC ids, and what it takes.
- **Two targets**: Juice Shop (judged — it flips its own `solved`) and a
  detection-only Django board on MySQL behind the WAF as `board.com`.
  `objectives.py` reads per scenario; a board session lists no objectives.
- **Score**: objectives (target-decided) beside detection TP/FP/FN/TN with the
  `corroborated` gate; the zero-sum game score is being layered on (backlog 1).
- **Console**: one blue console (Dashboard, Live, Scoreboard, Rules), light
  theme, world map, every value escaped.
- **Stack**: every service `linux/amd64`; `docker compose up` is the whole
  bring-up (the platform entrypoint sets the socket group and registers the
  ingest pipeline).

## Backlog

The range is a web-entry range for now: attacks that come in through the
application, such as taking data out of a database. A foothold, privilege
escalation and persistence are a later goal, not this list's (decided
2026-09-28; `docs/THREAT-MODEL.md` already says so).

The scoring redesign is the active work. The deployment target is now settled:
one Ubuntu 24.04 x86_64 instance where you clone and run `docker compose up` —
the whole stack in Docker on one VM. `range/openstack.py` (a Nova server per
segment) is only needed if a target must be non-Linux (FreeBSD, Windows), since
those cannot be containers; every current target is Linux, so it is not on this
path. More targets (a WordPress site, a Java system) plug in where the board
did.

### 1. The scoring redesign (in progress)

Design in `docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`. One
zero-sum balance; the defence is a single score of four pillars (speed,
accuracy, coverage, response); revealed only when the session closes. The
target still decides which objectives fell.

Done: `platform/game.py` settles all four pillars against the attacker's take
into one balance (`GET /api/sessions/<id>/score/` carries `game`, withheld
until `ended_at`). Speed, accuracy and coverage are computed from data already
recorded; the response pillar's math is in place too (attacks blocked lift the
balance, benign blocked is an availability cost) and stays absent until a case
is actually blocked. A case carries its blocked disposition in `meta["blocked"]`.
Left:
- **Turn blocking on.** Nothing sets `meta["blocked"]` yet because nothing
  blocks: the WAF is `DetectionOnly` and Suricata is IDS. This is the user's
  "IPS/IDS/Firewall basics" and it needs an infrastructure decision (how
  blocking physically happens, and who toggles it), then wiring that records
  which cases were blocked.
- **Console**: show the four pillars and the balance after close, with the
  declared weights visible; keep alerts and the rules editor live during the run.
- **Weights and dwell** in `game.py` are v1 defaults (`WEIGHTS`, `FAST`/`SLOW`,
  `DETECTED_TAKE`); tune once the console shows them.

### 2. Deploy the range on OpenStack (next session)

`range/openstack.py`'s read path works against a real kolla cloud. The range
is not deployed there yet (no `fsl.segment.id`-tagged network, so `describe()`
raises). This path is for the non-Linux/multi-VM case; the one-VM Docker
deployment does not use it.

KVM cloud at `master@192.168.0.100` (ssh key `fsl_claude`, passwordless sudo).
Steps: create the image/flavour/keypair/security group, the six
`fsl.segment.id`-tagged networks, a role-named target VM, then run
`describe()`/`segments()` against it. See the `openstack-test-cloud` memory.

## Known gaps

- `test_declaration.py` compares two files, never the running range.
- The platform mounts the Docker socket (non-root, via the socket's group): an
  escape path that goes away with the OpenStack adapter.
- The Kali terminal on 7681 is an unauthenticated root shell, loopback only.
- `elastic.fetch` reads at most 5000 documents per ingest, oldest first, `http`
  records included (a three-day window read 5000 of 42,231). Truncation drops
  the newest: the last cases fired become FN and the last benign ones TN, so a
  busier red team looks better defended. `Session.truncated` and `read_of` flag
  it and stay set after a later ingest that fits. Paging with `search_after` needs a monotonic write-time field; one `set:
  _ingest.timestamp` processor gives it, and any ES-only store needs it too.
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
- The rule editor's unsaved text is replaced when it reloads after a change: a
  trade-off against writing back a stale file.
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
- **Asserting that no alert in a red team window is unmarked.** It is false: a
  window reaches a minute either side, so it holds whatever used the range
  just before. That is why `unattributed` is reported, not asserted;
  acceptance checks only for the stack alerting on its own traffic (loopback
  source or the numeric-Host signature).
- **Feeding window correlation the scorer's address.** It would measure the
  judge, not the defence; a zero with a stated reason beats that number.
