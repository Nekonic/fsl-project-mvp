# Architecture

How the range is built, how traffic and evidence move through it, and the
design decisions behind it. How the score is defined is in `CLAUDE.md`; open
problems and measured quirks are in `docs/STATE.md`.

Everything up to "Decisions" describes what runs today: a Docker compose
range. The product is moving onto OpenStack. What exists of that and what has
been decided are kept apart in the last section, "OpenStack".

The hypothesis the repo started from: red team attacks can be labelled with
ground truth, and Suricata and ModSecurity alerts can be matched to those
labels automatically, so false positives and negatives can be scored
mechanically. The objective score was added on top once that held.

## The range

Eleven compose services on six Docker networks. The targets are grouped by
wargame, one folder each under `wargames/`, whose `compose.yaml` the top
`compose.yaml` includes: `juice-shop` (Juice Shop and the wiki its SSRF
reaches) and `board` (the board and its MySQL). A new wargame is a new folder
and one more `include:` line; the measure counts the services it adds.

| Service | Image | Networks | Host port |
|---|---|---|---|
| `fsl-juice-shop` | `bkimminich/juice-shop` | estate | |
| `fsl-board` | `wargames/board/app` (Django under gunicorn, port 8000) | estate | |
| `fsl-board-db` | `mysql` | estate | |
| `fsl-wiki` | `nginx`, alias `wiki.internal` | estate | |
| `fsl-waf` | `owasp/modsecurity-crs` (nginx), alias `shop.com` on edge, `board.com` on all four edge networks | edge, edge-br, edge-hk, edge-kp, estate | 8080 |
| `fsl-suricata` | `jasonish/suricata` | the WAF's namespace | |
| `fsl-elasticsearch` | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-filebeat` | `filebeat:8.15.0` | mgmt | |
| `fsl-kali` | `deploy/kali` | edge | 7681 |
| `fsl-proxy` | `deploy/proxy` (mitmdump) | the four edge networks | |
| `fsl-platform` | `platform/` (Django) | all six | 8000 |

| Network | Subnet | Name | Origin |
|---|---|---|---|
| `edge` | 5.188.10.0/24 | Internet | Moscow, Russia |
| `edge-br` | 177.54.144.0/24 | Internet | Sao Paulo, Brazil |
| `edge-hk` | 103.152.220.0/24 | Internet | Kwai Chung, Hong Kong |
| `edge-kp` | 175.45.176.0/24 | Internet | North Korea |
| `estate` | 172.30.0.0/24 | Application estate | |
| `mgmt` | 172.31.0.0/24 | Management | |

Segmentation is Docker network membership only: no firewall, no iptables, no
ACL. `test/test_segmentation.py` asserts it against the live stack (Kali
reaches `shop.com` but not `juice-shop:3000`). Only the subnets are fixed;
container addresses are assigned by Docker and change on recreate. The views
build a new adapter and read them on every request. The rule that refuses
requests from range hosts caches their addresses for 30 s, and when it cannot
reach the substrate it treats the range as empty and lets the request through
(`docs/THREAT-MODEL.md`).

The platform, the WAF and the proxy are multi-homed. The attacker's traffic
crosses into the estate only at the WAF, but the platform stands on every
segment, which is why the API guards itself (`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --console-fired case--------------+
 edge-br                                              |
 edge-hk   proxy, platform (no kali, no shop.com)     |
 edge-kp                                              v
         fsl-waf: nginx + ModSecurity CRS, DetectionOnly, port 80
         fsl-suricata in the same network namespace, af-packet on all five
         interfaces, so it sees client->WAF and WAF->target
                                                      |
 estate    juice-shop:3000 <--any other Host----------+
           board:8000 <--Host: board.com--------------+
           juice-shop --SSRF--> wiki.internal
           board --> board-db (MySQL)
 mgmt      filebeat --> elasticsearch <-- platform

 Not network traffic:
   eve.json --bind mount--> filebeat
   ModSecurity audit.log --volume waflogs--> filebeat
   ./data/label --bind mount--> proxy (read-write), kali (read-only)
   kali's shell --> /var/log/fsl/commands.log, each command with its marker
   platform --docker exec--> wiki (read log), proxy (/label files),
                             suricata (rules), kali (command log)
   platform --docker run--> throwaway fsl-kali for tool cases
   platform --> volume platformdata --> /data/db.sqlite3
