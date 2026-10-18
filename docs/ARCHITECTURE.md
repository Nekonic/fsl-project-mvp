# Architecture

How the range is built, how traffic and evidence move through it, and the
design decisions behind it. How the score is defined is in `CLAUDE.md`; open
problems and measured quirks are in `docs/STATE.md`.

Everything up to "Decisions" describes what runs today: the Docker compose
range, and the OpenStack range where it differs. The last section,
"OpenStack", describes the OpenStack range and separates what is built there
from what is planned (`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`).

The hypothesis the repo started from: red team attacks can be labelled with
ground truth, and Suricata and ModSecurity alerts can be matched to those
labels automatically, so false positives and negatives can be scored
mechanically. The objective score was added once that held.

## The range

The compose services and networks are listed below; `bin/measure` counts them.
Two compose files hold them. `compose.yaml` is the control plane (project
`fsl`, one long-lived copy): the platform, Elasticsearch, Kibana, the
`collector`, the GNS3 server, the four edge networks and `mgmt`. `session.yaml` is one
session's data plane: the WAF, Suricata, Filebeat, Kali, the proxy and the
wargames. It joins the edge networks and `mgmt` as `external`
(`fsl_<network>`) and owns its `estate` network (no fixed subnet; Docker draws
one from its private pools) and its volumes. Opening a
session (`POST /api/sessions/`, `platform/range/docker.py` `open_session`)
runs `docker compose -p fsl-<session id> -f session.yaml up -d --wait
--no-build` from inside the platform, with `FSL_HOST_DIR` set to the host
directory compose started the platform from (its
`com.docker.compose.project.working_dir` label), so the stack's bind mounts
resolve on the host, and `FSL_SESSION` set to the session id. The platform then
joins the session's `estate` (`docker network connect`, alias `platform`;
its own `edge` keeps the default gateway through `gw_priority: 1`) and
aims the session's proxy at the session's own WAF (`/var/lib/session/origin`); the
baseline is read after that. Sessions run concurrently: opening a session runs
`down -v` only on `fsl-<n>` projects whose session ended more than three
minutes ago (leaving their `estate` first), deciding which under one lock so
two opens at once cannot take down each other's new stack. Docker opens at most `FSL_MAX_SESSIONS` sessions (default 2,
`platform/fsl/settings.py`) and answers 409 past that; OpenStack opens one per range slot.
Closing a session leaves its stack until an open at least three minutes
later, while its Filebeat ships the last alerts. The store keeps a closed
session for `FSL_RETAIN_CLOSED_MINUTES` (default 60, set in `compose.yaml`);
`platform/api/retention.py` deletes older closed sessions, with everything
that belongs to them, at start (`fsl/wsgi.py`) and after each close: a
session's detections and customer requests 2,000 rows per transaction, then
the session, so a large prune never holds the store's write lock for long. The
store is SQLite with `transaction_mode: IMMEDIATE` (`fsl/settings.py`): a
read-then-write transaction takes the write lock at its start and waits out
the 30 s busy timeout instead of failing at once with `database is locked`.
`bin/backup` snapshots the store with `VACUUM INTO` and keeps the newest
`--keep` copies (default 1; `backups: {keep}` in `cloud.yaml` for
`bin/platform-rebuild` and `bin/cloud down`). The OpenStack substrate has
no `open_session`: its range is the Nova VMs, so no session stack starts; the
wargames run on one VM, `fsl-wargame-host`, as the same GHCR containers. Its
readiness probe and session baseline read the board through the adapter's
`address("board")`, the wargame host's management address, where the board's
port 8000 is published, which `loot.ground_truth` puts in place of the host in
`BOARD_API_URL`.

Each target is a wargame, a folder under `wargames/` whose `compose.yaml`
`session.yaml` includes: `board` (Django and MySQL, `loot_verified`) and
`corp` (WordPress and MySQL, `effect_observed`). The platform discovers each
from `wargames/<id>/scenario.yaml` (`platform/wargames.py`; fields `name`,
`description`, `image`, `public_url`, `objective_model`, `case_file`, and
optionally `category`, `difficulty` (easy, medium, hard) and `minutes` for the
console's scenario card, and `defense`, `foundations` and `scenarios`,
described under "Sessions, WAF tuning and the step engine" and "Scenarios").
Nothing
reads `image` yet. Each app image is built by CI
(`.github/workflows/images.yml`) and pulled as
`ghcr.io/nekonic/fsl-<name>:${FSL_IMAGE_TAG:-dev}`, or built locally under that
name; sessions start from it with `--no-build`. The platform passes its own
`FSL_IMAGE_TAG` to the session stacks it starts, and tool cases run
`ghcr.io/nekonic/fsl-kali` with the same tag (`redteam/tools.py`). A new wargame needs `scenario.yaml`, `objectives.yaml` and
`compose.yaml` in its folder, a case file under `redteam/cases/`, and an
`include:` line in `session.yaml`.

Nothing in `session.yaml` or a wargame pins `container_name`; a session's
containers are `fsl-<id>-<service>-1`. Only the control plane keeps fixed names
(`fsl-platform`, `fsl-elasticsearch`, `fsl-kibana`, `fsl-collector`, `fsl-gns3`). The
first table below gives each session service under its declared host name,
which `platform/range/docker.py` maps the container back to.

Every endpoint that acts on the range (rules, validate, suppressions,
`/api/attacker/`, origin, label, canary) takes `session` from the query or
body. Without one, a write goes to the newest open session and answers 409
when none is open, and a read uses the newest session; a write naming a closed
session is refused. Suppressions are stored with their session (migration
0014). Each
session's sensor keeps its live `local.rules` in its own container. On docker
every session's sensor is seeded at open with its defense's rule file, or with
`deploy/suricata/rules/local.rules` when the scenario declares no `defense`
(corp); nothing bind-mounts `deploy/suricata/rules`, so applying a rule changes
only that session's sensor. Open on docker: the middleware that refuses
requests from range hosts covers only the newest session's `estate`.

| Service | File | Image | Networks | Host port |
|---|---|---|---|---|
| `fsl-wg-board` | session | `ghcr.io/nekonic/fsl-board` from `wargames/board/app` (Django under gunicorn, port 8000) | estate | |
| `fsl-wg-board-db` | session | `mysql` | estate | |
| `fsl-wg-corp-wp` | session | `ghcr.io/nekonic/fsl-corp` from `wargames/corp/app` (WordPress 6.6.2, three pinned vulnerable plugins; `corp.com` by `Host` header) | estate | |
| `fsl-wg-corp-db` | session | `ghcr.io/nekonic/fsl-corp-db` from `wargames/corp/db` (MySQL 8.4, binlog `ROW`) | estate | |
| `fsl-waf` | session | `owasp/modsecurity-crs` (nginx), alias `board.com` on edge (shared, so the platform aims each session's proxy and tools at its own WAF) | edge, edge-br, edge-hk, edge-us, estate | |
| `fsl-suricata` | session | `jasonish/suricata` | the WAF's namespace | |
| `fsl-filebeat` | session | `filebeat:8.15.0`, ships the session's `eve.json` and audit log | mgmt | |
| `fsl-kali` | session | `ghcr.io/nekonic/fsl-kali` from `deploy/kali`; `http_proxy` is `http://proxy-<id>:8081`, an alias only that session's proxy carries on the shared `edge` | edge | |
| `fsl-proxy` | session | `ghcr.io/nekonic/fsl-proxy` from `deploy/proxy` (mitmdump); `/var/lib/session` is the project's named volume `label` | the four edge networks | |
| `fsl-elasticsearch` | control | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-collector` | control | `filebeat:8.15.0`, the syslog input only (the OpenStack range) | mgmt | 5140/udp |
| `fsl-kibana` | control | `kibana:8.15.0`, served at `/kibana/` | mgmt | |
| `fsl-platform` | control | `platform/` (Django under waitress, behind nginx; nginx also serves Kibana at `/kibana/`, each session's Kali ttyd at `/terminal/<session id>/`, each session's WAF shell at `/waf-terminal/<session id>/`, the VM terminals at `/vm-terminal/kali/` and `/vm-terminal/waf/`); carries the compose plugin and mounts `session.yaml` at `/src/session.yaml` | the edge networks, mgmt, and each open session's estate | 8000, 8002 |
| `fsl-gns3` | control | `ghcr.io/nekonic/fsl-gns3` from `deploy/gns3` (gns3-server 3.1.0a6, qemu, uBridge 1.2.3, busybox-static, docker-cli; holds open the learner maps the platform loads and starts their display nodes; `CAP_NET_ADMIN`, `/dev/net/tun`, the Docker socket, the host's pid namespace) | mgmt | 3080 |

8000, 8002 and 3080 bind to `FSL_PUBLISH` and 5140/udp to `FSL_SYSLOG_PUBLISH`,
both defaulting to 127.0.0.1; 9200 binds to loopback only.

| Network | Segment | Subnet | Name | Origin |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | Internet | Russia |
| `edge-br` | `br` | 177.54.144.0/24 | Internet | Brazil |
| `edge-hk` | `hk` | 103.152.220.0/24 | Internet | Hong Kong |
| `edge-us` | `us` | 73.0.0.0/24 | Internet | United States |
| `estate` | `estate` | per session, drawn by Docker | Application estate | |
| `mgmt` | `mgmt` | 172.31.0.0/24, shared | Management | |

The edge networks are shared by every session and keep fixed subnets: Docker
refuses overlapping subnets, and the subnet carries the origin for GeoIP.
`mgmt` is shared too, because Elasticsearch, Kibana and the collector live on it
and every session's Filebeat must reach Elasticsearch (`docs/DECISIONS.md`,
2026-10-10). Suricata's `HOME_NET` is the four WAF edge subnets plus 10/8,
172.16/12 and 192.168/16, since a floating `estate` is drawn from Docker's
private pools.

The declaration lists thirty origins on one Internet segment, the top thirty
countries by Cloudflare Radar's share of HTTP requests, each with a /24 that
GeoIP places in it and a share of about 100 attack addresses. Docker builds
four of them, one network each, because a bridge holds one IPv4 subnet; the
OpenStack fabric builds all thirty as subnets of one network.
`bin/pick-origins` reproduces the table, and an acceptance test checks every
subnet against the pipeline scoring reads.

On docker, segmentation is network membership only: no firewall, no iptables, no
ACL; on OpenStack it is the fabric's networks and security groups.
`test/test_attacker_reach.py` asserts it against the live range on both (Kali
reaches neither `board:8000` nor `corp-wp` directly, and no service off its
route out; `test/test_board_exfil.py` reaches the board through `board.com`),
and `test/test_concurrent_sessions.py`
that two concurrent sessions do not see each other. Only the edge subnets are fixed;
container addresses are assigned by Docker and change on recreate. The views
build a new adapter and read them on every request. The rule that refuses
requests from range hosts caches their addresses for 30 s, and when it cannot
reach the substrate it treats the range as empty and lets the request through
(`docs/THREAT-MODEL.md`).

The platform, the WAF and the proxy are multi-homed. The attacker's traffic
enters the internal network (`estate`) only through the WAF, but the platform
is attached to every edge network and each session's `estate`, so the API checks the caller itself
(`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --console-fired case--------------+
 edge-br                                              |
 edge-hk   proxy, platform (no kali, no board.com)    |
 edge-us                                              v
         fsl-waf: nginx + ModSecurity CRS, SecRuleEngine On, port 80
         fsl-suricata in the same network namespace, af-packet on all five
         interfaces, so it sees client->WAF and WAF->target
                                                      |
 estate    board:8000 <--any Host, /internal/ 404-----+
           board --> board-db (MySQL)
           platform --GET /internal/auth-users--> board:8000, past the WAF
 mgmt      filebeat --> elasticsearch <-- platform

 Not network traffic:
   eve.json --volume suricatalogs--> filebeat
   ModSecurity audit.log --volume waflogs--> filebeat
   volume label (per session) --> proxy (read-write), kali (read-only)
   kali's shell --> /var/log/commands.log, each command with its marker
   platform --docker exec--> proxy (/var/lib/session files), suricata (rules),
                             waf (CRS tuning, nginx reload),
                             kali (command log), corp-db (mysql, mysqlbinlog)
   platform --docker run--> throwaway fsl-kali for tool cases
   platform --> volume platformdata --> /data/db.sqlite3
```

`deploy/suricata/suricata.yaml` names the interfaces eth0 to eth4 and relies on
Docker attaching the WAF's networks in the priority order set in
`compose.yaml`. Nothing checks that mapping. Its `default` entry gives any
other interface (the estate sensor's `ens3` on OpenStack) the same capture
settings.

The WAF routes `board.com` to `board:8000` and sends `/internal/` to a path
the board does not serve, so the answer is the board's own 404, byte for byte
(`deploy/nginx/board.conf`, and `deploy/waf/board.com.conf` on OpenStack); `corp.com` is a second vhost to
`corp-wp:80` (`deploy/nginx/corp.conf`). The board is the first wargame: Django
3.2.4 (an unpatched version with a known `order_by` SQL-injection flaw,
CVE-2021-35042) under gunicorn, which migrates and seeds itself on start, on
MySQL pinned by digest. Neither is published. It is scored by exfiltrated
credentials: when a session starts the platform reads the board's `auth_user`
usernames and password hashes from `/internal/auth-users`, which it reaches on
the `estate` network directly and the WAF never forwards, and keeps them as
the session's snapshot. That read does not pass through the WAF, so neither
the IDS nor the WAF sees it.

The corp wargame is the second: WordPress 6.6.2 (`fsl-wg-corp-wp`) with three
plugins pinned to unpatched versions: Ultimate Member 2.6.6 (CVE-2023-3460, a
registration flaw that injects `wp_capabilities` to grant administrator), WP
GDPR Compliance 1.4.2 (CVE-2018-19207, an unauthenticated option change that
opens admin self-registration), and Easy Post Submission 2.3.0 (CVE-2026-4431,
an unauthenticated post overwrite). None triggers the default OWASP CRS. Its
database, `fsl-wg-corp-db`, is MySQL 8.4 run with `--binlog-format=ROW`;
WordPress itself is not instrumented. corp is scored by the changes an attack
commits to its database (below).

## The declaration and the substrate seam

Docker and OpenStack are both first-class substrates (2026-10-11 ruling). The platform does not
ask Docker what the range means. It reads that from
`platform/range/declaration.yaml`: per segment an id, a display name and an
attack origin; a role table (attacker, scorer, gateway, proxy, sensor, board,
board-db, corp, corp-db, and under `openstack:` the edge, sensor and proxy
roles that differ there); which host the sensor watches; the default origin;
and the defended site (Seoul). A segment is outside if and only if it declares
an origin.

The declaration holds no subnet, gateway or address. Those come from the
substrate, because Docker and Neutron both assign them, and a declared subnet
that disagreed with the real one would bin alerts by a subnet nothing lives
on. `compose.yaml` repeats the segment identity in network labels;
`platform/tests/test_declaration.py` checks the two files against each other,
but never checks the running range.

Segments are found by a label. On docker the adapter finds hosts by label too:
`declaration.yaml`'s `compose:` section maps each role to a compose service,
and the adapter picks the container with that `com.docker.compose.service`
label in the session's project. No platform code names a container by the
compose naming convention any more (the site proxy did, `http://fsl-<id>-waf-1`,
until 2026-10-18); only the WAF terminal script does, for the person's shell
(the exceptions table below). Each segment
carries `fsl.segment.id` as a Docker label or a Neutron tag, and the adapters
fetch only labelled networks; a session-owned network wins over a control-plane
one with the same segment id. Matching by name broke on compose prefixes and
overrides, Heat stack suffixes and non-unique Neutron names. On OpenStack a
role is still the server name the declaration gives: OpenStack lists every server in the project and matches
`server["name"]`, which Nova does not keep unique. That is still open in
`docs/STATE.md`.

`platform/range/ports.py` defines the interface. Core code and most of the
platform use only its four methods:

- `describe()` returns the shape: segments, their nodes and addresses, sensors;
- `segments()` returns which host is on which segment, without the sensor check;
- `runner(role, segment)` runs a command on a standing host (the sensor, the
  proxy, the attacker whose command log the platform reads, and corp-db);
- `launcher(segment)` runs a one-shot tool on a segment and returns its output.

