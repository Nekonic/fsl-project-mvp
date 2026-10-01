# State

The handover between sessions. Keep it true; it is all the next session gets.
Finished work is one line each; the detail is in `git log`, `README.md` and
`docs/ARCHITECTURE.md`.

Updated: 2026-10-01

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
it. `bin/openstack-range up|down` (run on the host with that openrc, the
`openstack` CLI from `/root/kolla-venv`, and `FSL_RANGE_PUBLIC_KEY` for the
first keypair) creates keypair `fsl-claude`, security group `fsl-sg`
(22/80/3000/icmp), six networks `fsl-<id>` tagged `fsl.segment.id=<id>` with
compose's subnets, and `fsl-juice-shop` (ubuntu-24.04, m1.small, config drive)
on `fsl-estate`. Re-running `up` creates nothing. Through
`FSL_SUBSTRATE=range.openstack.connect` from the Mac, `describe()` returned
all six segments with their declared names and origins, the subnets, `.1`
gateways and network ids Neutron lists, `fsl-juice-shop` at its fixed address
on `estate`, and no sensors (no gateway or sensor server stands);
`segments()` returned the same. Not exercised: `runner()`/`launcher()` (the
tenant networks have no router or floating IP, so the Mac cannot reach the
VM), and the VM is bare Ubuntu with the target's name, no Juice Shop.

Left for OpenStack, in order:

1. **Name resolution.** Compose gives away `shop.com`, `wiki.internal`,
   `juice-shop:3000` and `proxy:8081`; Neutron does not. cloud-init writing
   `/etc/hosts` is the cheapest answer that keeps `shop.com`, and a target
   with no name is not the product.
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
- **GeoIP is loaded once**, not refreshed: country ranges rarely move. It
  still needs a durable home, a bind mount for `config/ingest-geoip` with the
  downloader off. Today the files sit inside the container: the downloader
  failed at every Elasticsearch start (it runs before `.geoip_databases` has
  an active primary, then waits three days), one of its two download
  addresses (`172.64.66.1`) does not connect through the VPN, and turning it
  off on 2026-09-30 deleted the downloaded databases, as documented. The same
  GeoLite2 files were fetched from `geoip.elastic.co` (md5 checked) and copied
  in; they vanish when the container is recreated.
- **Evidence is selected by event time**: `@timestamp` set from Suricata's
  `timestamp` and ModSecurity's own time, as ECS defines it and Elastic's own
  pipelines do, with every range VM's clock kept by chrony. Today it is
  Filebeat's read time, 5 s late median and 17 s worst.
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
  when it comes, are reached through it by path. 8080 and 9200 are used only
  by the command-line cases and the acceptance suite; they stop being
  published and those reach the target and Elasticsearch from inside the
  range, through `test/range.py`'s runner.
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
- **Getting pfSense CE**: its only installer comes from a $0 Netgate Store
  checkout with an account, which the user has to do.
- **How browsers reach the platform VM** from outside, now that it is on a
  floating IP: a login, a front proxy, or both.
- The reasoning behind the placement and the WAF console is in
  `docs/superpowers/specs/2026-09-30-openstack-range-placement.md` and
  `docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`.

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
   - Stack `fsl-platform` is still up, at floating IP `192.168.0.209`.
2. **The fabric from the platform, through the API**: one Internet network
   with a subnet per origin country (30, from a public traffic ranking, placed
   by GeoIP, about 100 addresses weighted by traffic), the estate and
   management networks. This replaces `bin/openstack-range`; the declaration
   gains a segment with many origin subnets.
3. **Targets and the WAF as VMs**: Juice Shop, the board on MySQL (its user
   database becomes an objective, judged from the board's side), the wiki,
   and the WAF VM (nginx + ModSecurity + CRS). Golden images come from setup
   scripts in the repo, then snapshots.
4. **pfSense CE** as the edge firewall with Suricata as its package; its logs
   by syslog to Elasticsearch. Needs the user first: the installer comes only
   from a $0 Netgate Store checkout with an account.
5. **Kali VM** holding the country addresses, with the source rewritten as
   packets leave.
6. **The sidebar and one port**: Kibana (Elasticsearch security on, a
   read-only blue role), the pfSense pane through a kiosk browser VM's noVNC
   console, and ttyd, all behind the platform's one published port, with no
   service or package added. ttyd speaks WebSocket, which waitress cannot
   carry, so nginx (from apt) runs inside the platform's image on 8000: `/`
   to waitress on `127.0.0.1`, `/terminal/` to `kali:7681` (ttyd `-b
   /terminal`). waitress trusts only `127.0.0.1` for `X-Forwarded-For`, so the
   refusal of range addresses reads the real client as before, and the
   terminal path asks the platform the same question first. Acceptance and
   the command-line cases stop using 8080 and 9200.
7. **Evidence by event time**, GeoIP in a durable bind mount, and the slot
   lifecycle (Stop rebuilds).

## Known gaps

- The first full `bin/verify` right after `docker compose up -d --build`
  (2026-09-30) failed 56 tests in `test_console_behaviour.py` that passed in
  `--fast` before it, alone, as a file, and in the next full run. The cause
  was not found; the output was truncated.

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
