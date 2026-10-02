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

Backlog 2, steps 4 and 5 (pfSense edge + Kali attacker on OpenStack). The
images, the standing topology and the un-NAT routing are proven on the cloud;
what remains is the detection pipeline, the config-push code, the per-country
attacker and the scored end-to-end run. On `dev` (pushed 2026-10-02);
`bin/verify` green.

**Committed (10 commits, `d240daf..92cd4d1`):**
- An OpenStack declaration **flavor**: `declaration.yaml` gains an `openstack:`
  overlay that `declared.read(flavor=...)` merges over the Docker base;
  `flavor_for()` picks it from `FSL_SUBSTRATE`, and `settings.RANGE` and the
  console's topology use it. In it `edge`=fsl-pfsense is the sensor
  (`watches: {sensor: edge}`), the WAF is estate+mgmt only and carries
  `shop.com`/`board.com`, and `fsl-pfsense` (prebuilt `image:`) and `fsl-kali`
  are hosts. A host declares a `setup:` script **or** a prebuilt `image:`, and
  may set its own `base:` image and `ssh_user:`.
- The slot boots pfSense from its image with no cloud-init (FreeBSD); the edge
  holds every origin `.1` + the estate `.1`, its forwarding ports carry
  `allowed_address_pairs 0.0.0.0/0` (un-NAT routing), and the attacker stands on
  the Internet too. `fsl-kali` builds on its own `kali-rolling` base.
- `pfsense.home_net()` builds the Suricata HOME_NET (30 origins + estate + mgmt).
- The runner reaches pfSense as `admin` (per-host ssh user), and its exit-report
  wrapper runs on FreeBSD's `/bin/sh` too (`sh -c '"$@"; ...' sh <argv>`, no
  `--`, which FreeBSD reads as the command).

**Cloud-verified (2026-10-02):**
- `kali-rolling` (Kali GenericCloud 2026.2, qcow2, min_disk 25) uploaded to
  Glance; the platform built **`fsl-kali`** end to end from
  `deploy/kali/setup.sh`.
- **`fsl-pfsense-edge`** built from the base `fsl-pfsense` through the web GUI
  (over an ssh tunnel): + the Suricata 8.0.5 package, sshd with the
  `fsl-platform` key on `admin`, WAN MTU 1450, and OPT1=vtnet2 as MGMT (DHCP,
  pass rule). The declaration's pfSense host names it.
- The slot stands in the pfSense topology: **fsl-pfsense** holds all 30 origin
  `.1`s + the estate `.1` (10.30.0.1) + a mgmt address; `fsl-kali` on an origin
  + mgmt; WAF and the targets on estate+mgmt. `describe()` shows pfSense as the
  sensor on every origin and Kali. NIC order held (internet=vtnet0,
  estate=vtnet1, mgmt=vtnet2); the platform reaches pfSense as root over mgmt
  ssh.
