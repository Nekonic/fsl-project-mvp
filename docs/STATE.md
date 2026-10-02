# State

The handover between sessions. Keep it true; it is all the next session gets.
Finished work is one line each; the detail is in `git log`, `README.md` and
`docs/ARCHITECTURE.md`.

Updated: 2026-10-02

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

Backlog 2, steps 4 and 5 (pfSense edge + Kali attacker on OpenStack) are
**done end to end** (2026-10-02). The whole chain is proven on the cloud:
a case fired from the Kali box leaves as a chosen country, crosses
pfSense -> WAF -> Juice Shop, both sensors detect it, the logs reach the
platform's Elasticsearch geolocated, and the platform scores it.

**Backlog 2 step 6's in-scope part is done (2026-10-02):** the target port is
no longer published and the acceptance suite and command-line cases reach the
target from inside the range. **Step 7's first two parts are done too
(2026-10-02): evidence by event time, and GeoIP's durable home.** What is left
of backlog 2 is step 7's last part - the slot's Stop-rebuild lifecycle, which
the user is directing later (cloud work) - plus the two blue-screen panes the
user held out of this backlog (Kibana and the pfSense GUI pane) and the
board's user-database objective. On `dev`; `bin/verify` green.

**Committed this session (step 6, the acceptance/CLI move):**
- `compose.yaml` drops the WAF's `127.0.0.1:8080:80` publish; the target is
  reached only from inside the range now.
- The acceptance suite reaches the target through `test/range.py`'s runner:
  `conftest.target_code()`/`target_answers()` curl `http://shop.com` from the
  attacker box (so `stack_is_up`, `reset_target` and `test_criterion_1` no
  longer need a host port), and `test_front_door`'s probe fires through
  `from_attacker`.
- The command-line harness runs inside the range: `run_redteam()` execs
  `redteam/run.py` on the `scorer` host (the platform container) with
  `--target/--tool-target http://shop.com`, the way the console fires. A fresh
  run scored TP 8 / FP 0 / FN 2 / TN 6, both engines.
- `test_judge_isolation` drops 8080 from its published-port set; `README.md`
  and CLAUDE.md's "Running it" show the in-range invocation.

**Committed this session (step 7, evidence by event time):** the `fsl-geoip`
ingest pipeline now sets `@timestamp` from the event's own clock - Suricata's
`timestamp`, ModSecurity's `transaction.time_stamp` - with two date processors
ahead of the geoip ones, so the ingest fetch window selects evidence by when it
happened, not when Filebeat read it (read time ran 0.8-8.6 s late here). Core
is untouched: `platform/ingest/elastic.py` already timestamped detections by
event time and already re-checked the window by event time (`stale`); only the
fetch query disagreed. `test/test_event_time.py` holds `@timestamp` to the
event time for both engines.

**Committed this session (step 7, GeoIP's durable home):** on the user's
go-ahead to take the lightest path, the managed GeoIP downloader is off
(`ingest.geoip.downloader.enabled: false`) and Elasticsearch reads
`GeoLite2-City.mmdb` from a bind-mounted `config/ingest-geoip`, so a container
recreate - or the cloud's blocked CDN - no longer loses it. The `.mmdb` is not
committed (63 MB, git-ignored); `bin/fetch-geoip` fetches it from
`geoip.elastic.co` (MD5-checked) and `config/ingest-geoip/README.md` carries
the MaxMind attribution. `test/test_geoip_durable.py` holds the downloader off
and the pipeline still placing a source. The MaxMind licence review for the
production repo still stands (see "Decisions left for a person").

**Committed this session (step 7, the slot's Stop rebuild):** `rebuild_slot()`
on the OpenStack adapter Nova-rebuilds every standing slot VM from its golden
image (`POST {nova}/servers/{id}/action {"rebuild": {"imageRef": ...}}`, the
microversion already on every Nova call), which keeps each server's id,
flavour, ports and fixed IPs, so a session leaves no solved flag, edited rule
or planted datum for the next. It refuses before touching anything if the slot
is not fully standing or any standing host's image is not ready (the
refuse-before-write invariant `ensure_slot` holds). Exposed as
`POST /api/range/slot/rebuild/` (Docker 409s); unit-tested against the Nova
fakes (`test_openstack_slot.py`, `test_api_slot.py`). An adversarial 5-way
review (Nova API, lifecycle, fakes, edge cases, completeness) found and fixed
the readiness-inside-the-loop bug and surfaced two deliberate scope edges:

- **Re-configure must follow a rebuild.** A rebuild wipes the disk, so pfSense
  and the WAF lose the ssh-pushed config (`configure_slot`): WAN addresses, the
  WAN pass rule, Suricata, and the ModSecurity log forwarding; the targets are
  baked, so only the edge and WAF need it. Run `POST /api/range/configure/`
  once the VMs are ACTIVE again; until then the slot is not READY and the edge
  denies range traffic. Not auto-chained, because configure needs the VMs up -
  the ACTIVE wait is the READY gate below.
- **The trigger and the READY gate are the deferred session lifecycle.** "Stop
  rebuilds" is here as an operator action; firing it from session close,
  waiting for ACTIVE, re-configuring, and checking the slot answers for itself
  (nothing solved, rules at baseline, a canary alert) is the session
  Start/Stop design the user is directing. Live-cloud verification of the
  rebuild is also still the user's to run (the Nova rebuild is proven against
  fakes only).