```

`deploy/suricata/suricata.yaml` names the interfaces eth0 to eth4 and relies on
Docker attaching the WAF's networks in the priority order set in
`compose.yaml`. Nothing checks that mapping.

The WAF sends `Host: board.com` to `board:8000` (`deploy/nginx/board.conf`)
and everything else to its `BACKEND`, `juice-shop:3000`. The board is the
second wargame: Django 5.2 under gunicorn, which migrates and seeds itself on
start, on MySQL pinned by digest. Neither is published. The board is not
judged: it has no objectives, and a session snapshots a baseline only for a
judged wargame, so a board session scores the defence alone.

## The declaration and the substrate seam

Docker is the MVP's substrate; OpenStack is the target. The platform never
asks Docker what the range means. It is told, by
`platform/range/declaration.yaml`: per segment an id, a display name and an
attack origin; a role table (attacker, scorer, gateway, proxy, sensor, target,
wiki, board, board-db); which host the sensor watches; the default origin; and
the defended site the map draws lines to (Seoul). A segment is outside if and
only if it declares an origin.

**Identity is declared, allocation is reported.** The declaration holds no
subnet, gateway or address. Those come from the substrate, because Docker and
Neutron both hand them out, and a declared subnet that disagreed with the real
one would bin alerts by a subnet nothing lives on. `compose.yaml` repeats the
identity in network labels; `platform/tests/test_declaration.py` holds the two
files to each other, but never checks the running range.

**Segments are bound by a mark; hosts are still bound by name.** Each segment
carries `fsl.segment.id` as a Docker label or a Neutron tag, and the adapters
fetch only marked networks. Name rules broke on compose prefixes and
overrides, Heat stack suffixes and non-unique Neutron names. A role is the
container or server name the declaration gives: Docker runs `docker exec
<name>`, and OpenStack lists every server in the project and matches
`server["name"]`, which Nova does not keep unique. That is still open in
`docs/STATE.md`.

`platform/range/ports.py` is the port. Core code and most of the platform see
only its four verbs:

- `describe()` returns the shape: segments, their nodes and addresses, sensors;
- `segments()` returns who stands where, without asking about the sensor;
- `runner(role, segment)` runs a command on a standing host (the sensor, the
  wiki, the proxy, and the attacker, whose command log the platform reads);
- `launcher(segment)` runs a one-shot tool on a segment and returns its output.

`range.substrate()` builds the adapter named by `FSL_SUBSTRATE` (default
`range.docker.Docker`), with the options `FSL_SUBSTRATE_OPTIONS` keeps under
that name plus `declared=RANGE`. Docker takes `FSL_PROJECT` (default `fsl`).
OpenStack takes `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PASSWORD`, `_PROJECT`,
`_SSH_USER` and `_SSH_KEY`, each refused by name when missing; `_SSH_CONFIG`
is optional and must exist if given; `_REGION` defaults to `RegionOne` and
`_INTERFACE` to `public`. `redteam/harness.py` is handed a launcher and
`platform/rules/suricata.py` a runner, so neither imports `subprocess` or
names a substrate.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| shape | `docker network ls/inspect`, label filter | Keystone v3, Neutron with `tags-any`, Nova |
| sensor | refuses to describe the range unless each declared sensor shares the declared gateway's network namespace (`docker ps`, `.HostConfig.NetworkMode`) | reports a sensor whenever both named servers exist; nothing confirms it sees the gateway's traffic |
| runner | `docker exec` | `ssh` to the instance |
| launcher | `docker run --rm --network <segment>` | `runner("attacker")`: runs the tool over ssh on the declared attacker; any other image is refused, because Nova cannot boot a host, return its output and delete it |
| tested against | the live stack | unit tests on fakes built from the published API reference and a local sshd; on the `fsl-range` cloud, `describe()` and `segments()`, which need only the API, returned the six segments `bin/openstack-range` built, from inside the platform VM too; `runner()` and `launcher()` have not run on a cloud |

Compose mounts the Docker socket into the platform whatever the substrate, and
the entrypoint adds the platform user to its group. It is a container escape
path. The OpenStack adapter would make it removable; nothing removes it yet.
What is left before the adapter can drive a range (name resolution, reading a
sensor that runs as the pfSense package instead of confirming `watches`, one
Internet segment with many origin subnets and the one Kali VM on it, roles by
server name, how the operator's address appears through a router, SNAT) is
listed in `docs/STATE.md` under "The substrate seam".

## Where requests come from

| Route | Sender | Source address in the alert | Marker |
|---|---|---|---|
| Terminal, HTTP | Kali, through `proxy:8081` | the proxy, on the chosen origin | added by the proxy |
| Terminal, raw TCP | Kali directly | Kali, on `edge` only | none |
| Console case, HTTP | the platform | the platform, on the chosen origin | added by the harness |
| Console case, tool | a throwaway `fsl-kali` container | that container, on the chosen origin | sqlmap `--headers=` |
| CLI run or browser, HTTP | the host, through port 8080 | the `edge` bridge gateway | added by the harness; none from a browser |
| CLI run, tool | a throwaway `fsl-kali` container, from `launcher(--origin or the declared default)` | that container | sqlmap `--headers=` |

The proxy is a `mitmdump` script. It sets `X-FSL-Case` from `/label/active`
and, when `/label/origin` names an address, forwards the request there with the
original `Host`. The platform writes both files with `docker exec`. There is no
TLS interception, so the proxy is an environment variable, not an enforcement
point: `curl --noproxy '*'` skips it.

The terminal also records what the operator types. Kali's shell appends each
command, with the current `/label/active` marker, to
`/var/log/fsl/commands.log`. The platform reads it through
`runner("attacker")` and serves it at `GET /api/sessions/<id>/commands/`.

A console HTTP case carries the `Host` of the session's wargame, `shop.com` or
`board.com`, whether or not an origin was chosen. Choosing an origin points
traffic at the WAF's address on that segment. `board.com` resolves on all four
edge networks; `shop.com` on `edge` only. `rotate` is a per-session round
robin, not a random pick.

A console tool case is pointed at the origin's target URL, or, with no origin
chosen, at `TARGET_URL` (`http://shop.com`) from the declared default origin.
The CLI's `--tool-target` defaults to `http://waf:8080`, but inside the range
the WAF listens on 80 (and 8443); 8080 is only the host-side publish.

