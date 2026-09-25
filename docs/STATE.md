# State

The handover between sessions. Keep it true; it is all the next session gets.
Finished work is one line each; the detail is in `git log`, `README.md` and
`docs/ARCHITECTURE.md`.

Updated: 2026-09-25 (compressed from 1,180 lines; claims rechecked against code)

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
- **Filebeat identifies files by fingerprint**: colima's virtiofs renumbers
  inodes when the VM restarts, and inode identity re-shipped both logs. 8.15
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
- **Build with `DOCKER_GID=$(bin/docker-gid)`**; the image refuses to build
  without it. Read on the Mac instead of inside the VM, the gid comes back `1`.
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
- Backlog item 1 and OpenStack item 3 are decisions too.

## Done since v1.0

One line each.

**The range**
- Three segments, the Internet as four origin networks, crossed only at the WAF.
- Attacks come from four countries chosen in the console.
- The target is `http://shop.com` on port 80: no appliance name, no port.
- An internal wiki, reached only through the app by SSRF, judges its own reads.
- An alert stores the host that held its address at ingest; addresses move.

**The red team**
- One Kali image (nmap, sqlmap, ffuf, hydra and more); `tool:` cases run in it.
- The shell is the red team; the case file is a scripted baseline.
- Two routes out: the proxy for HTTP, direct for raw TCP; windows record which.
- A window's address, origin and route are fixed at Start, not at Stop.
- Typed commands are kept per case: `GET /api/sessions/<id>/commands/`.
- Cases carry a Mandiant stage and ATT&CK and CAPEC ids, linked in the console.
- Cases declare what they take, and seven objectives fall instead of two.

**The score**
- Objectives lead it: the target flips its own `solved`.
- A breach goes to a malicious case that was running when the target stamped it.
- 13 challenges Juice Shop checks on a later request carry upper-bound stamps.
- A TP is corroborated by an `expect` match from a rule that hit no benign case.
  Failing that only raises `wrong_reason`; it is not an input to `detected`.
- A case recorded since migration 0009 stores the `expect` it was judged by.
  Older ones hold NULL (123 of the store's 125) and read the current catalogue,
  so editing cases re-scores their sessions.
- The score reports `unattributed` and `benign_cases`; FP is shown as `1 / 6`.
- `scoring/` returns `(key, *args)`, never sentences, and a test holds it there.
- Silencing a rule is the verdict; the ingest tick lifts it when it expires.
- A session closes once and observes the target at close. A case still running
  then stretches its end and observes the target anyway, or its breach is lost.
- An unreadable wiki keeps Juice Shop's verdicts and reports `unreadable`; a
  session with no baseline yet waits for a full read (a recorded decision).

**The console**
- One blue console: Dashboard, Live, Scoreboard, Rules; top-N, map and trend.
- The map is Equal Earth cut at 60°S (24 KB, was 68), draws the declared
  `defended_site` (Seoul) and a bowed line from each origin to it; its
  colours are six `--map-*` variables. `bin/worldmap`'s input
  `land-110m.json` is not in the repo; this map was rebuilt from the old SVG's
  own coordinates and has not been regenerated from the real file.
- The console is light: Elastic EUI Borealis 8.1.0 light tokens as CSS
  variables in `base.html`; `bin/build-css` builds only semantic colour
  names, so a default Tailwind colour builds nothing and a test refuses it.
  The Kali terminal stays black. No web fonts (offline).
- The Alerts table has 8 columns (source carries zone and country, the
  destination reads IP:port, time is HH:MM:SS) so path and case show at 1280.
- Tables read at half a screen: every cell padded, IPs and counts never
  wrap, signatures clamp to two lines with the full text in `title`.
- Every value is escaped before it reaches the page, and a test says so.
  Juice Shop's HTML descriptions are therefore turned into plain text by the
  API (`objectives._displayed`), or the escaping shows their tags.
- Red case cards name their objective from the list the page already has,
  rewriting only that line, so a late list cannot unlock cards mid-run. The
  stub DOM in `tests/browser.js` now parses `innerHTML`, so tests can click.
- A session with nothing fired shows no no-benign warning (raised only beside
  a malicious case, and it says to fire the benign ones), coverage of nothing
  as `-` (the API sends `null`), and each warning once.
- Polls run one at a time, catch up once on wake, and give up after 90 s.
- `_segments()` swallows `RangeUnavailable` on purpose: the dashboard draws
  without zones rather than not at all. Uncaught elsewhere, it is a 503.
- `platform/tests/browser.py` runs each page's scripts under node, without npm.
- Tailwind is built by `bin/build-css` and inlined; rebuild after a new class.

**Operations and tests**
- The wiki log starts with NULs; it is read with `grep -a`, or the match hides.
- OpenStack host keys are filed per instance generation, so a rebuild is new.
- Acceptance tests assert on their own case's evidence and close their sessions.
- Acceptance fails a run in which the stack alerted on its own traffic.
- Unit fixtures open sessions before their alert times, or `stale` drops them.
- Two tests comparing YAML strings were deleted; one passed on a blind sensor.

**Smaller**
- Dropped djangorestframework, Kibana, Django boilerplate, dead marker-probing.
- 2026-09-25 shrink: the refusals middleware answers 409/404/503/400 so views
  raise; both substrates share one `execute()`/`reported()` in `ports.py`;
  `views.py` 1,107 -> 999, core_loc 477 -> 472. Docs 1,252 -> 496 lines; the
  2026-09-18 design spec was superseded and deleted, its live decisions moved
  to ARCHITECTURE. `attacker.origins()` now reads the declaration loaded at
  startup, so an edit to it needs a restart.
- A slop sweep (2026-09-25): 139 findings, 80 upheld by two refuters each and
  applied. Error messages say what to change, a swallowed wiki or range error
  is reported, 23 tests that could not fail now can, config restating
  defaults is gone (`eve-log.alert.http` was a deprecated no-op). The 59 that
  one refuter rejected were not applied; rechecked, they are deliberate
  (ingest blanks the host during a range outage, `c83ea24`, pinned by
  `test_asset_identity.py`; the Protocols in `range/ports.py` state the port)
  or already caught elsewhere.

## Backlog

The user's direction, from the Korean red team playbook at www.xn--hy1b43d247a.com:
the range should cover more of the attack lifecycle than initial access. Its
nine stages are attacker infrastructure, initial reconnaissance, initial
access, foothold, privilege escalation, internal reconnaissance, lateral
movement, persistence, mission. The inside now exists; what is missing is
below.

### 1. A foothold to escalate from

Absent: foothold, privilege escalation, persistence. There is no code
execution on the target, so the estate is reached through the application
rather than from a shell on it, and there is nothing to escalate. Whether that
matters is a scope decision: a C2 and a foothold is a large step, and the
range may be more useful as a web-entry range that is honest about where it
stops.

It is the only item left on this list, and it is a decision rather than a
task: either the range grows a C2 and a foothold, or it says in the product
that it is a web-entry range and stops there. `docs/THREAT-MODEL.md` currently
says the second, because that is what is true today.

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