`range.substrate()` builds the adapter named by `FSL_SUBSTRATE` (default
`range.docker.Docker`), with the options `FSL_SUBSTRATE_OPTIONS` keeps under
that name plus `declared=RANGE`. Docker takes `FSL_PROJECT` (default `fsl`).
OpenStack takes `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PASSWORD`, `_PROJECT`,
`_SSH_USER`, `_SSH_KEY`, `_REGION`, `_INTERFACE` and `_DOMAIN`, each refused by
name when missing, and the range-shaping values `_BASE_IMAGE`, `_FLAVOR`,
`_BUILD_FLAVOR`, `_ROLE_FLAVORS`, `_AVAILABILITY_ZONE`, `_SUBNETS`, `_MTU` and
`FSL_OPNSENSE`, refused by name where they are used, and `FSL_IMAGE_TAG` (the
wargame host's images; written to `/opt/fsl/.env` at boot). None has a default in
code: all come from `deploy/openstack/cloud.yaml` through the Heat stack
(`platform/range/cloud.py` reads and validates that file). `redteam/harness.py` is handed a launcher and
`platform/rules/suricata.py` a runner, so neither imports `subprocess` or
names a substrate.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| shape | `docker network ls/inspect`, label filter | Keystone v3, Neutron with `tags-any`, Nova |
| sensor | refuses to describe the range unless each declared sensor shares the declared gateway's network namespace (`docker ps`, `.HostConfig.NetworkMode`) | reports a sensor whenever both named servers exist; nothing confirms it sees the gateway's traffic |
| runner | `docker exec` into the role's service container in the session's project | `ssh` to the instance; a role the wargame host fills and `compose:` maps to a service runs in that container (`sudo docker exec <service>`, `range/wargame_host.py`) |
| address | the role's `estate` IP in the session's project | the host's `mgmt` address |
| launcher | `docker run --rm --network <segment>`, with `--add-host` for the session WAF's names | `runner("attacker")`: runs the tool over ssh to the declared attacker's mgmt address (the origin only checks that the attacker stands on that segment; the source country comes from `set-origin` SNAT); any other image is refused, because Nova cannot boot a host, return its output and delete it |
| tested against | the live stack | unit tests on fakes built from the published API reference and a local sshd; on the `fsl-range` cloud, the platform VM built the fabric, the images and the slot through `/api/range/`, `describe()` read back the WAF on the thirty origins and the four hosts on estate and mgmt, and `runner()` ran on each host over ssh to its mgmt address; `launcher()` fired sqlmap from the `ru` and `tw` origins on 2026-10-08 |

Compose mounts the Docker socket into the platform whatever the substrate, and
the entrypoint adds the platform user to its group. It is a container escape
path. The OpenStack adapter would make it removable; nothing removes it yet.
What is left before the adapter can drive a range is listed in
`docs/STATE.md` under "The substrate seam".

## The topology

The range's topology is GNS3 project files, `revision` 9 so GNS3 2.2 opens them
and 3.x upgrades them on load. Two kinds, per substrate:

- **The system map**, `deploy/topology/system/range-{docker,openstack}.gns3`:
  the full wiring of the declaration (the management segment, `fsl-platform`,
  the control-plane containers, the stamping proxy). English only, for
  development and GNS3's MCP; the GNS3 service never sees the repo's maps, so
  learners are never offered it.
- **The learner map**, `deploy/topology/range-{docker,openstack}.gns3` and
  their Korean pairs: the company web-service network the learner defends, as
  a logical diagram drawn the way lab topologies are (Cisco NetAcad lab
  topology, NSRC workshop logical diagram): role hostnames, the interface and
  its address with prefix at each link end (the interface alone at `kali` and
  `customers`), each zone captioned with its network (the Internet with its
  name alone), the text "IDS" beside each host a Suricata runs on (`firewall`
  and the site on OpenStack, `waf` on Docker), nothing
  else (no title, legend or note, no machine's own name, no `fsl-`, no
  management segment, no Docker bridge name). The request path runs left to
  right: the Internet zone, `firewall`, the Services zone (`waf`, the site),
  the database zone, the monitoring zone. `topology.for_wargame` keeps a text
  that lies in no zone, such as the firewall's "IDS" between two zones. The nodes are `customers` and
  `kali` (the attacker's Kali box) on the `internet` switch, the `firewall` (OpenStack's OPNsense
  edge, whose Suricata is folded into it), `sw1` (the service segment) with the
  `waf` and the site (`board.com` or `corp.com`, the WAF host's declared
  names), on OpenStack `sw2` (the database segment) behind the site with its
  database (`board-db`), on Docker the database on `sw1` (the Docker range has
  no edge and puts the sites and their databases on the estate, so its map
  does too, and has no `sw2`), and `sw3` (monitoring) linking the `log-server`
  (Elasticsearch) to the
  hosts whose records reach it: on OpenStack the firewall, the WAF and the
  site (the estate sensor runs on the sites' host and ships its own eve.json),
  on Docker the WAF alone (the session shipper reads the WAF's audit log and
  the volume of Suricata, which runs in the WAF's namespace). Switches are
  numbered as lab topologies number them (`sw1`, `sw2`, `sw3`, NSRC's `sw1`),
  in a fixed order: service, database, monitoring; the zone captions say
  which segment each is. A template draws both wargames' site and database in
  one place, both on the one `sw2`;
  `topology.for_wargame` keeps the session's own, and a wargame that declares
  no customers (`corp`, no `traffic.yaml`) has no `customers` node.
  `topology.learner(declaration, wargame)` is the mapping from the range's
  names to the map's: hosts (`fsl-kali` is `kali` and, where customers run
  on it, `customers`; `fsl-edge` is `firewall`; the wargame host and its site
  container are the site; `fsl-elasticsearch` is `log-server`), roles,
  segments to switches (origins to `internet`, the estate to `sw1`, a
  wargame's compose network to `sw2`; the management segment to `sw3` for the
  NIC name alone) and each sensor to the
  node whose NIC it uses; the overlay, the lesson's range
  questions and the interface read go through it. Every link is one straight
  line, level, upright or diagonal, none crossing another link or a node; a
  node a link reaches from straight above carries its name beside it. Every
  host is one square frame of one size and line weight (`host-*.svg`, built
  by `deploy/gns3/symbols.py` when the GNS3 image is built and uploaded by
  `provision.py`): GNS3's bundled affinity glyph inside, the frame red for
  the attacker, green for the defence, blue for the sites, gray for
  customers and the log server; switches and the internet keep GNS3's
  bundled square switch and globe. `kali`'s frame holds OffSec's Kali dragon
  (the press pack's `kali-dragon-black.svg` at a pinned commit, checked by
  sha256, placed unmodified inside the frame; `host-kali.txt` and the
  Map pane say whose trademark it is).
- **Every learner-map host is a display container.** GNS3 colours a link end
  by its node's status, so a stopped node draws every end red. Each host is a
  `docker` node of one pinned image (`busybox`, `topology.DISPLAY_IMAGE`) that
  only runs `sleep`, with no console; the real machines run in the range and
  the map's nodes only display it. Measured on the platform VM with a board
  map on slot 1 and a corp map on slot 2, both languages: 26 display
  containers, 115 MB PSS for their processes and runc shims, 12 MB for their
  uBridge processes (`docs/DECISIONS.md`).

Segments are `ethernet_switch` nodes. On the system map Docker containers are
`docker` nodes carrying their real images, never started, and OpenStack VMs
are `qemu` nodes with no disk image (the OPNsense edge has three NICs in vtnet
order); the wargame host's containers hang off a switch per compose project
(`board-default`, `corp-default`); a sensor that shares another's network
namespace or the host network has no NIC and a note beside it says whose
network it watches (in the Docker project a dashed line joins `fsl-suricata` to
`fsl-waf`). On the system map each declared segment is a titled rectangle
holding its switch (Internet, Application estate, Management and monitoring),
and each container or VM has a plain-words note; GNS3 3.1 makes a node's label
its name.
`platform/tests/test_gns3_topology.py`
derives the system maps' expected nodes and links from `declaration.yaml`, `compose.yaml`,
`session.yaml` and the wargame compose files and checks GNS3's structural
rules; it checks each wargame's learner map as the projection above: its nodes,
its links against the system map's wiring through `topology.learner`, its log
links, its geometry and its display nodes. `bin/check-topology` installs
gns3-server 2.2.61 and 3.1.0a6 into venvs under `~/.cache/fsl/check-topology`
and runs each release's `load_topology` on a copy of each file, on a range map
generated for each wargame from each learner map with a fixture range, and
checks every bundled symbol a node names exists in that release.

### A range's own map

The learner sees the addresses of their own range. `api/maps.py` derives, from
the learner map, one project per OpenStack slot or Docker session and the
session's wargame (`slot 1 board`, `session <id> corp`) in each language
(`topology.labelled`): every link is labelled at both ends, as a lab topology
labels it. A switch's end (and the `internet` switch's) carries the port the
link uses in short form (`Ethernet2` is `e2`). Every host's end is labelled with
the real interface and its address with prefix on that switch's segment
(`ens3 10.30.0.102/24`, `vtnet0 5.188.10.1/24`), read from the range through `topology.learner`: the
attacker's interface in the default origin and the customers' in their busiest
origin (`traffic.yaml`'s weights, the default origin left out, as
`attacker.customer_origins` does; no label where the box holds none, as on
Docker, whose customers' box starts with the customers), each without its
address (`topology.ADDRESS_VARIES`), because their source address changes with
the origin of every request (origin SNAT, several origins), the site's host
address on `sw1` (the WAF reaches the site there) and the site container's on
`sw2` (a dual-homed server, one label at each of its own link ends). A `sw3`
end carries the NIC name alone (`ens4`, `vtnet2`), because its address is on
the management network the learner does not see; the `log-server`'s is the log
store's own NIC where it has one on that network (Docker) and otherwise the
platform VM's (OpenStack, `ens7`). No label names a Docker bridge (`br-`). The
one end that can stay blank is Docker's `customers`, whose box runs only while
the customers do. Each zone caption gains the networks of the labels on its switch
(`Services 10.30.0.0/24`, `Internal DB 172.18.0.0/16`; the caption
of a switch is the text in the smallest box holding it, `topology.captions`);
Internet and Monitoring keep their name alone. A label lies level beside its node on the side its link leaves
(`topology.leaving`): on a level or shallow link above or below the line on
whichever side the node's other links leave more room, clear of where the
line runs under the text; on a steep link below the node, or above it where
the node's name is beside it, left or right of the line by the same rule
(right of the node where its name is above); clear of every line, GNS3's
status mark (6 units round, 60 along the line from the node's centre in the
3.1 web UI), a node's name, a zone's edge and its caption, with the text
estimated at 7 units a character (the web UI renders `font-size: 10.0` at
13.3 px); a shallow label goes to the other side of its line where it would
touch its node's name; right-aligned with `text-anchor: end` on the left; every id is `uuid5(<learner id>,
"slot-<n>-<wargame>")` (or `session-<id>-<wargame>`), the name gets the key,
and `show_interface_labels` is on. The adapters read the interfaces
(`interfaces()`): on OpenStack `ip -o -4 addr` (`ifconfig` on OPNsense) on
each slot host over a runner that runs on the host itself, and on the wargame
host the compose containers' addresses through `nsenter` and the bridges by
Docker network id, and the platform VM's own NICs with the same `ip` in a
`busybox` container on the host network (`interfaces.on_this_host`; the
platform takes no SSH); on Docker each session endpoint's MAC is matched to
`/sys/class/net` inside its container.

`gns3.publish` signs in as GNS3's admin (the password from
`FSL_GNS3_ADMIN_PASSWORD` or `/run/fsl-gns3/admin-password`, the GNS3 data
directory mounted read-only; the file is 0640 to the Docker socket's group),
deletes the project if GNS3 lists it (a DELETE of a project GNS3 never held
is logged at ERROR), imports it as a portable project whose `project.gns3`
keeps the URL's project id (GNS3 then keeps every id, as for a snapshot), turns
`auto_close` off (an import is made with it on, whatever the file says, and a
project closed when the last web client leaves stops its nodes), opens it and
starts its nodes. A map is loaded at session open, after a slot's reset, and
when the Map pane asks (`GET /api/topology/?language=&session=`) and GNS3
does not hold it open; an unchanged map is not loaded again. The maps kept are
the newest session's of each slot and the open sessions' on Docker; the others
are deleted. Generated maps are never committed. If GNS3 cannot load one, the
endpoint serves the session's wargame's learner map from the file and says why
in `detail`.

Each project has a Korean pair for Korean learners,
`deploy/topology/range-docker.ko.gns3` and `range-openstack.ko.gns3`: the same
nodes, links, ports and positions, with only the zone captions in Korean, in
the terms of `docs/vocabulary.md`; node names stay the role names. Every id in the pair is
`uuid5(<English id>, "ko")` and the project name carries a Korean suffix,
because GNS3's compute keeps nodes by node id alone, so two open projects may
not share one. The English file is canonical; the test rebuilds the Korean
file's structure from it and fails on any difference but the words.

The `gns3` service (`deploy/gns3`, gns3-server 3.1.0a6 with its MCP extra)
holds only the maps the platform loads (a template draws every wargame, so none
is copied in), sets the admin password before the controller database exists
(`FSL_GNS3_ADMIN_PASSWORD`, or generated once into
`/var/lib/fsl-gns3/admin-password`), gives the learner user the
built-in Auditor role on `/` (`FSL_GNS3_AUDITOR_PASSWORD`, or generated once
into `/var/lib/fsl-gns3/auditor-password`, which the platform reads from the
same mount), and writes
`/static/web-ui/map.html`, which signs in as the learner and stores the
token where the bundled web UI reads its controller (`controller-1`,
`controllerIds` in `localStorage`), with `showInterfaceLabels` on and
`integrateLinkLabelsToLinks` off so each link end's label is drawn where the
project puts it, and `statistics_command` set to `false`, so the web UI sends
no usage statistics from the learner's browser; the page is titled Map. It opens the project in a same-origin frame and makes it
view-only before the map draws: a stylesheet hides every piece of editing
chrome (the title bar, the tool column, context menus, the topology summary,
dialogs and the Angular CDK overlay) and takes pointer events off everything
inside `svg.map`, and capture-phase listeners on the frame's window swallow every
trusted click, double-click, context menu, key and drop, and every mousedown
but a left press on `svg.map` itself. The page's own synthetic events are not
trusted, so its clicks on the hidden controls still land. Once the map is
drawn it closes the topology summary (its visibility is a constant in the
3.1.0a6 bundle), turns the web UI's moving mode on for good (a drag on the map
pans, the wheel zooms), resets the zoom, zooms out with the web UI's own button
(0.1 a step; the web UI never reads the project's `zoom`) until the drawing
fits, and centres it with one mousemove (the web UI pans by
`movementX`/`movementY`). The pane's Fit to view button posts `fit` to the
frame, which runs the same reset and fit; the console posts it on every pane
open and resize too, and shows "Loading the map..." on every open until the page
posts `{map: "drawn"}` (after its first fit) or `{map: "fitted"}` (after
every later one, which retries until the drawing lies inside the frame); the
frame stays hidden until then. The page answers the coach's
`{locate}` for a node, a link, a link end's label (read once from
`/v3/projects/<id>/nodes` and `/links` with the Auditor's token) or a zone
with its rectangle in the pane, plus the rectangles of every node and interface
label (`text`, so callouts stay off the map's text). The Auditor role still refuses every
write on the server. For development MCP use (`/v3/mcp/`), `docker
exec fsl-gns3 python /opt/fsl-gns3/provision.py api-key <name>` prints an API
key; nothing in the console exposes MCP. The console's tab for it reads
Map (`blue.pane.topology`, one word in Korean too); no word a learner reads
names GNS3.

A read-only user cannot open a project (`Project.Allocate`), so `provision.py`
opens every project as admin at start and starts each of its stopped display
nodes (the pinned image only; a node of any other image is never run), and the
Auditor sees them open and green. What the service needs: uBridge 1.2.3, built
from its release tag with `cap_net_admin,cap_net_raw` file capabilities, and
`CAP_NET_ADMIN` plus `/dev/net/tun` for the `ethernet_switch` nodes (3.1 backs
each with a kernel bridge and TAPs inside the container's own network
namespace); for the `docker` nodes the host's Docker socket (each node is a
container `GNS3.<node>.<project id>` on the host's daemon), Debian's
`docker-cli` (GNS3 closes a docker node with `docker exec`), `busybox-static`
(GNS3 copies it into every docker node it starts) and the host's pid namespace
(`pid: host`: uBridge moves a started node's interface into the namespace of
the container's host pid); `qemu-system-x86` stays for the system maps' `qemu`
nodes. The `[ai-features]` extra, without which 3.1.0a6 does not start, brings
a copilot that clones a skills repository at start; the image sets its
`enabled` to `False` in `skills_config.py` and its build fails if that line is
gone. The host daemon resolves the containers' bind mounts on the host, so
the data directory is the same path on both sides (`/var/lib/fsl-gns3`). The
server runs as the user `gns3`, which joins the socket's group at start as
`fsl` does in the platform. `GET /api/topology/` offers the web UI (`web_ui`)
only while GNS3 reports the project `opened`; otherwise the console's Map
pane says the map is not open.

`GET /api/topology/?language=en|ko` returns the substrate's learner map drawn in
that language (with `&session=<id>`, that session's map for its wargame, above)
from GNS3 (`platform/gns3.py`) or the repo's file (`en` when absent, 400 for
another); the console sends its own language, and `web_ui` deep-links the GNS3
web UI to that project's id. The Map pane is that map alone: the framed
GNS3 web UI and its fit button. `GET /api/sessions/<id>/topology/` reads the
English map of the session's wargame (the pair has the same node names and
links) and adds `project.nodes`: each host node's addresses per switch from the
same range read, `running` or `not reported`; the session overlay lists only the
map's hosts and their addresses on the map's switches. The overlay places hosts
by the names the range reports them under; OpenStack reports a slot's servers by
their declared names (`slot.known_as`), and only the VM's own hostname, which the
syslog records carry, has the slot suffix.

## Isolation seams

Each concern has one owning file. The exceptions below exist in code today.

| Concern | Owning file | Known exceptions |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py` PUTs the `geoip` ingest pipeline at bring-up |
| The Kibana HTTP API, its saved objects and the Discover link | `platform/kibana.py` | none |
| The GNS3 API | `platform/gns3.py` | `deploy/gns3/provision.py`, inside the GNS3 container, signs in as admin to provision the learner and open the projects; the console's Map pane frames the web UI at the port and path `gns3.py` returns |
| CRS configuration and the nginx reload | `platform/rules/crs.py` | the WAF terminal (`waf-terminal.sh`) opens a shell in `fsl-<id>-waf-1` for the person (on OpenStack, `vm-terminal.sh fsl-waf` an ssh shell on the WAF VM), and f6's WAF-pane steps show the commands the learner types (`grep -n ruleRemove {waf_rules}`, `{sudo}nano {waf_rules} && {waf_reload}`), filled in by `wargames.lesson` from the declared exclusion file and reload command (`settings.FSL_WAF`); the platform does not drive the terminal |
| The session's WAF container (docker) | `platform/range/docker.py`, by compose label | none in Python; `waf-terminal.sh` names `fsl-<id>-waf-1` (the row above) |
| The Suricata process | `platform/rules/suricata.py` | `platform/range/opnsense.py` and `deploy/opnsense/` configure and restart Suricata on the OPNsense edge (OpenStack); each sensor host in `declaration.yaml` (the edge, and the wargame host for `estate-sensor`) names the rule file and reload command `suricata.py` is handed; `platform/range/wargame_host.py` (with `deploy/wargame-host/sensor.yaml`) stops and starts the estate sensor's compose service on the wargame host when a slot is configured or reset (OpenStack), and its baseline rules then go through `suricata.py` |
| The attacker box | `platform/attacker.py` | `platform/operator_log.py` reads `/var/log/commands.log`; the terminal wiring (`settings.py`, `nginx.conf`, `entrypoint.sh`) names `fsl-kali` and `fsl-<id>-kali-1`. Not an exception: the Website pane (`platform/api/site.py`) reaches the box only through `attacker.py` (`customer_origins`, `unbound_source`, `as_customer`, which holds the command) and the substrate's `opened` (an ssh stdio stream on OpenStack) |
| The target's own records | `platform/api/loot.py` (board), `platform/api/effect.py` (corp) | none; on OpenStack they reach the same containers, `loot.py` over HTTP at the wargame host's published port and `effect.py` through the runner, which `docker exec`s into `corp-db` |

## Where requests come from

| Route | Sender | Source address in the alert | Marker |
|---|---|---|---|
| Terminal, HTTP | Kali, through `proxy:8081` | the proxy, on the chosen origin | added by the proxy |
| Terminal, raw TCP | Kali directly | Kali, on `edge` only | none |
| Console case, HTTP | the platform | the platform, on the chosen origin | added by the harness |
| Console case, tool | a throwaway `fsl-kali` container | that container, on the chosen origin | sqlmap `--headers=` |
| CLI run, HTTP | the platform, `redteam/run.py` | the platform, on `edge` (where `board.com` resolves) | added by the harness |
| CLI run, tool | a throwaway `fsl-kali` container, from `launcher(<declared default origin>)` | that container | sqlmap `--headers=` |
| Site browser | the learner's browser, through the platform's nginx on port 8002 and `platform/api/site.py` | a customers address: on OpenStack one Kali holds, sent as the `fsl-users` account so it crosses the edge; on docker the platform's own address on the customers network | the session's secret `browse-<hex>`, set by `site.py`; the API shows it as `browse` |
| Customers | `deploy/traffic/users.py`, in `fsl-<id>-users` (docker) or as `fsl-users` on the Kali VM (OpenStack) | the persona's own address on a non-default origin, never one the attacker sends from | a fresh UUID per request |

The proxy is a `mitmdump` script (on the OpenStack Kali, `web-proxy.service` runs it from `/usr/local/lib/web-proxy.py`, and `ttyd.service` the terminal; `/var/lib/session/active` and `origin` are mode 0600 for `ubuntu`, which the platform logs in as, and the shell hook reads the marker through `sudo -n cat` when it cannot read it; `/var/log/commands.log` is 0622 `ubuntu`, so `kali` can only append). It sets `X-Request-ID` from `/var/lib/session/active`
on a request that carries none and, when `/var/lib/session/origin` names an address, forwards the request there with the
original `Host`. The platform writes both files with `docker exec`. There is no
TLS interception, so the proxy is an environment variable and does not enforce
anything: `curl --noproxy '*'` skips it.

The terminal also records what the operator types. Kali's shell appends each
command, with the current `/var/lib/session/active` marker, to
`/var/log/commands.log`. The platform reads it through
`runner("attacker")` and serves it at `GET /api/sessions/<id>/commands/`.
The Kali pane (the red console's, and the blue console's in a lesson or
scenario session) frames the URL the session API names (`kali_terminal` in
`GET /api/sessions/<id>/`). On compose it is `/terminal/<session id>/`, which
nginx proxies to Kali's own ttyd in `fsl-<id>-kali-1:7681`. On OpenStack it is
`/vm-terminal/kali/?arg=<session id>`, a ttyd inside the platform that
connects over ssh to the mgmt address of the host in the session's slot; on compose, Kali and the WAF have no mgmt address, so
`/vm-terminal/` does not connect there.

`vm-terminal.sh` checks the host key under the alias the platform's runner
uses for the same server, `fsl-<server id>-<launch time>`
(`OpenStack.host_key_alias`), with `StrictHostKeyChecking=accept-new`: a
server rebuilt by a reset is a new alias, so its new key is learnt without
the "REMOTE HOST IDENTIFICATION HAS CHANGED" warning, and a changed key under
an alias already known is refused. Kali gets a plain login as the `kali` user
(sudo, hostname `kali`, Kali's own two-line prompt, no motd), so
`/etc/profile.d/proxy.sh` (`http_proxy`) and the command hook
(`/usr/local/lib/shell-hook.sh`, `__log_command`, sourced from
`/etc/bash.bashrc`) apply as at any login. The WAF runs `bash --rcfile` with
`-i` as `ubuntu`: the rc file reads `/etc/profile` and `~/.profile`, sets the
time zone, replaces `\h` in the prompt with the host's name without `fsl-`
(`ubuntu@waf`) and prints `/etc/motd`; with a command, sshd prints no Ubuntu
login banner or last-login line. The WAF VM's own hostname is `waf` too: the
boot unit `set-hostname` renames it after cloud-init and hands the Nova name to
rsyslog as `localHostname` without the `fsl-` prefix (`waf`, `waf-2`), so Filebeat
still reads the slot from the sender name.

The blue console's WAF pane frames the URL the session API names
(`waf_terminal` in `GET /api/sessions/<id>/`). On compose it is
`/waf-terminal/<session id>/`: nginx takes the session from the path, drops the
client's query and proxies to a ttyd inside the platform
(`ttyd -W -a -b /waf-terminal -i 127.0.0.1 -p 7693 /app/waf-terminal.sh`) with `?arg=<session id>`;
ttyd's `-a` passes that as the script's argument, and the script, after checking
it is a number, runs `docker exec -it fsl-<id>-waf-1 bash`. The WAF image has
no ttyd of its own. The same `auth_request /terminal-allowed` guards it. On
OpenStack the pane frames `/vm-terminal/waf/?arg=<session id>`.

The blue console's Website pane is a browser inside the console: back,
forward, reload (a stop button with a thin progress bar while a page loads),
an address bar that shows the full URL (`http://board.com/<path>`) with
Chrome's "Not secure" marker for http and takes a URL or a path and Enter,
the page in an iframe, and a "Developer tools" toggle (also F12, inside the
page too). An address for another host shows Chrome's "This site can't be
reached" page. The target is not published, so nginx on 8002 passes
`/site/<session>/<host>/<path>`, behind the same `auth_request
/terminal-allowed` as the terminals, to the platform's recorder
(`/site-proxy/<session>/<host>/`, `platform/api/site.py`, with the exact path
and query in `X-Site-Uri`), which sends it from the customers side of the
range (below) with `Host: <host>`, no redirect following and no compression.
It passes on only `Accept`, `Accept-Language`, `Content-Type`,
`User-Agent`, `Referer` and `Origin`, the last two rewritten to what a
browser on `http://<host>/` would send (`as_browsed`); `X-Forwarded-For` is
not among them, so the WAF adds the customers address and the target never
sees the learner's LAN address. It answers 404 for a session that does not
exist and 409 for a closed one, without calling the WAF, 400 for a path that
is not a valid request target, and 502 ("board.com did not answer") when
nothing answers within 3 s to connect or 20 s to read. The page is
streamed to the browser as it arrives. nginx on 8000 answers 404
for `/site-proxy/`, and the platform's same-origin check for POSTs skips that
path, so a form on the target can still be submitted. The WAF judges every page: a block is the WAF's own 403 page
and lands in Kibana. The path and query go on exactly as the browser sent them
(a `map` on `$request_uri`). nginx rewrites what would leave the prefix:
`Location` headers (`proxy_redirect`), and in HTML `href="/`, `src="/`,
`action="/`, `http://<host>/` and `http://<host>"` (`sub_filter`, with the
upstream asked for no compression); WordPress's escaped `http:\/\/corp.com\/`
too. It strips `Cookie` and `Set-Cookie`, so the platform's cookies never reach
the target and the target's `Set-Cookie` headers are dropped, which means the
target cannot be logged into from this pane. That does not stop a script on the
target page: it runs on the platform's host (port 8002), and cookies are not
isolated by port, so `document.cookie` could set a cookie the console on 8000
would send. The console uses no cookies today; one added later would be
reachable this way. It appends a script before `</body>` that posts
`location.pathname + search` to the parent, which is how the address bar and
the history follow a link clicked inside the page, passes F12 up, and
answers the coach's `{locate: <selector>}` with the element's rectangle
(again on scroll and resize), only for a message from its parent whose origin
is the console's host; it adds no request of its own. It shows each link as
`http://<site>/...` (the markup nginx rewrote keeps the proxy path, so a hover
shows the address the customer would see) and sends a plain click on such a
link through the proxy path.

The Website pane's egress (`site.found_egress`, once per session) leaves
from a customers address, so its requests take the customers' path and the
sensors see them as they see the customers: the origin the scenario's
customer traffic weights most (`customers.declared`, else the first by id)
among `attacker.customer_origins`. On OpenStack (`ATTACKER_ORIGIN_MODE=snat`)
the recorder opens an ssh stdio stream to Kali (`OpenStack.opened`) running
`attacker.as_customer`: a Python bridge, as the `fsl-users` account that
Kali's origin SNAT leaves alone (created with its exemption when the
customers never ran on the slot), bound to that origin's first address and
connected to the WAF's `estate` address on port 80; the request crosses the
edge (DNAT), the edge sensor sees it arrive at `waf`, and the estate sensor
sees `waf` send it on to `board.com` with the customers address in
`X-Forwarded-For`. On docker the platform binds its own address on that
customers network and connects to the WAF's address there; the Suricata in
the WAF's namespace sees both legs. No container or `mgmt` address is named.

The route is served on its own port, 8002, a different origin from the
console's 8000, and every response carries `Content-Security-Policy: sandbox
allow-forms allow-scripts allow-same-origin`. The target is the red team's to
plant script in; on the console's origin that script could read and drive the
console and its APIs. A sandbox without `allow-same-origin` (an opaque origin)
would do that on 8000 alone, but Chromium-based embedded browsers refuse such a
frame (`ERR_BLOCKED_BY_CLIENT` in the Claude desktop browser). `SITE_PORT` is
8002 on every substrate. The session API gives `site: {port, path}` or
`null`, and the console hides the pane without it. The platform template's
security group opens 8002 (`docs/OPENSTACK.md` §3.5).

The recorder keeps each session's last 200 requests in the platform's memory
(lost on restart) and forgets them when the session closes: method,
`http://<host><path>`, status and its text, type and category (from
`Sec-Fetch-Dest`, else the content type), initiator, transferred size, time,
the egress address, the remote address, the referrer policy the page set,
the request headers as sent without the marker, the response headers
without `Set-Cookie`, and the bodies, each cut to 64 KB (the response is
streamed and only its first 64 KB kept). `GET
/api/sessions/<id>/site/requests/?after=<id>` lists them and
`.../site/requests/<id>/` gives one in full. The Developer tools panel is
Chrome's Network panel, docked under the page (its top edge drags taller or
shorter); while open, the tab visible and the session open, it polls the
list every 2 s (a closed session answers 409 and the polling stops). Columns
Name (the last path segment and query, the full URL on hover), Status (4xx
and 5xx in red), Type, Initiator, Size and Time; a toolbar with clear, a
filter, Preserve log (off: a navigation clears the list) and type chips (All,
Fetch/XHR, Doc, CSS, JS, Img); a selected row has Headers (General: Request
URL, Request Method, Status Code, Remote Address, Referrer Policy; then
Response Headers and Request Headers, each with a raw view), Payload (Query
String Parameters decoded, with source and URL-encoded views, and a form
body), Preview and Response. Rows, tabs and lines carry `data-coach` for the
coach. The Korean labels are Chrome's own (`front_end/core/i18n/locales/ko.json`),
the English ones Chrome's en-US casing; nothing in the panel says "WAF".