The WAF runs CRS at paranoia 1, anomaly threshold 5, in `DetectionOnly`, and
every Suricata rule is `alert`. Nothing in the range blocks a request.

The wiki is reached only through the application, by SSRF: Juice Shop fetches
`imageUrl` posted to `/profile/image/url`. No scripted case does this.

## Where alerts go

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-<day>
                                     (fsl_source)   pipeline fsl-geoip
                                                          |
             blue console timer -> POST /api/sessions/<id>/ingest/
                                                          |
             parse per fsl_source, lift the marker onto alerts, store
             as Detection rows in SQLite
```

ModSecurity's audit log carries the request headers, so its alerts carry the
marker directly. Suricata's alert events carry no request headers; only its
`http` events do (with `dump-all-headers: request`; `custom: [X-FSL-Case]` has
no effect). Ingest copies the marker from the `http` event onto the alert with
the same `(flow_id, tx_id)`. Joining on `flow_id` alone attributed every alert
on a keep-alive connection to its first case.

Each ingest call:

- first restores rule suppressions that have expired;
- asks Elasticsearch for `@timestamp` from the session's start minus a minute
  to its end (or now) plus a minute. `@timestamp` is Filebeat's read time:
  neither `filebeat.yml` nor the pipeline sets it from the event;
- reads at most 5000 hits, oldest first. Beyond that the reply carries
  `truncated`, and the session stays flagged, which adds
  `score.warning.truncated`;
- keeps Suricata's `alert` events, and turns ModSecurity's record into one
  Detection per matched rule message, with id `<Elasticsearch _id>:<n>`;
- drops alerts whose own event time falls outside the window, counted as
  `stale`;
- writes markers found later onto stored rows that had none;
- fills `src_host` and `dest_host` from the substrate's segments, empty if the
  substrate cannot be reached.

Elasticsearch is used for storage and for geoip at index time, which is why
there is no Logstash. Nothing uses its query engine beyond a time-range
search: the map and top-N tables are computed in Python over the SQLite copy,
and `src_geo.location` is mapped as two floats, not a `geo_point`. The world map
is an Equal Earth projection cut at 60 degrees south, generated by
`bin/worldmap`.

The pipeline has two geoip processors, `src_ip` (Suricata) and
`transaction.client_ip` (ModSecurity), both writing `src_geo`. The repo does
not provision the GeoLite2 databases: compose mounts nothing at
`config/ingest-geoip` and sets no downloader option. On the live node the
downloader has never succeeded; the databases were copied in by hand and are
lost when the container is recreated.

## How the scores are computed

**Objectives.** The platform reads the target's `/api/Challenges/` and takes
each `solved` flag as it is. The time is Juice Shop's `updatedAt`, trusted
only between the session's start minus 5 s and the moment of observation;
otherwise the objective is dated when it was observed. A trusted stamp becomes
a window stored on the Objective row: from 100 ms before it to its resolution
(1 ms with a fraction, 1 s without) plus 100 ms after. For the 13 challenges
Juice Shop checks only on a later request (`stamped_late`), the window reaches
back 2 minutes instead of 100 ms.

The one objective the platform judges itself is `internalRunbookRead`: a
successful read of a secret wiki page in the wiki's own access log. Its
difficulty of 6 has no recorded reason. Nothing clears the wiki log except the
acceptance tests, so after one successful SSRF later sessions start with the
runbook already read.

A session snapshots the objectives already solved when it starts and never
credits them. If the target or the wiki cannot be read then, the session is
still created, with no baseline, and the snapshot is taken at the first
successful observation: anything solved in between is never credited. Only a
judged wargame has a snapshot and objectives; observing the board returns 0
of 0.

An unreachable target is a 503 only on the two objective endpoints,
`GET /api/wargames/<id>/objectives/` and `POST /api/sessions/<id>/objectives/`.
Creating a session, firing or recording a case (`POST .../cases/` replies
`objectives: null`) and closing a session (the reply carries `unobserved`)
absorb it. Once a baseline exists an unreadable wiki log is not a 503 either:
the observation carries `unreadable`, and the objective list shows the runbook
with `solved: null`.

A taken objective goes to a malicious case whose run overlaps the objective's
window; among several, the one that started latest. Without a trusted stamp
the window is from 2 minutes before the observation to 100 ms after. The
objective counts as detected only if that case was detected, and one that no
case overlaps counts as undetected. Attribution is by time only: a case's
`takes:` field is shown in the red console but not read by scoring.

In the score's `objectives` block, `coverage` is detected difficulty over total
difficulty, `null` when nothing was taken, and `false_positives` is FP.
`damage` is undetected difficulty plus half of detected difficulty; that ratio
is where "an undetected loss counts double" lives.

**Detection.** A case is matched to alerts by one of two strategies, declared
per case:

- `marker`: the alert carries the case's `X-FSL-Case` value;
- `window`: the alert's source address matches the case's and its time falls
  within the case's start and end, with two seconds of slack each side.

There is no fallback from one to the other. A marker case whose marker was
lost should show up as a miss, not be covered for by the window. Terminal cases
carry both. `?correlation=marker` or `?correlation=window` on the score
endpoint forces a strategy; any other value is a 400. The blue console compares
the two by asking once per strategy. A disagreement is a finding about the
scoring method, not the defence.

Each `per_case` entry carries `expect` and `corroborated`. `corroborated` is
true when `expect` appears, ignoring case, in the signature of some matched
alert; a signature that also matched a benign case in the same session does
not count. It is `null` when the case has no `expect`, which is always so for
terminal cases: the red console sends none. A detected case that is not
corroborated adds `score.warning.wrong_reason`.

A case's `expect` is stored with the case when it is fired, so editing the
case file does not re-judge a finished session. Rows recorded before migration
0009 have no stored `expect` and are still judged against the current case
file. Alert severity and rule type are not used.

**The game.** The score's `game` block is `{"revealed": false}` until the
session closes. Then it carries four pillars, their weights and a balance:

- speed (0.25): per malicious case, 1 if its first matched alert came within
  10 s of its start, 0 at 120 s or later, linear in between; averaged;
- accuracy (0.30): recall minus false-positive rate, floored at 0;
- coverage (0.20): attack stages (`platform/lifecycle.py`) with a detected
  malicious case over the stages attacked, 0 when none was attacked. It is not the `objectives`
  block's `coverage`;
- response (0.25): the share of malicious cases blocked minus the share of
  benign cases blocked. It is `null`, and the other weights are renormalised,
  until some case has `meta["blocked"]`. Nothing sets that yet.

`attacker` is the difficulty of the taken objectives, halved when detected:
the same sum as `damage`. `defender` is the weighted mean of the pillars times
the difficulty taken, minus 1 per FP. `balance` is `defender - attacker`. On
the board nothing is ever taken, so the balance is minus FP. The weights and
dwell times are v1 defaults
(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

The score endpoint is read-only and keeps no history.

## Decisions

- **One case file per wargame, attacks and benign traffic together**:
  `redteam/cases/default.yaml` for Juice Shop (10 attacks, 6 benign) and
  `board.yaml` for the board (6 and 3). Separate files make it easy to forget
  the benign half. The CLI reads `default.yaml` unless `--cases` names another
  file, and always opens a Juice Shop session.
- **The harness refuses to send a rewritten path.** `requests` turns
  `/ftp/../../etc/passwd` into `/etc/passwd`; sending that would record an
  attack that never left and score the harness's failure as the defence's.
  Percent-encoding differences are allowed.
- **A tool that cannot start raises; a tool that exits non-zero counts.**
  sqlmap exits non-zero when it finds nothing, but its traffic went out.
- **Suricata shares the WAF's network namespace** rather than using host
  networking, whose meaning varies with the Docker host. The WAF's interfaces
  carry both legs of every request.
- **No Kibana in the compose range yet.** The blue console lists detections
  and Elasticsearch still answers ad-hoc queries. Kibana is to return,
  read-only, for the blue team (see "OpenStack").
- **Elasticsearch is a single node with a 512 MB heap** so the whole stack fits
  in a default Docker memory allowance.
- **Missing data is an error, not a zero**, with stated exceptions. An
  unreachable Elasticsearch or substrate, an unreadable rule file and the
  objective endpoints above answer 503. Session create, firing or recording a
  case and close absorb an unreachable target or wiki log (firing still
  answers 503 when it needs the substrate for an origin or a tool). The
  suppression restore inside ingest and placing alerts on segments and hosts
  (which comes back empty) absorb an unreachable substrate, so a round can
  still start and stop. A ratio with a zero denominator is 0.0, not null:
  precision, recall, F1 and FPR, and the game's speed, coverage and accuracy. Only the `objectives` block's
  `coverage` is null.
- **A score says what it cannot vouch for.** It carries a warning when there
  are no benign cases (`no_benign`), marker cases and no marker on any alert
  (`no_marker`), a window case with no source address (`no_source_ip`), a
  detected case that is not corroborated (`wrong_reason`), or more hits in
  Elasticsearch than ingest read (`truncated`).
- **Console-fired cases send one case per HTTP connection**, while the CLI
  keeps one connection for a whole run. Measured on the same twelve cases,
  both gave identical scores and per-case alert counts. The acceptance tests
  drive the CLI, so the shared-connection case stays tested.

## OpenStack

The build follows the OpenStack item of the backlog in `docs/STATE.md`, in its
order; only its first step, the platform VM, exists. The reasoning behind
every choice below is in `docs/STATE.md` ("Decided on 2026-09-30"),
`docs/superpowers/specs/2026-09-30-openstack-range-placement.md` and
`docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`; this section
records only the shape.

The cloud is one KVM compute node (8 vCPU, 64 GB) running kolla-ansible
2026.1 with ML2/Open vSwitch. The range lives in project `fsl-range`, driven
by the member-role user `fsl-range`. Horizon is never shown to users.

### Built: the platform VM

`deploy/openstack/platform.yaml` is a Heat template. It creates:

- network and subnet `fsl-platform`;
- a router to the external network, and a floating IP;
- a security group opening tcp/22 and ICMP to any address;
- the Nova server `fsl-platform`, with a config drive.

Its parameters and their defaults are in `README.md`.

cloud-init installs `docker.io`, `docker-compose-v2` and `git`, adds 4 GB of
swap, sets Docker's MTU to the Neutron network's for the default bridge
(`mtu`) and for every new bridge network, compose's included
(`default-network-opts`), clones `repository` at `ref` into `/opt/fsl` and
adds `ubuntu` to the `docker` group. A systemd unit, `fsl-platform.service`,
runs `docker compose -f /opt/fsl/compose.yaml up -d --build` on every boot.

So today the whole compose range above, all eleven services, runs inside one
Nova VM. Its ports stay on the VM's loopback and are reached through an ssh
tunnel (`README.md`).

cloud-init writes `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PROJECT` (the stack's
own project), `_SSH_USER=ubuntu` and `_SSH_KEY=/data/ssh/id_ed25519` to
`/root/openstack.env` with mode 0600, then moves it to
`/opt/fsl/openstack.env`, which git ignores. The password is not in the
template: Nova keeps the user data and its metadata service serves it to
whatever runs on the VM, the range's containers included. The operator
appends `FSL_OPENSTACK_PASSWORD` over ssh once the VM is up (`README.md`).
The platform service reads the file with `env_file` (`required: false`,
`format: raw`), so compose passes it through without interpolating or
unquoting.

The platform on the VM still uses the Docker adapter, and could not use the
OpenStack one yet:

- `openstack.env` sets no `FSL_SUBSTRATE`, so the default
  `range.docker.Docker` is chosen and the `FSL_OPENSTACK_*` settings are not
  used;
- nothing creates `/data/ssh/id_ed25519`;
- the VM's router attaches only its own subnet, and `bin/openstack-range`
  creates no router, so the VM has no route to the range's networks.

`bin/openstack-range` builds a stand-in range for the adapter: the six
segments as tagged networks and one bare Ubuntu server named
`fsl-juice-shop`, with no Juice Shop on it. How to run it is in `README.md`.

### Decided, not built: the range on OpenStack

Decided by the user on 2026-09-30.

```
 OpenStack project fsl-range.

 platform VM: Ubuntu 24.04, floating IP, docker compose up
   console and /api/, scoring, Elasticsearch, Filebeat, Kibana
   landing page /: start and stop a session, the scoreboard after close
   sidebar, three panes inside the page:
     pfSense   noVNC console of a kiosk browser VM showing pfSense's GUI
     Kibana    framed directly, on a read-only Elasticsearch role
     terminal  ttyd on the Kali VM, reverse-proxied by the platform
     |
     +--OpenStack API, as member fsl-range--> networks, VMs, consoles
     +--management network, ssh-------------> Kali VM, target VMs

 Internet network: one subnet per origin country (30), no Neutron router
   Kali VM: one port holds every attack address; the source is rewritten
            to the chosen country's address as packets leave
     |
     v
 pfSense CE VM: edge firewall; its WAN holds each subnet's gateway address
                and routes on without NAT, so country sources survive
   Suricata package: IDS/IPS, drop rules switched by blue in the pfSense GUI
     |
     v
 WAF VM: nginx + ModSecurity v3 + CRS, blocking mode switched by blue
     |
     v
 estate network
   Juice Shop VM     board VM (Django on MySQL)     wiki VM
   Juice Shop --SSRF--> wiki, inside the estate, past no gateway

 Evidence:
   pfSense: Suricata EVE, filterlog --syslog, UDP--> Filebeat --+
   WAF VM: ModSecurity audit log --------------------------------+
                                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch --read-only role--> Kibana --> blue team