**Committed this session (`4ec543b..HEAD`):**
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
canonical SQLi fired from Kali through pfSense to Juice Shop: the platform
scored **TP 1, FP 0, FN 0, TN 1**, the attack **corroborated** and credited to
**both engines** (pfSense Suricata `FSL SQLi attempt - URI` + ModSecurity CRS),
the benign a TN. The `objectives` dimension read 0 from Juice Shop (the probe
was detected but did not actually beat the target - the objective ground truth
is orthogonal to the detector, as designed), and `game.balance` revealed on
close.

**Re-verified 2026-10-02 (adversarial workflow + direct measurement + a clean
rebuild).** Left 1, 2, 3/4 and 6 each survived an independent read-only
refutation attempt against the live cloud + committed code (CONFIRMED). Left 5
was then proven from a bare slot+image rebuild (see below), which also exposed
and fixed the WAN-pass-rule bug. Two earlier claims were wrong and are
corrected here.

**Findings to carry:**
- **Syslog loss is a pfSense send-side burst problem, not the network, and
  paced traffic loses nothing** (measured, not asserted). Fire the SQLi 30x at
  0.5-1s spacing: pfSense detects 30, Elasticsearch indexes 30 - 0 loss, both
  engines. Fire 50 concurrently: pfSense detects 50, ES indexes 44 then 13 on a
  repeat (12-74%, variable). A dual tcpdump showed the dropped datagrams never
  reach the platform NIC and NIC-arrivals == ES-indexed, so the loss is at
  pfSense's FreeBSD syslogd under a burst, not the virtual network and not the
  receive buffer (raising `rmem_max` 80x to 16 MB changed nothing). Re-ingest
  does **not** recover a dropped datagram (it is gone, not late) - it only
  recovers a late one. Impact: the console fires cases one at a time (paced) ->
  0 loss; a bursty tool (sqlmap, 94 requests) loses a fraction of its many
  alerts but the case still scores TP (>=1 survivor across two engines). Only
  per-alert fidelity of bursty tools degrades. Session 3's FN earlier was this
  (one firing, one dropped alert). pfSense offers no non-UDP remote-syslog
  transport, so this is accepted, not fixed.
- The config-push is idempotent and keyed on the WAN Suricata instance / the
  VIP descr `fsl origin <id>` / the WAN pass rule descr / the `fsl_home` and
  `fsl_anywhere` pass lists, so a second `configure` changes nothing.