Browsing is marked with the session's own secret (`Session.browse_marker`,
`browse-` and 32 random hex digits, made when the session is created; the
recorder replaces whatever `X-Request-ID` the browser sent), and the request
comes from a customers address (above). Its alerts are ingested and listed
like any other, so the learner finds them in Kibana and in `/detections/`, but
`/score/` leaves out detections carrying that session's secret the way it
leaves out replays (`views.REPLAY_MARKS`): browsing is not a case, so it is neither a
true or false positive nor an unattributed alert. A literal `X-Request-ID:
browse` sent by hand is just an unknown marker and is scored, and `POST
/api/attacker/label/` refuses labels that start with `browse`. The API never
shows the secret: `/detections/`, `/api/detections/<id>/` (including `raw`)
and the Network panel show `browse` in its place. Kibana shows it, which is
the blue team's tool. The red console's Website pane is the same pane on
the same session: in a wargame the attacker's browsing carries the session's
secret too, so it is left out of `/score/` like the defender's, and the
defender's Network panel lists it (open: the person-against-person wargame,
4.2, is not built).

A console HTTP case carries the `Host` of the session's wargame, `board.com`,
whether or not an origin was chosen. Choosing an origin points traffic at the
WAF's address on that origin's segment, by IP; the name resolves on the `edge`
network, which the platform uses when no origin is set. The edge networks are
shared, so `board.com` there resolves to every session's WAF; at open the
platform aims the session's proxy at its own WAF, and launched tools get
`--add-host board.com` and `corp.com` at that WAF's address.
`rotate` is a per-session round robin, not a random pick.

A console tool case is pointed at the origin's target URL, or, with no origin
chosen, at `TARGET_URL` (`http://board.com`) from the declared default origin.
The target is not host-published, so the command-line harness reaches it from
inside the range too: `redteam/run.py` runs on the platform (the way the
acceptance suite drives it), has no origin option, and its `--target` defaults to the `public_url` of the
scenario its `--cases` file belongs to (`http://board.com` for board), which
resolves to the WAF on port 80. `--tool-target` defaults to `http://board.com`.