```

What the diagram does not show:

- **Origins**: 30 countries from a public, token-free ranking of Internet
  traffic, placed by GeoIP, about 100 addresses weighted by traffic, at least
  one each. The declaration gains one segment with many origin subnets; today
  the adapter refuses a segment with more than one IPv4 subnet.
- **The attacker**: the stamping proxy moves onto the Kali VM; the Nova
  console is the terminal's fallback.
- **Blocking works as in practice**: the blue team switches the WAF's mode and
  Suricata's drop rules itself. Whether a case was blocked is read from the
  target side into `meta["blocked"]`, which the response pillar needs.
- **Objectives** move toward the board: its `auth_user` table becomes
  something the red team can take, judged from the board's own side.
- **Evidence by event time**: `@timestamp` from Suricata's `timestamp` and
  ModSecurity's own time, every range VM's clock kept by chrony. GeoIP is
  loaded once into a durable bind mount for `config/ingest-geoip`, with the
  downloader off.
- **Kibana** comes back to compose with Elasticsearch security on and a
  read-only blue role. The blue dashboard mostly goes; the live dashboard and
  the rules editor go.
- **Images**: a setup script kept in the repo builds each VM once, and a
  snapshot of it is the image.
- **Lifecycle** (a first try): the fabric (networks, security group, keypair,
  images) is created and destroyed only by an operator action, REST first.
  Each slot is one Heat stack; roles are found through its resource list.
  Provision builds and test-runs a slot. Start takes a ready slot and creates
  nothing. Stop rebuilds every VM either side can change, at once. A slot is
  ready only once the range answers for itself: nothing solved, rules and WAF
  mode at baseline, clocks in sync, a canary alert in Elasticsearch.

Decisions still open for a person are in `docs/STATE.md` ("Decisions left for
a person").

Not settled by any source yet: how the board judges from its own side that
`auth_user` was taken; how the WAF VM's audit log reaches Elasticsearch;
which interface the blue team switches the WAF's mode in; Suricata's inline
or legacy mode on pfSense; which token-free ranking supplies the countries.
What has to be tested on this cloud before building is in the placement spec,
"To test on this cloud before building".