- **un-NAT routing works, source preserved**: with pfSense WAN set to one origin
  `.1`, outbound NAT off and a pass-all WAN rule (pushed by a pfSense 2.9
  `config_set_path` **playback** over mgmt ssh), Kali (120.96.0.208, Taiwan) →
  pfSense (120.96.0.1) → WAF (10.30.0.217) → Juice Shop: `curl http://shop.com/`
  = 200 "OWASP Juice Shop", a SQLi probe = 500. The WAF logs the client as
  120.96.0.208 (no NAT), so GeoIP places it right. Kali needs no manual routing
  (config-drive gave eth0 its origin address, a default route via `.1`, and
  `shop.com`/`board.com` → the WAF's estate IP in `/etc/hosts`).

**Findings to carry** (also memory `pfsense-cloud-config`):
- Configure pfSense from the **web GUI over an ssh tunnel**, not noVNC (noVNC
  key entry mangles `:`/`/`-heavy strings and drops `-`); the console is good
  only for the numeric interface menu (set LAN to fsl-mgmt DHCP+HTTP, then
  `ssh -L` through the platform VM).
- Push config as pfSense 2.9 **playback** scripts (`config_set_path`,
  `add_filter_rules`); `$config[...]` edits and `php -f` do **not** persist.
- `base64 -d` of a single line needs **`-A`** (else a silent empty file).
- `interface_configure('wan')` did **not** bring the WAN IPv4 up; `ifconfig
  vtnet0 inet <ip>/24 alias` did - the playback must force the interface up and
  set `ipaddrv6`=none.
- WAN MTU must be 1450; confirm NIC order each boot.

**Done (2026-10-02): Left 1, the WAN sticks.** `POST /api/range/configure/`
(`configure_slot()` -> `configure_edge()`) plays `deploy/pfsense/configure.php`
back on pfSense over mgmt ssh (`pfSsh.php playback fsl-edge`, settings as a
base64 JSON line ahead of the static script, sent on stdin). It sets the WAN
static at the first origin's `.1`, drops IPv6/`dhcphostname`/block-private,
holds the other 29 `.1`s as `ipalias` VIPs (uniqid `fsl<id>`, descr `fsl
origin <id>`, replaced each run), turns outbound NAT off, adds one WAN pass
rule `fsl range crosses the edge` if absent, kills the WAN's dhclient/dhcp6c,
configures the interface and VIPs, forces it up and `ifconfig ... alias`es any
address still missing, then prints `fsl-edge wan <addresses>`; the platform
refuses (409) unless all 30 are held. Cloud: two runs left 29 VIPs and one
rule; after a reboot pfSense came up holding all 30 with no dhclient, and Kali
reached `shop.com` (200). The stray dhclient started at the DHCP-WAN boot was
what wiped the hand-set address before.

**Done (2026-10-02): Left 2, Suricata on the WAN.** The same playback
configures the pfSense package (so the GUI shows it): pass lists `fsl_home`
(`pfsense.home()`: 30 origins + estate + mgmt) as HOME_NET and `fsl_anywhere`
(0.0.0.0/0) as EXTERNAL_NET (the default `!$HOME_NET` would exclude the
attackers), legacy mode, no blocking, EVE to syslog (local1.info) with only
`alert` and `http`, and a passthrough of dotted keys - Suricata's YAML loader
merges `detect.guess-applayer-tx: yes` and
`outputs.N.eve-log.types.M.http.dump-all-headers: request`, N and M read back
from `suricata --dump-config` of the generated file (two passes). The sensor
starts from `deploy/suricata/rules/local.rules` as its custom rules and no ET
set, **only when it is first created**: afterwards the rules are the blue
team's. The playback restarts it and prints `fsl-edge sensor vtnet0 running`,
which the platform requires. Cloud: a SQLi probe from Kali (120.96.0.208)
raised `FSL SQLi attempt - URI` in pfSense's alert log.

**Left, in order:**
**Done (2026-10-02): Left 3 and 4, the log pipeline, codified.**
`configure_slot()` now runs three idempotent steps over mgmt ssh and reports
what each host said:
- **The edge** also turns on remote syslog (`system_syslogd_start`,
  `remoteserver` = the scorer's mgmt address `:5140`, `logall`, RFC 5424) in
  the same playback, and the platform refuses unless it prints `logs <addr>`.
- **The WAF** (`range/waf.py`) gets an rsyslog drop-in that `imfile`-tails
  ModSecurity's own audit log (`SecAuditLog`, read from
  `deploy/waf/modsecurity.conf`) and `omfwd`s it UDP to the collector, tagged
  `modsecurity`, `maxMessageSize 64k`; written, `rsyslogd -N1`-checked and
  `systemctl restart`ed with sudo. Drift if it does not apply.
- **The collector** opens `fsl-reach` to exactly the edge and WAF on UDP 5140
  (`fabric.hearing`: one rule per sender, stale ones removed), and compose
  publishes Filebeat's new UDP syslog input on `${FSL_SYSLOG_PUBLISH:-127.0.0.1}`
  (the platform VM's `.env` sets `0.0.0.0`; the stack's group keeps 5140 shut
  on the floating IP, fsl-reach opens it per sender). Filebeat's `syslog`
  processor parses every line to `fsl_source: syslog`; a Suricata or
  ModSecurity line whose body is JSON is decoded and re-tagged so ingest
  normalizes it as before.
- Cloud: `POST /api/range/configure/` reported all three; a SQLi probe from
  Kali (120.96.0.208, carrying `X-FSL-Case`) produced in Elasticsearch a
  Suricata `alert` and its marked `http` event (both `pfSense.home.arpa`), a
  ModSecurity record (`fsl-waf`), and seven `filterlog` lines arrived whole.

**Left, in order:**
5. **Attacker addresses**5. **Attacker addresses** - the ~100 per-country addresses on Kali's one
   Internet port + the source rewrite (SNAT), so any origin fires, not just the
   Neutron-chosen one.
6. **End-to-end** - fire a case from the red console (`/terminal/`) →
   pfSense→WAF→target → blue console detection → TP/FP/FN/TN + objective score.

Each piece: test-first, `bin/verify`, commit, update STATE.

**Cloud state:** the slot's pfSense is configured by the platform (Left 1);
re-run `POST /api/range/configure/` after rebuilding the slot.

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
  when it comes, are reached through it by path. 9200 stays published for
  the acceptance suite, which is all that uses it (the user, 2026-10-01).
  8080 is used only by the command-line cases and the acceptance suite; it
  stops being published and those reach the target from inside the range,
  through `test/range.py`'s runner.
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
  sits against "GeoIP is loaded once" (step 7 of backlog 2). Cloudflare
  Radar's shares are CC BY-NC 4.0, fine here, to be looked at before they
  move to the production repo.
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
   - **In progress (2026-10-02, see "In progress" above for detail).** The
     edge image `fsl-pfsense-edge` (base + Suricata 8.0.5 + sshd + MTU 1450 +
     OPT1 mgmt) is built; the slot stands with pfSense holding the 30 origin
     `.1`s and the estate `.1`; un-NAT routing Kali→pfSense→WAF→target is
     proven on the cloud with the source preserved. Left: the WAN config
     sticking (30 VIP aliases, the IP up), Suricata on the WAN interface with
     `HOME_NET`, the syslog→Elasticsearch pipeline, and codifying the
     config-push. The GUI pane is step 6.
5. **Kali VM** holding the country addresses, with the source rewritten as
   packets leave.
   - **In progress (2026-10-02).** The `fsl-kali` image is built from
     `deploy/kali/setup.sh` on a `kali-rolling` base and boots in the slot on
     an origin + mgmt (the terminal/proxy/tooling baked in). Left: the ~100
     per-country addresses on its one Internet port and the source rewrite, so
     any origin fires (see "In progress").
6. **The sidebar and one port**: Kibana (Elasticsearch security on, a
   read-only blue role), the pfSense pane through a kiosk browser VM's noVNC
   console, and ttyd, all behind the platform's one published port, with no
   service or package added. **The terminal is done (2026-10-01):** nginx
   (from apt) runs inside the platform's image on 8000, `/` to waitress on
   `127.0.0.1:8001`, `/terminal/` to `kali:7681` (ttyd `-b /terminal`), and
   7681 is no longer published. waitress trusts only `127.0.0.1` for
   `X-Forwarded-For`, so the refusal of range addresses reads the real client
   as before; `/terminal/` asks `/api/attacker/` first (`auth_request`), and
   acceptance checks that a range host gets 403 there. Left: Kibana, the
   pfSense pane, and acceptance and the command-line cases off 8080.
7. **Evidence by event time**, GeoIP in a durable bind mount, and the slot
   lifecycle (Stop rebuilds).

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