On docker the session WAF runs CRS with `SecRuleEngine On` and anomaly
threshold 5 (`session.yaml`); its paranoia level and rule exclusions are the
session's own (`Session.waf`), written at open from the scenario's defense and
changed through `/api/sessions/<id>/waf/` ("Sessions, WAF tuning and the
step engine"). `GET` reads the
file with a 10 s timeout so a poll never holds a server thread longer. Every Suricata
rule is `alert`, so the WAF is the only part of the range that blocks. The
OpenStack WAF VM blocks the same way (`SecRuleEngine On` in
`deploy/waf/modsecurity.conf`, CRS's default threshold 5 and Paranoia Level 1).

## Where alerts go

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, logs-<session>-<day>
                                     (event.module) pipeline geoip
                                                          |
             POST /api/sessions/<id>/ingest/ (called by tests and by the session page's close)
                                                          |
             parse per event.module, copy the marker onto alerts, store
             as Detection rows in SQLite
```

`test/conftest.py` and the session page's confirm-close call `ingest/`;
`redteam/run.py` prints the curl. A browser round ingests its detections once,
at close; alerts that arrive after the click are not ingested.

ModSecurity's audit log carries the request headers, so its alerts carry the
marker directly. Suricata's alert events carry no request headers; only its
`http` events do (with `dump-all-headers: request`; `custom: [X-Request-ID]` has
no effect). Ingest copies the marker from the `http` event onto the alert with
the same `(flow_id, tx_id)`. Joining on `flow_id` alone attributed every alert
on a keep-alive connection to its first case.

Each ingest call:

- first restores rule suppressions that have expired;
- reads `logs-<session>-*` on docker (`ELASTIC_SESSION_INDEX`; each
  session's Filebeat writes its own index) and `logs-<N>-*` on
  OpenStack, where the shared collector tags each syslog line with the slot
  its sender's hostname names (`-N` before the domain, slot 1 otherwise),
  writes it to that slot's index and the ingest pipeline removes the tag
  before the document is stored. Filebeat sets `event.module`
  (`suricata` or `modsecurity`) on every event and drops a syslog line that
  is neither, so an index holds only the two engines' events and no field,
  index or header a learner can open in Kibana names the platform (the case
  marker travels as an `X-Request-ID` header);
- asks Elasticsearch for `@timestamp` from the session's start minus a minute
  to its end (or now) plus a minute. The `geoip` pipeline sets `@timestamp`
  from the event's own clock (Suricata's `timestamp`, ModSecurity's
  `transaction.time_stamp`), so the window selects events by when they
  happened, not when Filebeat read them;
- reads 5000 hits at a time, oldest first, and when a read is cut asks again
  from the newest `@timestamp` it got (`api/views.py` `_fetched`, at most 40
  more reads; documents already read are skipped by `_id`). A window it still
  cannot finish, or one whose 5000 hits share one timestamp, makes the reply
  carry `truncated` and the session record `read_of`, which adds
  `score.warning.truncated` to the score. One sqlmap case leaves more than
  5000 records, so a single read scored every case fired after it FN;
- keeps Suricata's `alert` events, and turns ModSecurity's record into one
  Detection per matched rule message, with id `<Elasticsearch _id>:<n>`;
- drops alerts whose own event time falls outside the window, counted as
  `stale`;
- writes markers found later onto stored rows that had none;
- fills `src_host` and `dest_host` from the substrate's segments, empty if the
  substrate cannot be reached. Ingest and `/detections/` reuse a session's
  segments for 30 s instead of running `docker network ls` and `inspect` on
  every step poll; `/top/`, `/map/` and `/topology/` read them fresh.

Elasticsearch is used for storage and for GeoIP enrichment at index time,
which is why there is no Logstash. Nothing uses its query engine beyond a
time-range search: `GET /api/sessions/<id>/map/` and `/top/` compute in Python
over the SQLite copy, and `src_geo.location` is mapped as two floats, not a
`geo_point`. `bin/worldmap` generates an Equal Earth map cut at 60 degrees
south; no console page draws it since the blue dashboard was removed.

Two geoip processors, on `src_ip` (Suricata) and `transaction.client_ip`
(ModSecurity), write `src_geo`. Compose turns the managed downloader off and
bind-mounts `./config/ingest-geoip`, which `bin/fetch-geoip` fills, so
`GeoLite2-City.mmdb` survives a container recreate. The entrypoint registers
the pipeline at bring-up (`platform/register_pipeline.py`, in the background
like `kibana.py`, so the platform serves while Elasticsearch is still coming
up). waitress serves the platform with 16 threads on 127.0.0.1:8001; the
entrypoint tests nginx's configuration and starts nginx only once that port
accepts, so nginx never answers 502 for a platform still starting. nginx sets
`proxy_max_temp_file_size 0` for every location and a 1 MB request body
buffer, so no proxied response or request body is written to a temporary
file.

## Sessions, WAF tuning and the step engine

A session is opened with `POST /api/sessions/` `{scenario, guidance, lesson,
defense}`, stored on the session (migrations 0015, 0022). `scenario` names a
wargame (default `board`) or a scenario id; a scenario open refuses `lesson`,
`guidance` and `defense` ("Scenarios"). On a wargame, `defense` names one of
its `defense` entries (default `full`); `guidance` (default off, on when
`lesson` is given) needs the wargame to declare `foundations`, and a `lesson`
with `guidance: false` is refused. `{"lesson": "f1"}` to `"f6"` opens that
foundation unit; `{"guidance": true}` alone opens the first by `order` (f1).
The unit is kept as `Session.lesson` and reported as `lesson_id`; a guided
open that names no defense takes the unit's declared `defense`. A session's
`kind` is `scenario`, `lesson` (guided) or `wargame`. A session whose stored
lesson id names no unit any more (one from the older course,
`docs/DECISIONS.md` 2026-10-14) reads `lesson: null` and `lesson_id: null`
and keeps kind `lesson`. Migration 0026 dropped `Session.mode` and cleared
`Session.result_cache`, so stored results are scored again without a lesson
verdict; a `mode` in the body is ignored. The board declares `minimal` (CRS
paranoia level 4, `local.rules`), `full` (paranoia level 1, the same
`local.rules`), `ids` (paranoia level 1, `no-uri-sqli.rules`: `local.rules`
without sid 9000001), `xss-gap` and `overbroad` ("Foundations F1-F6") and the scenario
postures `level2`, `level3`, `inherited`, `untuned`, `broken-rule` and
`spelled` ("Scenarios"); each unit's `defense` is checked against them at
discovery; no unit or scenario starts from `minimal`, so it is reached only
by naming it. `GET
/api/sessions/?ids=1,2` narrows the session list to the ids given. On
every substrate, after the stack is up, the open path seeds the sensor with the
defense's rule file, or `local.rules` without a defense (`suricata.seed`), and
writes the CRS tuning when there is a defense (`crs.apply`); a guided session
then replays the unit's `cases` once (`meta.seed`, with the status curl
reported and `blocked` on a 403), so its ModSecurity and Suricata records are
in Kibana when the learner arrives; a worked scenario does not. On a slotted
(OpenStack) range the seed is skipped when the rule file is `local.rules`:
readiness offered the slot only once every sensor held it. Each slot's sensors
hold their own rule files (measured 2026-10-13: a sid applied to slot 1 was
absent from slot 2), so another rule file is seeded into the slot's sensors
only. If a replay at open cannot
run, the open answers 503 and the session is closed; its stack is left
standing and taken down by the next open.

`platform/rules/crs.py` renders the tuning into
`REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`, the CRS hook that loads after
`crs-setup.conf` and before the rules: a `SecAction` setting
`tx.blocking_paranoia_level` and `tx.detection_paranoia_level`, and one runtime
exclusion per entry (`ctl:ruleRemoveTargetById=<id>;<target>`,
`ctl:ruleRemoveById=<id>`, or `ctl:ruleRemoveTargetByTag=<tag>;<target>` for
an entry that names a CRS `tag` with its target, such as `OWASP_CRS`), scoped by `SecRule REQUEST_FILENAME "@beginsWith
<path>"` when a path is given), with ids 10000 to 10020. It writes the file into the session's WAF with
`runner("gateway")`, runs `nginx -t && nginx -s reload`, and restores the
previous file if nginx refuses. It returns once a worker that was not there
before the reload is up (worker PIDs read from `/proc` by parent PID), so new
connections meet the new tuning; old workers may still drain a slow request.
If no new worker appears within 5 s the reload did not happen: it restores the
previous file, reloads and refuses. Input is validated before anything is written:
paranoia 1-4, rule id 900000-999999 (or a tag of letters, `_` and `-`
with a target), target `ARGS`, `ARGS_GET`, `ARGS_POST`,
`ARGS_NAMES`, `REQUEST_COOKIES` or `REQUEST_HEADERS` with an optional
`:name`, or `REQUEST_URI_RAW` (the Korean search at PL3 also matches 920272
there), a path of `[A-Za-z0-9_./-]`, at most 20 entries; optional
`thresholds` `{inbound, outbound}` (1-100000) are set as
`tx.inbound_anomaly_score_threshold` and `tx.outbound_anomaly_score_threshold`
on the same `SecAction` as the level and read back. A `PUT` that leaves
`thresholds` out keeps the ones in force; `"thresholds": null` clears them.
`PUT /api/sessions/<id>/waf/` changes it (the agent path; no console screen
calls it); `GET` reads the
file in the session's WAF back through `crs.read`, which parses the paranoia
level and every `ctl:ruleRemove*` line (commented lines skipped, continued
lines joined), so it reports an edit made in the WAF terminal, where the
learner tunes. Each scenario final check, when its window is judged, and each
close before the slot is rebuilt, snapshots what `crs.read` reads
(`Session.waf_snapshots`, migration 0021: `{at, scenario_window|closed,
waf}`; sessions from the older course also hold `{at, run, waf}` from their
VERIFY runs); the latest is also `Session.waf`, so a closed session reports
the learner's last configuration, file included (`file: null` when none was
ever read). A WAF that cannot be read takes no snapshot and stops neither.

The fix class (`lesson.fix_class(waf, posture)`, ruling D1) names what the
learner changed against the session's declared posture: `level` when the
paranoia level is below the posture's (a file with no level counts as CRS's
default 1), else `threshold` when an anomaly threshold is above the posture's
(CRS's 5 inbound and 4 outbound when none is set), else `rule` when an
exclusion the posture lacks removes a whole rule, `target` when one removes a
target on no path, `path_target` when every added exclusion removes a target
on a path, and null when nothing was added. The scenario final check reports
it beside its verdict (`result.fix`, `result.scenario.fix`) and it never
changes the verdict. `platform/lesson.py` holds it with the step-answer
helpers (`answered`, `rules_named`, `added_rules`, `pasted_rows`, `within`),
the help counts, and the exclusions added and removed and the file diff the
scenario debrief shows (`exclusions_changed`, `config_diff`).

A case marked with any of `views.REPLAY_MARKS` (`seed`, `verify`, `check`,
`replay`) is left out of `/score/` (TP/FP/FN/TN, the alerts it drew, and the
game) and out of the windows corp's effect observation attributes changes to,
except a benign `seed` case: a lesson's seed replay is scored as a benign
case (2026-10-18), so a lesson session has a true negative. Only `seed` is
still written; `verify`, `check` and `replay` stay listed so the replays
older sessions hold stay out of both scores.

The console is four screens, every one filled from `/api/` (a static mockup
the user approved, with two rulings on top; `docs/DECISIONS.md`, 2026-10-11,
console redesign). The palette and component classes are in `base.html` and
`platform/console/components.css`, which `bin/build-css` puts into
`tailwind.css`. The header carries the breadcrumb, the range state and the
language switch.

- Main (`/`): running sessions with their kind (`scenario`, `lesson` or
  `wargame`), the step a foundation session reached and whether opening has
  finished (`ready`, from `Session.ready_at`; "Preparing ns / about 80s"
  until then); wargame cards with category, difficulty and minutes from
  `scenario.yaml` and counts of attack cases, benign cases and objectives
  from `GET /api/wargames/`. Under each card come the foundations block
  (each unit with its minutes, what it teaches and Start, which posts
  `{scenario, guidance: true, lesson, defense}` with the unit's declared
  defense), the scenarios block ("Scenarios"), then one plain "Start
  wargame" (`[data-wargame-start]`, posting `{scenario}`: no guidance, the
  `full` defense). Each foundation and scenario also shows its newest run
  among the sessions this browser opened (`fsl-opened-sessions` in
  localStorage, written by the session and blue pages, newest first, at most
  20; read through `?ids=`): still open or closed for a foundation, and for a
  scenario PASS/FAIL, still open, or closed with no final check. Finished
  sessions with their `result`: PASS/FAIL from the scenario's last final
  check (`result.scenario`), or objectives lost of the total and how many
  went unnoticed. The result is scored once and stored
  (`Session.result_cache`, migration 0018) with the inputs it was scored
  from: `ended_at`, the hint count, each of detections (last id, rows, rows
  with a marker), cases and objectives (last id, rows), and each final
  check's verdict. A list reads three aggregates per session and scores again
  only a session whose inputs changed, such as a late ingest. A refused
  start is said under the button that was pressed; on 409 "Close open
  sessions" lists the open ones, each closed through `ingest/` then
  `close/`. `GET /api/range/ready/` names `max_sessions`. The range
  controls (the alert pipeline check, the open-session count, the range's
  health and the counts on a wargame card) show only with `?operator`.
- Session (`/session/<id>/`): header figures (the step a guided session
  reached, objectives lost, target), the blue console card and, for a
  wargame session only, the red console card (Kali terminal, Website, the
  objectives), recent
  cases from `GET /api/sessions/<id>/cases/`. Once closed: a scenario's
  verdict banner and its debrief ("Scenarios"), then the primary score
  (every tier, lost or kept, noticed or not, penalty difficulty x1 or x2),
  then plain sentences on what the defence judged: "Caught 7 of 8 attacks,
  missed 1 (name)", "3 of 4 benign requests passed, wrongly blocked 1
  (O'Brien search)", and that a case counts once however many alerts it
  drew. TP/FP/FN/TN and the game's balance stay in the API; no string a
  person reads names them (`test_strings.py`). A lesson session's page
  names each run by its case name and, for a Kali run, "Lesson n · step m"
  (`per_case[].lesson`, `.step`, `.seed`), never by case id, and its course
  card lists every lesson taken with its steps passed and skipped. "Start the same scenario again" ("Start the
  same lesson again" for a unit) reopens the same
  scenario, the same unit (`{scenario, guidance: true, lesson, defense}`
  when `lesson_id` is set) or the same wargame.
- Blue (`/blue/<id>/`): a rail (Kibana, Website, Map, Alerts for a
  judgement scenario, IDS rules for a detection or unknown scenario or a
  lesson with a step on it (F4), WAF,
  then a divider and Kali) and the pane. Kali shows only when the session's
  `kind` is `lesson` or `scenario`: in a `wargame` session a person attacks
  from the red console and the defender does not hold the attacker's shell.
  The Kali pane has its own frame, loaded once, so a running sqlmap survives
  a switch to another pane. On the WAF pane a banner names only the box
  (`waf_box`, `waf`) and the CRS rules directory (`waf_rules`, derived from
  `crs.EXCLUSIONS`).
- Red (`/red/<id>/`): the session and wargame name, the objectives (Korean
  names under `objective.<key>`) and "Submit stolen hashes" at the top; a rail
  with two panes, the session's Kali terminal and the Website pane (address
  bar and developer tools, the blue console's own scripts). It runs no
  prepared attack: no case list, run buttons, recording window or source
  picker (2026-10-18). Narrow widths stack the rail above the pane; the red
  and blue pages do not scroll sideways.

In a guided session (a foundation or a worked scenario) the lesson note is a
column beside the pane, never over it: 340 px wide (300 px at 1280 px or
less), folded to a 44 px strip ("step n/N"), and below 1024 px a panel under
the pane. From the top: the step card (step n/N, the step's title, the task,
the command to type once the step is reached, an "Open <pane>" button when
the step's pane is not shown, the question and its input, the status line,
the help, Skip, Back and Next), the theory card (open on a unit's first
visit, `fsl-lesson-landed-<id>-<lesson>`, then as the viewer left it), F6's
objectives card (`lesson_objectives`: each objective lost since the unit
started, its difficulty, detected or not, and its penalty, difficulty x 1 or
x 2, with the total), a worked scenario's cards and hints, F4's and F6's
ungraded "Do it yourself" card, and the folded step list. The step list ticks
a step only when `progress` says it passed, marks one left unpassed
"skipped", and says "n of N steps passed". Folding is kept per viewer
(`fsl-lesson-note`); the step shown is kept in
`fsl-lesson-step-<id>-<lesson>`, which the main and session pages read for
"step n/N". Progress itself is the session's, kept per unit
(`Session.lesson_steps[<lesson>][<step>]`, migrations 0020 and 0027): per
step `reached`, `passed`, `skipped` (times), `hint` (the level shown),
reported for the session's current unit as `progress` in `GET
/api/sessions/<id>/` and in every step and hint response. A step's record
also carries what it has earned: `command` once the step is reached, `ok`
(the line said on a pass, `{en, ko}`) once it is passed, and in a worked
scenario `answer` once its hint level reaches 3 (`lesson.ANSWER`). `POST
/api/sessions/<id>/lesson/steps/<step>/ {state: reached|skipped}` records a
step reached or left unpassed; reaching a step whose check names a Kali case
gives it a marker and writes that marker to the stamp proxy's
`/var/lib/session/active`. The console sends `skipped` on Next or a list jump from a
step not passed, never on Back or a pass. A pass is said on the passed step;
the next step opens on a clean card.

The steps are declared in the unit (`steps` of a foundation or a worked
scenario in `scenario.yaml`): an `id`, a `check` whose `kind` is one of
`click`, `answer`, `choice`, `rules`, `sent`, `kali`, `loot`, `triage`,
`waf_changed` or `replay` (`wargames.CHECK_KINDS`, validated at discovery),
a `point`, and a terminal `command` when the learner types one, in which
`wargames.lesson` fills `{waf_rules}`, `{waf_reload}` and `{sudo}` from the
declared WAF layout (`settings.FSL_WAF`). A foundation step has no Kibana
`query`. The session API shows a check's `kind` only, plus `form`,
`options` (for `form: order`, every non-switch host on the learner map), the
step's own `match` or the `match` of the step it is `about`, and `solo` on a
foundation's last step: no `accept` list or answer rule reaches the browser.
A step's `command` is in the payload only once `progress` records the step
reached; it is text to type, with no button that runs or copies it. The
pass lines (`<text>.ok.<step>`) and a worked scenario's answers sit in a
`{% comment %}` section at the end of `strings.html`, which Django never
renders; `console/strings.py` reads them and the step's `progress` record
carries them once earned. Each step is advanced by its check; Back and Next
stay as the way around one.

An `answer` or a `choice` passes when the text given equals an accepted value,
ignoring case and spaces (`lesson.answered`); `form: order` compares the hosts
in the order given (split on spaces, commas, `>` and `→`) and says
`<text>.wrong.<step>.order` when the hosts are right and the order is not; a
`wrong_if` rule whose `match` fits the answer says
`<text>.wrong.<step>.<says>`, and a value listed in `known` gets its own
`<text>.wrong.<step>.<value>`. The accepted values are the `accept` list or
are read `of:` the session's records ("Foundations F1-F6"). `of: rule`
(`wargames.ANSWERS_OF`) takes the `path` of the request with `marker:
browse` for the learner's own request, or `marker: step:<id>` for a Kali
step's run, optionally narrowed to a rule `family`: the platform ingests the
last 600 s, takes the session's ModSecurity detections of that request or
run, drops the CRS totals (rule ids starting 949, 959 or 980) and accepts
each remaining `ruleId` (`lesson.rules_named`). With nothing recorded the
reason is `lesson.check.unrecorded`. A `rules` step passes once the sensor's
file (`GET /api/rules/`) holds a sid the posture's rule file does not hold,
or holds with other text (`lesson.added_rules`, `suppress.sids`), and
answers `added`; `needs: nocase` also wants that rule to carry `nocase` or a
pcre with the `i` flag (`lesson.ignores_case`). `triage` (`judged: customer
| attack | all`) passes on the learner's right verdicts ("Scenarios").
`waf_changed` (`removed_target`) passes once no exclusion in the WAF's file
targets that variable while the posture declared one. `replay` passes once,
after the step named `after` passed, an attack (`sent` regex, or `kali` case)
meets its `expect` (an alert from one of the learner's added sids; or the
run blocked, 949110 among its detections, with no loot credited) and a
benign request after the same time meets its own (`status_class`, no added
sid alerting, or no WAF record); the reason names the half that is missing
(`lesson.check.replay_attack`, `lesson.check.replay_benign`). `click` is the
console's word.

Every check is judged by the platform, `POST
/api/sessions/<id>/lesson/steps/<step>/check/` (`{answer}` for an answer, a
choice or a pasted table, `{poll: true}` for a background poll), which
records `passed` and answers `{passed, reason, hint, hints, progress}` (plus
`added` from a `rules` check, `kali` from a `kali` or `replay` check and
`loot` from a `loot` check); `reason` is a `strings.html` key with its
values. A failed check that is not a poll counts as wrong; two raise the
step's hint level and record the hint, or in a worked scenario offer the
scenario's next hint (`scenario_run.stuck`).

Checks run by themselves. `sent`, `triage`, `kali`, `replay` and
`waf_changed` are polled silently every 5 s while their step is shown, the
tab is visible and the session open (the page re-reads the session every
30 s to notice a close); a poll never writes the status line. `sent` also
runs 1.5 s after the Website pane shows a path matching the step's `match`,
and `rules` when the rule editor applies a file. A pass says the step's `ok`
line on the passed step and 1.5 s later moves to the next step. The step
after a Kali step shows that step's row: the case's name and "Open Kibana at
this run's time" (the run's window, an empty query; no request count, no
sensor name), read again by a poll of the Kali check after a reload. On the
last step a foundation says "Lesson complete. Next lesson: <title>" and moves
on ("One session, F1 to F6"); after F6 the card lists the lessons taken and
a button closes the session. A worked scenario says "Lesson complete". A
wrong answer says what is wrong. A recent ingest (`within`) reads the newest
records of the window first and records no truncation, because one sqlmap
case leaves more than 5000.

Help climbs a ladder per step, on "Show a hint" or after two wrong answers
or failed checks: in a foundation the nudge (`<text>.nudge.<step>`, where to
look), then the hint (`<text>.hint.<step>`, how to read it, never the
answer), then Skip (`lesson.SKIP_OFFERED_IN_FOUNDATIONS`, 3); a worked
scenario keeps its answer rung before Skip (`lesson.ANSWER`,
`lesson.SKIP_OFFERED`). Each press is `POST /api/sessions/<id>/lesson/hints/
{step, level: "hint"}`, which raises the step's `hint` level, and the first
is recorded in `Session.hints` with its unit (`{lesson, step, level}`;
migrations 0017 and 0027; 400 for a session that is not guided or a step or
level the unit does not have, 409 when closed). After 60 s on a step the
button only changes to "Show the new hint"; nothing is recorded until the
learner presses it. A foundation's last step is solo: no highlight, no
nudge, no hint, Skip from the start. Skip is `POST
/api/sessions/<id>/lesson/steps/<step>/ {state: skipped}` and the next step
reached; on the last step it records the skip and, in a foundation, moves to
the next unit as a pass does, or in a worked scenario closes the step.
Nothing is entered, fired, applied or credited for the learner, so a later
step that reads a skipped step's record (an answer about a request never
sent, the loot of a run never made) stays unanswered until the learner does
that step or skips it too. `result.scenario.helped` (`["hint"]` or none) puts
"hints used" beside PASS or FAIL on the main page and the closed session's
page.

Each lesson opens on the pane its first step names (`opens`), and the
console names no unit's step and no selector: where a step points is its
`point` in `scenario.yaml`, one locator and `opens`, the pane it needs.
Locators: `panel` (a console element: the site's address bar, the rule
editor, the objectives total), `map` (`node`, `link`, `label: [host,
switch]` or `zone`, which the server resolves from `{switch:<host>}`;
`deploy/gns3/auditor.html` answers `{locate}` by `postMessage` with the
rectangle, every zone drawing's rectangle (`zones`) and the boxes of the nodes, interface labels and zone captions (`text`, so callouts stay off them), refits on `{fit}`, and posts `{map: "drawn"}` after its first fit and `{map: "fitted"}` after each later one), `site` (a
selector inside the cross-origin site frame, answered by the script nginx
injects), `dev` (a `data-coach` name in the developer tools: the toggle, the
matching row, a tab, a line), `kibana` (in the same-origin Kibana frame:
`query`, `hits` with `discoverNoResults` as its fallback (its own stage callout), `doc: <field>` for
a field's row in the document flyout, brought into view through the
flyout's field filter; on a step whose check names a `leg` the coach rings
the expand toggle of the row on that leg (the one whose source is another
row's destination, or the reverse) and the flyout's arrow while the other
event is open (when that row cannot be found, or the open document's position
is unknown, it rings the field filter and never a value; `keep: true` on the
point leaves the flyout open on arrival), `sidebar: <field>`) and `term`
(`{pane: kali | waf, match}`: the row of the xterm buffer that matches; an
optional `done` pattern, once printed after the last typed command, moves the
ring to the step's check button). A two-phase point holds
the first target `until: sent` and then points at `then` (the select, then
the payload line). The highlight dims the pane alone (`pointer-events:
none`), rings the target in the primary colour and puts a one-line callout
beside it (`<text>.callout.<step>`, `.callout.<step>.then` for the second
phase), flipped or shifted inside the pane, never over the target, the
rail, the bars or the note, nor over the text and controls the site frame or
the Kibana frame report around the target (Kibana's leaf text and controls
within 220 px of the ring, skipping what the document flyout covers); with no
one-line spot free it wraps to two or three lines, a flyout step (the next-event
arrow) looks inside the flyout first, and a target in the note card gets its
callout in the pane beside the card; the leader line crosses no text and is
left out when the callout is within 48 px of the ring; the hint says "Look at the highlighted spot."
when the step has a locator. While the step's pane is not shown, the step
card shows the "Open <pane>" button (`lesson.open.<pane>`), ringed with its own
callout (`lesson.open.callout`; none on the last step); with no target
for about 2 s the card says where to look (`lesson.coach.missing`). The map
refits when its pane's size differs from the size it was last fitted at (a pane open or a
resize), so a step change or a lesson's last step alone does not redraw it.
`test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console`
holds every `point` of every foundation and stepped scenario to the console
as rendered.

The rule editor (`#lesson-rules`, ruling D3) sits in the blue console's IDS
rules pane, which `rulesPane()` shows for a scenario of class `detection` or
`unknown`. It reads `GET /api/rules/?session=<id>`, checks with `POST
/api/rules/validate/` and writes with `POST /api/rules/apply/` on the version
it loaded. Check rules answers `errors`: the lines carrying Suricata's `Error`
from every sensor that refused, and `output` is the refusing sensor's output
with the most of them. The OPNsense edge's Suricata logs to syslog only (its
template has no console output), so its `-T` output carries no error line;
the wargame host's estate sensor prints them.

### Foundations F1-F6

`docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`
phase P2, rebuilt on 2026-10-18 as attack and defence lessons
(`docs/DECISIONS.md`, "Foundations rebuilt as integrated attack and defence
lessons"). The board's `scenario.yaml` declares a `foundations:` list, checked
at discovery (ids unique across the foundations and the scenarios,
`wargames.checked_groups`). The foundations are the taught units; the worked
scenarios 1.1 and 3.1 run their steps on the same engine.
`wargames.foundations()` lists them by `order`; `wargames.lesson(lesson_id=...)`
finds a foundation or a scenario with steps, refuses any other id, and marks a
foundation `group: foundations`. `GET /api/wargames/` lists `foundations`
(`wargames._foundation_card`: `id`, `order`, the `title` and `goal` string
keys, `minutes`, `level`, `defense`, `prerequisites`, the step count,
`step_ids`, and `learns`, the string key of what the unit teaches); the main
page lists them first, as lessons, with minutes, what each teaches and a
Start button (a guided open of that unit). Every unit seeds
`board-normal-search` at open; the seed is a benign case and counts in the
second score (`views._replayed` keeps a benign `meta.seed` case), so a closed
course has a true negative, and `no_benign` and `no_marker` are not shown in
a lesson session.

| unit | defense, opens on | the learner | answers read from |
|---|---|---|---|
| f1 Reading the network map (`lesson.map`) | `full`, Map | reads board.com's Services address, board-db's subnet, the name of kali's network, picks in order the hosts a customer's search passes, names the host that collects the logs; solo: board-db's address | the session's learner map (`topology.facts` through `topology.learner`): link-label addresses (`address`, with or without the prefix length), the zone's subnet (`subnet`), the zone caption in both languages (`zone_of`), `customers` then the transit roles present then the site (`path`: `customers > firewall > waf > board.com` on OpenStack, `customers > waf > board.com` on Docker), the `log-server` node (`logs`) |
| f2 Reading HTTP requests in DevTools (`lesson.http`) | `full`, Website | searches with the board's search box; reads method, parameter, path and status in the Network panel, then the parameter behind the board's sort control; solo: the status of a post that does not exist | the learner's own Website pane records: `method`, `parameter`, `path` (a `wrong_if` says when the answer carries the host or the query), `status` |
| f3 Finding your requests in Kibana (`lesson.logs`) | `full`, Website | searches a word of letters and digits and writes KQL for it; the source IP of the event arriving at board.com, the map host that uses it, the source IP of the same search arriving at waf, its X-Forwarded-For; whether the WAF logged it; solo: how many of their searches arrived at waf | the sensors' http events of the record (`sensor_source`, `forwarded_for`), split by leg: `upstream` when `dest_ip` is one of board.com's addresses (waf sends it on), `inbound` otherwise (it arrives at waf), so one sensor that sees both legs counts each search once; `host_of` the map host with that address; `waf_logged` from the WAF's own records; `hits` one count of the learner's own searches: the inbound events with the browse marker under `/search/` since the unit (or the session) started |
| f4 Blocking an XSS request and writing an IDS rule (`lesson.xss`) | `xss-gap`, Website | `<script>alert(1)</script>`: status, one detecting rule, the Total Score; the mixed-case probe's status; whether either drew an IDS alert; writes a rule for `<script` in the URI, reads its sid from its alert, sees the mixed case slip past, adds `nocase`; solo: replays the mixed case and an ordinary search | `status`; `rule` (ModSecurity rule ids of the request, 949110 excluded); `anomaly_total` (949110's `Total Score: N`); `alerted`, `alerted_sid`, `alerted_sid_present` (Suricata alerts in the record's window, against `lesson.added_rules`); `rules` with `needs: nocase`; `replay` |
| f5 Analysing SQL injection on the sort parameter (`lesson.sqli`) | `full`, Website | reads the sort value; adds `)` in the address bar and reads the status; says whether a WAF rule detected it; types sqlmap in the Kali pane, reads its verdict, the run's source IP and the rule that named the scanner; reruns with `--random-agent`; solo: one rule that still blocked it | `param_value`, `status`, `waf_detected` (ModSecurity detections of the request: a 500 is logged with no rule, which is no detection); `sqlmap_found` (`attacker.sqlmap_found` reads `<home>/.local/share/sqlmap/output/<host>/log` on the box: a `Parameter:` line or not); `kali_source` (the run's ModSecurity `src_ip`); `rule` with `marker: step:<id>` and `family: "913"` (the scanner), then with `family: "942"` and `known: [949110, 913100]` (the SQL injection rule that still blocked the rerun) |
| f6 Finding the attack an over-broad exception let through (`lesson.miss`) | `overbroad`, WAF | greps the exclusion file for the parameter left out; dumps the accounts with sqlmap and pastes the table; says which engines alerted; how many WAF log records of the run have status 500; the penalty the admin objective would carry if detected; deletes the exception and reloads nginx; solo: replays the dump and sorts once | `excluded_target` (the WAF file in force: `ARGS:sort` or `sort`); `loot` against the session's snapshot; `alerted_by` (none, IDS only, WAF only, both, from the run's detections); `run_errors` (count of the WAF (ModSecurity) log records with status 500 in the window Kibana opens on, the number `log_source : modsecurity and status : 500` shows, `lesson.server_errors`); `detected_penalty` with `objective:` (the objective's difficulty x 1, the penalty it would carry if detected; the tier is read from `wargames.objectives`, empty when the scenario is not judged); `waf_changed`; `replay` (the run blocked with no loot, an ordinary sort 2xx with no WAF record) |

The postures: `xss-gap` is CRS paranoia level 1 with `no-xss.rules`
(`local.rules` without sid 9000003); `overbroad` is level 1 with one
exclusion, `{tag: OWASP_CRS, target: "ARGS:sort"}` (`SecAction
"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:sort"`:
every CRS rule skips `sort`), and `no-uri-sqli.rules`. F6's sqlmap command
carries `--skip-waf`: sqlmap's own WAF-detection request would otherwise
trip IDS 9000003 and 9000004 and one CRS rule, and the run would count as
detected. No unit question carries an `accept` list.

One session, F1 to F6. `POST /api/sessions/<id>/lesson/ {"lesson": "<id>"}`
moves an open guided session to any foundation in place: when that unit's
declared defense differs from `Session.defense`, it writes the unit's CRS
tuning (`crs.apply`, as `PUT /waf/` does) and seeds the sensors only when the
posture's rule file changes; it then sets `Session.lesson` and
`Session.defense`, appends `{id, started_at}` to `Session.lessons` (migration
0027; a foundation open writes the first entry), clears the stamp proxy's
label, replays the unit's `cases` as an open does, and answers the session
detail. It refuses a closed session, a scenario session and an unguided one
(409) and an id that is not a foundation (400). The detail carries
`lessons`, `next_lesson` (`{id, text}` of the next foundation by `order`, or
null) and `course` (`[{id, steps, passed, skipped, hints}]` for every unit
taken). The console offers only the next unit: when a foundation's last step
passes or is skipped, the card says "Lesson complete. Next lesson: <title>"
with a "Next lesson" button, and 2 s later posts the switch and reloads the
page into the new unit; after F6 it lists the lessons taken and its button
ingests, closes the session through `POST /close/` and opens the session
page, whose course card lists each lesson's steps passed and skipped and
labels each Kali run "Lesson n · step m". Restarting starts the first lesson
with its own defense. Nothing is reset between units, which the board
allows: its objective layer is exfiltration only (loot matched against the
snapshot taken at open), so a unit leaves the ground truth as it found it;
F4 and F6 change the posture in place, and F5 returns it to `full`.

A unit judges only what happened since it started (`views._lesson_started`,
the last `Session.lessons` entry once there is more than one): a `sent`
check counts only Website pane requests made after it, the `rule` answer only
ModSecurity records after it, a `kali` check reads the sensor from the later
of the step's `reached` and the unit's start, `lost_points` counts only
objectives achieved after it, and the Kibana links open from it. Step
records are the unit's own, so F3's `search` is not passed by F2's.

Three check kinds follow the learner's own actions: `sent` passes when the
session's Website pane kept a request whose decoded path and query match the
step's `match` regular expression; `kali` names a tool case of the case file:
reaching the step gives it a marker, which the platform writes to the stamp
proxy's `/var/lib/session/active` (cleared on a lesson switch and at close), so what
the learner types in the Kali pane goes out marked through Kali's
`http_proxy`. The step's `command` is plain text to type. The check passes
when the sensor's http records carry the marker and the tool's user agent
(any user agent with `ua: any`, for `--random-agent`); it then records the
run as an ordinary malicious case (`meta.kali` and `meta.lesson`, no replay
mark, so it counts in both scores like any other red action) and ingests
the session. A learner who unsets `http_proxy` sends unmarked requests and
the step does not pass. `loot` takes the pasted table (`tools.dumped`, or
`name:hash` and `| name | hash |` lines) and credits it as `POST /loot/`
does, attributed to the kali case; `_credit_loot` keeps the matched accounts
on the case it was attributed to (`meta.loot`).

An answer reads `of:` a range fact (`address`, `subnet`, `zone_of`, `path`,
`logs`, `host_of`, `excluded_target`, `lost_points`, `detected_penalty`), a request fact
(`status`, `method`, `path`, `parameter`, `param_value`, `sensor_source`,
`forwarded_for`, `waf_logged`, `waf_detected`, `anomaly_total`, `alerted`,
`alerted_sid`, `alerted_sid_present`, `hits`) `about:` a step with a `match`
or with its own `match` (the latest Website pane record matching it), a Kali
fact (`sqlmap_found`, `kali_source`, `alerted_by`, `run_errors`) `about:` a `kali` step,
or `rule` with the request's `path` or a `step:` marker (above);
`wargames.read_from_record` refuses anything else at discovery.

## How the scores are computed

Objectives. The board is a `loot_verified` target. Its
`wargames/board/objectives.yaml` names the secret (the `auth_user` username and
password columns, read from `/internal/auth-users`) and three tiers by how much
of it the attacker holds: any one hash (difficulty 2), the `admin` account's
(4), every account's (5). The attacker exfiltrates hashes and submits them with
`POST /api/sessions/<id>/loot/`, from the red console's loot panel (shown only
for `loot_verified` scenarios). The platform credits a tier only for submitted
`(username, hash)` pairs that match the session's start-of-session snapshot
exactly, and only once the session has fired a malicious case. It never credits
an objective from its own belief about what an attack did. The ground truth is
the target's own records, which the detectors do not see.

A credited tier becomes an Objective row dated by the submission. If the
submission names a malicious case (`case_id`), its window runs from 100 ms
before that case started to 100 ms after it ended; otherwise it runs from 2
minutes before the submission to 100 ms after.

The snapshot is taken once, when the session starts. On docker a board
session whose accounts cannot be read (or read empty) is refused with 503 and
closed. On OpenStack it is still created, with no snapshot, and
`POST /api/sessions/<id>/loot/` answers 409 for it. Nothing reads the board
afterwards: `GET /api/wargames/<id>/objectives/` lists the tiers from
`objectives.yaml` and `GET /api/sessions/<id>/objectives/` reports the stored
rows. `POST /api/sessions/<id>/objectives/` observes, and does nothing for a
`loot_verified` wargame.

The corp wargame is an `effect_observed` target: it is scored from the rows
the target commits to its own database, with nothing submitted by the
attacker. Its `wargames/corp/objectives.yaml` declares the read channel
(`estate://corp-db`, scope `wp_state`) and three tiers: a rogue administrator
(`rogue_admin`, difficulty 5), the site opened to self-registration
(`option_flip`, 4) and unauthorized content written (`content_write`, 3). At
session start the platform snapshots the existing admins, the watched
`wp_options` and the published posts with read-only `mysql` SELECTs against
corp-db (`platform/api/effect.py`), run through `runner("corp-db")`, not over
the network. On `POST /api/sessions/<id>/objectives/` it reads corp-db's
binary log with `mysqlbinlog` and credits a tier for each committed change (a
`wp_usermeta` admin grant to a user not in the snapshot, a `wp_options` change
of `users_can_register`/`default_role`, a new or overwritten `wp_posts` row)
whose timestamp falls inside a malicious case's window. As with the board,
the detectors do not see this read.

A taken objective goes to a malicious case whose run overlaps the objective's
window; among several, the one that started latest. The objective counts as
detected only if that case was detected, and one that no case overlaps counts
as undetected. Attribution is by time only: a case's
`takes:` field is not read by scoring.

In the score's `objectives` block, `coverage` is detected difficulty over total
difficulty, `null` when nothing was taken, and `false_positives` is FP.
`damage` is undetected difficulty plus half of detected difficulty, which is
how an undetected loss counts double.

Detection. A case is matched to alerts by one of two strategies, declared
per case:

- `marker`: the alert carries the case's `X-Request-ID` value;
- `window`: the alert's source address matches the case's and its time falls
  within the case's start and end, with two seconds of slack each side.

There is no fallback from one to the other. A marker case whose marker was
lost should show up as a miss, not be covered for by the window. Terminal cases
carry both. `?correlation=marker` or `?correlation=window` on the score
endpoint forces a strategy; any other value is a 400. No console page passes
it (`session.html` requests `/score/` without it); comparing the two is done
by calling the endpoint once per strategy. A disagreement says something about
the scoring method, not the defence.

Each `per_case` entry carries `expect` and `corroborated`. `corroborated` is
true when `expect` appears, ignoring case, in the signature of some matched
alert; a signature that also matched a benign case in the same session does
not count. It is `null` when the case has no `expect`, which is always so for
window cases recorded through `POST /api/sessions/<id>/cases/`, which carry
none. A detected case that is not
corroborated adds `score.warning.wrong_reason`.

A case's `expect` is stored with the case when it is fired, so editing the
case file does not re-judge a finished session. Rows recorded before migration
0009 have no stored `expect` and are still judged against the current case
file. Alert severity and rule type are not used.

The game. The score's `game` block is `{"revealed": false}` until the
session closes. Then it carries four components, their weights and a balance:

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
the same sum as `damage`. `defender` is the weighted mean of the components
times the difficulty taken, minus 1 per FP. `balance` is `defender - attacker`.
When nothing is taken the balance is minus FP. The weights and dwell times are
v1 defaults (`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

Customers. The score's `customers` block counts the customer requests the
session recorded (below): `sent`, `served` (2xx and 3xx), `blocked` (403,
except Django's own CSRF refusal, which the generator marks
`refused_by: "app"`), `unanswered` (no answer within 10 s, status 0), `other`
(any other 4xx or 5xx), `alerted` (customer requests whose marker some alert
carries) and `blocked_actions`. Each request counts once; none is a case, so
the `per_case` list and TP/FP/FN/TN are unchanged, and an alert a customer
request drew is not counted in `unattributed`. The console's second score
says "Customer requests blocked: N of M" beside the case sentences.

The score endpoint is read-only and keeps no history.

## Customer traffic

A board session can carry its customers: Korean community users who browse,
search, sign in and comment for the whole session. The mix is declared in
`wargames/board/traffic.yaml` (users, origin weights, the seeded accounts,
posts 1-3, browser User-Agents, search terms, comment texts, profiles of
action weights). `platform/traffic.py` renders it: twelve personas allocated to
origins by the declared weights (largest remainder), each with its own source
address, browser and language; and 2,000 flows of steps the box cycles
through. Sign-in and comments are form posts: the flow first GETs the page,
the box takes `csrfmiddlewaretoken` from it and sends it with the `csrftoken`
cookie, and follows the 302. A flow whose page carried no token (the GET was
blocked) stops there, as a browser would.

`deploy/traffic/users.py` is the generator: Python's standard library only,
paced to the plan's rate across threads, one fresh UUID in `X-Request-ID` per
request (the same shape as a case's marker, so a learner cannot tell a
customer from an attack by it), one JSON line per request in
`records.jsonl`. It re-reads the plan when the file changes and stops when the
file is removed or on SIGTERM.

| | Docker | OpenStack |
|---|---|---|
| Where it runs | `fsl-<id>-users`, a container from the Kali image started by `Docker.users_box` on the personas' origin networks, labelled `fsl.customers=<id>`; not a compose service | the slot's `fsl-kali` VM, as the system account `fsl-users` |
| Source address | the container's own address on each origin network | each persona is bound to one of the VM's origin addresses |
| Kept apart from the attacker | the declared default origin is not used; the container's addresses are its own | the default origin is not used; nor is any origin's `source_ip` the attacker wears, nor the VM's unbound source (`ip route get` to the target); `POSTROUTING -m owner --uid-owner fsl-users -j RETURN` is inserted before the `ORIGIN-SNAT` SNAT jump, so the attacker's origin rewrite never applies to customers |

`platform/attacker.py` holds every command run on the box: `place_customers`
(the account, the NAT exemption and the program, through `sudo` on OpenStack),
`run_customers` (writes the plan, starts the program with `setsid` and
`setpriv` if it is not running), `stop_customers`, `customer_records`. The
program is shipped from the platform at each start, not baked into the Kali
image: the VM is rebuilt from its golden image at every close, and a file under
`deploy/kali/` would change that image's digest and stop the next rebuild until
the image was rebuilt.

API (`platform/api/customers.py`, `views.session_traffic`):

- `PUT /api/sessions/<id>/traffic/ {rate, profile}` starts the customers or
  changes a running generator's rate and profile (same personas). `rate` is
  requests per second, default 1, at most 50; `profile` is one of the
  wargame's declared profiles: on the board `community` (default), `plain`
  (no unusual searches), `readers` (`plain` without comments) and `club`
  (`community` plus code questions in comments). 404 for a wargame with no
  `traffic.yaml`, 409 for a closed session, 503 when the box or the origins are
  not there.
- `GET` reads the new records first, then returns `declared`, `profiles`,
  `running`, `rate`, `profile`, `started_at`, `stopped_at`, `error`, the
  counts `sent`, `served`, `blocked` (403 from the defence, not the app),
  `unanswered` and `other`, `sources` (origin, address, requests) and
  `by_action` (sent and blocked per action).
- `DELETE` stops it and reads what it sent last. Closing the session does the
  same before the slot is rebuilt; if the box is unreachable the close goes on
  and the error is kept in `traffic.error`.

Records are pulled by byte offset (`tail -c`, at most 1 MiB a call, whole lines
only) into `CustomerRequest` rows with one `bulk_create` per call; the offset
lives in `Session.traffic`. The session page offers the switch only with
`?traffic` in its URL, for testing; a scenario starts it itself.

The generator tells the board's own CSRF refusal (`refused_by: "app"`, not
counted as blocked) by Django's failure page, `<span>(403)</span></h1>`, as
well as its English sentence: the board answers in the customer's language, and
a Korean customer's refusal (two flows of one persona racing the token rotation
at sign-in) is in Korean.

## Scenarios

A scenario is a timed exercise on the range: customers and an attacker use
the board while the learner defends with the real tools, and the platform
judges it over a final verification window. The design is
`docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`
(phase P4); rulings are the 2026-10-13 "scenario course" entries in
`docs/DECISIONS.md`.

**Descriptor.** `scenarios:` in a wargame's `scenario.yaml`, validated by
`wargames.checked_scenarios`:

| Field | Meaning |
|---|---|
| `id`, `order` | `1.1`, `2.1`, ...; ids share one namespace with the foundations |
| `task_class` | `judgement`, `availability`, `detection` or `unknown` |
| `guidance` | `worked` (may declare `steps`, run on the step engine), `faded`, `none` |
| `text`, `briefing` | the strings prefix; `briefing` maps `situation`, `goal`, `measured_by` to string keys |
| `minutes`, `window_minutes` | the scenario's length and its final verification window |
| `defense` | a posture of the wargame's `defense:` map (CRS level, exclusions, thresholds; Suricata ruleset) |
| `traffic` | `{profile, rate}` for the customers (`traffic.yaml`) |
| `red` | `schedule` (the default) or `person`: a person uses the red console and the scenario may declare no attacks |
| `attacks` | `[{at, case, origin}]`: seconds after open (within `minutes`), a malicious case, an optional origin; hidden from the learner |
| `completion` | per class: judgement `{judged: all}`, optionally `pattern: judged`; availability `{served: all, held: all}`, optionally `thresholds: {inbound, outbound}`; unknown `{served: all, held: all}`; detection `{detected_by: suricata}` |
| `cards` | `[{id, when}]`, `when` one of `start`, `alert`, `blocked`, `window` |
| `hints` | hint ids, offered one at a time |

`GET /api/wargames/` lists each scenario's card (`wargames.scenario_card`)
without `attacks`; `GET /api/sessions/<id>/` drops `attacks` and
`completion` from a worked scenario's `lesson` and empties its `cases`.

**Opening.** `POST /api/sessions/ {"scenario": "2.1"}` resolves the wargame
from the scenario id, refuses `lesson`, `guidance` and `defense`, takes
the declared posture as any session does, then `scenario_run.begin` starts the
customers and writes `Session.scenario_state` (migration 0025, beside
`Session.course_scenario`): the schedule with each attack's absolute due time,
the windows, the verdicts, the hint offer and the WAF versions seen. A worked
scenario sets `guidance` true and `lesson` to its id, so its steps run on
`/lesson/steps/` without seeding replays. Customers that cannot start close
the session with 503.

**The engine** (`platform/api/scenario_run.py`, pure rules in
`platform/scenarios.py`) is one thread in the platform process, started on
the first scenario and at boot by `fsl/wsgi.py` (`resume`, which puts an
attack interrupted mid-fire back to due). A failure of a tick or of the
connection cleanup after it is logged on its own and does not end the
thread. Every `FSL_SCENARIO_TICK` (2 s) it, for each open scenario session:

- opens the window at its scheduled time (`minutes - window_minutes` after
  open) if the learner has not;
- claims each due attack and fires it on a pool of four through
  `views._fire`, marked `meta.scheduled` (not a replay mark, so it counts in
  both scores); a sqlmap dump goes through `views._credit_loot`, attributed to
  that case, so the first score counts a loss only when the board's own
  accounts match; the entry keeps `outcome` held or leaked; the case keeps
  sqlmap's conclusion lines and its 403 count (`meta.conclusions`,
  `meta.forbidden`, not judged), and `meta.blocked` is set on a 403 or on
  sqlmap's own not-injectable conclusion after a clean exit with no dumped
  row (`tools.found_not_injectable`); the sqlmap cases decline sqlmap's offer
  to crack the hashes (`--answers=crack=N`), so the dumped cells are the raw
  hashes `loot.matched` compares;
- every `FSL_SCENARIO_OBSERVE` (15 s) pulls the customers' records, ingests
  the last 180 s, and every `FSL_SCENARIO_WAF_POLL` (20 s) reads the WAF file
  to notice a change made in the terminal;
- judges an open window once it has ended and every attack due inside it has
  fired or failed.

Closing cancels the attacks still due; one already firing finishes and is
recorded.

**The final verification window.** `POST .../scenario/verify-window/` ("Start
final check") or the schedule opens it for `window_minutes`; the engine adds one
entry inside it for every attack case the schedule names that is not already
due there. What it judges is the class's `completion`: `served`, no customer
request blocked by the defence within it (403, not the app's); `held`, every
attack inside it fired and was held (no loot match, no effect); `judged`,
every item listed when the window opened judged right (the list is kept with
the window; verdicts given during it count, and an item that reaches the
records later with an earlier time is not added); `detected_by`, every
attack inside it drew a corroborated Suricata alert and no customer request
did; `thresholds`, the CRS anomaly thresholds in force at the window's WAF
snapshot are at most the ones named (a tuning without thresholds runs at the
CRS defaults, 5 inbound and 4 outbound). With `red: person` the window also
judges, like scheduled ones, the malicious cases the person fired inside it
that are not replays. A judgement scenario is judged on its verdicts alone, as the design's
class table says, so customers blocked during its window are reported beside
the result, not counted against it. The result
names the fix (`lesson.fix_class` on the WAF snapshot taken then: `level`,
`threshold`, `rule`, `target`, `path_target`; "Sessions, WAF tuning and the
step engine"). A failed window can be followed
by another.

**Judging alerts** (`GET/POST /api/sessions/<id>/triage/`). One item per
marker that drew alerts: each customer request, and each attack case however
many requests it sent (one case is one decision). The item id is a hash of the
marker with the session's browse marker, so it cannot be matched to
`/cases/`. An item shows the first and last alert, the alert count, source
addresses, one request, the WAF verdict (`blocked` when a 949/959 total fired,
`logged`, `none`), the status and up to 12 rules with engine, id, message and
count; never the case name or a label. Replays and the learner's own Website
pane requests are left out. A verdict `{item, verdict: attack|customer,
succeeded}` is judged against the record (a case's `malicious`, or a customer
row) and `succeeded` against the target (loot matched on the case, or an
objective in its window). A scenario whose completion has `pattern: judged`
also asks an attack's `pattern`, one of the CAPEC ids of the case file's
malicious cases (listed in the scenario card's `patterns`), judged against the
case's own `pattern`; it is kept with the verdict and never shown on an item. The step check kind `triage` (`judged: customer |
attack | all`) passes on the learner's right verdicts.

**Status, hints, debrief.** `GET .../scenario/` returns the scenario card,
`phase` (running, window, passed, failed, closed), `time_left`, the last
minute's blocked customers and alerted requests (`alerted_per_minute`, distinct
markers that drew an alert: each customer request, and each attack case once
however many requests it sent), objectives lost, the window, the
completion, the cards due and the hint offer. A hint is offered (not
recorded) when a step check fails twice, the same item is judged wrong twice,
a `PUT /waf/` writes the file already in force, or five minutes pass without a
WAF change while customers are blocked; `POST .../scenario/hints/` opens the
next hint and records it in `Session.hints`. `GET .../scenario/debrief/`
(409 until a window is judged or the session closes, so the schedule stays
hidden) returns, in the Igloo/ASEC report order, `overview` (the last final
check's verdict, its fix class and reasons, the number of checks judged,
steps passed of the total, and the hints used), `evidence` (at most 20 of the
session's own detections from the scheduled attacks, from the completion's
detector when it names one, with rule, request and case; no Elasticsearch
read), `change` (the declared posture against the last WAF snapshot:
exclusions added and removed, both levels, and a line diff of the exclusion
file against what `crs.rendered` writes for the posture), `cases` (each
scheduled case before and inside the judged windows, held or leaked), `risk`
(a string key named by the fix class), `customers`, the attack `timeline` and
`triage`; `at` carries the open and last-judged times for agents. The console
renders it with `debrief_script.html` on the blue console and the closed
session's page.

**Console.** The home page lists the scenarios under each wargame; Start
opens the blue console on the briefing. A strip above the panes shows the
time left, customers blocked and alerted requests per minute, objectives lost,
the hint offer and Start final check; a judgement scenario adds the Alerts pane, which
keeps its list clear: the cards and the opened hints sit in the lesson note's
column beside the pane, and the highlight's callout stays inside the pane; a
detection or unknown scenario adds the IDS rules pane (the rule editor on
`/api/rules/`); cards appear when their moment comes; the debrief opens when the window is judged. A worked
scenario's steps run on the note with its hint list empty: its hints are the
scenario's offer.

**On the board.** Eleven scenarios, listed on the home page by task class
after the foundations (`order`):

| Id | Title | Class, guidance | Posture | Customers | Attacks (hidden) |
|---|---|---|---|---|---|
| 1.1 | Telling customer requests from attacks | judgement, worked | `level2`: PL2 | `community` 2/s | sqlmap at 150 s (`ru`) |
| 1.2 | Judging alerts the WAF only logs | judgement, faded | `inherited`: PL2, 949110 and 959100 removed | `community` 2/s | sqlmap at 120 s, a search injection at 300 s (`ru`) |
| 1.3 | Telling attack types apart | judgement, none; judges the pattern too | `inherited` | `community` 4/s | eight cases from 90 to 660 s, all from `kr`: sqlmap stock and tamper, search, union and sign-in injections, two XSS, path traversal |
| 2.1 | Fixing false positives on Korean search | availability, faded | `level3`: PL3 | `readers` 2/s | sqlmap at 240 s (`ru`) |
| 2.2 | Fixing false positives on tags and links | availability, faded | `level2` | `community` 2/s | sqlmap at 240 s (`ru`) |
| 2.3 | Lowering the anomaly threshold | availability, none; final check at thresholds 5/4 | `untuned`: PL3, thresholds 10,000/10,000 | `plain` 2/s | sqlmap at 600 s (`ru`) |
| 3.1 | Fixing a detection rule | detection, worked | `broken-rule`: PL1, `broken-sort.rules` (sid 9000101 reads `http.request_body`) | `plain` 2/s | sqlmap at 120 s (`ru`) |
| 3.2 | Writing a rule for the sort attack | detection, faded | `ids`: PL1, `no-uri-sqli.rules` | `plain` 2/s | sqlmap at 120 s (`ru`) |
| 3.3 | Detecting a variant of an attack | detection, faded | `spelled`: PL1, `spaced-sort.rules` (SQL words between spaces) | `plain` 2/s | sqlmap at 120 s, the tamper variant at 300 s (`ru`) |
| 3.4 | Writing a rule for XSS in comments | detection, none | `full`: PL1, `local.rules` | `plain` 2/s | the comment XSS at 120 s, the search XSS at 240 s (`ru`) |
| 4.1 | Combined exercise | unknown, none (no cards, no hints) | `full` | `club` 2/s (adds code questions in comments) | `board-sqli-orderby-sqlmap-versioned` at 300 s, sqlmap at 600 s (`us`) |

At PL3 a Korean search is refused by 920272 and 942460 on `ARGS:q` (and 920272
on `REQUEST_URI_RAW` once those are excluded), and every page a customer opens
after one by 920272 on `REQUEST_HEADERS:Referer`; a Korean comment by 920272 on
`REQUEST_BODY` and 942460 on `ARGS:body`. At PL2 the `<b>` search is refused by
941320 and the YouTube link by 931130, both on `ARGS:q`. At PL1 the club's code
questions are refused by 942100, 942190, 941100, 941110 and 941160 on
`ARGS:body`. Scenario 4.2 (a person on the red console against the learner) is
not declared: it needs a second person; the engine accepts `red: person`.

## Decisions

- One case file per wargame, attacks and benign traffic together:
  `redteam/cases/board.yaml` for the board, `redteam/cases/corp.yaml` for corp.
  Separate files make it easy to forget the benign cases. The CLI reads
  `board.yaml` unless `--cases` names another file, and opens the session of the
  scenario whose `case_file` matches that file's basename (board for an unknown
  one).
- The harness refuses to send a rewritten path. `requests` turns
  `/static/../../etc/passwd` into `/etc/passwd`; sending that would record an
  attack that never left and score the harness's failure as the defence's.
  Percent-encoding differences are allowed.
- A tool that cannot start raises; a tool that exits non-zero counts.
  sqlmap exits non-zero when it finds nothing, but its traffic went out.
- Suricata shares the WAF's network namespace (`network_mode: service:waf`)
  instead of using host networking, whose meaning varies with the Docker host.
  The WAF's interfaces carry both legs of every request.
- Kibana is in compose, with full access (not a read-only role), reading the
  same Elasticsearch the platform ingests from. It is reached through the
  platform's port 8000 at `/kibana/`, where the front refuses
  everything but Discover (below), and on the platform host's loopback at
  127.0.0.1:5601 for an operator's ssh tunnel. The blue console frames it. At bring-up `platform/kibana.py` (in the background,
  asking `/api/status` first and importing only once it answers, retrying
  while Kibana cannot be reached or answers 502/503/504, and reporting any
  other HTTP error once with its status and body; a starting Kibana answers a
  multipart import 415) imports `deploy/kibana/objects.ndjson` with
  overwrite: the data view `logs-*` on `@timestamp`, whose runtime fields
  fold each Suricata/ModSecurity pair into one column (`rule`, `rule_id`,
  `source_ip`, `destination`, `url`, `status`), the "Alerts" search and the
  "Overview" dashboard (their titles and the data view's `sourceFilters` name no platform). It sets `defaultRoute` to that search. A data view
  existing is what keeps Kibana's Welcome screen away. It also drops `_index`
  from Kibana's `metaFields`. When a session opens, `kibana.py` imports a data
  view of its own in a Kibana space of its own (`ensure_session_view`, needs
  `KIBANA_URL`, which `compose.yaml` sets): the space and the data view share
  the id `soc-<pattern>`; the space disables every feature but Discover
  (dashboards, visualize, dev tools and the rest). Its settings turn ES|QL off
  (`enableESQL`, which reads every index past the view's pattern and hidden
  fields), set `defaultColumns` to the session columns, and set `defaultRoute`
  to the space's own saved search "Events" (the session columns, newest first) so the
  learner never reaches the operator objects, which stay in the default space.
  Kibana runs without security, so what the features cannot switch off is
  refused by the front: `platform/nginx.conf` answers 403 to the Kibana APIs of
  Elasticsearch and Kibana administration (the console proxy, ingest pipelines,
  index management, snapshot and restore, transforms, rollups, remote clusters,
  license, upgrade assistant, index lifecycle, watcher, the data views API,
  the spaces API except `_active_space`, the security API, the settings API,
  saved objects import and export) and refuses the Default space (`s/default/...`) and every path without a space prefix under
  `app`, `spaces`, `api` and `internal`, and redirects the pages `app/management`,
  `app/dev_tools`, `app/home`, `app/observability`, `app/security` and `app/kibana_overview`
  to Discover of the same space; every call Discover
  makes goes through, and the platform's own setup (`KIBANA_URL`) reaches Kibana
  directly. The space is named "SOC"; the data view is on the session's
  index pattern, shown by its name `logs-*`, never the pattern; the shared
  runtime fields plus `log_source` (`suricata` or `modsecurity`),
  `sensor` (the map name of the sensor, matched on the sender's host name
  without its domain and slot number, with or without its first dash-separated part, so the script names no `fsl` host and the edge's `edge`
  still reads as its map name:
  `firewall` and `board.com` on
  OpenStack, `waf` on docker and for every ModSecurity record, slot suffixes
  stripped) and `request_headers` (one `Name: value` per request header,
  `X-Request-ID` left out); `sourceFilters` hide `_index`, `event.*`,
  `log.*`, `message`, `agent.*`, `ecs.*`, `host`, `host.*`,
  `input.*`, `error.*` and `http.request_headers*` (KQL on them still
  works). A refused import is logged and does not stop the session. `GET
  /api/sessions/<id>/` carries `discover`: an unsaved Discover state on that
  view at `/kibana/s/<space>/app/discover`, from the current unit's start, with the columns `log_source,
  sensor, event_type, source_ip, destination, url, status, rule_id,
  rule` and no filter (Filebeat keeps the range hosts' own
  syslog lines out of the index); a lesson opens it with an empty query, a scenario or a
  wargame with the alert query. While the space or view is not ready (or
  without `KIBANA_URL`) `discover` is null, never the shared operator view;
  the ELK pane shows a preparing line and polls the session until the link
  arrives (the import is retried every 10 seconds). The ELK pane opens it. It is not the saved search with an overriding query, which Kibana
  badges "Unsaved changes". Before the pane loads, the blue console marks
  Kibana's first-visit callouts seen in the shared same-origin localStorage
  (`discover:docExplorerUpdateCalloutClosed`,
  `discover:docExplorerCalloutClosed`, `data.noDataPopover`).
- Elasticsearch is a single node with a 512 MB heap so the whole stack fits
  in a default Docker memory allowance.
- Missing data is an error, not a zero, with stated exceptions. An
  unreachable Elasticsearch or substrate and an unreadable rule file answer
  503. Session create on OpenStack tolerates an unreachable target (the session
  starts with no snapshot, and the board's `loot/` answers 409; on docker a
  board session is refused with 503); firing or recording a case and close
  read no target (firing still answers 503 when it needs the substrate for an
  origin or a tool). The suppression restore inside ingest and placing alerts
  on segments and hosts (which comes back empty) tolerate an unreachable
  substrate, so a round can still start and stop. A ratio with a zero
  denominator is 0.0, not null: precision, recall, F1 and FPR, and the game's
  speed, coverage and accuracy. Only the `objectives` block's `coverage` is
  null.
- A score lists what it cannot vouch for. It carries a warning when there
  are no benign cases (`no_benign`), marker cases and no marker on any alert
  (`no_marker`), a window case with no source address (`no_source_ip`), a
  detected case that is not corroborated (`wrong_reason`), or more hits in
  Elasticsearch than ingest read (`truncated`).
- Console-fired cases send one case per HTTP connection, while the CLI
  keeps one connection for a whole run. Measured on the case set of the time
  (twelve cases), both gave identical scores and per-case alert counts. The
  acceptance tests drive the CLI, so the shared-connection path stays tested.

## OpenStack

The build follows the OpenStack item of the backlog in `docs/STATE.md`, in its
order. What is built is described below, run on the cloud or against fakes;
what is left is listed at the end. The reasoning is in `docs/STATE.md`
("Decided on 2026-09-30"),
`docs/superpowers/specs/2026-09-30-openstack-range-placement.md` and
`docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`; this section
records only the structure.

The cloud is one KVM compute node (8 vCPU, 64 GB) running kolla-ansible
2026.1 with ML2/Open vSwitch. The range lives in project `fsl-range`, driven
by the member-role user `fsl-range`. Horizon is never shown to users.

Everything that differs between clouds is in `deploy/openstack/cloud.yaml`
(copied from the committed `cloud.example.yaml`, ignored by git, no secrets):
identity, networks and MTU, base image, zone, flavors, keys, the OPNsense
release and the platform's stack and ref. `platform/range/cloud.py` validates
it and reports every problem by key; `bin/platform-rebuild` and `bin/cloud`
drive the openstack CLI and the Heat parameters from it, and the stack writes
it into the platform's `openstack.env`. `bin/cloud up` creates the stack and
then calls fabric, images, slot and configure until `/api/range/ready/` is
ready; `bin/cloud down` keeps the key, backs the store up (`bin/backup`,
keeping `backups.keep` copies) and removes slot,
fabric, any image builder and the stack. A `*_FAILED` stack is deleted (builders
first) and created again by `up`, and deleted by `down`.

### Built: the platform VM

`deploy/openstack/platform.yaml` is a Heat template. It creates:

- network and subnet `fsl-platform`;
- a router to the external network, and a floating IP (or, with
  `network.address` set, an association to one the project already holds,
  which a stack delete leaves in place);
- a security group opening tcp/22, tcp/8000, tcp/8002, tcp/3080 and ICMP to
  any address;
- the Nova server `fsl-platform`, with a config drive.

It has no defaults; every parameter comes from `deploy/openstack/cloud.yaml`
(below, and `docs/OPENSTACK.md` §4).

cloud-init installs `docker.io`, `docker-compose-v2` and `git`, adds 4 GB of
swap, sets Docker's MTU to the Neutron network's for the default bridge
(`mtu`) and for every new bridge network, compose's included
(`default-network-opts`), clones `repository` at `ref` into `/opt/fsl`, writes
`FSL_IMAGE_TAG=<the checkout's commit>` to `/opt/fsl/.env`, fetches the GeoIP
database (`bin/fetch-geoip`, which needs no credential: Elastic's GeoIP
endpoint serves GeoLite2 to anyone accepting its terms in the URL) and adds
`ubuntu` to the `docker` group. A systemd unit, `fsl-platform.service`, pulls
`compose.yaml`'s and `session.yaml`'s images and runs `docker compose -f
/opt/fsl/compose.yaml up -d` on every boot; it builds nothing. A failed pull
does not stop the unit (`ExecStartPre=-`); `up` then builds what is missing
from the checkout, which `bin/platform-rebuild` avoids by checking ghcr.io first.

So the compose control plane, and only it, runs inside one Nova VM; on the
OpenStack substrate no session stack starts there, and the board's ground truth
is read from the wargame host at its management address. cloud-init sets
`FSL_PUBLISH` to the VM's fixed address, so 8000, 8002 and 3080 are
published there and opened in the security group, and a browser reaches the
console at the floating IP. `FSL_SYSLOG_PUBLISH=0.0.0.0` publishes 5140/udp on every address
for the edge's syslog; 9200 stays on loopback.

Every parameter of the template comes from `deploy/openstack/cloud.yaml`
(`bin/platform-rebuild`, `bin/cloud`); the template has no defaults. cloud-init
writes those values as `FSL_OPENSTACK_*` and `FSL_OPNSENSE`, plus `_PROJECT`
(the stack's own project), `_SSH_USER=ubuntu` and
`_SSH_KEY=/data/ssh/id_ed25519`, to `/root/openstack.env` with mode 0600, then moves it to
`/opt/fsl/openstack.env`, which git ignores. The password is not in the
template: Nova keeps the user data and its metadata service serves it to
whatever runs on the VM, the range's containers included. `bin/platform-rebuild` appends
`FSL_OPENSTACK_PASSWORD` over ssh once the VM is up, and writes the range ssh
key into the platform's data volume the same way (`README.md`).
The platform service reads the file with `env_file` (`required: false`,
`format: raw`), so compose passes it through without interpolating or
unquoting.

The platform on the VM uses the OpenStack adapter
(`FSL_SUBSTRATE=range.openstack.connect`, written by cloud-init) and builds the
range's networks itself through `/api/range/fabric/`, planned by
`range/fabric.py`: one `internet` network with a subnet per declared origin
(DHCP off), `estate` and `mgmt` (no gateway) on the CIDRs `cloud.yaml` gives,
which its loader refuses if they overlap each other, the platform's network,
Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and
192.168.0.0/16; moby `daemon/libnetwork/ipamutils/utils.go`), a network
`compose.yaml` declares or a declared origin, and the keypair
`fsl-platform` from the key at `/data/ssh/id_ed25519`. The platform makes that
key only when it is absent at the first fabric POST; `bin/platform-rebuild` keeps a copy
on the operator's machine and writes it into every new platform VM, so a
replaced VM keeps the key the keypair and the range's VMs trust.
`describe()` binds each origin to its subnet of the one Internet network by
CIDR. The VM's router attaches only its own subnet; the platform reaches range
hosts through its `mgmt` port (below).

The hosts boot from golden images, built through `/api/range/images/` and
planned by `range/images.py`. The cloud holds one uploaded image, the stock
Ubuntu 24.04 cloud image (`compute.base_image`); every builder boots it.
`declaration.yaml`'s `hosts:` gives each VM a setup script and the files it
needs; the platform packs them into its builder's user data, boots the builder
on its own network (the one with a router), reads the builder's console for
the line the setup prints when it ends, then stops and snapshots it. The image
carries the bundle's digest, so an edited script shows up as an image of
another bundle rather than a silently stale one. A host that `uploads` (the
edge) is different: its builder gets no credential; it makes the disk, serves
it over HTTP on the platform network and prints the disk's SHA256 on its
console. The platform pulls the disk, checks the SHA256, creates the Glance
record and uploads it with its own token; the builder is deleted once Glance
says active, never snapshotted. The edge's builder downloads the OPNsense nano image, checks its
SHA256 and the release key's against `cloud.yaml`, verifies the signature,
boots it once under QEMU answering its configuration importer so it starts
from `deploy/opnsense/config.xml`, converts it with `qemu-img` and serves it
for the platform to upload as `fsl-opnsense-<version>` (`deploy/opnsense/build.sh`, `importer.py`).

The wargames have no image each. One host image, `fsl-wargame-host`
(`deploy/wargame-host/setup.sh`), is the base image plus `docker.io` and
`docker-compose-v2`, and runs every wargame its declaration entry lists
(`wargames: [board, corp]`) as the GHCR containers the docker substrate runs.
`range/wargame_host.py` renders each `wargames/<id>/compose.yaml` for the host
into the bundle: `build:` and the session network dropped, each container
named by its service, the platform's `FSL_IMAGE_TAG` written into the image
references, and the ports the WAF proxies to (`publish: {board: 8000, corp-wp:
80}`) published; `daemon.json` gives Docker's bridges the tenant MTU. The
builder, which has the Internet, pulls the images into the image; the range has
none. The tag is in the bundle's digest, so a platform on a new tag plans a new
host image. The image count stays fixed as wargames are added: the base, the
edge, the WAF, Kali and the wargame host.

A wargame image sideloaded onto the platform (`FSL_SIDELOADED`, the names
`bin/platform-rebuild --sideload` gave, `docs/OPENSTACK.md` §5.3) reaches the
wargame host without GHCR: `wargame_host.sideloaded_images` finds each
service whose image is exactly `ghcr.io/nekonic/fsl-<name>:<FSL_IMAGE_TAG>`,
the platform reads its image id from its own docker, and the bundle gains a
generated `deploy/wargame-host/loaded` (`<image> <image id> <url>` per line),
so the id is in the bundle digest. `setup.sh` pulls from GHCR as before,
then fetches each `<url>`, `GET /api/range/images/sideloaded/<name>/`
(`platform/api/sideloaded.py`, which streams `docker save` of that image and
answers 404 for a name not sideloaded or not run by a declared wargame, and
on docker), `docker load`s it, refuses unless the loaded image's id equals
the platform's, and prunes the GHCR copy. With nothing sideloaded for a
wargame nothing changes. A slot standing before the new image is ready keeps
its old wargame host until `POST /api/range/slot/rebuild/`, since a close
resets that host in place.

The fabric also makes three security groups: `fsl-range`, which every range
port off `mgmt` joins and which lets any IPv4 in (the WAF defends the range,
not Neutron; anti-spoofing stays on); `fsl-reach`, which lets in only NTP
(udp 123) from members of `fsl-mgmt`; and `fsl-mgmt`, which every range
host's `mgmt` port joins and which lets in only members of `fsl-reach`. The
platform attaches itself to `mgmt` through a port in `fsl-reach`, found by its
own server id (`FSL_OPENSTACK_PLATFORM`, written at boot), so it can ssh to
every host while no host can open a connection to it but NTP, and Kali's
`mgmt` port reaches no other host. The runner reaches a host at its `mgmt`
address unless the caller names a segment.

The range has no Internet and so no time source of its own, and the scorer
compares target and sensor times with case windows on the platform's clock.
The platform VM runs chrony (cloud-init: `allow <network.mgmt>`, `local
stratum 10`), and every range host keeps time by the platform's `mgmt`
address: `range/clock.py` writes a `systemd-timesyncd` drop-in on the Ubuntu
hosts and waits for the first answer (`keep_time()`, in every host's configure
chain and before the wargames start), and the edge's rendered `config.xml`
names it in `system/timeservers` with ntpd bound to `opt1`. On docker every
container reads the host kernel's clock, so nothing is needed there.

The slot is the set of range hosts, managed through `/api/range/slot/` and
planned by `range/slot.py`. Each host has a port per declared segment, named
`<host>.<segment>`, in `fsl-range` or, on `mgmt`, `fsl-mgmt` (a standing
`mgmt` port in another group is moved into it). The host filling `gateway` holds
every origin's gateway address on one Internet port, and since cloud-init
configures only the first, its user data adds the rest at every boot.
Every host's user data appends the `estate` names to `/etc/hosts` (the WAF's
`board.com` and `corp.com`, the wargame host's `board` and `corp-wp`), which is
how the WAF finds each wargame's published port; each database answers only
inside its compose project on the host.

Range slots. `compute.slots` in `cloud.yaml` (default 1, `FSL_OPENSTACK_SLOTS`
on the platform) sets how many copies of the range stand at once, and
`max_sessions` is that count. Slot 1 keeps the names above; slot N>1 names
its servers and ports `<host>-N` (`fsl-edge-2`, `fsl-waf-2.mgmt`) and tags
its servers `fsl_slot=N` beside `fsl_host`. Each slot beyond the first has
its own copy of the internet and estate networks (`fsl-internet-N`,
`fsl-estate-N`, tagged `fsl.slot=N`) with the same subnets, so every edge
holds the same 30 origin gateways, every Kali the same origin addresses, and
an alert's source is binned to the same country in every slot; Neutron allows
the same CIDR on two networks that share no router. `mgmt` is shared: each
slot's hosts take their own DHCP addresses there and `fsl-mgmt` fences them
as before. A slot adapter (`OpenStack.in_slot(n)`) reads only its own slot's
servers, by their declared host name, so roles, runners, topology and the
edge's rendered settings are the same in every slot; slot N's edge renders
its hostname as `firewall-N`. Opening the collector for one slot keeps the
other slots' sender rules. The platform binds a session to a slot at open
(`Session.slot`, one open session per slot by a unique constraint): the
first free slot that is READY, chosen under a lock. Every per-session range
call goes to that slot, the close resets only it and marks only its
suppressions restored, its reset state is its own (`api/reset.py`), and rule
changes take that slot's turn, so one slot's reset does not hold the other
slot's session. `run_on_role` takes `--session` or `--slot` and refuses
neither when there is more than one slot; the console's VM terminals take the
session as `?arg=<id>` (ttyd `-a`) and open its slot's host.

The OPNsense edge `fsl-edge` (vtnet0 internet as WAN, vtnet1 estate as LAN,
vtnet2 mgmt as opt1) boots in the slot. `POST /api/range/configure/` renders
`deploy/opnsense/config.xml` for the slot (`range/opnsense.py`; the file
carries the defaults of the `dnsmasq`, `Syslog` and `unboundplus` models, which
the early-boot template render needs before OPNsense's migrations run), stages it
with the Suricata include `deploy/opnsense/suricata.yaml` and the starting
rules over the management ssh as root, installs them and reboots the edge;
it then waits for a new boot time and checks that the edge holds the 30
origin gateway addresses (one static, the rest as IP aliases), runs Suricata
on the WAN in IDS mode with the estate and mgmt as `HOME_NET` and EVE alerts
and HTTP records going to syslog, sends syslog to the collector, and has a WAN
pass rule in pf, which admits tcp 80 to the WAF's estate address and nothing
else. The rules editor writes the file the include names and
reloads with `suricatasc` on the socket it opens. The edge's syslog and the
WAF's ModSecurity audit log reach the platform's Elasticsearch, with GeoIP
enrichment. One Kali image serves every origin: its
single Internet port holds the ~100 per-country addresses (the slot's
`bootcmd` adds them to the NIC) and `/usr/local/sbin/set-origin` SNATs the
box's outgoing source per country, so every tool leaves as the chosen country.
The marker-adding proxy and the ttyd terminal run on the Kali box.

`rebuild_slot()` (`POST /api/range/slot/rebuild/`) rebuilds
every standing slot VM from its golden image, keeping each server's id,
flavour, ports and fixed IPs. `POST /api/sessions/<id>/close/` calls
`reset_slot()` instead, which rebuilds only the VMs that hand out a shell
(Kali, the WAF) and leaves the edge and the wargame host to be reset in place
(`docs/OPENSTACK.md` §6.1), so a session leaves the next one no edited rule
or planted data. A rebuild wipes the disk, so configure must follow once the
VMs are ACTIVE. On the wargame host the in-place reset (`clear_wargames()`)
runs `docker compose down -v` for each wargame and the estate sensor, removes
the sensor's eve log and rsyslog's imfile state, leaving the images and no container or volume; configure's last step, `start_wargames()`, runs `sudo docker compose
-p <id> -f /opt/fsl/wargames/<id>.yaml up -d --wait --pull never` for each
wargame through the `wargames` role, so every session starts on freshly
seeded targets. Then it starts the estate sensor: docker's Suricata image and
`deploy/suricata/suricata.yaml`, which each start writes to the host from the
platform's copy, from `deploy/wargame-host/sensor.yaml` with
host networking, on the interface holding the host's estate address, so it
sees the WAF-to-target leg docker's one sensor sees from the WAF's namespace;
once it answers, `start_sensor()` seeds the baseline rules through
`rules/suricata.py` with the rule file and reload the host entry names.
Its role, `estate-sensor`, maps to the compose service `suricata`, so the
runner execs into it; the host entry names its rule file and reload command
(`settings.FSL_EXTRA_SENSORS`), and every rule seed, validation, change and
baseline check goes to both sensors. The host's `logs:` entry has rsyslog
forward `eve.json` to the collector tagged `suricata` (`range/waf.py`'s
forwarding, by tag), and `fsl-reach` hears the host as it hears the edge and
the WAF.
After a close the platform does that itself: `platform/api/reset.py` starts a
background thread that, under one hold of the rules lock, runs two sides at
once. One is `reset_in_place()`: the edge's in-place reset (`reset_edge()`:
baseline `fsl.rules` back, the installed files checked by sha256 against the
hash the edge recorded after its last install and boot, range pf states
dropped, filter reloaded, Suricata restarted; on any mismatch it falls back
to `configure_edge()`'s install and reboot), the collector's security group,
and the wargame host (cleared, then its time source, wargames, sensor and log
forwarding, in that order). The other polls `plan_slot()` until each rebuilt VM has been seen
out of ACTIVE and back to ACTIVE, then runs `configure_rebuilt()` (each
rebuilt host's time source, and the WAF's log forwarding) from a fresh read
of the cloud. Both retry while a VM does not
answer ssh (up to 30 minutes) and the first failure fails the reset.
`configure_slot()` (the manual configure) runs every host's steps side by
side, one thread per host: the edge (configure and reboot), the WAF, Kali,
the wargame host, and the collector's security group; every Ubuntu host's
chain starts with its time source; it waits for all of them
and fails with the first failure in that order. The close answers at once; the reset
state (idle, running, failed and why) is held in the platform process.
`POST /api/range/configure/` stays the manual retry and clears a failed reset.

On OpenStack, session create answers 409 while every slot is held or no free
slot is ready. `GET /api/range/ready/` reports every slot under `slots` (its
number, the session holding it, its phase: `IN_USE` while a session holds it,
`RESETTING` while its reset runs, `RESET_FAILED` with its reason if it
failed, otherwise `NOT_STANDING`, `REBUILDING`, `CHECKING`, `READY`), its
reset state, and three checks: every VM
ACTIVE, the board's ground truth readable, and the sensor rules at baseline
with no suppression of that slot in force. The top-level `ready` and `slot`
are the slot the next open would take. `/api/range/slot/`, `slot/rebuild/`
and `configure/` take `?slot=N`; without it they act on every slot. `POST /api/range/canary/` fires a marked case
and reports whether Suricata and ModSecurity both alerted and how far their
clocks differ; it is not part of the ready check. The landing page calls both.

### The range on OpenStack: the target structure

Decided by the user on 2026-09-30, with the 2026-10-08 changes marked. Most
of it is built (see above).

```
 OpenStack project fsl-range.

 platform VM: Ubuntu 24.04, floating IP, docker compose up
   console and /api/, scoring, Elasticsearch, Filebeat, Kibana
   landing page /: start and stop a session, the scoreboard after close
   sidebar, panes inside the page:
     pfSense   web GUI pane (built; dropped from scope and removed 2026-10-08)
               (the edge is OPNsense since 2026-10-11)
     Kibana    framed directly, reading the same Elasticsearch (full)
     terminal  ttyd in the platform, ssh to the Kali VM on mgmt
     |
     +--OpenStack API, as member fsl-range--> networks, VMs, consoles
     +--management network, ssh-------------> Kali VM, WAF VM, wargame host

 Internet network: one subnet per origin country (30), no Neutron router
   Kali VM: one port holds every attack address; the source is rewritten
            to the chosen country's address as packets leave
     |
     v
 OPNsense VM: edge router; its WAN holds each subnet's gateway address
              and routes on without NAT, so country sources survive
   Suricata (OPNsense IDS): detects; no firewall lesson, per 2026-10-08
     |
     v
 WAF VM: nginx + ModSecurity v3 + CRS
         (planned: SecRuleEngine On, blue tunes CRS to block)
     |
     v
 estate network
   wargame host VM (Docker): board + board-db, corp-wp + corp-db,
                             the GHCR images docker runs (2026-10-11)
     Suricata on the estate NIC: the WAF-to-target leg (2026-10-12)

 Evidence:
   OPNsense: Suricata EVE, syslog-ng, UDP-------> Filebeat --+
   WAF VM: ModSecurity audit log --------------------------------+
   wargame host: Suricata EVE, rsyslog imfile, UDP --------------+
                                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch ----------------> Kibana --> blue team
```

Left to build:

- Session lifecycle: check WAF mode and clock skew as part of readiness
  (re-running `configure` after the close-time rebuild is automatic since
  2026-10-11).
- Blocking (planned, 2026-10-08 spec): the WAF runs `SecRuleEngine On` and the
  blue team tunes CRS (paranoia level, rule exclusions) so the attack is
  blocked and benign traffic passes; Suricata detects. The starting paranoia level was
  measured on 2026-10-10 (`docs/DECISIONS.md`): PL1 already blocks the board
  SQLi and passes O'Brien, so a posture meant to over-block starts above it
  (the scenarios' `level2` and `level3`), and the learner tunes it (a lower PL,
  a threshold or a rule exclusion). Whether a case was
  blocked is read from the target side into `meta["blocked"]`. The earlier
  plan, switching Suricata drop rules in the pfSense GUI, is superseded.

Decisions still open for a person are in `docs/STATE.md` ("Decisions left for
a person").

Built: the WAF VM forwards its ModSecurity audit log with rsyslog imfile over
UDP to 5140 (`platform/range/waf.py`), and Suricata on the OPNsense edge runs
in IDS (pcap) mode (`deploy/opnsense/`), not built against a cloud yet. What has to be tested on this
cloud before building is in the placement spec, "To test on this cloud before
building".