**Left 5/6 reproduced from a clean boot (2026-10-02), and it exposed a real
bug.** The whole slot was torn down, the Kali image rebuilt (its `setup.sh`
ships `/usr/local/sbin/fsl-origin`), and the slot re-booted and re-configured
through the API alone (`DELETE /slot/`, `DELETE`+`POST /images/` until clean,
`POST /slot/`, `POST /configure/`). The fresh Kali came up with **100 eth0
addresses from the slot `bootcmd`** and `fsl-origin` **from the image** - no
hand steps - and `POST /api/attacker/origin/` SNATs it per country. A fresh
scored session then read **TP 1, FP 0, FN 0, TN 1**, the SQLi corroborated
across both engines (ModSecurity 16 + Suricata 4 detections), src 120.96.0.10
geolocated TW.
- **The bug the rebuild found:** on a fresh pfSense, `configure.php` added the
  WAN pass rule and reloaded pf, but the **Suricata package sync that runs
  afterwards reloaded the filter and dropped it**, so the edge denied all range
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
  geolocates `src_ip` and ModSecurity's `transaction.client_ip`. Two ways carry
  it to a doc: filebeat's `output.pipeline: fsl-geoip` per request (the Docker
  path), and the `fsl-logs` index template's `index.default_pipeline`, which
  filebeat writes in only when it *first creates* the template - a long-running
  ES whose template predates the setting keeps a template without it, so set
  `index.default_pipeline` on the live data stream's write index there (the
  cloud needed this; a fresh VM does not). **Do not add
  `setup.template.overwrite: true` to force it - filebeat 8.15 then fails every
  write with "no matching index template found for data stream [fsl-logs]".**
  Acceptance fails if the live pipeline or the sensor's `local.rules` differ
  from the committed ones.
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
- **Every published port is on `127.0.0.1`, except 8000 on the platform VM**,
  which cloud-init binds to the VM's own address (`FSL_PUBLISH` in `.env`)
  and opens to any address with no login (the user, 2026-10-01); Django
  answers to its floating IP. Before, each segment's gateway
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
- **Same-site writes are refused too**: `:8080` (the target) and `:8000` are
  one site, and making the target run script is what the red team is scored
  on. A write with a body must be `application/json`.
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

`platform/range/openstack.py` is unit-tested against fakes built from the
published API reference's responses and a local unprivileged sshd; Keystone
is simplified (domain `default`, project by id). It is loaded only by name, and
a test holds every field it reads to the reference. It reads endpoints off the
Keystone v3 token's catalogue (`public`, `RegionOne` by default), renews the
token 30 s before `expires_at` and retries a 401 once, sends the Nova
microversion, follows `next` links (at most 50 pages), asks Neutron only for
tagged networks, and keeps fixed IPv4 addresses.

**Deployed on the KVM cloud (2026-09-30).** `master@192.168.0.100` (ssh key
`fsl_claude`, passwordless sudo); its API endpoints are on `192.168.0.110`.
It runs kolla-ansible 2026.1 (Gazpacho, the 22.x series; the host has
22.2.1.dev9), Ubuntu images, ML2/Open vSwitch, inventory `/root/all-in-one`.
**Tap-as-a-Service is on (2026-09-30, the user's go-ahead):**
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
compose's subnets, and `fsl-juice-shop` (ubuntu-24.04, m1.small, config drive)
on `fsl-estate`. Re-running `up` creates nothing. Through
`FSL_SUBSTRATE=range.openstack.connect` from the Mac, `describe()` returned
all six segments with their declared names and origins, the subnets, `.1`
gateways and network ids Neutron lists, `fsl-juice-shop` at its fixed address
on `estate`, and no sensors (no gateway or sensor server stands);
`segments()` returned the same. That stand-in is gone; since step 3 of
backlog 2 the platform VM reaches the range's hosts over `mgmt` and
`runner()` has run on each of them (`launcher()` has not run on a cloud).

Left for OpenStack, in order:

1. **Name resolution.** Compose gives away `shop.com`, `wiki.internal`,
   `juice-shop:3000` and `proxy:8081`; Neutron does not. Inside the estate
   it is done: the slot's user data appends every host's declared names to
   `/etc/hosts`. Left: `shop.com` and `board.com` for the attacker (step 5).
2. **Where the sensor sits.** Docker shares the WAF's namespace and the adapter
   confirms `watches`; on Nova nothing confirms it. Either Suricata rides the
   WAF instance or Tap-as-a-Service mirrors its ports.
3. **One attacker, every origin (decided by the user, 2026-09-30).** One Kali
   VM with a Neutron port on each origin network, and several addresses per
   origin so a blocked attacker can move to another (how many is not
   decided). The adapter still runs a tool on "the attacker on that segment"
   and refuses other segments; it has to find this one attacker on all of
   them.
4. **Roles are found by Nova server name**, which is not unique; segments are
   bound by tag for that reason, roles not yet. The slot marks its servers
   with metadata `fsl_host`, which `describe()` does not read yet. Credentials are settled:
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

## Decided on 2026-09-30 (the user)

- **Blocking works as in practice**: the blue team turns the WAF's blocking
  mode and the IPS's drop rules on and off itself.
- **An IPS outage is an infrastructure fault**, not part of the exercise; it
  is neither planned for nor scored.
- **Objectives do not centre on Juice Shop.** The board's user database
  (Django `auth_user`: accounts and password hashes) becomes something the red
  team can take. How the board judges from its own side that it was taken is
  still to design; the platform must not decide it. Juice Shop's
  continue-code restore is not pursued.
- **GeoIP is loaded once**, not refreshed: country ranges rarely move. **Its
  durable home is done (2026-10-02):** a bind mount of `config/ingest-geoip`
  with `ingest.geoip.downloader.enabled: false`, so the files survive a
  container recreate instead of vanishing with it. `bin/fetch-geoip` fills the
  bind mount with `GeoLite2-City.mmdb` from `geoip.elastic.co` (md5 checked);
  it is git-ignored (63 MB), so a fresh host runs that once before
  `docker compose up`. Before this, the files sat inside the container: the
  downloader failed at every Elasticsearch start (it runs before
  `.geoip_databases` has an active primary, then waits three days), one of its
  two download addresses (`172.64.66.1`) does not connect through the VPN, and
  turning it off on 2026-09-30 deleted the downloaded databases.
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
  managed in the pfSense GUI (placement spec, "pfSense").
- **The blue team reads alerts in Kibana**, read-only, and the blue dashboard
  mostly goes. Kibana returns to compose (a gated `services` step the user's
  call justifies), with Elasticsearch security on for a read-only role.
- **The platform UI is a left sidebar with three panes shown inside the
  page**: pfSense, Kibana, a terminal. No new-tab buttons. Kibana is framed
  directly. pfSense refuses framing and has no setting for it, so its pane is
  the Nova noVNC console of a small VM whose kiosk browser has the pfSense GUI
  open; the platform asks `POST /servers/{id}/remote-consoles` (member role,
  microversion 2.6+) for a fresh URL each time the pane opens (tokens last
  600 s; an open session outlives them). The terminal pane is ttyd, as Kali's
  already is. Horizon is never shown to users.
- **One published port (2026-10-01)**: everything happens on the website, so
  the platform's port is the only one published. The terminal, and Kibana
  when it comes, are reached through it by path. 9200 stays published for
  the acceptance suite, which is all that uses it (the user, 2026-10-01).
  8080 is no longer published (2026-10-02): the command-line cases and the
  acceptance suite reach the target from inside the range, through
  `test/range.py`'s runner.
- **Session start/stop and the scoreboard stay on the landing page `/`**,
  outside the sidebar; the sidebar is only the work screen.
- **Tap-as-a-Service is dropped from the design**: it was there for a sensor
  the blue team could not tamper with, which is no longer assumed. It stays
  enabled on the cloud, off every path.

## Left to engineering (no decision needed)

- `no_marker` per engine, without warning on raw-TCP-only sessions.
- `bin/verify` refuses to run while a person's session is open.
- The ratchet counts statements with the baseline from `HEAD`, and
  `scoreboard.py` moves into core.
- The terminal's label cleared on page load and at Stop; a tool killed on the
  attacker when its timeout passes; the rule editor refuses a rule indented so
  far that Suricata skips it; `fsl-logs-*` expire after 30 days, with a disk
  warning.

## Decisions left for a person

- **The tutorial**, to be designed later (the user).
- **How the board judges that its user database was taken** (held out of
  backlog 2 step 3 by the user, 2026-10-01). The board's `auth_user`
  (accounts and password hashes) on the board VM's MySQL is to be an
  objective, decided from the board's side like Juice Shop's `solved`, never
  by the platform. The board VM stands on the cloud; nothing judges yet.
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
  estate and management, crossed only at the WAF; target `http://shop.com`; an internal wiki reachable only by SSRF
  that judges its own reads.
- **Red team**: one Kali image; cases fired from the console or a labelled
  shell; each case carries a Mandiant stage, ATT&CK/CAPEC ids, and what it takes.
- **Two targets**: Juice Shop (judged — it flips its own `solved`) and a
  detection-only Django board on MySQL behind the WAF as `board.com`.
  `objectives.py` reads per scenario; a board session lists no objectives.
  Each wargame is one folder, `wargames/<id>/`, whose `compose.yaml` the top
  one includes: `juice-shop` holds Juice Shop and the wiki its SSRF reaches,
  `board` the board and its MySQL. A test holds the folders, the includes and
  the console's catalogue to each other.
- **Score**: objectives (target-decided) beside detection TP/FP/FN/TN with the
  `corroborated` gate; the zero-sum game score is being layered on (backlog 1).
- **Console**: one blue console (Dashboard, Live, Scoreboard, Rules), light
  theme, world map, every value escaped.
- **Stack**: every service `linux/amd64`; `docker compose up` is the whole
  bring-up (the platform entrypoint sets the socket group and registers the
  ingest pipeline).
- **Platform VM**: `deploy/openstack/platform.yaml` boots the whole stack on
  the OpenStack cloud as one Heat stack (backlog 2, step 1).
- **The range on OpenStack**: the platform builds the networks, the golden
  images and the slot (WAF, Juice Shop, wiki, board as VMs) through
  `/api/range/fabric/`, `/images/` and `/slot/`, and reaches every host over
  ssh on `mgmt` (backlog 2, steps 2 and 3). No attacker, pfSense or sensor
  VM yet.

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
  blocks. Decided: as in practice, the blue team turns on blocking itself, in
  the pfSense GUI (Suricata drop rules) and the WAF's mode. Left: record which
  cases were blocked, read from the target side. Lands with item 2.
- **The scoreboard after close** on the landing page: the four pillars and the
  balance, with the declared weights visible. Alerts move to Kibana and rules
  to pfSense (item 2), so the live dashboard and rules editor go.
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
   `fsl-*` segments and `fsl-juice-shop` from `describe()` and `segments()`.
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
   - **Acceptance cleared the wiki's read log by writing the host file**, which
     works on colima's mounts but not on a Linux Docker host, where the wiki
     writes it as root: 21 errors on the VM. `test/range.py`'s
     `forget_wiki_reads()` truncates it inside the wiki instead.
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
   by GeoIP, about 100 addresses weighted by traffic), the estate and
   management networks. This replaces `bin/openstack-range`; the declaration
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
3. **Done (2026-10-01): targets and the WAF as VMs**: Juice Shop, the board
   on MySQL, the wiki, and the WAF VM (nginx + ModSecurity + CRS). Golden
   images come from setup scripts in the repo, then snapshots. Left out of
   this step (the user, 2026-10-01): making the board's user database an
   objective, judged from the board's side; it is still to design (see
   "Decisions left for a person").
   - **Done (2026-10-01): the images.** `declaration.yaml`'s `hosts:` names,
     per VM, a setup script and the files it needs (`deploy/waf/`,
     `wargames/juice-shop/shop/`, the wiki's conf and site,
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
     the Docker range: Juice Shop 20.2.0 on node 24.19.0, CRS 4.25.1,
     ModSecurity 3.0.16 compiled with connector 1.0.4 against Ubuntu's nginx
     1.24.0, each download pinned by sha256; the board runs Ubuntu's MySQL
     8.0 on the same VM.
   - **Checked on the cloud (2026-10-01):** the platform VM, given this tree
     and `FSL_OPENSTACK_BUILD_NETWORK`, built `fsl-waf` (4.8 GB),
     `fsl-juice-shop`, `fsl-wiki` and `fsl-board` (2.3 to 3.2 GB, min disk
     20) by repeated POSTs, each carrying the digest the Mac computes, with no
     builder left. Setup takes about two minutes for Juice Shop and the
     wiki, four for the board and seven for the WAF. The first WAF builds
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
     its `segments` (every one includes `mgmt`) and its `names` on the
     estate. `range/slot.py` plans a port `<host>.<segment>` per segment in
     `fsl-range` (Neutron picks the address where DHCP is on) and, for the
     host filling `gateway`, one Internet port holding every origin's
     gateway `.1`; it refuses a slot whose image is not ready, whose fabric
     lacks a segment, or whose non-gateway host stands on the Internet.
     The platform boots each host from its image with a config drive, the
     keypair `fsl-platform` and metadata `fsl_host`, and user data that
     appends every host's estate names to `/etc/hosts` and, on the gateway,
     a `bootcmd` adding all thirty addresses to the NIC with that port's MAC
     every boot. `GET/POST/DELETE /api/range/slot/`; `DELETE` removes the
     servers and the ports named for them.
   - **Checked on the cloud (2026-10-01):** one POST booted `fsl-waf`,
     `fsl-juice-shop`, `fsl-wiki` and `fsl-board`, all ACTIVE. Inside the
     platform container `describe()` returned `fsl-waf` on all thirty
     origins at each `.1`, the four hosts on estate, the five (the platform
     too) on mgmt, and no sensor. `runner()` over ssh to each mgmt address:
     Juice Shop answered 200, the wiki served its page, MySQL and the board
     were active and answered 200, and the WAF held 33 IPv4 addresses and
     proxied `shop.com` and `board.com` (200 each) through the names in
     `/etc/hosts`. A request with a scanner's User-Agent was logged by
     ModSecurity 3.0.16 / CRS 4.25.1 (913100, 949110), the same producer
     line as the Docker WAF's, and Juice Shop reached `wiki.internal`.
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
   - **`README.ko.md` and `ARCHITECTURE.ko.md` do not describe step 3**:
     writing them means writing Korean, which CLAUDE.md keeps out of files.
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
   - **Done (2026-10-02, see "In progress" above for detail).** The edge
     image `fsl-pfsense-edge` (base + Suricata 8.0.5 + sshd + MTU 1450 + OPT1
     mgmt) boots in the slot; `POST /api/range/configure/` plays
     `deploy/pfsense/configure.php` back over mgmt ssh and pfSense holds the 30
     origin `.1`s (static + 29 VIP aliases, IP up, IPv6/NAT off), runs Suricata
     on the WAN with the range as `HOME_NET` and EVE to syslog, and ships its
     syslog + the WAF's ModSecurity audit log to the platform's Elasticsearch,
     geolocated. The config-push is idempotent and the WAN pass rule survives
     the Suricata filter reload. The GUI pane is step 6.
5. **Kali VM** holding the country addresses, with the source rewritten as
   packets leave.
   - **Done (2026-10-02).** The `fsl-kali` image is built from
     `deploy/kali/setup.sh` on a `kali-rolling` base and boots in the slot on
     an origin + mgmt (the terminal/proxy/tooling baked in). Its one Internet
     port holds the ~100 per-country addresses (the slot `bootcmd` spreads them
     onto the NIC) and `/usr/local/sbin/fsl-origin` SNATs the box's source per
     country, so any origin fires. Proven from a clean image+slot rebuild.
6. **The sidebar and one port**: Kibana (Elasticsearch security on, a
   read-only blue role), the pfSense pane through a kiosk browser VM's noVNC
   console, and ttyd, all behind the platform's one published port, with no
   service or package added. **The terminal is done (2026-10-01):** nginx
   (from apt) runs inside the platform's image on 8000, `/` to waitress on
   `127.0.0.1:8001`, `/terminal/` to `kali:7681` (ttyd `-b /terminal`), and
   7681 is no longer published. waitress trusts only `127.0.0.1` for
   `X-Forwarded-For`, so the refusal of range addresses reads the real client
   as before; `/terminal/` asks `/api/attacker/` first (`auth_request`), and
   acceptance checks that a range host gets 403 there. **Done (2026-10-02):**
   the WAF's `:8080` publish is gone, and the acceptance suite and the
   command-line cases reach the target from inside the range through
   `test/range.py`'s runner (the attacker box for probes, the `scorer` host
   for `redteam/run.py`), not a host port. The same suite runs unchanged
   against the OpenStack range once `test/range.py` has its OpenStack adapter.
   **Out of scope (the user): Kibana and the pfSense GUI pane** - the two
   blue-screen panes are not to be built in this backlog.
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
     fakes. **A rebuild must be followed by `POST /api/range/configure/`** once
     the VMs are ACTIVE (pfSense/WAF config is ssh-pushed, not baked).
   - **Left of step 7: wire the rebuild to session Stop, and the READY gate**
     (wait for ACTIVE, re-configure, check nothing solved / rules at baseline /
     a canary alert) - the session Start/Stop design the user is directing.
     Live-cloud verification of the rebuild is the user's to run.

## Known gaps

- The first full `bin/verify` right after `docker compose up -d --build`
  (2026-09-30) failed 56 tests in `test_console_behaviour.py` that passed in
  `--fast` before it, alone, as a file, and in the next full run. The cause
  was not found; the output was truncated. It recurred on 2026-10-01 as two
  acceptance failures (one case of ten detected) that passed when rerun.

- `test_declaration.py` compares two files, never the running range.
- A slot host booted again on its own (its server deleted, then POST)
  takes a new estate address the others' `/etc/hosts` does not have; take
  the whole slot down and up instead.
- The platform mounts the Docker socket (non-root, via the socket's group): an
  escape path that goes away with the OpenStack adapter.
- The Kali terminal at `/terminal/` is an unauthenticated root shell to
  whoever reaches the platform's port, which is published on loopback only.
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
