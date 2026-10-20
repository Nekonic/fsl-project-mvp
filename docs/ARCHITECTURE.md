# Architecture

This document explains how the range is built, how traffic and evidence move through it, and why it was designed this way. `CLAUDE.md` defines the score. `docs/STATE.md` lists open problems and measured quirks.

OpenStack is the only supported way to run the range (2026-10-20). The sections up to "Decisions" still describe the docker adapter first, because its code stays until `docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md` runs. Read every "On docker" passage as that code, not as a way to run the product. The last section, "OpenStack", describes the OpenStack range. It separates what is built from what is planned (`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`).

The repo started from one hypothesis. Red team attacks can be labelled with ground truth, and Suricata and ModSecurity alerts can be matched to those labels automatically. Then false positives and false negatives can be scored mechanically. The objective score was added after that held.

Words used throughout:

- **Range**: the whole training environment, meaning its networks, hosts and target apps.
- **Session**: one run of the range, shared by the red team that attacks and the blue team that defends.
- **Wargame**: one target app with its objectives and its cases. The two wargames are `board` and `corp`.
- **Case**: one attack or one benign request set that the harness sends. A case counts as one decision however many alerts it draws.
- **Marker**: the `X-Request-ID` value on a case's requests. It lets the platform match an alert to its case.
- **Ground truth**: the target's own stored data. It shows what the attacker really took. For the board it is the secret that submitted loot is matched against; for corp it is the changes in its database log.
- **Substrate**: what the platform builds the range on, chosen by `FSL_SUBSTRATE`. Only OpenStack is supported; the docker adapter is code awaiting removal.
- **`estate`**: the internal network that holds the target apps.
- **Slot**: on OpenStack, one complete set of range VMs. One session uses one slot.
- **Posture**: a named starting state of the defence (WAF tuning plus an IDS rule file). The wargame declares it in its `defense:` map, and a session starts from one.
- **Coach**: the lesson highlight. It draws a ring around the screen element a step is about and puts a one-line note beside it.
- **Isolation seam**: the rule that one file owns one concern. The "Isolation seams" section lists them.
- **Store**: the platform's SQLite database, `/data/db.sqlite3`.
- **Unit**: one foundation lesson or worked scenario, as the step engine runs it.
- **Box**: the VM or container that fills a role, such as the attacker box (Kali).

## The range

Two compose files define the services and networks listed below, and `bin/measure` counts them.

- `compose.yaml` is the control plane. It is one long-lived copy, project `fsl`. It runs the platform, Elasticsearch, Kibana, the `collector`, the GNS3 server, the four edge networks and `mgmt`.
- `session.yaml` is the data plane of one session. It runs the WAF, Suricata, Filebeat, Kali, the proxy and the wargames. It joins the edge networks and `mgmt` as `external` networks (`fsl_<network>`). It owns its own `estate` network and its volumes. The `estate` network has no fixed subnet, so Docker draws one from its private pools.

Opening a session (`POST /api/sessions/`, `open_session` in `platform/range/docker.py`) goes in these steps:

1. The platform runs `docker compose -p fsl-<session id> -f session.yaml up -d --wait --no-build` from inside its own container.
2. It sets `FSL_HOST_DIR` to the host directory compose started the platform from (the `com.docker.compose.project.working_dir` label). This makes the stack's bind mounts resolve on the host.
3. It sets `FSL_SESSION` to the session id.
4. It joins the session's `estate` network (`docker network connect`, alias `platform`). The platform's own `edge` network keeps the default gateway through `gw_priority: 1`.
5. It points the session's proxy at the session's own WAF (`/var/lib/session/origin`).
6. It reads the baseline, the snapshot of the target's data that scoring compares against later.

Sessions run at the same time.

- Opening a session runs `down -v` only on `fsl-<n>` projects whose session ended more than three minutes ago. Each such project leaves its `estate` network first.
- The platform decides which projects to take down under one lock. Two simultaneous opens therefore cannot take down each other's new stack.
- Docker opens at most `FSL_MAX_SESSIONS` sessions (default 2, `platform/fsl/settings.py`) and answers 409 past that. OpenStack opens one session per slot.
- Closing a session leaves its stack running until an open at least three minutes later. In that time the session's Filebeat ships the last alerts.

The store keeps a closed session for `FSL_RETAIN_CLOSED_MINUTES` (default 60, set in `compose.yaml`).

- `platform/api/retention.py` deletes older closed sessions, with everything that belongs to them. It runs at start (`fsl/wsgi.py`) and after each close.
- It deletes a session's detections and customer requests 2,000 rows per transaction, then the session. A large prune therefore never holds the store's write lock for long.
- The store is SQLite with `transaction_mode: IMMEDIATE` (`fsl/settings.py`). A read-then-write transaction takes the write lock at its start. It waits out the 30 s busy timeout instead of failing at once with `database is locked`.
- `bin/backup` snapshots the store with `VACUUM INTO` and keeps the newest `--keep` copies (default 1). For `bin/platform-rebuild` and `bin/cloud down`, the value is `backups: {keep}` in `cloud.yaml`.

The OpenStack substrate has no `open_session`.

- Its range is the Nova VMs, so no session stack starts.
- The wargames run on one VM, `fsl-wargame-host`, as the same GHCR containers.
- The readiness probe and the session baseline read the board through the adapter's `address("board")`. This is the wargame host's management address, where the board's port 8000 is published. `loot.ground_truth` puts it in place of the host in `BOARD_API_URL`.

Each target is a wargame, a folder under `wargames/` whose `compose.yaml` is included by `session.yaml`. There are two:

- `board` (Django and MySQL, `loot_verified`).
- `corp` (WordPress and MySQL, `effect_observed`).

The platform finds each wargame from `wargames/<id>/scenario.yaml` (`platform/wargames.py`).

- Required fields: `name`, `description`, `image`, `public_url`, `objective_model`, `case_file`.
- Optional fields for the console's scenario card: `category`, `difficulty` (easy, medium, hard) and `minutes`.
- Optional fields `defense`, `foundations` and `scenarios`. They are described under "Sessions, WAF tuning and the step engine" and "Scenarios".
- Nothing reads `image` yet.

The images are built and pulled as follows.

- CI (`.github/workflows/images.yml`) builds each app image.
- Sessions pull it as `ghcr.io/nekonic/fsl-<name>:${FSL_IMAGE_TAG:-dev}`, or build it locally under that name. They start from it with `--no-build`.
- The platform passes its own `FSL_IMAGE_TAG` to the session stacks it starts.
- Tool cases run `ghcr.io/nekonic/fsl-kali` with the same tag (`redteam/tools.py`).

A new wargame needs `scenario.yaml`, `objectives.yaml` and `compose.yaml` in its folder, a case file under `redteam/cases/`, and an `include:` line in `session.yaml`.

Nothing in `session.yaml` or a wargame pins `container_name`. A session's containers are named `fsl-<id>-<service>-1`. Only the control plane keeps fixed names: `fsl-platform`, `fsl-elasticsearch`, `fsl-kibana`, `fsl-collector` and `fsl-gns3`. The first table below lists each session service under its declared host name, which `platform/range/docker.py` maps the container back to.

Every endpoint that acts on the range takes `session` from the query or the body. These endpoints are rules, validate, suppressions, `/api/attacker/`, origin, label and canary.

- Without `session`, a write goes to the newest open session. It answers 409 when none is open.
- Without `session`, a read uses the newest session.
- A write that names a closed session is refused.
- Suppressions are stored with their session (migration 0014).

Each session's sensor keeps its live `local.rules` in its own container.

- On docker, every session's sensor is seeded at open with its defense's rule file. When the scenario declares no `defense` (corp), it is seeded with `deploy/suricata/rules/local.rules`.
- Nothing bind-mounts `deploy/suricata/rules`, so applying a rule changes only that session's sensor.
- Known gap on docker: the middleware that refuses requests from range hosts covers only the newest session's `estate`.

| Service | File | Image | Networks | Host port |
|---|---|---|---|---|
| `fsl-wg-board` | session | `ghcr.io/nekonic/fsl-board` from `wargames/board/app` (Django under gunicorn, port 8000) | estate | |
| `fsl-wg-board-db` | session | `mysql` | estate | |
| `fsl-wg-corp-wp` | session | `ghcr.io/nekonic/fsl-corp` from `wargames/corp/app` (WordPress 6.6.2, three pinned vulnerable plugins; `corp.com` by `Host` header) | estate | |
| `fsl-wg-corp-db` | session | `ghcr.io/nekonic/fsl-corp-db` from `wargames/corp/db` (MySQL 8.4, binlog `ROW`) | estate | |
| `fsl-waf` | session | `owasp/modsecurity-crs` (nginx), alias `board.com` on edge. The alias is shared, so the platform points each session's proxy and tools at its own WAF | edge, edge-br, edge-hk, edge-us, estate | |
| `fsl-suricata` | session | `jasonish/suricata` | the WAF's namespace | |
| `fsl-filebeat` | session | `filebeat:8.15.0`, ships the session's `eve.json` and audit log | mgmt | |
| `fsl-kali` | session | `ghcr.io/nekonic/fsl-kali` from `deploy/kali`; `http_proxy` is `http://proxy-<id>:8081`, an alias that only that session's proxy carries on the shared `edge` | edge | |
| `fsl-proxy` | session | `ghcr.io/nekonic/fsl-proxy` from `deploy/proxy` (mitmdump); `/var/lib/session` is the project's named volume `label` | the four edge networks | |
| `fsl-elasticsearch` | control | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-collector` | control | `filebeat:8.15.0`, the syslog input only (the OpenStack range) | mgmt | 5140/udp |
| `fsl-kibana` | control | `kibana:8.15.0`, served at `/kibana/` | mgmt | 5601 |
| `fsl-platform` | control | `platform/` (Django under waitress, behind nginx). nginx also serves Kibana at `/kibana/`, each session's Kali ttyd at `/terminal/<session id>/`, each session's WAF shell at `/waf-terminal/<session id>/`, and the VM terminals at `/vm-terminal/kali/` and `/vm-terminal/waf/`. The image carries the compose plugin and mounts `session.yaml` at `/src/session.yaml` | the edge networks, mgmt, and each open session's estate | 8000, 8002 |
| `fsl-gns3` | control | `ghcr.io/nekonic/fsl-gns3` from `deploy/gns3` (gns3-server 3.1.0a6, qemu, uBridge 1.2.3, busybox-static, docker-cli). It holds open the learner maps the platform loads and starts their display nodes. It has `CAP_NET_ADMIN`, `/dev/net/tun`, the Docker socket and the host's pid namespace | mgmt | 3080 |

Ports 8000, 8002 and 3080 bind to `FSL_PUBLISH`. Port 5140/udp binds to `FSL_SYSLOG_PUBLISH`. Both variables default to 127.0.0.1. Ports 9200 and 5601 bind to loopback only.

| Network | Segment | Subnet | Name | Origin |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | Internet | Russia |
| `edge-br` | `br` | 177.54.144.0/24 | Internet | Brazil |
| `edge-hk` | `hk` | 103.152.220.0/24 | Internet | Hong Kong |
| `edge-us` | `us` | 73.0.0.0/24 | Internet | United States |
| `estate` | `estate` | per session, drawn by Docker | Application estate | |
| `mgmt` | `mgmt` | 172.31.0.0/24, shared | Management | |

Every session shares the edge networks, and they keep fixed subnets. Docker refuses overlapping subnets, and the subnet carries the origin for GeoIP.

`mgmt` is shared too. Elasticsearch, Kibana and the collector live on it, and every session's Filebeat must reach Elasticsearch (`docs/DECISIONS.md`, 2026-10-10).

Suricata's `HOME_NET` is the four WAF edge subnets plus 10/8, 172.16/12 and 192.168/16. The private ranges are there because Docker draws a floating `estate` from its private pools.

The declaration lists thirty origins on one Internet segment.

- They are the top thirty countries by Cloudflare Radar's share of HTTP requests.
- Each has a /24 that GeoIP places in that country, and a share of about 100 attack addresses.
- Docker builds four of them, one network each, because a bridge holds one IPv4 subnet. The OpenStack fabric builds all thirty as subnets of one network.
- `bin/pick-origins` reproduces the table. An acceptance test checks every subnet against the pipeline that scoring reads.

On docker, segmentation is network membership only. There is no firewall, no iptables and no ACL. On OpenStack it is the fabric's networks and security groups.

- `test/test_attacker_reach.py` asserts the segmentation against the live range on both substrates. Kali reaches neither `board:8000` nor `corp-wp` directly, and no service off its route out. `test/test_board_exfil.py` reaches the board through `board.com`.
- `test/test_concurrent_sessions.py` asserts that two concurrent sessions do not see each other.
- Only the edge subnets are fixed. Docker assigns container addresses, and they change on recreate. The views build a new adapter and read the addresses on every request.
- The rule that refuses requests from range hosts caches their addresses for 30 s. When it cannot reach the substrate, it treats the range as empty and lets the request through (`docs/THREAT-MODEL.md`).

The platform, the WAF and the proxy are each attached to several networks.

- The attacker's traffic enters the internal network (`estate`) only through the WAF.
- The platform is attached to every edge network and to each session's `estate`. The API therefore checks the caller itself (`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --fired: schedule/seed/API--------+
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

`deploy/suricata/suricata.yaml` names the interfaces eth0 to eth4. It relies on Docker attaching the WAF's networks in the priority order set in `session.yaml`. Nothing checks that mapping. Its `default` entry gives any other interface the same capture settings, for example the estate sensor's `ens3` on OpenStack.

The WAF sends `board.com` to `board:8000`. It sends `/internal/` to a path the board does not serve, so the answer is the board's own 404, byte for byte (`deploy/nginx/board.conf`, and `deploy/waf/board.com.conf` on OpenStack). `corp.com` is a second vhost that goes to `corp-wp:80` (`deploy/nginx/corp.conf`).

The board is the first wargame.

- It runs Django 3.2.4 under gunicorn, on MySQL pinned by digest. This Django version is unpatched and has a known `order_by` SQL injection flaw (CVE-2021-35042).
- It migrates and seeds itself on start.
- Neither the board nor its database is published.
- It is scored by exfiltrated credentials. When a session starts, the platform reads the board's `auth_user` usernames and password hashes from `/internal/auth-users` and keeps them as the session's snapshot.
- The platform reaches that path directly on the `estate` network, and the WAF never forwards it. The read therefore passes through neither the WAF nor the IDS, and neither sees it.

The corp wargame is the second. It is WordPress 6.6.2 (`fsl-wg-corp-wp`) with three plugins pinned to unpatched versions:

- Ultimate Member 2.6.6 (CVE-2023-3460): a registration flaw that injects `wp_capabilities` to grant administrator.
- WP GDPR Compliance 1.4.2 (CVE-2018-19207): an unauthenticated option change that opens admin self-registration.
- Easy Post Submission 2.3.0 (CVE-2026-4431): an unauthenticated post overwrite.

None of the three triggers the default OWASP CRS. The database, `fsl-wg-corp-db`, is MySQL 8.4 run with `--binlog-format=ROW`. WordPress itself is not instrumented. corp is scored by the changes an attack commits to its database (see "How the scores are computed").

## The declaration and the substrate seam

The "substrate seam" is the interface between the platform and the adapter that talks to Docker or OpenStack. `platform/range/ports.py` defines it.

OpenStack is the only supported substrate (2026-10-20 ruling, superseding 2026-10-11). The docker adapter stays in the code until `docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md` runs.

The platform does not ask Docker what the range means. It reads that from `platform/range/declaration.yaml`. The file holds:

- per segment, an id, a display name and an attack origin;
- a role table: attacker, scorer (the platform), gateway, proxy, sensor, board, board-db, corp and corp-db, plus the edge, sensor and proxy roles that differ on OpenStack, under `openstack:`;
- the host the sensor watches;
- the default origin;
- the defended site (Seoul).

Only a segment that declares an origin is outside.

The declaration holds no subnet, gateway or address. Docker and Neutron both assign those, so the platform takes them from the substrate. If the declaration named a subnet and the cloud assigned a different one, alerts would be grouped under a subnet where no host is. `compose.yaml` repeats the segment identity in network labels. `platform/tests/test_declaration.py` checks the two files against each other. It never checks the running range.

The platform finds segments by a label.

- On docker, the adapter finds hosts by label too. The `compose:` section of `declaration.yaml` maps each role to a compose service. The adapter picks the container with that `com.docker.compose.service` label in the session's project.
- No Python code names a container by the compose naming convention any more. The site proxy did (`http://fsl-<id>-waf-1`) until 2026-10-18.
- The terminal wiring still does, for the person's shells: `waf-terminal.sh` (`fsl-<id>-waf-1`) and nginx's Kali terminal route (`fsl-<id>-kali-1:7681`). The "Isolation seams" table lists them as exceptions.
- Each segment carries `fsl.segment.id` as a Docker label or a Neutron tag. The adapters fetch only labelled networks. A session-owned network wins over a control-plane one with the same segment id.
- Matching by name broke on compose prefixes and overrides, on Heat stack suffixes and on non-unique Neutron names.
- On OpenStack, a role is still the server name the declaration gives. The adapter lists every server in the project and matches `server["name"]`, which Nova does not keep unique. This is still open in `docs/STATE.md`.

Core code and most of the platform use only four methods of that interface:

- `describe()` returns the shape: segments, their nodes and addresses, and sensors.
- `segments()` returns which host is on which segment, without the sensor check.
- `runner(role, segment)` runs a command on a standing host. The standing hosts are the sensor, the proxy, the attacker (whose command log the platform reads) and corp-db.
- `launcher(segment)` runs a one-shot tool on a segment and returns its output.

`range.substrate()` builds the adapter named by `FSL_SUBSTRATE` (default `range.docker.Docker`). It passes the options that `FSL_SUBSTRATE_OPTIONS` keeps under that name, plus `declared=RANGE`.

- Docker takes `FSL_PROJECT` (default `fsl`).
- OpenStack takes `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PASSWORD`, `_PROJECT`, `_SSH_USER`, `_SSH_KEY`, `_REGION`, `_INTERFACE` and `_DOMAIN`. It refuses by name any that is missing.
- OpenStack also takes the values that shape the range: `_BASE_IMAGE`, `_FLAVOR`, `_BUILD_FLAVOR`, `_ROLE_FLAVORS`, `_AVAILABILITY_ZONE`, `_SUBNETS`, `_MTU` and `FSL_OPNSENSE`. It refuses by name where they are used.
- It takes `FSL_IMAGE_TAG` as well, for the wargame host's images. The tag is written to `/opt/fsl/.env` at boot.
- None has a default in code. All come from `deploy/openstack/cloud.yaml` through the Heat stack. `platform/range/cloud.py` reads and validates that file.
- `redteam/harness.py` is handed a launcher and `platform/rules/suricata.py` is handed a runner. Neither imports `subprocess` or names a substrate.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| shape | `docker network ls/inspect`, label filter | Keystone v3, Neutron with `tags-any`, Nova |
| sensor | refuses to describe the range unless each declared sensor shares the declared gateway's network namespace (`docker ps`, `.HostConfig.NetworkMode`) | reports a sensor whenever both named servers exist. Nothing confirms that it sees the gateway's traffic |
| runner | `docker exec` into the role's service container in the session's project | `ssh` to the instance. A role that the wargame host fills and `compose:` maps to a service runs in that container (`sudo docker exec <service>`, `range/wargame_host.py`) |
| address | the role's `estate` IP in the session's project | the host's `mgmt` address |
| launcher | `docker run --rm --network <segment>`, with `--add-host` for the session WAF's names | `runner("attacker")`: runs the tool over ssh to the declared attacker's mgmt address. The origin only checks that the attacker stands on that segment, and the source country comes from `set-origin` SNAT. Any other image is refused, because Nova cannot boot a host, return its output and delete it |
| tested against | the live stack | unit tests on fakes built from the published API reference and a local sshd. On the `fsl-range` cloud, the platform VM built the fabric, the images and the slot through `/api/range/`. `describe()` read back the WAF on the thirty origins and the four hosts on estate and mgmt. `runner()` ran on each host over ssh to its mgmt address. `launcher()` fired sqlmap from the `ru` and `tw` origins on 2026-10-08 |

Compose mounts the Docker socket into the platform whatever the substrate, and the entrypoint adds the platform user to the socket's group. This is a container escape path. The OpenStack adapter would make it removable, but nothing removes it yet. `docs/STATE.md` lists, under "The substrate seam", what is left before the adapter can drive a range.

## The topology

The range's topology is kept as GNS3 project files. They use `revision` 9, so GNS3 2.2 opens them and 3.x upgrades them on load. There are two kinds, one set per substrate.

- **The system map**, `deploy/topology/system/range-{docker,openstack}.gns3`, shows the full wiring of the declaration. It includes the management segment, `fsl-platform`, the control-plane containers and the stamping proxy. It is English only, for development and GNS3's MCP. The GNS3 service never sees the repo's maps, so learners are never offered it.
- **The learner map**, `deploy/topology/range-{docker,openstack}.gns3` and their Korean pairs, shows the company web-service network the learner defends. It is a logical diagram, drawn the way lab topologies are drawn (Cisco NetAcad lab topology, NSRC workshop logical diagram). The rules below describe what the learner map contains.

What the learner map shows:

- Role hostnames.
- At each link end, the interface and its address with prefix. At `kali` and `customers` it shows the interface alone.
- A caption on each zone with its network. The Internet zone shows its name alone.
- The text "IDS" beside each host that runs Suricata. That is `firewall` and the site on OpenStack, and `waf` on Docker.

It shows nothing else. It has no title, legend or note, no machine's own name, no `fsl-`, no management segment and no Docker bridge name.

- The request path runs left to right: the Internet zone, `firewall`, the Services zone (`waf` and the site), the database zone, then the monitoring zone.
- `topology.for_wargame` keeps a text that lies in no zone, such as the firewall's "IDS" between two zones.

The nodes of the learner map:

- `customers` and `kali` (the attacker's Kali box) are on the `internet` switch.
- `firewall` is OpenStack's OPNsense edge. Its Suricata is folded into this node.
- `sw1` is the service segment. The `waf` and the site (`board.com` or `corp.com`, the WAF host's declared names) are on it.
- On OpenStack, `sw2` is the database segment. It sits behind the site and holds the database (`board-db`).
- On Docker, the database is on `sw1`. The Docker range has no edge and puts the sites and their databases on the estate, so its map does too, and it has no `sw2`.
- `sw3` is monitoring. It links the `log-server` (Elasticsearch) to the hosts whose records reach it.
  - On OpenStack, those hosts are the firewall, the WAF and the site. The estate sensor runs on the sites' host and ships its own eve.json.
  - On Docker, the host is the WAF alone. The session shipper reads the WAF's audit log and the volume of Suricata, which runs in the WAF's namespace.

Switches are numbered the way lab topologies number them (`sw1`, `sw2`, `sw3`, as in NSRC's `sw1`), in a fixed order: service, database, monitoring. The zone captions say which segment each switch is.

A template draws both wargames' site and database in one place (both on `sw2` on OpenStack, on `sw1` on Docker). `topology.for_wargame` keeps the session's own. A wargame that declares no customers (`corp`, which has no `traffic.yaml`) has no `customers` node.

`topology.learner(declaration, wargame)` maps the range's names to the map's names.

- Hosts: `fsl-kali` is `kali`, and also `customers` where the customers run on it. `fsl-edge` is `firewall`. The wargame host and its site container are the site. `fsl-elasticsearch` is `log-server`.
- Roles.
- Segments to switches: origins to `internet`, the estate to `sw1`, a wargame's compose network to `sw2`, and the management segment to `sw3` for the NIC name alone.
- Each sensor to the node whose NIC it uses.

The overlay, the lesson's range questions and the interface read all go through this mapping. (The overlay is the host list with live addresses that `GET /api/sessions/<id>/topology/` returns, described below.)

Drawing rules:

- Every link is one straight line, level, upright or diagonal. No link crosses another link or a node.
- A node that a link reaches from straight above carries its name beside it.
- Every host is one square frame of one size and line weight (`host-*.svg`). `deploy/gns3/symbols.py` builds the frames when the GNS3 image is built, and `provision.py` uploads them.
- Inside the frame is GNS3's bundled affinity glyph. The frame is red for the attacker, green for the defence, blue for the sites, and gray for customers and the log server.
- Switches and the internet keep GNS3's bundled square switch and globe.
- `kali`'s frame holds OffSec's Kali dragon. It is the press pack's `kali-dragon-black.svg` at a pinned commit, checked by sha256 and placed unmodified inside the frame. `host-kali.txt` and the Map pane say whose trademark it is.

**Every learner-map host is a display container.**

- GNS3 colours a link end by its node's status, so a stopped node draws every end red.
- Each host is therefore a `docker` node of one pinned image (`busybox`, `topology.DISPLAY_IMAGE`). It only runs `sleep` and has no console.
- The real machines run in the range. The map's nodes only display them.
- Measured on the platform VM with a board map on slot 1 and a corp map on slot 2, both languages: 26 display containers, 115 MB PSS for their processes and runc shims, and 12 MB for their uBridge processes (`docs/DECISIONS.md`).

Segments are `ethernet_switch` nodes. The system map draws the rest as follows.

- Docker containers are `docker` nodes that carry their real images and are never started.
- OpenStack VMs are `qemu` nodes with no disk image. The OPNsense edge has three NICs in vtnet order.
- The wargame host's containers hang off one switch per compose project (`board-default`, `corp-default`).
- A sensor that shares another's network namespace, or the host network, has no NIC. A note beside it says whose network it watches. In the Docker project a dashed line joins `fsl-suricata` to `fsl-waf`.
- Each declared segment is a titled rectangle that holds its switch (Internet, Application estate, Management and monitoring).
- Each container or VM has a plain-words note. GNS3 3.1 makes a node's label its name.

`platform/tests/test_gns3_topology.py` checks the maps.

- It derives the system maps' expected nodes and links from `declaration.yaml`, `compose.yaml`, `session.yaml` and the wargame compose files, and checks GNS3's structural rules.
- It checks each wargame's learner map against the system map, which the learner map is a reduced copy of. It checks the nodes, the links against the system map's wiring through `topology.learner`, the log links, the geometry and the display nodes.

`bin/check-topology` installs gns3-server 2.2.61 and 3.1.0a6 into venvs under `~/.cache/fsl/check-topology`. For each release it runs `load_topology` on a copy of each file, and on a range map generated for each wargame from each learner map with a fixture range. It also checks that every bundled symbol a node names exists in that release.

### A range's own map

The learner sees the addresses of their own range. `api/maps.py` derives the maps from the learner map. For each OpenStack slot or Docker session, and for the session's wargame (`slot 1 board`, `session <id> corp`), it makes one project per language (`topology.labelled`). Every link is labelled at both ends, as a lab topology labels it.

Labels at the switch end:

- A switch's end, and the `internet` switch's end, carries the port the link uses in short form (`Ethernet2` is `e2`).

Labels at the host end:

- Every host's end carries the real interface and its address with prefix on that switch's segment (`ens3 10.30.0.102/24`, `vtnet0 5.188.10.1/24`).
- The platform reads these through `topology.learner`.
- Two hosts show only the interface, not the address (`topology.ADDRESS_VARIES`): each request can leave from a different origin, so the source address changes (origin SNAT, several origins):
  - the attacker, whose interface is the one in the default origin;
  - the customers, whose interface is the one in their busiest origin. The busiest origin comes from the weights in `traffic.yaml`, leaving the default origin out, as `attacker.customer_origins` does. Where the box holds no such interface, there is no label. On docker the customers' container starts only when the customers start, so it has no interface to label.
- The site shows its host address on `sw1`, because the WAF reaches the site there. It shows the site container's address on `sw2`. The site is a dual-homed server, so it gets one label at each of its own link ends.
- A `sw3` end carries the NIC name alone (`ens4`, `vtnet2`), because its address is on the management network, which the learner does not see.
- The `log-server`'s end is the log store's own NIC where it has one on that network (Docker). Otherwise it is the platform VM's NIC (OpenStack, `ens7`).
- No label names a Docker bridge (`br-`).
- The one end that can stay blank is Docker's `customers`, whose box runs only while the customers do.

Zone captions:

- Each zone caption gains the networks of the labels on its switch (`Services 10.30.0.0/24`, `Internal DB 172.18.0.0/16`).
- The caption of a switch is the text in the smallest box that holds it (`topology.captions`).
- Internet and Monitoring keep their name alone.

Where a label sits (`topology.leaving`):

- A label lies level beside its node, on the side its link leaves.
- On a level or shallow link, it goes above or below the line, on whichever side the node's other links leave more room. It stays clear of where the line runs under the text.
- On a steep link, it goes below the node, or above it where the node's name is beside it. It sits left or right of the line by the same rule, and right of the node where its name is above.
- It stays clear of every line, of GNS3's status mark (6 units round, 60 along the line from the node's centre in the 3.1 web UI), of a node's name, and of a zone's edge and its caption.
- The text width is estimated at 7 units a character, because the web UI renders `font-size: 10.0` at 13.3 px.
- A shallow label goes to the other side of its line where it would touch its node's name.
- A label on the left is right-aligned with `text-anchor: end`.

Ids and names: every id is `uuid5(<learner id>, "slot-<n>-<wargame>")`, or `session-<id>-<wargame>`. The name gets the key. `show_interface_labels` is on.

The adapters read the interfaces with `interfaces()`:

- On OpenStack, `ip -o -4 addr` (`ifconfig` on OPNsense) runs on each slot host through a runner that runs on the host itself.
- On the wargame host, the compose containers' addresses come through `nsenter`, and the bridges by Docker network id.
- The platform VM's own NICs are read with the same `ip` in a `busybox` container on the host network (`interfaces.on_this_host`). The platform takes no SSH.
- On Docker, each session endpoint's MAC is matched to `/sys/class/net` inside its container.

`gns3.publish` loads a project into GNS3 in these steps:

1. It signs in as GNS3's admin. The password comes from `FSL_GNS3_ADMIN_PASSWORD` or `/run/fsl-gns3/admin-password`. The GNS3 data directory is mounted read-only, and the file is 0640 to the Docker socket's group.
2. It deletes the project if GNS3 lists it. A DELETE of a project GNS3 never held is logged at ERROR.
3. It imports the project as a portable project. Its `project.gns3` keeps the URL's project id, so GNS3 keeps every id, as for a snapshot.
4. It turns `auto_close` off. An import is made with it on, whatever the file says, and a project closed when the last web client leaves stops its nodes.
5. It opens the project and starts its nodes.

When the platform loads a map:

- at session open;
- after a slot's reset;
- when the Map pane asks (`GET /api/topology/?language=&session=`) and GNS3 does not hold it open.

An unchanged map is not loaded again. The platform keeps the newest session's map of each slot, and on Docker the open sessions' maps. It deletes the others. Generated maps are never committed. If GNS3 cannot load a map, the endpoint serves the session's wargame's learner map from the file and says why in `detail`.

Each project has a Korean pair for Korean learners, `deploy/topology/range-docker.ko.gns3` and `range-openstack.ko.gns3`.

- The pair has the same nodes, links, ports and positions. Only the zone captions are in Korean, in the terms of `docs/vocabulary.md`. Node names stay the role names.
- Every id in the pair is `uuid5(<English id>, "ko")`, and the project name carries a Korean suffix. GNS3's compute keeps nodes by node id alone, so two open projects may not share one.
- The English file is canonical. The test rebuilds the Korean file's structure from it and fails on any difference but the words.

The `gns3` service (`deploy/gns3`, gns3-server 3.1.0a6 with its MCP extra) does the following at start.

- It holds only the maps the platform loads. A template draws every wargame, so none is copied in.
- It sets the admin password before the controller database exists (`FSL_GNS3_ADMIN_PASSWORD`, or generated once into `/var/lib/fsl-gns3/admin-password`).
- It gives the learner user the built-in Auditor role on `/` (`FSL_GNS3_AUDITOR_PASSWORD`, or generated once into `/var/lib/fsl-gns3/auditor-password`, which the platform reads from the same mount).
- It writes `/static/web-ui/map.html`, titled Map. The page signs in as the learner and stores the token where the bundled web UI reads its controller (`controller-1`, `controllerIds` in `localStorage`). It sets `showInterfaceLabels` on and `integrateLinkLabelsToLinks` off, so each link end's label is drawn where the project puts it. It sets `statistics_command` to `false`, so the web UI sends no usage statistics from the learner's browser.

The page opens the project in a same-origin frame and makes it view-only before the map draws.

- A stylesheet hides every piece of editing chrome: the title bar, the tool column, context menus, the topology summary, dialogs and the Angular CDK overlay. It also takes pointer events off everything inside `svg.map`.
- Capture-phase listeners on the frame's window swallow every trusted click, double-click, context menu, key and drop. They also swallow every mousedown except a left press on `svg.map` itself.
- The page's own synthetic events are not trusted, so its clicks on the hidden controls still land.

Once the map is drawn, the page does this:

- It closes the topology summary. Its visibility is a constant in the 3.1.0a6 bundle.
- It turns the web UI's moving mode on for good. A drag on the map pans and the wheel zooms.
- It resets the zoom.
- It zooms out with the web UI's own button (0.1 a step) until the drawing fits. The web UI never reads the project's `zoom`.
- It centres the drawing with one mousemove. The web UI pans by `movementX`/`movementY`.

The page and the console cooperate as follows.

- The pane's Fit to view button posts `fit` to the frame, which runs the same reset and fit. The console also posts `fit` on every pane open and resize.
- On every open, the console shows "Loading the map..." and keeps the frame hidden until the page posts `{map: "drawn"}` (after its first fit) or `{map: "fitted"}` (after every later one). After a later fit, the page retries until the drawing lies inside the frame.
- The page answers the lesson coach's `{locate}` for a node, a link, a link end's label or a zone. It answers with the rectangle in the pane. It reads the link ends' labels once from `/v3/projects/<id>/nodes` and `/links` with the Auditor's token.
- It also sends every zone drawing's rectangle (`zones`) and the boxes of every node, interface label and zone caption (`text`), so that callouts stay off the map's text.
- The Auditor role still refuses every write on the server.

For development MCP use (`/v3/mcp/`), `docker exec fsl-gns3 python /opt/fsl-gns3/provision.py api-key <name>` prints an API key. Nothing in the console exposes MCP. The console's tab for the map reads Map (`blue.pane.topology`, one word in Korean too). No word a learner reads names GNS3.

A read-only user cannot open a project (`Project.Allocate`). So `provision.py` opens every project as admin at start and starts each of its stopped display nodes. It starts only nodes of the pinned image and never runs a node of any other image. The Auditor then sees the projects open and green.

What the service needs:

- uBridge 1.2.3, built from its release tag with `cap_net_admin,cap_net_raw` file capabilities.
- `CAP_NET_ADMIN` and `/dev/net/tun` for the `ethernet_switch` nodes. GNS3 3.1 backs each with a kernel bridge and TAPs inside the container's own network namespace.
- For the `docker` nodes, the host's Docker socket. Each node is a container `GNS3.<node>.<project id>` on the host's daemon.
- Debian's `docker-cli`, because GNS3 closes a docker node with `docker exec`.
- `busybox-static`, because GNS3 copies it into every docker node it starts.
- The host's pid namespace (`pid: host`), because uBridge moves a started node's interface into the namespace of the container's host pid.
- `qemu-system-x86`, kept for the system maps' `qemu` nodes.

Other facts about the image:

- The `[ai-features]` extra is needed, or 3.1.0a6 does not start. It brings a copilot that clones a skills repository at start. The image sets its `enabled` to `False` in `skills_config.py`, and the image build fails if that line is gone.
- The host daemon resolves the containers' bind mounts on the host, so the data directory has the same path on both sides (`/var/lib/fsl-gns3`).
- The server runs as the user `gns3`, which joins the socket's group at start, as `fsl` does in the platform.
- `GET /api/topology/` offers the web UI (`web_ui`) only while GNS3 reports the project `opened`. Otherwise the console's Map pane says the map is not open.

`GET /api/topology/?language=en|ko` returns the substrate's learner map drawn in that language. With `&session=<id>`, it returns that session's map for its wargame, described above.

- The map comes from GNS3 (`platform/gns3.py`) or from the repo's file.
- `en` is the default when the parameter is absent. Any other value gets 400.
- The console sends its own language. `web_ui` deep-links the GNS3 web UI to that project's id.
- The Map pane is that map alone: the framed GNS3 web UI and its fit button.

`GET /api/sessions/<id>/topology/` reads the English map of the session's wargame (the pair has the same node names and links) and adds `project.nodes`.

- `project.nodes` holds each host node's addresses per switch, from the same range read, and the state `running` or `not reported`.
- The session overlay lists only the map's hosts and their addresses on the map's switches.
- The overlay places hosts by the names the range reports them under. OpenStack reports a slot's servers by their declared names (`slot.known_as`). Only the VM's own hostname, which the syslog records carry, has the slot suffix.

## Isolation seams

An isolation seam is a rule that only one file may handle one concern. For example, only `platform/ingest/elastic.py` talks to Elasticsearch. The table gives each concern, its owning file and the places in code today that break the rule (the known exceptions).

| Concern | Owning file | Known exceptions |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py` PUTs the `geoip` ingest pipeline at bring-up |
| The Kibana HTTP API, its saved objects and the Discover link | `platform/kibana.py` | `platform/nginx.conf` knows Kibana's API paths. It refuses the administration APIs, the Default space, unprefixed paths and `?namespaces=`. It answers `GET /kibana/s/<space>/api/spaces/space` itself with the one SOC space |
| The GNS3 API | `platform/gns3.py` | `deploy/gns3/provision.py`, inside the GNS3 container, signs in as admin to provision the learner and open the projects. `deploy/gns3/auditor.html`, served by GNS3 as `/static/web-ui/map.html`, signs in as the learner and reads `/v3/projects/<id>/nodes` and `/links`. The console's Map pane frames the web UI at the port and path `gns3.py` returns |
| CRS configuration and the nginx reload | `platform/rules/crs.py` | The WAF terminal (`waf-terminal.sh`) opens a shell in `fsl-<id>-waf-1` for the person. On OpenStack, `vm-terminal.sh fsl-waf` opens an ssh shell on the WAF VM. F6's WAF-pane steps show the commands the learner types (`grep -n ruleRemove {waf_rules}`, `{sudo}nano {waf_rules} && {waf_reload}`). `wargames.lesson` fills them in from the declared exclusion file and reload command (`settings.FSL_WAF`). The platform does not drive the terminal |
| The session's WAF container (docker) | `platform/range/docker.py`, by compose label | None in Python. `waf-terminal.sh` names `fsl-<id>-waf-1` (the row above) |
| The Suricata process | `platform/rules/suricata.py` | `platform/range/opnsense.py` and `deploy/opnsense/` configure and restart Suricata on the OPNsense edge (OpenStack). Each sensor host in `declaration.yaml` (the edge, and the wargame host for `estate-sensor`) names the rule file and reload command that `suricata.py` is handed. `platform/range/wargame_host.py` (with `deploy/wargame-host/sensor.yaml`) stops and starts the estate sensor's compose service on the wargame host when a slot is configured or reset (OpenStack). Its baseline rules then go through `suricata.py` |
| The attacker box | `platform/attacker.py` | `platform/operator_log.py` reads `/var/log/commands.log`. The terminal wiring (`settings.py`, `nginx.conf`, `entrypoint.sh`) names `fsl-kali` and `fsl-<id>-kali-1`. The Website pane (`platform/api/site.py`) is not an exception: it reaches the box only through `attacker.py` (`customer_origins`, `unbound_source`, `as_customer`, which holds the command) and the substrate's `opened` (an ssh stream on OpenStack) |
| The target's own records | `platform/api/loot.py` (board), `platform/api/effect.py` (corp) | None. On OpenStack they reach the same containers: `loot.py` over HTTP at the wargame host's published port, and `effect.py` through the runner, which `docker exec`s into `corp-db` |

## Files

Important files that this document does not otherwise name.

| File | What it does |
|---|---|
| `deploy/filebeat/filebeat.yml` | The shipper and collector configuration. It sets `event.module`, tags the slot (`fsl_slot`) and writes `logs-<session\|slot>-sensors` |
| `deploy/elastic/ingest-pipeline.json` | The `geoip` ingest pipeline. It puts the event time into `@timestamp`, adds GeoIP of `src_ip` and drops `fsl_slot` |
| `deploy/proxy/stamp.py` | The mitmdump script that stamps `X-Request-ID` and forwards to the session's origin |
| `deploy/kali/operator-log.sh` | Kali's shell hook. It appends each command with its marker to `/var/log/commands.log` |
| `platform/scoring/` | `correlate.py` matches detections to cases by marker or window. `metrics.py` counts TP, FP, FN and TN |
| `platform/scoreboard.py` | Objective scoring. It attributes detections to attempts, decides `corroborated` and tallies the lost objectives |
| `platform/game.py` | The game score (speed, accuracy, coverage, response) in the score's `game` block |
| `platform/suppress.py` | Comments a Suricata rule out until a time and restores it (`# fsl-suppressed`) |
| `platform/api/models.py` | The Django models: `Session`, `Case`, `CustomerRequest`, `Detection`, `Objective`, `RuleSet`, `Suppression` |
| `platform/fsl/urls.py` | The route table of every endpoint |
| `platform/api/refusals.py` | Maps exceptions to HTTP statuses (a 404 under `/api/` is JSON). It also holds the same-origin check for unsafe methods |
| `platform/api/reachability.py` | The middleware that refuses requests from range hosts |
| `platform/range/declared.py` | Reads `declaration.yaml` into `Declaration` |
| `platform/range/openstack.py` | The OpenStack adapter (`connect`): Keystone, Neutron, Nova and ssh |
| `bin/verify` | The ratchet check, which refuses a change that grows a gated size number (see `CLAUDE.md`), and the tests a change reaches (`--changed`, `--fast`; `bin/select-tests` picks them) |

## Where requests come from

| Route | Sender | Source address in the alert | Marker |
|---|---|---|---|
| Terminal, HTTP | Kali, through `proxy:8081` | the proxy, on the chosen origin | added by the proxy |
| Terminal, raw TCP | Kali directly | Kali, on `edge` only | none |
| Fired case, HTTP | the attacker box: the platform runs `curl` there through the launcher (`views._fire`: scenario schedule, lesson seed, `POST /api/sessions/<id>/attacks/`) | the attacker box, on the chosen origin | added by the harness |
| Fired case, tool | a throwaway `fsl-kali` container | that container, on the chosen origin | sqlmap `--headers=` |
| CLI run, HTTP | the attacker box: `redteam/run.py` runs `curl` there through `launcher(<declared default origin>)` | the attacker box, on the default origin | added by the harness |
| CLI run, tool | a throwaway `fsl-kali` container, from `launcher(<declared default origin>)` | that container | sqlmap `--headers=` |
| Site browser | the learner's browser, through the platform's nginx on port 8002 and `platform/api/site.py` | a customers address. On OpenStack it is an address Kali holds, sent as the `fsl-users` account so it crosses the edge. On docker it is the platform's own address on the customers network | the session's secret `browse-<hex>`, set by `site.py`; the API shows it as `browse` |
| Customers | `deploy/traffic/users.py`, in `fsl-<id>-users` (docker) or as `fsl-users` on the Kali VM (OpenStack) | the persona's own address on a non-default origin, never one the attacker sends from | a fresh UUID per request |

The proxy is a `mitmdump` script.

- On the OpenStack Kali, `web-proxy.service` runs it from `/usr/local/lib/web-proxy.py`, and `ttyd.service` runs the terminal.
- `/var/lib/session/active` and `origin` are mode 0600 for `ubuntu`, which the platform logs in as. The shell hook reads the marker through `sudo -n cat` when it cannot read it directly.
- `/var/log/commands.log` is 0622 `ubuntu`, so `kali` can only append to it.
- The proxy sets `X-Request-ID` from `/var/lib/session/active` on a request that carries none.
- When `/var/lib/session/origin` names an address, the proxy forwards the request there with the original `Host`.
- The platform writes both files with `docker exec`.
- There is no TLS interception. The proxy is only an environment variable and enforces nothing: `curl --noproxy '*'` skips it.

The terminal also records what the operator types.

- Kali's shell appends each command, with the current `/var/lib/session/active` marker, to `/var/log/commands.log`.
- The platform reads that file through `runner("attacker")` and serves it at `GET /api/sessions/<id>/commands/`.

The Kali pane (the red console's, and the blue console's in a lesson or scenario session) frames the URL that the session API names (`kali_terminal` in `GET /api/sessions/<id>/`).

- On compose, the URL is `/terminal/<session id>/`. nginx proxies it to Kali's own ttyd in `fsl-<id>-kali-1:7681`.
- On OpenStack, the URL is `/vm-terminal/kali/?arg=<session id>`. It is a ttyd inside the platform that connects over ssh to the mgmt address of the host in the session's slot.
- On compose, Kali and the WAF have no mgmt address, so `/vm-terminal/` does not connect there.

`vm-terminal.sh` checks the host key under the alias that the platform's runner uses for the same server, `fsl-<server id>-<launch time>` (`OpenStack.host_key_alias`), with `StrictHostKeyChecking=accept-new`.

- A server rebuilt by a reset gets a new alias. Its new key is learnt without the "REMOTE HOST IDENTIFICATION HAS CHANGED" warning.
- A changed key under an alias already known is refused.

How each terminal logs in on OpenStack:

- Kali gets a plain login as the `kali` user: sudo, hostname `kali`, Kali's own two-line prompt, no motd. So `/etc/profile.d/proxy.sh` (`http_proxy`) and the command hook (`/usr/local/lib/shell-hook.sh`, `__log_command`, sourced from `/etc/bash.bashrc`) apply as at any login.
- The WAF runs `bash --rcfile` with `-i` as `ubuntu`. The rc file reads `/etc/profile` and `~/.profile`, sets the time zone, and replaces `\h` in the prompt with the host's name without `fsl-` (`ubuntu@waf`). It prints `/etc/motd`. With a command, sshd prints no Ubuntu login banner or last-login line.
- The WAF VM's own hostname is `waf` too. The boot unit `set-hostname` renames it after cloud-init and gives the Nova name to rsyslog as `localHostname` without the `fsl-` prefix (`waf`, `waf-2`). Filebeat can therefore still read the slot from the sender name.

The blue console's WAF pane frames the URL that the session API names (`waf_terminal` in `GET /api/sessions/<id>/`).

- On compose, the URL is `/waf-terminal/<session id>/`. nginx takes the session from the path, drops the client's query and proxies to a ttyd inside the platform (`ttyd -W -a -b /waf-terminal -i 127.0.0.1 -p 7693 /app/waf-terminal.sh`) with `?arg=<session id>`.
- ttyd's `-a` passes that value as the script's argument. After checking that it is a number, the script runs `docker exec -it fsl-<id>-waf-1 bash`.
- The WAF image has no ttyd of its own.
- The same `auth_request /terminal-allowed` guards the URL.
- On OpenStack, the pane frames `/vm-terminal/waf/?arg=<session id>`.

The blue console's Website pane is a browser inside the console. It has:

- back, forward and reload, with a stop button and a thin progress bar while a page loads;
- an address bar that shows the full URL (`http://board.com/<path>`) with Chrome's "Not secure" marker for http. It takes a URL or a path and Enter;
- the page in an iframe;
- a "Developer tools" toggle (also F12, inside the page too).

An address for another host shows Chrome's "This site can't be reached" page.

The target is not published. So nginx on 8002 passes `/site/<session>/<host>/<path>` to the platform's recorder, behind the same `auth_request /terminal-allowed` as the terminals. The recorder is `/site-proxy/<session>/<host>/` (`platform/api/site.py`), and the exact path and query travel in `X-Site-Uri`.

The recorder sends the request from the customers side of the range (below) as Chrome would.

- It sends `Host: <host>`, `Connection: keep-alive` and `Accept-Encoding: gzip, deflate`. The recorder decodes the answer before streaming it on.
- It sends `Upgrade-Insecure-Requests: 1` on a navigation, and the session's cookies for that host.
- It uses Chrome's header order (`CHROME_ORDER`). It follows no redirect.
- Of the browser's own headers it passes on only `Accept`, `Accept-Language`, `Content-Type`, `User-Agent`, `Referer` and `Origin`. It rewrites the last two to what a browser on `http://<host>/` would send (`as_browsed`).
- `X-Forwarded-For` is not among them. The WAF therefore adds the customers address, and the target never sees the learner's LAN address.

The recorder's answers:

- 404 for a session that does not exist, and 409 for a closed one, without calling the WAF.
- 400 for a path that is not a valid request target.
- 502 ("board.com did not answer") when nothing answers within 3 s to connect or 20 s to read.
- The page is streamed to the browser as it arrives.

Other facts about the route:

- nginx on 8000 answers 404 for `/site-proxy/`.
- The platform's same-origin check for POSTs skips that path, so a form on the target can still be submitted.
- The WAF judges every page. A block is the WAF's own 403 page, and it lands in Kibana.
- The path and query go on exactly as the browser sent them (a `map` on `$request_uri`).

nginx rewrites what would leave the prefix.

- `Location` headers are rewritten (`proxy_redirect`).
- In HTML, `href="/`, `src="/`, `action="/`, `http://<host>/` and `http://<host>"` are rewritten (`sub_filter`, with the upstream asked for no compression). WordPress's escaped `http:\/\/corp.com\/` is rewritten too.

Cookies:

- nginx strips the browser's `Cookie` and the answer's `Set-Cookie`. The platform's cookies therefore never reach the target, and no target cookie reaches the browser.
- The recorder keeps the target's cookies itself, per session and host (`site._keep_cookies`). It drops `Secure` cookies, removes expired ones and forgets them at close. It sends them back as `Cookie`, so a sign-in made from this pane holds for the session.
- Stripping does not stop a script on the target page. The script runs on the platform's host (port 8002), and cookies are not isolated by port. `document.cookie` could therefore set a cookie that the console on 8000 would send.
- The console uses no cookies today. One added later would be reachable this way.

nginx also appends a script before `</body>`.

- The script posts `location.pathname + search` to the parent. This is how the address bar and the history follow a link clicked inside the page.
- It passes F12 up.
- It answers the lesson coach's `{locate: <selector>}` with the element's rectangle (again on scroll and resize). It answers only a message from its parent whose origin is the console's host.
- It adds no request of its own.
- It shows each link as `http://<site>/...`. The markup nginx rewrote keeps the proxy path, so a hover shows the address the customer would see. A plain click on such a link goes through the proxy path.

The Website pane's egress (`site.found_egress`, once per session) leaves from a customers address. Its requests therefore take the customers' path, and the sensors see them as they see the customers. The address is in the origin that the scenario's customer traffic weights most (`customers.declared`, else the first by id) among `attacker.customer_origins`.

- On OpenStack (`ATTACKER_ORIGIN_MODE=snat`), the recorder opens an ssh stdio stream to Kali (`OpenStack.opened`) that runs `attacker.as_customer`.
  - `as_customer` is a Python bridge. It runs as the `fsl-users` account, which Kali's origin SNAT leaves alone. The account is created with its exemption when the customers never ran on the slot.
  - The bridge binds to that origin's first address and connects to the WAF's `estate` address on port 80.
  - The request crosses the edge (DNAT). The edge sensor sees it arrive at `waf`. The estate sensor sees `waf` send it on to `board.com` with the customers address in `X-Forwarded-For`.
- On docker, the platform binds its own address on that customers network and connects to the WAF's address there. The Suricata in the WAF's namespace sees both legs.
- No container or `mgmt` address is named.

The route is served on its own port, 8002, a different origin from the console's 8000. Every response carries `Content-Security-Policy: sandbox allow-forms allow-scripts allow-same-origin`.

- The red team can plant script in the target. On the console's origin, that script could read and drive the console and its APIs.
- A sandbox without `allow-same-origin` (an opaque origin) would block that even on port 8000, but Chromium-based embedded browsers refuse such a frame (`ERR_BLOCKED_BY_CLIENT` in the Claude desktop browser), so the site gets its own port instead.
- `SITE_PORT` is 8002 on every substrate.
- The session API gives `site: {port, path}` or `null`, and the console hides the pane without it.
- The platform template's security group opens 8002 (`docs/OPENSTACK.md` §3.5).

The recorder keeps each session's last 200 requests in the platform's memory. They are lost on restart and forgotten when the session closes. Each request holds:

- method, `http://<host><path>`, status and its text;
- type and category (from `Sec-Fetch-Dest`, else the content type);
- initiator, transferred size, time;
- the egress address, the remote address, the referrer policy the page set;
- the request headers as sent, without the marker;
- the response headers as received (`Set-Cookie` included, as Chrome's panel shows them);
- the decoded bodies, each cut to 64 KB. The response is streamed and only its first 64 KB kept.

Besides the learner's requests, the list shows two more kinds of row:

- `/favicon.ico`, fetched once per session and host after the first page.
- A `disk cache` row (`cache: "disk"`, size 0) for each same-host stylesheet, script or image that a page names, that was fetched with 200 before and is not asked for again within 1.5 s.

`GET /api/sessions/<id>/site/requests/?after=<id>` lists the requests. `.../site/requests/<id>/` gives one in full.

The Developer tools panel is Chrome's Network panel, docked under the page. Its top edge drags taller or shorter.

- While the panel is open, the tab is visible and the session is open, it polls the list every 2 s. A closed session answers 409 and the polling stops.
- The columns are Name (the last path segment and query, with the full URL on hover), Status (4xx and 5xx in red), Type, Initiator, Size and Time.
- The toolbar has clear, a filter, Preserve log (off: a navigation clears the list) and type chips (All, Fetch/XHR, Doc, CSS, JS, Img).
- A selected row has these tabs: Headers, Payload, Preview and Response.
  - Headers shows General (Request URL, Request Method, Status Code, Remote Address, Referrer Policy), then Response Headers and Request Headers, each with a raw view.
  - Payload shows the Query String Parameters decoded, with source and URL-encoded views, and a form body.
- Rows, tabs and lines carry `data-coach` for the coach.
- The Korean labels are Chrome's own (`front_end/core/i18n/locales/ko.json`). The English ones use Chrome's en-US casing. Nothing in the panel says "WAF".

Browsing is marked with the session's own secret.

- The secret is `Session.browse_marker`: `browse-` and 32 random hex digits, made when the session is created. The recorder replaces whatever `X-Request-ID` the browser sent.
- The request comes from a customers address (above).
- Its alerts are ingested and listed like any other. The learner finds them in Kibana and in `/detections/`.
- `/score/` leaves out detections that carry that session's secret, the way it leaves out replays (`views.REPLAY_MARKS`). Browsing is not a case, so it is neither a true or false positive nor an unattributed alert.
- A literal `X-Request-ID: browse` sent by hand is just an unknown marker and is scored.
- `POST /api/attacker/label/` refuses labels that start with `browse`.
- The API never shows the secret. `/detections/`, `/api/detections/<id>/` (including `raw`) and the Network panel show `browse` in its place. Kibana shows the secret, because it is the blue team's tool.
- The red console's Website pane is the same pane on the same session. In a wargame, the attacker's browsing carries the session's secret too. It is therefore left out of `/score/` like the defender's, and the defender's Network panel lists it. Still open: the person-against-person wargame, 4.2, is not built.

A fired HTTP case carries the `Host` of the session's wargame, `board.com`, whether or not an origin was chosen.

- Choosing an origin points traffic at the WAF's address on that origin's segment, by IP.
- The name resolves on the `edge` network, which the platform uses when no origin is set.
- The edge networks are shared, so `board.com` there resolves to every session's WAF. At open, the platform points the session's proxy at its own WAF. Launched tools get `--add-host` for `board.com` and `corp.com` at that WAF's address.
- `rotate` is a per-session round robin, not a random pick.

A fired tool case is pointed at the origin's target URL. With no origin chosen, it is pointed at `TARGET_URL` (`http://board.com`) from the declared default origin.

The target is not host-published, so the command-line harness reaches it from inside the range too.

- `redteam/run.py` runs on the platform, the way the acceptance suite drives it.
- It has no origin option.
- Its `--target` defaults to the `public_url` of the scenario that its `--cases` file belongs to (`http://board.com` for board). That name resolves to the WAF on port 80.
- `--tool-target` defaults to `http://board.com`.

On docker, the session WAF runs CRS with `SecRuleEngine On` and anomaly threshold 5 (`session.yaml`).

- Its paranoia level and rule exclusions are the session's own (`Session.waf`). They are written at open from the scenario's defense and changed through `/api/sessions/<id>/waf/` ("Sessions, WAF tuning and the step engine").
- `GET` reads the file with a 10 s timeout, so a poll never holds a server thread longer.
- Every Suricata rule is `alert`, so the WAF is the only part of the range that blocks.
- The OpenStack WAF VM blocks the same way: `SecRuleEngine On` in `deploy/waf/modsecurity.conf`, CRS's default threshold 5 and Paranoia Level 1.

## Where alerts go

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, logs-<session|slot>-sensors
                                     (event.module) pipeline geoip
                                                          |
             POST /api/sessions/<id>/ingest/ (called by tests, at close, by the scenario engine and by lesson checks)
                                                          |
             parse per event.module, copy the marker onto alerts, store
             as Detection rows in SQLite
```

Callers of `ingest/`:

- `test/conftest.py` and the session page's confirm-close call it.
- `redteam/run.py` prints the curl.
- A wargame session ingests at close.
- A lesson or scenario also ingests while it runs. The scenario engine ingests every 15 s (the last 180 s). Each step check that reads records ingests the last 600 s.
- Alerts that arrive after the close are not ingested.

How an alert gets its marker:

- ModSecurity's audit log carries the request headers, so its alerts carry the marker directly.
- Suricata's alert events carry no request headers. Only its `http` events do (with `dump-all-headers: request`; `custom: [X-Request-ID]` has no effect).
- Ingest copies the marker from the `http` event onto the alert with the same `(flow_id, tx_id)`. Joining on `flow_id` alone attributed every alert on a keep-alive connection to its first case.

Each ingest call does the following.

- It first restores rule suppressions that have expired.
- It reads `logs-<session>-*` on docker (`ELASTIC_SESSION_INDEX`), because each session's Filebeat writes its own index. On OpenStack it reads `logs-<N>-*`.
  - On OpenStack, the shared collector tags each syslog line with the slot that its sender's hostname names (`-N` before the domain, slot 1 otherwise). It writes the line to that slot's index, and the ingest pipeline removes the tag before the document is stored.
  - Filebeat sets `event.module` (`suricata` or `modsecurity`) on every event. It drops a syslog line that is neither.
  - An index therefore holds only the two engines' events. No field, index or header that a learner can open in Kibana names the platform (the case marker travels as an `X-Request-ID` header).
- It asks Elasticsearch for `@timestamp` from the session's start minus a minute to its end (or now) plus a minute.
  - The `geoip` pipeline sets `@timestamp` from the event's own clock (Suricata's `timestamp`, ModSecurity's `transaction.time_stamp`).
  - The window therefore selects events by when they happened, not when Filebeat read them.
- It reads 5000 hits at a time, oldest first.
  - When a read is cut, it asks again from the newest `@timestamp` it got (`api/views.py` `_fetched`, at most 40 more reads). It skips documents already read by `_id`.
  - A window it still cannot finish, or one whose 5000 hits share one timestamp, makes the reply carry `truncated` and the session record `read_of`. That adds `score.warning.truncated` to the score.
  - One sqlmap case leaves more than 5000 records. So while ingest read only once, every case fired after it was scored as a false negative.
- It keeps Suricata's `alert` events. It turns ModSecurity's record into one Detection per matched rule message, with id `<Elasticsearch _id>:<n>`.
- It drops alerts whose own event time falls outside the window, and counts them as `stale`.
- It writes markers found later onto stored rows that had none.
- It fills `src_host` and `dest_host` from the substrate's segments. The fields stay empty if the substrate cannot be reached.
  - Ingest and `/detections/` reuse a session's segments for 30 s. This avoids running `docker network ls` and `inspect` on every step poll.
  - `/top/`, `/map/` and `/topology/` read the segments fresh.

Elasticsearch is used for storage and for GeoIP enrichment at index time, which is why there is no Logstash.

- Nothing uses its query engine beyond a time-range search.
- `GET /api/sessions/<id>/map/` and `/top/` compute in Python over the SQLite copy.
- `src_geo.location` is mapped as two floats, not a `geo_point`.
- `bin/worldmap` generates an Equal Earth map cut at 60 degrees south. No console page draws it since the blue dashboard was removed.

Two geoip processors write `src_geo`: one on `src_ip` (Suricata) and one on `transaction.client_ip` (ModSecurity).

- Compose turns the managed downloader off and bind-mounts `./config/ingest-geoip`, which `bin/fetch-geoip` fills. `GeoLite2-City.mmdb` therefore survives a container recreate.
- The entrypoint registers the pipeline at bring-up (`platform/register_pipeline.py`). It runs in the background, like `kibana.py`, so the platform serves while Elasticsearch is still coming up.
- waitress serves the platform with 16 threads on 127.0.0.1:8001.
- The entrypoint tests nginx's configuration and starts nginx only once that port accepts. nginx therefore never answers 502 for a platform that is still starting.
- nginx sets `proxy_max_temp_file_size 0` for every location and a 1 MB request body buffer. No proxied response or request body is written to a temporary file.

Django runs with `DEBUG` off unless `DJANGO_DEBUG=1`.

- With no `DJANGO_SECRET_KEY`, the entrypoint generates a key once into `/data/secret-key` (mode 600).
- `fsl/wsgi.py` refuses to serve with `DEBUG` off and no key.
- A 404 under `/api/` is JSON `{detail}` (`api/refusals.py`).

## Sessions, WAF tuning and the step engine

A session is opened with `POST /api/sessions/` `{scenario, guidance, lesson, defense}`. These fields are stored on the session (migrations 0015, 0022).

- `scenario` names a wargame (default `board`) or a scenario id. A scenario open refuses `lesson`, `guidance` and `defense` ("Scenarios").
- On a wargame, `defense` names one of its `defense` entries (default `full`).
- `guidance` is off by default and on when `lesson` is given. It needs the wargame to declare `foundations`. A `lesson` with `guidance: false` is refused.
- `{"lesson": "f1"}` to `"f6"` opens that foundation unit. `{"guidance": true}` alone opens the first unit by `order` (f1).
- The unit is kept as `Session.lesson` and reported as `lesson_id`. A guided open that names no defense takes the unit's declared `defense`.
- A session's `kind` is `scenario`, `lesson` (guided) or `wargame`.
- A session whose stored lesson id names no unit any more reads `lesson: null` and `lesson_id: null`, and keeps kind `lesson`. This happens with a session from the older course (`docs/DECISIONS.md` 2026-10-14).
- Migration 0026 dropped `Session.mode` and cleared `Session.result_cache`. Stored results are therefore scored again, without a lesson verdict. A `mode` in the body is ignored.
- `GET /api/sessions/?ids=1,2` narrows the session list to the ids given.

The board declares these defenses.

| Defense | Setting |
|---|---|
| `minimal` | CRS paranoia level 4, `local.rules` |
| `full` | paranoia level 1, the same `local.rules` |
| `ids` | paranoia level 1, `no-uri-sqli.rules` (`local.rules` without sid 9000001) |
| `xss-gap`, `overbroad` | see "Foundations F1-F6" |
| `level2`, `level3`, `inherited`, `untuned`, `broken-rule`, `spelled` | the scenario postures, see "Scenarios" |

Discovery checks each unit's `defense` against this list. No unit or scenario starts from `minimal`, so it is reached only by naming it.

What the open path does after the stack is up, on every substrate:

- It seeds the sensor with the defense's rule file, or with `local.rules` when there is no defense (`suricata.seed`).
- It writes the CRS tuning when there is a defense (`crs.apply`).
- For a guided session, it replays the unit's `cases` once (`meta.seed`, with the status curl reported and `blocked` set on a 403). The session's ModSecurity and Suricata records are then in Kibana when the learner arrives. A worked scenario does not replay.

On a slotted (OpenStack) range, the seed is skipped when the rule file is `local.rules`, because readiness offered the slot only once every sensor held it. Each slot's sensors hold their own rule files (measured 2026-10-13: a sid applied to slot 1 was absent from slot 2). Any other rule file is therefore seeded into that slot's sensors only.

If a replay at open cannot run, the open answers 503 and the session is closed. Its stack is left standing and the next open takes it down.

`platform/rules/crs.py` renders the tuning into `REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`. This is the CRS hook that loads after `crs-setup.conf` and before the rules. The file contains:

- a `SecAction` that sets `tx.blocking_paranoia_level` and `tx.detection_paranoia_level`;
- one runtime exclusion per entry, with ids 10000 to 10020. The exclusion is `ctl:ruleRemoveTargetById=<id>;<target>`, `ctl:ruleRemoveById=<id>`, or `ctl:ruleRemoveTargetByTag=<tag>;<target>` for an entry that names a CRS `tag` with its target, such as `OWASP_CRS`. When a path is given, it is scoped by `SecRule REQUEST_FILENAME "@beginsWith <path>"`.

How the platform applies the file:

1. It writes the file into the session's WAF with `runner("gateway")`.
2. It runs `nginx -t && nginx -s reload`. If nginx refuses, it restores the previous file.
3. It returns once a worker that was not there before the reload is up. It reads worker PIDs from `/proc` by parent PID. New connections therefore meet the new tuning, though old workers may still drain a slow request.
4. If no new worker appears within 5 s, the reload did not happen. It restores the previous file, reloads and refuses.

It validates the input before it writes anything:

- paranoia 1-4;
- a rule id 900000-999999, or a tag of letters, `_` and `-` with a target;
- a target `ARGS`, `ARGS_GET`, `ARGS_POST`, `ARGS_NAMES`, `REQUEST_COOKIES` or `REQUEST_HEADERS` with an optional `:name`, or `REQUEST_URI_RAW` (the Korean search at PL3 also matches 920272 there), or `REQUEST_BODY`;
- a path of `[A-Za-z0-9_./-]`;
- at most 20 entries;
- optional `thresholds` `{inbound, outbound}` (1-100000). They are set as `tx.inbound_anomaly_score_threshold` and `tx.outbound_anomaly_score_threshold` on the same `SecAction` as the level, and read back.

A `PUT` that leaves `thresholds` out keeps the ones in force. `"thresholds": null` clears them.

`PUT /api/sessions/<id>/waf/` changes the tuning. This is the agent path, and no console screen calls it.

`GET` reads the file in the session's WAF back through `crs.read`. It parses the paranoia level and every `ctl:ruleRemove*` line, skips commented lines and joins continued lines. It therefore reports an edit made in the WAF terminal, which is where the learner tunes.

Snapshots of the WAF state:

- Each scenario final check, when its window is judged, takes a snapshot of what `crs.read` reads. So does each close, before the slot is rebuilt.
- The snapshots are kept in `Session.waf_snapshots` (migration 0021): `{at, scenario_window|closed, waf}`. Sessions from the older course also hold `{at, run, waf}` from their VERIFY runs.
- The latest snapshot is also `Session.waf`. A closed session therefore reports the learner's last configuration, file included (`file: null` when none was ever read).
- A WAF that cannot be read takes no snapshot, and stops neither the check nor the close.

The fix class (`lesson.fix_class(waf, posture)`, ruling D1) names what the learner changed against the session's declared posture. A posture is the defense the session started from. The result is one of these, checked in this order:

1. `level`: the paranoia level is below the posture's. A file with no level counts as CRS's default 1.
2. `threshold`: an anomaly threshold is above the posture's. CRS's 5 inbound and 4 outbound count when none is set.
3. `rule`: an exclusion the posture lacks removes a whole rule.
4. `target`: an added exclusion removes a target on every path.
5. `path_target`: every added exclusion removes a target on one path only.
6. null: nothing was added.

The scenario final check reports the fix class beside its verdict (`result.fix`, `result.scenario.fix`). It never changes the verdict.

`platform/lesson.py` holds the fix class together with:

- the step-answer helpers: `answered`, `rules_named`, `added_rules`, `pasted_rows`, `server_errors`, `alerted_by`, `detected_penalty`;
- the help counts;
- the exclusions added and removed, and the file diff that the scenario debrief shows (`exclusions_changed`, `config_diff`).

A case marked with any of `views.REPLAY_MARKS` (`seed`, `verify`, `check`, `replay`) is left out of `/score/` (TP/FP/FN/TN, the alerts it drew, and the game). It is also left out of the windows that corp's effect observation attributes changes to.

- The exception is a benign `seed` case. A lesson's seed replay is scored as a benign case (2026-10-18), so a lesson session has a true negative.
- Only `seed` is still written. `verify`, `check` and `replay` stay listed so that the replays older sessions hold stay out of both scores.

The console is four screens, and every one is filled from `/api/`. It follows a static mockup the user approved, with two rulings on top (`docs/DECISIONS.md`, 2026-10-11, console redesign). The palette and component classes are in `base.html` and `platform/console/components.css`, which `bin/build-css` puts into `tailwind.css`. The header carries the breadcrumb, the range state and the language switch.

- **Main** (`/`):
  - It lists running sessions with their kind (`scenario`, `lesson` or `wargame`), the step a foundation session reached, and whether opening has finished (`ready`, from `Session.ready_at`). Until then it shows "Preparing ns / about 80s".
  - It lists wargame cards with category, difficulty and minutes from `scenario.yaml`, and counts of attack cases, benign cases and objectives from `GET /api/wargames/`.
  - Under each card come the foundations block, the scenarios block ("Scenarios"), and one plain "Start wargame" button.
    - The foundations block shows each unit with its minutes and what it teaches. Its Start button posts `{scenario, guidance: true, lesson, defense}` with the unit's declared defense.
    - "Start wargame" is `[data-wargame-start]`. It posts `{scenario}`, so there is no guidance and the defense is `full`.
  - Each foundation and scenario also shows its newest run among the sessions this browser opened. The browser keeps them in `fsl-opened-sessions` in localStorage, which the session and blue pages write, newest first, at most 20. The main page reads them through `?ids=`.
    - For a foundation it shows still open or closed.
    - For a scenario it shows PASS/FAIL, still open, or closed with no final check.
  - It lists finished sessions with their `result`: PASS/FAIL from the scenario's last final check (`result.scenario`), or the objectives lost of the total and how many went unnoticed.
  - The result is scored once and stored (`Session.result_cache`, migration 0018) with the inputs it was scored from: `ended_at`, the hint count, and each final check's verdict. The inputs also include, for each of detections, cases and objectives, the last id and the row count (for detections, also the rows with a marker).
  - A list reads three aggregates per session. It scores again only a session whose inputs changed, such as after a late ingest.
  - A refused start is explained under the button that was pressed. On 409, "Close open sessions" lists the open ones, and each is closed through `ingest/` then `close/`. `GET /api/range/ready/` names `max_sessions`.
  - The range controls (the alert pipeline check, the open-session count, the range's health and the counts on a wargame card) show only with `?operator`.
- **Session** (`/session/<id>/`):
  - The header shows the step a guided session reached, objectives lost and the target.
  - It shows the blue console card and, for a wargame session only, the red console card (Kali terminal, Website, the objectives).
  - It shows recent cases from `GET /api/sessions/<id>/cases/`.
  - Once the session is closed, it shows these in order:
    1. a scenario's verdict banner and its debrief ("Scenarios");
    2. the primary score: every tier, lost or kept, noticed or not, with the penalty (difficulty x1 or x2);
    3. plain sentences on what the defence judged, such as "Caught 7 of 8 attacks, missed 1 (name)" and "3 of 4 benign requests passed, wrongly blocked 1 (O'Brien search)", and a line saying that a case counts once however many alerts it drew.
  - TP/FP/FN/TN and the game's balance stay in the API. No string a person reads names them (`test_strings.py`).
  - A lesson session's page names each run by its case name. For a Kali run it says "Lesson n · step m" (`per_case[].lesson`, `.step`, `.seed`). It never names a run by case id. Its course card lists every lesson taken with its steps passed and skipped.
  - "Start the same scenario again" ("Start the same lesson again" for a unit) reopens the same scenario, the same unit (`{scenario, guidance: true, lesson, defense}` when `lesson_id` is set) or the same wargame.
- **Blue** (`/blue/<id>/`):
  - It has a rail and a pane. The rail holds Kibana, Website, Map, then Alerts for a judgement scenario, IDS rules for a detection or unknown scenario or for a lesson with a step on it (F4), WAF, then a divider and Kali.
  - Kali shows only when the session's `kind` is `lesson` or `scenario`. In a `wargame` session a person attacks from the red console, and the defender does not hold the attacker's shell.
  - The Kali pane has its own frame, loaded once, so a running sqlmap survives a switch to another pane.
  - On the WAF pane, a banner names only the box (`waf_box`, `waf`) and the CRS rules directory (`waf_rules`). That is the directory of the declared exclusion file, `settings.FSL_WAF.rules`, and `crs.EXCLUSIONS` on docker.
- **Red** (`/red/<id>/`):
  - It shows the session and wargame name, the objectives (Korean names under `objective.<key>`) and "Submit stolen hashes" at the top.
  - Its rail has two panes: the session's Kali terminal and the Website pane (address bar and developer tools, the blue console's own scripts).
  - It runs no prepared attack: no case list, run buttons, recording window or source picker (2026-10-18).
  - Narrow widths stack the rail above the pane. The red and blue pages do not scroll sideways.

In a guided session (a foundation or a worked scenario), the lesson note is a column beside the pane and never over it.

- It is 340 px wide (300 px at 1280 px or less). It folds to a 44 px strip ("step n/N"). Below 1024 px it is a panel under the pane.
- From the top, the note holds:
  - the step card: step n/N, the step's title, the task, the command to type once the step is reached, an "Open <pane>" button when the step's pane is not shown, the question and its input, the status line, the help, and Skip, Back and Next;
  - the theory card, open on a unit's first visit (`fsl-lesson-landed-<id>-<lesson>`) and then as the viewer left it;
  - F6's objectives card (`lesson_objectives`), which lists each objective lost since the unit started, its difficulty, detected or not, and its penalty (difficulty x 1 or x 2), with the total;
  - a worked scenario's cards and hints;
  - F4's and F6's ungraded "Do it yourself" card;
  - the folded step list.
- The step list ticks a step only when `progress` says it passed. It marks a step left unpassed as "skipped" and says "n of N steps passed".
- The note's folding is kept per viewer (`fsl-lesson-note`). The step shown is kept in `fsl-lesson-step-<id>-<lesson>`, which the main and session pages read for "step n/N".

Progress itself belongs to the session and is kept per unit (`Session.lesson_steps[<lesson>][<step>]`, migrations 0020 and 0027).

- Per step it records `reached`, `passed`, `skipped` (times) and `hint` (the level shown).
- It is reported for the session's current unit as `progress` in `GET /api/sessions/<id>/` and in every step and hint response.
- A step's record also carries what the step has earned: `command` once the step is reached, `ok` (the line said on a pass, `{en, ko}`) once it is passed, and in a worked scenario `answer` once its hint level reaches 3 (`lesson.ANSWER`).
- `POST /api/sessions/<id>/lesson/steps/<step>/ {state: reached|skipped}` records a step as reached or left unpassed. Reaching a step whose check names a Kali case gives the step a marker and writes that marker to the stamp proxy's `/var/lib/session/active`.
- The console sends `skipped` on Next or a list jump from a step not passed. It never sends it on Back or a pass.
- A pass is said on the passed step. The next step opens on a clean card.

The steps are declared in the unit (`steps` of a foundation or a worked scenario in `scenario.yaml`). A step has:

- an `id`;
- a `check` whose `kind` is one of `click`, `answer`, `choice`, `rules`, `sent`, `kali`, `loot`, `triage`, `waf_changed` or `replay` (`wargames.CHECK_KINDS`, validated at discovery);
- a `point`;
- a terminal `command` when the learner types one. `wargames.lesson` fills `{waf_rules}`, `{waf_reload}` and `{sudo}` in it from the declared WAF layout (`settings.FSL_WAF`).

A foundation step has no Kibana `query`.

The session API shows only what the browser needs.

- It shows a check's `kind` only, plus `form`, `options` (for `form: order`, every non-switch host on the learner map), the step's own `match` or the `match` of the step it is `about`, and `solo` on a foundation's last step.
- No `accept` list or answer rule reaches the browser.
- A step's `command` is in the payload only once `progress` records the step as reached. It is text to type, with no button that runs or copies it.
- The pass lines (`<text>.ok.<step>`) and a worked scenario's answers sit in a `{% comment %}` section at the end of `strings.html`, which Django never renders. `console/strings.py` reads them, and the step's `progress` record carries them once earned.
- Each step is advanced by its check. Back and Next stay as the way around one.

How each check kind passes:

- `answer` and `choice` pass when the text given equals an accepted value, ignoring case and spaces (`lesson.answered`).
  - `form: order` compares the hosts in the order given, split on spaces, commas, `>` and `→`. When the hosts are right and the order is not, it says `<text>.wrong.<step>.order`.
  - A `wrong_if` rule whose `match` fits the answer says `<text>.wrong.<step>.<says>`.
  - A value listed in `known` gets its own `<text>.wrong.<step>.<value>`.
  - The accepted values are the `accept` list, or they are read `of:` the session's records ("Foundations F1-F6").
  - `of: rule` (`wargames.ANSWERS_OF`) takes the `path` of the request with `marker: browse` for the learner's own request, or `marker: step:<id>` for a Kali step's run. It may be narrowed to a rule `family`. The platform ingests the last 600 s, takes the session's ModSecurity detections of that request or run, drops the CRS totals (rule ids starting 949, 959 or 980) and accepts each remaining `ruleId` (`lesson.rules_named`). With nothing recorded, the reason is `lesson.check.unrecorded`.
- `rules` passes once the sensor's file (`GET /api/rules/`) holds a sid that the posture's rule file does not hold, or holds with other text (`lesson.added_rules`, `suppress.sids`). It answers `added`. `needs: nocase` also wants that rule to carry `nocase` or a pcre with the `i` flag (`lesson.ignores_case`).
- `triage` (`judged: customer | attack | all`) passes on the learner's right verdicts ("Scenarios").
- `waf_changed` (`removed_target`) passes once no exclusion in the WAF's file targets that variable, while the posture declared one.
- `replay` passes once, after the step named `after` passed, when both of these hold:
  - an attack (a `sent` regex, or a `kali` case) meets its `expect`: an alert from one of the learner's added sids, or the run blocked (949110 among its detections) with no loot credited;
  - a benign request after the same time meets its own `expect`: its `status_class`, no added sid alerting, or no WAF record.
  The reason names the half that is missing (`lesson.check.replay_attack`, `lesson.check.replay_benign`).
- `click` passes as soon as the check is called. The platform tests no condition.

The platform judges every check, with `POST /api/sessions/<id>/lesson/steps/<step>/check/`.

- The body is `{answer}` for an answer, a choice or a pasted table, or `{poll: true}` for a background poll.
- The call records `passed` and answers `{passed, reason, hint, hints, progress}`. A `rules` check adds `added`, a `kali` or `replay` check adds `kali`, and a `loot` check adds `loot`.
- `reason` is a `strings.html` key with its values.
- A failed check that is not a poll counts as wrong. Two wrong checks raise the step's hint level and record the hint. In a worked scenario they offer the scenario's next hint instead (`scenario_run.stuck`).

Checks run by themselves.

- `sent`, `triage`, `kali`, `replay` and `waf_changed` are polled silently every 5 s while their step is shown, the tab is visible and the session is open. The page re-reads the session every 30 s to notice a close. A poll never writes the status line.
- `sent` also runs 1.5 s after the Website pane shows a path that matches the step's `match`.
- `rules` also runs when the rule editor applies a file.
- A pass says the step's `ok` line on the passed step, and 1.5 s later the note moves to the next step.
- The step after a Kali step shows that step's row: the case's name and "Open Kibana at this run's time". The link opens the run's window with an empty query. It shows no request count and no sensor name. A poll of the Kali check reads the row again after a reload.
- On the last step, a foundation says "Lesson complete. Next lesson: <title>" and moves on ("One session, F1 to F6"). After F6, the card lists the lessons taken and a button closes the session. A worked scenario says "Lesson complete".
- A wrong answer says what is wrong.
- A recent ingest (`within`) reads the newest records of the window first and records no truncation, because one sqlmap case leaves more than 5000.

Each step offers help in a fixed order. The next level opens when the learner presses "Show a hint", or after two wrong answers or failed checks.

- In a foundation the rungs are the nudge (`<text>.nudge.<step>`, where to look), then the hint (`<text>.hint.<step>`, how to read it, never the answer), then Skip (`lesson.SKIP_OFFERED_IN_FOUNDATIONS`, 3).
- A worked scenario keeps its answer rung before Skip (`lesson.ANSWER`, `lesson.SKIP_OFFERED`).
- Each press is `POST /api/sessions/<id>/lesson/hints/ {step, level: "hint"}`. It raises the step's `hint` level. The first press is recorded in `Session.hints` with its unit (`{lesson, step, level}`; migrations 0017 and 0027). It answers 400 for a session that is not guided, or for a step or level the unit does not have, and 409 when the session is closed.
- After 60 s on a step, the button only changes to "Show the new hint". Nothing is recorded until the learner presses it.
- A foundation's last step is solo: no highlight, no nudge, no hint, and Skip from the start.
- Skip is `POST /api/sessions/<id>/lesson/steps/<step>/ {state: skipped}`, and the next step is reached. On the last step, Skip records the skip. In a foundation it then moves to the next unit as a pass does. In a worked scenario it closes the step.
- Nothing is entered, fired, applied or credited for the learner. A later step that reads a skipped step's record therefore stays unanswered until the learner does that step or skips it too. Examples are an answer about a request never sent, or the loot of a run never made.
- `result.scenario.helped` (`["hint"]` or none) puts "hints used" beside PASS or FAIL on the main page and the closed session's page.

Each lesson opens on the pane that its first step names (`opens`). The console code names no lesson step and no CSS selector. Where a step points is its `point` in `scenario.yaml`: one locator, plus `opens`, the pane it needs. The highlight that shows it is called the coach.

The locators are:

- `panel`: a console element, such as the site's address bar, the rule editor or the objectives total.
- `map`: a `node`, `link`, `label: [host, switch]` or `zone`, which the server resolves from `{switch:<host>}`.
  - `deploy/gns3/auditor.html` answers `{locate}` by `postMessage`. The answer holds the rectangle, every zone drawing's rectangle (`zones`) and the boxes of the nodes, interface labels and zone captions (`text`, so that callouts stay off them).
  - The page refits on `{fit}`. It posts `{map: "drawn"}` after its first fit and `{map: "fitted"}` after each later one.
- `site`: a selector inside the cross-origin site frame, answered by the script nginx injects.
- `dev`: a `data-coach` name in the developer tools, such as the toggle, the matching row, a tab or a line.
- `kibana`: a target in the same-origin Kibana frame. The forms are:
  - `query`;
  - `hits`, with `discoverNoResults` as its fallback (its own stage callout);
  - `doc: <field>`, a field's row in the document flyout, brought into view through the flyout's field filter;
  - `sidebar: <field>`.
  On a step whose check names a `leg`, the coach rings the expand toggle of the row on that leg and the flyout's arrow while the other event is open. The row on a leg is the one whose source is another row's destination, or the reverse. When that row cannot be found, or the open document's position is unknown, the coach rings the field filter and never a value. `keep: true` on the point leaves the flyout open on arrival.
- `term`: `{pane: kali | waf, match}`, the row of the xterm buffer that matches. An optional `done` pattern, once printed after the last typed command, moves the ring to the step's check button.

A two-phase point holds the first target `until: sent` and then points at `then` (the select, then the payload line).

How the highlight draws:

- It dims the pane alone (`pointer-events: none`). It rings the target in the primary colour and puts a one-line callout beside it (`<text>.callout.<step>`, and `.callout.<step>.then` for the second phase).
- The callout is flipped or shifted inside the pane. It never covers the target, the rail, the bars or the note. It also never covers the text and controls that the site frame or the Kibana frame report around the target (Kibana's leaf text and controls within 220 px of the ring, skipping what the document flyout covers).
- With no one-line spot free, it wraps to two or three lines.
- A flyout step (the next-event arrow) looks inside the flyout first.
- A target in the note card gets its callout in the pane beside the card.
- The leader line crosses no text. It is left out when the callout is within 48 px of the ring.
- The hint says "Look at the highlighted spot." when the step has a locator.
- While the step's pane is not shown, the step card shows the "Open <pane>" button (`lesson.open.<pane>`), ringed with its own callout (`lesson.open.callout`; none on the last step).
- With no target for about 2 s, the card says where to look (`lesson.coach.missing`).
- The map refits when its pane's size differs from the size it was last fitted at (a pane open or a resize). A step change or a lesson's last step alone does not redraw it.

`test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console` holds every `point` of every foundation and stepped scenario to the console as rendered.

The rule editor (`#lesson-rules`, ruling D3) sits in the blue console's IDS rules pane, which `rulesPane()` shows for a scenario of class `detection` or `unknown`.

- It reads `GET /api/rules/?session=<id>`.
- It checks with `POST /api/rules/validate/` and writes with `POST /api/rules/apply/` on the version it loaded.
- Check rules answers `errors`: the lines carrying Suricata's `Error` from every sensor that refused. `output` is the refusing sensor's output with the most of them.
- The OPNsense edge's Suricata logs to syslog only (its template has no console output), so its `-T` output carries no error line. The wargame host's estate sensor prints them.

### Foundations F1-F6

The design is phase P2 of `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`. It was rebuilt on 2026-10-18 as attack and defence lessons (`docs/DECISIONS.md`, "Foundations rebuilt as integrated attack and defence lessons").

The board's `scenario.yaml` declares a `foundations:` list. Discovery checks it: ids must be unique across the foundations and the scenarios (`wargames.checked_groups`). The foundations are the taught units. The worked scenarios 1.1 and 3.1 run their steps on the same engine.

- `wargames.foundations()` lists the foundations by `order`.
- `wargames.lesson(lesson_id=...)` finds a foundation or a scenario with steps, refuses any other id, and marks a foundation `group: foundations`.
- `GET /api/wargames/` lists `foundations` (`wargames._foundation_card`). Each card has `id`, `order`, the `title` and `goal` string keys, `minutes`, `level`, `defense`, `prerequisites`, the step count, `step_ids`, and `learns` (the string key of what the unit teaches).
- The main page lists the foundations first, as lessons, with minutes, what each teaches and a Start button (a guided open of that unit).
- Every unit seeds `board-normal-search` at open. The seed is a benign case and counts in the second score (`views._replayed` keeps a benign `meta.seed` case). A closed course therefore has a true negative, and `no_benign` and `no_marker` are not shown in a lesson session.

Each unit below lists its defense and opening pane, what the learner does, and where the answers are read from.

**f1 Reading the network map** (`lesson.map`). Defense `full`, opens on Map.

- The learner reads board.com's Services address and board-db's subnet, and names kali's network. They pick in order the hosts a customer's search passes, and name the host that collects the logs. The solo step asks for board-db's address.
- Answers are read from the session's learner map (`views._range_fact`: `topology.address`, `topology.subnet`, `topology.zone_names`, `topology.route` and `topology.hosts`, through `topology.learner`):
  - `address`: the link-label addresses, with or without the prefix length;
  - `subnet`: the zone's subnet;
  - `zone_of`: the zone caption in both languages;
  - `path`: `customers`, then the transit roles present, then the site (`customers > firewall > waf > board.com` on OpenStack, `customers > waf > board.com` on Docker);
  - `logs`: the `log-server` node.

**f2 Reading HTTP requests in DevTools** (`lesson.http`). Defense `full`, opens on Website.

- The learner searches with the board's search box. They read method, parameter, path and status in the Network panel, then the parameter behind the board's sort control. The solo step asks for the status of a post that does not exist.
- Answers are read from the learner's own Website pane records: `method`, `parameter`, `path` (a `wrong_if` says when the answer carries the host or the query) and `status`.

**f3 Finding your requests in Kibana** (`lesson.logs`). Defense `full`, opens on Website.

- The learner searches a word of letters and digits and writes KQL for it. They then read:
  - the source IP of the event arriving at board.com, and the map host that uses it;
  - the source IP of the same search arriving at waf, and its X-Forwarded-For;
  - whether the WAF logged it.
  The solo step asks how many of their searches arrived at waf.
- Answers are read from the sensors' http events of the record (`sensor_source`, `forwarded_for`), split by leg.
  - A leg is `upstream` when `dest_ip` is one of board.com's addresses (waf sends it on). Otherwise it is `inbound` (the request arrives at waf). A sensor that sees both legs therefore counts each search once.
  - `host_of` gives the map host with that address.
  - `waf_logged` comes from the WAF's own records.
  - `hits` is one count of the learner's own searches: the inbound events with the browse marker under `/search/` since the unit (or the session) started.

**f4 Blocking an XSS request and writing an IDS rule** (`lesson.xss`). Defense `xss-gap`, opens on Website.

- The learner sends `<script>alert(1)</script>` and reads the status, one detecting rule and the Total Score. They read the status of the mixed-case probe, and say whether either drew an IDS alert. They write a rule for `<script` in the URI, read its sid from its alert, see the mixed case slip past, and add `nocase`. The solo step replays the mixed case and an ordinary search.
- Answers are read from:
  - `status`;
  - `rule`: the ModSecurity rule ids of the request, 949110 excluded;
  - `anomaly_total`: 949110's `Total Score: N`;
  - `alerted`, `alerted_sid`, `alerted_sid_present`: the Suricata alerts in the record's window, against `lesson.added_rules`;
  - `rules` with `needs: nocase`;
  - `replay`.

**f5 Analysing SQL injection on the sort parameter** (`lesson.sqli`). Defense `full`, opens on Website.

- The learner reads the sort value. They add `)` in the address bar and read the status, then say whether a WAF rule detected it. They type sqlmap in the Kali pane and read its verdict, the run's source IP and the rule that named the scanner. They rerun with `--random-agent`. The solo step asks for the one rule that still blocked the rerun.
- Answers are read from:
  - `param_value` and `status`;
  - `waf_detected`: the ModSecurity detections of the request. A 500 is logged with no rule, which is no detection;
  - `sqlmap_found`: `attacker.sqlmap_found` reads `<home>/.local/share/sqlmap/output/<host>/log` on the box and looks for a `Parameter:` line;
  - `kali_source`: the run's ModSecurity `src_ip`;
  - `rule` with `marker: step:<id>` and `family: "913"` (the scanner), then with `family: "942"` and `known: [949110, 913100]` (the SQL injection rule that still blocked the rerun).

**f6 Finding the attack an over-broad exception let through** (`lesson.miss`). Defense `overbroad`, opens on WAF.

- The learner greps the exclusion file for the parameter that was left out. They dump the accounts with sqlmap and paste the table. They say which engines alerted, and how many WAF log records of the run have status 500. They say the penalty the admin objective would carry if detected. They delete the exception and reload nginx. The solo step replays the dump and sorts once.
- Answers are read from:
  - `excluded_target`: the WAF file in force (`ARGS:sort` or `sort`);
  - `loot`: against the session's snapshot;
  - `alerted_by`: none, IDS only, WAF only, or both, from the run's detections;
  - `run_errors`: the count of the WAF (ModSecurity) log records with status 500 in the window Kibana opens on. It is the number that `log_source : modsecurity and status : 500` shows (`lesson.server_errors`);
  - `detected_penalty` with `objective:`: the objective's difficulty x 1, the penalty it would carry if detected. The tier is read from `wargames.objectives`, and the value is empty when the scenario is not judged;
  - `waf_changed`;
  - `replay`: the run blocked with no loot, and an ordinary sort 2xx with no WAF record.

The postures `xss-gap` and `overbroad`:

- `xss-gap` is CRS paranoia level 1 with `no-xss.rules` (`local.rules` without sid 9000003).
- `overbroad` is level 1 with `no-uri-sqli.rules` and one exclusion, `{tag: OWASP_CRS, target: "ARGS:sort"}`. In the WAF file this is `SecAction "id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:sort"`, so every CRS rule skips `sort`.

F6's sqlmap command carries `--skip-waf`. Without it, sqlmap's own WAF-detection request would trip IDS 9000003 and 9000004 and one CRS rule, and the run would count as detected. No unit question carries an `accept` list.

One session, F1 to F6. `POST /api/sessions/<id>/lesson/ {"lesson": "<id>"}` moves an open guided session to any foundation in place. It does the following:

- When that unit's declared defense differs from `Session.defense`, it writes the unit's CRS tuning (`crs.apply`, as `PUT /waf/` does). It seeds the sensors only when the posture's rule file changes.
- It sets `Session.lesson` and `Session.defense`.
- It appends `{id, started_at}` to `Session.lessons` (migration 0027). A foundation open writes the first entry.
- It clears the stamp proxy's label.
- It replays the unit's `cases` as an open does.
- It answers the session detail.

It refuses a closed session, a scenario session and an unguided one with 409. It refuses an id that is not a foundation with 400.

The detail carries:

- `lessons`;
- `next_lesson` (`{id, text}` of the next foundation by `order`, or null);
- `course` (`[{id, steps, passed, skipped, hints}]` for every unit taken).

The console offers only the next unit.

- When a foundation's last step passes or is skipped, the card says "Lesson complete. Next lesson: <title>" with a "Next lesson" button. 2 s later the console posts the switch and reloads the page into the new unit.
- After F6, the card lists the lessons taken. Its button ingests, closes the session through `POST /close/` and opens the session page. That page's course card lists each lesson's steps passed and skipped, and labels each Kali run "Lesson n · step m".
- Restarting starts the first lesson with its own defense.

Nothing is reset between units. The board allows this, because its objective layer is exfiltration only (loot matched against the snapshot taken at open). A unit therefore leaves the ground truth as it found it. F4 and F6 change the posture in place, and F5 returns it to `full`.

A unit judges only what happened since it started (`views._lesson_started`, the last `Session.lessons` entry once there is more than one).

- A `sent` check counts only Website pane requests made after the start.
- The `rule` answer counts only ModSecurity records after the start.
- A `kali` check reads the sensor from the later of the step's `reached` and the unit's start.
- `lost_points` counts only objectives achieved after the start.
- The Kibana links open from the start.
- Step records belong to the unit, so F3's `search` is not passed by F2's.

Three check kinds follow the learner's own actions.

- `sent` passes when the session's Website pane kept a request whose decoded path and query match the step's `match` regular expression.
- `kali` names a tool case of the case file.
  - Reaching the step gives it a marker. The platform writes the marker to the stamp proxy's `/var/lib/session/active` (cleared on a lesson switch and at close). What the learner types in the Kali pane therefore goes out marked, through Kali's `http_proxy`.
  - The step's `command` is plain text to type.
  - The check passes when the sensor's http records carry the marker and the tool's user agent (any user agent with `ua: any`, for `--random-agent`).
  - It then records the run as an ordinary malicious case (`meta.kali` and `meta.lesson`, no replay mark). The case counts in both scores like any other red action. It then ingests the session.
  - A learner who unsets `http_proxy` sends unmarked requests, and the step does not pass.
- `loot` takes the pasted table (`tools.dumped`, or `name:hash` and `| name | hash |` lines). It credits the table as `POST /loot/` does, attributed to the kali case. `_credit_loot` keeps the matched accounts on the case it was attributed to (`meta.loot`).

An answer reads one of these facts. `wargames.read_from_record` refuses anything else at discovery.

- `of:` a range fact: `address`, `subnet`, `zone_of`, `path`, `logs`, `host_of`, `excluded_target`, `lost_points`, `detected_penalty`.
- `of:` a request fact, `about:` a step that has a `match` (or with its own `match`, taking the latest Website pane record that matches it): `status`, `method`, `path`, `parameter`, `param_value`, `sensor_source`, `forwarded_for`, `waf_logged`, `waf_detected`, `anomaly_total`, `alerted`, `alerted_sid`, `alerted_sid_present`, `hits`.
- `of:` a Kali fact, `about:` a `kali` step: `sqlmap_found`, `kali_source`, `alerted_by`, `run_errors`.
- `rule`, with the request's `path` or a `step:` marker (above).

## How the scores are computed

**Objectives.** The board is a `loot_verified` target.

- `wargames/board/objectives.yaml` names the secret: the `auth_user` username and password columns, read from `/internal/auth-users`.
- It declares three tiers, by how much of the secret the attacker holds: any one hash (difficulty 2), the `admin` account's hash (4), and every account's hash (5).
- The attacker exfiltrates hashes and submits them with `POST /api/sessions/<id>/loot/`, from the red console's loot panel. The panel is shown only for `loot_verified` scenarios.
- The platform credits a tier only for submitted `(username, hash)` pairs that match the session's start-of-session snapshot exactly, and only once the session has fired a malicious case.
- The platform never credits an objective from its own belief about what an attack did. The ground truth is the target's own records, which the detectors do not see.

A credited tier becomes an Objective row dated by the submission. The row has a window:

- If the submission names a malicious case (`case_id`), the window runs from 100 ms before that case started to 100 ms after it ended.
- Otherwise it runs from 2 minutes before the submission to 100 ms after.

The snapshot is taken once, when the session starts.

- On docker, a board session whose accounts cannot be read (or read empty) is refused with 503 and closed.
- On OpenStack, the session is still created, with no snapshot. `POST /api/sessions/<id>/loot/` answers 409 for it.
- Nothing reads the board afterwards. `GET /api/wargames/<id>/objectives/` lists the tiers from `objectives.yaml`. `GET /api/sessions/<id>/objectives/` reports the stored rows.
- `POST /api/sessions/<id>/objectives/` observes, and does nothing for a `loot_verified` wargame.

The corp wargame is an `effect_observed` target. It is scored from the rows the target commits to its own database, and the attacker submits nothing.

- `wargames/corp/objectives.yaml` declares the read channel (`estate://corp-db`, scope `wp_state`) and three tiers:
  - a rogue administrator (`rogue_admin`, difficulty 5);
  - the site opened to self-registration (`option_flip`, 4);
  - unauthorized content written (`content_write`, 3).
- At session start, the platform snapshots the existing admins, the watched `wp_options` and the published posts. It uses read-only `mysql` SELECTs against corp-db (`platform/api/effect.py`), run through `runner("corp-db")` and not over the network.
- On `POST /api/sessions/<id>/objectives/`, the platform reads corp-db's binary log with `mysqlbinlog`. It credits a tier for each committed change whose timestamp falls inside a malicious case's window. The changes are:
  - a `wp_usermeta` admin grant to a user not in the snapshot;
  - a `wp_options` change of `users_can_register` or `default_role`;
  - a new or overwritten `wp_posts` row.
- As with the board, the detectors do not see this read.

A taken objective goes to a malicious case whose run overlaps the objective's window. Among several, the case that started latest gets it.

- The objective counts as detected only if that case was detected.
- An objective that no case overlaps counts as undetected.
- Attribution is by time only. Scoring does not read a case's `takes:` field.

In the score's `objectives` block:

- `coverage` is detected difficulty over total difficulty. It is `null` when nothing was taken.
- `false_positives` is FP.
- `damage` is undetected difficulty plus half of detected difficulty. This is how an undetected loss counts double.

**Detection.** A case is matched to alerts by one of two strategies, declared per case:

- `marker`: the alert carries the case's `X-Request-ID` value.
- `window`: the alert's source address matches the case's, and its time falls within the case's start and end, with two seconds of slack on each side.

There is no fallback from one to the other. A marker case whose marker was lost should show up as a miss and not be covered by the window. Terminal cases carry both a marker and a window.

- `?correlation=marker` or `?correlation=window` on the score endpoint forces a strategy. Any other value is a 400.
- No console page passes it (`session.html` requests `/score/` without it).
- To compare the two, call the endpoint once per strategy. A disagreement says something about the scoring method and not about the defence.

Each `per_case` entry carries `expect` and `corroborated`.

- `expect` is a substring that a signature of the case should match.
- `corroborated` is true when `expect` appears, ignoring case, in the signature of some matched alert. A signature that also matched a benign case in the same session does not count.
- `corroborated` is `null` when the case has no `expect`. This is always so for window cases recorded through `POST /api/sessions/<id>/cases/`, which carry none.
- A detected case that is not corroborated adds `score.warning.wrong_reason`.

A case's `expect` is stored with the case when it is fired. Editing the case file therefore does not re-judge a finished session. Rows recorded before migration 0009 have no stored `expect` and are still judged against the current case file. Alert severity and rule type are not used.

**The game.** The score's `game` block is `{"revealed": false}` until the session closes. Then it carries four components, their weights and a balance:

- speed (0.25): per malicious case, 1 if its first matched alert came within 10 s of its start, and 0 at 120 s or later, linear in between. The cases are averaged.
- accuracy (0.30): recall minus false-positive rate, floored at 0.
- coverage (0.20): the attack stages (`platform/lifecycle.py`) with a detected malicious case, over the stages attacked. It is 0 when none was attacked. It is not the `objectives` block's `coverage`.
- response (0.25): the share of malicious cases blocked minus the share of benign cases blocked.
  - It is `null`, and the other weights are renormalised, until some case has `meta["blocked"]`.
  - Scheduled attacks set it (a 403, or sqlmap's own not-injectable conclusion), and so do a lesson's seed replays (a 403). Other fired cases leave it unset.

`attacker` is the difficulty of the taken objectives, halved when detected. It is the same sum as `damage`. `defender` is the weighted mean of the components times the difficulty taken, minus 1 per FP. `balance` is `defender - attacker`. When nothing is taken, the balance is minus FP. The weights and dwell times are v1 defaults (`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

**Customers.** The score's `customers` block counts the customer requests that the session recorded (see "Customer traffic"):

- `sent`;
- `served` (2xx and 3xx);
- `blocked` (403, except Django's own CSRF refusal, which the generator marks `refused_by: "app"`);
- `unanswered` (no answer within 10 s, status 0);
- `other` (any other 4xx or 5xx);
- `alerted` (customer requests whose marker some alert carries);
- `blocked_actions`.

Each request counts once. A customer request is not a case, so the `per_case` list and TP/FP/FN/TN are unchanged. An alert that a customer request drew is not counted in `unattributed`. The console's second score says "Customer requests blocked: N of M" beside the case sentences.

The score endpoint is read-only and keeps no history.

## Customer traffic

A board session can carry its customers: Korean community users who browse, search, sign in and comment for the whole session.

The mix is declared in `wargames/board/traffic.yaml`: users, origin weights, the seeded accounts, posts 1-3, browser User-Agents, search terms, comment texts, and profiles of action weights.

`platform/traffic.py` renders it into:

- twelve personas allocated to origins by the declared weights (largest remainder), each with its own source address, browser and language;
- 2,000 flows of steps that the box cycles through.

Sign-in and comments are form posts. The flow first GETs the page. The box takes `csrfmiddlewaretoken` from it, sends it with the `csrftoken` cookie, and follows the 302. A flow whose page carried no token (the GET was blocked) stops there, as a browser would.

`deploy/traffic/users.py` is the generator.

- It uses Python's standard library only.
- It is paced to the plan's rate across threads.
- It puts one fresh UUID in `X-Request-ID` per request. This has the same shape as a case's marker, so a learner cannot tell a customer from an attack by it.
- It writes one JSON line per request to `records.jsonl`.
- It re-reads the plan when the file changes, and stops when the file is removed or on SIGTERM.

| | Docker | OpenStack |
|---|---|---|
| Where it runs | `fsl-<id>-users`, a container from the Kali image started by `Docker.users_box` on the personas' origin networks, labelled `fsl.customers=<id>`. It is not a compose service | the slot's `fsl-kali` VM, as the system account `fsl-users` |
| Source address | the container's own address on each origin network | each persona is bound to one of the VM's origin addresses |
| Kept apart from the attacker | the declared default origin is not used, and the container's addresses are its own | the default origin is not used. Neither is any origin's `source_ip` the attacker wears, nor the VM's unbound source (`ip route get` to the target). `POSTROUTING -m owner --uid-owner fsl-users -j RETURN` is inserted before the `ORIGIN-SNAT` SNAT jump, so the attacker's origin rewrite never applies to customers |

`platform/attacker.py` holds every command run on the box:

- `place_customers`: the account, the NAT exemption and the program, through `sudo` on OpenStack;
- `run_customers`: writes the plan, and starts the program with `setsid` and `setpriv` if it is not running;
- `stop_customers`;
- `customer_records`.

The platform ships the program at each start. It is not baked into the Kali image, because the VM is rebuilt from its golden image at every close. A file under `deploy/kali/` would change that image's digest and stop the next rebuild until the image was rebuilt.

The API is in `platform/api/customers.py` and `views.session_traffic`:

- `PUT /api/sessions/<id>/traffic/ {rate, profile}` starts the customers, or changes a running generator's rate and profile (same personas).
  - `rate` is requests per second, default 1, at most 50.
  - `profile` is one of the wargame's declared profiles. On the board these are `community` (default), `plain` (no unusual searches), `readers` (`plain` without comments) and `club` (`community` plus code questions in comments).
  - It answers 404 for a wargame with no `traffic.yaml`, 409 for a closed session, and 503 when the box or the origins are not there.
- `GET` reads the new records first. It then returns:
  - `declared`, `profiles`, `running`, `rate`, `profile`, `started_at`, `stopped_at`, `error`;
  - the counts `sent`, `served`, `blocked` (403 from the defence, not the app), `unanswered` and `other`;
  - `sources` (origin, address, requests);
  - `by_action` (sent and blocked per action).
- `DELETE` stops the generator and reads what it sent last. Closing the session does the same before the slot is rebuilt. If the box is unreachable, the close goes on and the error is kept in `traffic.error`.

The platform pulls the records by byte offset (`tail -c`, at most 1 MiB a call, whole lines only) into `CustomerRequest` rows, with one `bulk_create` per call. The offset lives in `Session.traffic`.

The session page offers the traffic switch only with `?traffic` in its URL, for testing. A scenario starts the traffic itself.

The generator tells the board's own CSRF refusal (`refused_by: "app"`, not counted as blocked) by Django's failure page, `<span>(403)</span></h1>`, as well as by its English sentence. The board answers in the customer's language, and a Korean customer's refusal is in Korean. Such a refusal happens when two flows of one persona race the token rotation at sign-in.

## Scenarios

A scenario is a timed exercise on the range. Customers and an attacker use the board while the learner defends with the real tools, and the platform judges the result over a final verification window.

The design is phase P4 of `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`. The rulings are the 2026-10-13 "scenario course" entries in `docs/DECISIONS.md`.

**Descriptor.** `scenarios:` in a wargame's `scenario.yaml` holds the descriptors. `wargames.checked_scenarios` validates them.

| Field | Meaning |
|---|---|
| `id`, `order` | `1.1`, `2.1`, ... Ids share one namespace with the foundations |
| `task_class` | `judgement`, `availability`, `detection` or `unknown` |
| `guidance` | `worked` (may declare `steps`, which run on the step engine), `faded` or `none` |
| `text`, `briefing` | `text` is the strings prefix. `briefing` maps `situation`, `goal` and `measured_by` to string keys |
| `minutes`, `window_minutes` | the scenario's length and its final verification window |
| `defense` | a posture from the wargame's `defense:` map (CRS level, exclusions, thresholds, and the Suricata ruleset) |
| `traffic` | `{profile, rate}` for the customers (`traffic.yaml`) |
| `red` | `schedule` (the default) or `person`. With `person`, a person uses the red console and the scenario may declare no attacks |
| `attacks` | `[{at, case, origin}]`: seconds after open (within `minutes`), a malicious case, and an optional origin. Hidden from the learner |
| `completion` | per class. Judgement: `{judged: all}`, optionally `pattern: judged`. Availability: `{served: all, held: all}`, optionally `thresholds: {inbound, outbound}`. Unknown: `{served: all, held: all}`. Detection: `{detected_by: suricata}` |
| `cards` | `[{id, when}]`, where `when` is one of `start`, `alert`, `blocked`, `window` |
| `hints` | hint ids, offered one at a time |

`GET /api/wargames/` lists each scenario's card (`wargames.scenario_card`) without `attacks`. `GET /api/sessions/<id>/` drops `attacks` and `completion` from a worked scenario's `lesson` and empties its `cases`.

**Opening.** `POST /api/sessions/ {"scenario": "2.1"}` does the following:

1. It resolves the wargame from the scenario id.
2. It refuses `lesson`, `guidance` and `defense`.
3. It takes the declared posture, as any session does.
4. `scenario_run.begin` starts the customers and writes `Session.scenario_state` (migration 0025, beside `Session.course_scenario`). The state holds the schedule with each attack's absolute due time, the windows, the verdicts, the hint offer and the WAF versions seen.

A worked scenario sets `guidance` true and `lesson` to its id. Its steps then run on `/lesson/steps/` without seeding replays. Customers that cannot start close the session with 503.

**The engine** is `platform/api/scenario_run.py`, with the pure rules in `platform/scenarios.py`. It is one thread in the platform process. It starts on the first scenario and at boot, from `fsl/wsgi.py` (`resume` marks an attack that was interrupted while firing as due again). A failure of a tick, or of the connection cleanup after it, is logged on its own and does not end the thread.

Every `FSL_SCENARIO_TICK` (2 s), for each open scenario session, the engine does the following.

- It opens the window at its scheduled time (`minutes - window_minutes` after open) if the learner has not.
- It claims each due attack and fires it on a pool of four through `views._fire`, marked `meta.scheduled`. This is not a replay mark, so the attack counts in both scores.
  - A sqlmap dump goes through `views._credit_loot`, attributed to that case. The first score therefore counts a loss only when the board's own accounts match.
  - The entry keeps `outcome`, held or leaked.
  - The case keeps sqlmap's conclusion lines and its 403 count (`meta.conclusions`, `meta.forbidden`, not judged).
  - `meta.blocked` is set on a 403, or on sqlmap's own not-injectable conclusion after a clean exit with no dumped row (`tools.found_not_injectable`).
  - The sqlmap cases decline sqlmap's offer to crack the hashes (`--answers=crack=N`). The dumped cells are therefore the raw hashes that `loot.matched` compares.
- Every `FSL_SCENARIO_OBSERVE` (15 s), it pulls the customers' records and ingests the last 180 s.
- Every `FSL_SCENARIO_WAF_POLL` (20 s), it reads the WAF file to notice a change made in the terminal.
- It judges an open window once the window has ended and every attack due inside it has fired or failed.

Closing cancels the attacks still due. An attack already firing finishes and is recorded.

**The final verification window.** `POST .../scenario/verify-window/` ("Start final check") or the schedule opens the window for `window_minutes`. The engine adds one entry inside it for every attack case the schedule names that is not already due there.

The window judges the class's `completion`:

- `served`: no customer request was blocked by the defence within the window (a 403, not the app's).
- `held`: every attack inside the window fired and was held (no loot match, no effect).
- `judged`: every item listed when the window opened was judged right. The list is kept with the window. Verdicts given during the window count. An item that reaches the records later with an earlier time is not added.
- `detected_by`: every attack inside the window drew a corroborated Suricata alert, and no customer request did.
- `thresholds`: the CRS anomaly thresholds in force at the window's WAF snapshot are at most the ones named. A tuning without thresholds runs at the CRS defaults, 5 inbound and 4 outbound.

Other rules of the window:

- With `red: person`, the window also judges, like scheduled ones, the malicious cases the person fired inside it that are not replays.
- A judgement scenario is judged on its verdicts alone, as the design's class table says. Customers blocked during its window are reported beside the result and not counted against it.
- The result names the fix (`lesson.fix_class` on the WAF snapshot taken then: `level`, `threshold`, `rule`, `target`, `path_target`; see "Sessions, WAF tuning and the step engine").
- A failed window can be followed by another.

**Judging alerts** (`GET/POST /api/sessions/<id>/triage/`). The learner judges alerts one item at a time.

- There is one item per marker that drew alerts: each customer request, and each attack case however many requests it sent (one case is one decision).
- The item id is a hash of the marker with the session's browse marker, so it cannot be matched to `/cases/`.
- An item shows the first and last alert, the alert count, source addresses, one request, the WAF verdict (`blocked` when a 949/959 total fired, `logged` or `none`), the status, and up to 12 rules with engine, id, message and count. It never shows the case name or a label.
- Replays and the learner's own Website pane requests are left out.
- A verdict is `{item, verdict: attack|customer, succeeded}`. The platform judges `verdict` against the record (a case's `malicious`, or a customer row), and `succeeded` against the target (loot matched on the case, or an objective in its window).
- A scenario whose completion has `pattern: judged` also asks an attack's `pattern`. This is one of the CAPEC ids of the case file's malicious cases, listed in the scenario card's `patterns`. The platform judges it against the case's own `pattern`. It is kept with the verdict and never shown on an item.
- The step check kind `triage` (`judged: customer | attack | all`) passes on the learner's right verdicts.

**Status, hints, debrief.** `GET .../scenario/` returns:

- the scenario card;
- `phase` (running, window, passed, failed, closed) and `time_left`;
- the last minute's blocked customers and alerted requests (`alerted_per_minute`: distinct markers that drew an alert, each customer request and each attack case once however many requests it sent);
- objectives lost, the window and the completion;
- the cards due and the hint offer.

A hint is offered (not recorded) when any of these happens:

- a step check fails twice;
- the same item is judged wrong twice;
- a `PUT /waf/` writes the file already in force;
- five minutes pass without a WAF change while customers are blocked.

`POST .../scenario/hints/` opens the next hint and records it in `Session.hints`.

`GET .../scenario/debrief/` answers 409 until a window is judged or the session closes, so the schedule stays hidden. Then it returns these parts, in the Igloo/ASEC report order:

- `overview`: the last final check's verdict, its fix class and reasons, the number of checks judged, steps passed of the total, and the hints used;
- `evidence`: at most 20 of the session's own detections from the scheduled attacks, from the completion's detector when it names one, with rule, request and case. It makes no Elasticsearch read;
- `change`: the declared posture against the last WAF snapshot. It lists the exclusions added and removed, both levels, and a line diff of the exclusion file against what `crs.rendered` writes for the posture;
- `cases`: each scheduled case before and inside the judged windows, held or leaked;
- `risk`: a string key named by the fix class;
- `customers`;
- the attack `timeline`;
- `triage`;
- `at`, which carries the open and last-judged times for agents.

The console renders the debrief with `debrief_script.html` on the blue console and on the closed session's page.

**Console.** The home page lists the scenarios under each wargame. Start opens the blue console on the briefing.

- A strip above the panes shows the time left, customers blocked and alerted requests per minute, objectives lost, the hint offer and Start final check.
- A judgement scenario adds the Alerts pane. The pane keeps its list clear: the cards and the opened hints sit in the lesson note's column beside the pane, and the highlight's callout stays inside the pane.
- A detection or unknown scenario adds the IDS rules pane (the rule editor on `/api/rules/`).
- Cards appear when their moment comes. The debrief opens when the window is judged.
- A worked scenario's steps run on the note with its hint list empty. Its hints are the scenario's offer.

**On the board.** The board has eleven scenarios. The home page lists them by task class after the foundations (`order`). "Posture" is the defense the scenario starts from.

| Id | Title | Class, guidance | Posture | Customers | Attacks (hidden) |
|---|---|---|---|---|---|
| 1.1 | Telling customer requests from attacks | judgement, worked | `level2`: PL2 | `community` 2/s | sqlmap at 150 s (`ru`) |
| 1.2 | Judging alerts the WAF only logs | judgement, faded | `inherited`: PL2, 949110 and 959100 removed | `community` 2/s | sqlmap at 120 s, a search injection at 300 s (`ru`) |
| 1.3 | Telling attack types apart | judgement, none. It judges the pattern too | `inherited` | `community` 4/s | eight cases from 90 to 660 s, all from `kr`: sqlmap stock and tamper, search, union and sign-in injections, two XSS, path traversal |
| 2.1 | Fixing false positives on Korean search | availability, faded | `level3`: PL3 | `readers` 2/s | sqlmap at 240 s (`ru`) |
| 2.2 | Fixing false positives on tags and links | availability, faded | `level2` | `community` 2/s | sqlmap at 240 s (`ru`) |
| 2.3 | Lowering the anomaly threshold | availability, none. The final check runs at thresholds 5/4 | `untuned`: PL3, thresholds 10,000/10,000 | `plain` 2/s | sqlmap at 600 s (`ru`) |
| 3.1 | Fixing a detection rule | detection, worked | `broken-rule`: PL1, `broken-sort.rules` (sid 9000101 reads `http.request_body`) | `plain` 2/s | sqlmap at 120 s (`ru`) |
| 3.2 | Writing a rule for the sort attack | detection, faded | `ids`: PL1, `no-uri-sqli.rules` | `plain` 2/s | sqlmap at 120 s (`ru`) |
| 3.3 | Detecting a variant of an attack | detection, faded | `spelled`: PL1, `spaced-sort.rules` (SQL words between spaces) | `plain` 2/s | sqlmap at 120 s, the tamper variant at 300 s (`ru`) |
| 3.4 | Writing a rule for XSS in comments | detection, none | `full`: PL1, `local.rules` | `plain` 2/s | the comment XSS at 120 s, the search XSS at 240 s (`ru`) |
| 4.1 | Combined exercise | unknown, none (no cards, no hints) | `full` | `club` 2/s (adds code questions in comments) | `board-sqli-orderby-sqlmap-versioned` at 300 s, sqlmap at 600 s (`us`) |

Which CRS rules refuse the customers' requests:

- At PL3, rule 920272 and rule 942460 refuse a Korean search on `ARGS:q` (920272 also on `REQUEST_URI_RAW` once those are excluded). Rule 920272 on `REQUEST_HEADERS:Referer` refuses every page a customer opens after such a search. A Korean comment is refused by 920272 on `REQUEST_BODY` and 942460 on `ARGS:body`.
- At PL2, the `<b>` search is refused by 941320 and the YouTube link by 931130, both on `ARGS:q`.
- At PL1, the code questions in `club` profile comments are refused by 942100, 942190, 941100, 941110 and 941160 on `ARGS:body`.

Scenario 4.2 (a person on the red console against the learner) is not declared, because it needs a second person. The engine accepts `red: person`.

## Decisions

- **One case file per wargame**, with attacks and benign traffic together: `redteam/cases/board.yaml` for the board, `redteam/cases/corp.yaml` for corp. Separate files make it easy to forget the benign cases. The CLI reads `board.yaml` unless `--cases` names another file. It opens the session of the scenario whose `case_file` matches that file's basename (board for an unknown one).
- **The harness refuses to send a rewritten path.** `requests` turns `/static/../../etc/passwd` into `/etc/passwd`. Sending that would record an attack that never left, and would score the harness's failure as the defence's. Percent-encoding differences are allowed.
- **A tool that cannot start raises. A tool that exits non-zero counts.** sqlmap exits non-zero when it finds nothing, but its traffic went out.
- **Suricata shares the WAF's network namespace** (`network_mode: service:waf`) instead of using host networking, whose meaning varies with the Docker host. The WAF's interfaces carry both legs of every request.
- **Kibana is in compose, with full access** (not a read-only role). It reads the same Elasticsearch that the platform ingests from.
  - It is reached through the platform's port 8000 at `/kibana/`, where nginx in front of it refuses everything but Discover (below). An operator reaches it by an ssh tunnel to 127.0.0.1:5601 on the platform host's loopback. The blue console frames it.
  - **Bring-up import.** `platform/kibana.py` runs in the background at bring-up. It asks `/api/status` first and imports only once Kibana answers. It retries while Kibana cannot be reached or answers 502/503/504. It reports any other HTTP error once, with its status and body. A starting Kibana answers a multipart import with 415.
  - The import takes `deploy/kibana/objects.ndjson` with overwrite. It contains:
    - the data view `logs-*` on `@timestamp`. Its runtime fields fold each Suricata/ModSecurity pair into one column (`rule`, `rule_id`, `source_ip`, `destination`, `url`, `status`);
    - the "Alerts" search and the "Overview" dashboard. Their titles and the data view's `sourceFilters` name no platform.
  - `kibana.py` sets `defaultRoute` to that search. An existing data view is what keeps Kibana's Welcome screen away. It also drops `_index` from Kibana's `metaFields`.
  - **Per-session space.** When a session opens, `kibana.py` imports a data view of its own in a Kibana space of its own (`ensure_session_view`, which needs `KIBANA_URL`, set by `compose.yaml`).
    - The space and the data view share the id `soc-<pattern>`.
    - The space disables every feature but Discover (dashboards, visualize, dev tools and the rest).
    - Its settings turn ES|QL off (`enableESQL`, which reads every index past the view's pattern and hidden fields) and set `defaultColumns` to the session columns.
    - They set `defaultRoute` to the space's own saved search "Events" (the session columns, newest first). The learner therefore never reaches the operator objects, which stay in the default space.
  - **What nginx refuses.** Kibana runs without security, so nginx refuses what the features cannot switch off. `platform/nginx.conf`:
    - answers 403 to the Kibana APIs of Elasticsearch and Kibana administration. These are the console proxy, ingest pipelines, index management, snapshot and restore, transforms, rollups, remote clusters, license, upgrade assistant, index lifecycle, watcher, the data views API, the security API, the settings API, saved objects import and export, and the spaces API. The spaces API has two exceptions: `_active_space`, and a GET of `api/spaces/space`, which nginx answers with the one space;
    - refuses the Default space (`s/default/...`) and every path without a space prefix under `app`, `spaces`, `api` and `internal`;
    - redirects the pages `app/management`, `app/dev_tools`, `app/home`, `app/observability`, `app/security` and `app/kibana_overview` to Discover of the same space.
    Every call that Discover makes goes through. The platform's own setup (`KIBANA_URL`) reaches Kibana directly.
  - **What the learner sees.**
    - The space is named "SOC".
    - The data view is on the session's index pattern. It is shown by its name `logs-*` and never by the pattern.
    - It has the shared runtime fields plus these:
      - `log_source` (`suricata` or `modsecurity`);
      - `sensor`: the map name of the sensor, matched on the sender's host name without its domain and slot number, with or without its first dash-separated part. The script therefore names no `fsl` host, and the edge's `edge` still reads as its map name. The names are `firewall` and `board.com` on OpenStack, and `waf` on docker and for every ModSecurity record, with slot suffixes stripped;
      - `request_headers`: one `Name: value` per request header, `X-Request-ID` left out;
      - `request_header`: a composite with one keyword per common header (`request_header.host`, `.user_agent`, `.referer`, `.cookie`, `.x_forwarded_for`, and the rest of `kibana.REQUEST_HEADERS_SHOWN`). It comes from Suricata's `http.request_headers` or ModSecurity's `transaction.request.headers`.
    - `sourceFilters` hide `_index`, `event.*`, `log.*`, `message`, `agent.*`, `ecs.*`, `host`, `host.*`, `input.*`, `error.*`, `http.*`, `transaction.*`, `metadata.*`, `data_stream.*`, `flow_id`, `tx_id`, `pcap_cnt`, `in_iface`, `pkt_src`, `community_id`, `src_ip`, `dest_ip`, `alert.signature` and `alert.signature_id` (`kibana.HIDDEN_FIELDS`). KQL on them still works.
  - A refused import is logged and does not stop the session.
  - **Discover link.** `GET /api/sessions/<id>/` carries `discover`: an unsaved Discover state on that view, at `/kibana/s/<space>/app/discover`.
    - It starts at the current unit's start. Its columns are `event_type, source_ip, destination, url, status, rule_id, rule` (`kibana.SESSION_COLUMNS`, fixed widths). It has no filter, because Filebeat keeps the range hosts' own syslog lines out of the index.
    - A lesson opens it with an empty query. A scenario or a wargame opens it with the alert query.
    - While the space or view is not ready, or without `KIBANA_URL`, `discover` is null. It is never the shared operator view. The ELK pane then shows a preparing line and polls the session until the link arrives. The import is retried every 10 seconds.
    - The ELK pane opens the link. It is not the saved search with an overriding query, which Kibana badges "Unsaved changes".
  - Before the pane loads, the blue console marks Kibana's first-visit callouts as seen in the shared same-origin localStorage (`discover:docExplorerUpdateCalloutClosed`, `discover:docExplorerCalloutClosed`, `data.noDataPopover`).
- **Elasticsearch is a single node with a 512 MB heap**, so the whole stack fits in a default Docker memory allowance.
- **Missing data is an error, not a zero, with stated exceptions.**
  - An unreachable Elasticsearch or substrate, and an unreadable rule file, answer 503.
  - Session create on OpenStack tolerates an unreachable target. The session starts with no snapshot, and the board's `loot/` answers 409. On docker, a board session is refused with 503.
  - Firing or recording a case, and close, read no target. Firing still answers 503 when it needs the substrate for an origin or a tool.
  - The suppression restore inside ingest, and placing alerts on segments and hosts, tolerate an unreachable substrate. The placement comes back empty, so a session can still start and stop.
  - A ratio with a zero denominator is 0.0, not null. This covers precision, recall, F1 and FPR, and the game's speed, coverage and accuracy. Only the `objectives` block's `coverage` is null.
- **A score lists what it cannot vouch for.** It carries a warning in each of these cases:
  - there are no benign cases (`no_benign`);
  - there are marker cases and no marker on any alert (`no_marker`);
  - a window case has no source address (`no_source_ip`);
  - a detected case is not corroborated (`wrong_reason`);
  - Elasticsearch holds more hits than ingest read (`truncated`).
- **Cases fired through the API** (`views._fire`) send one case per HTTP connection, while the CLI keeps one connection for a whole run. Measured on the case set of the time (twelve cases), both gave identical scores and per-case alert counts. The acceptance tests drive the CLI, so the shared-connection path stays tested.

## OpenStack

The build follows the OpenStack item of the backlog in `docs/STATE.md`, in its order. This section describes what is built, run on the cloud or against fakes. What is left is listed at the end. The reasoning is in `docs/STATE.md` ("Decided on 2026-09-30"), `docs/superpowers/specs/2026-09-30-openstack-range-placement.md` and `docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`. This section records only the structure.

The cloud is one KVM compute node (8 vCPU, 64 GB) running kolla-ansible 2026.1 with ML2/Open vSwitch. The range lives in project `fsl-range`, driven by the member-role user `fsl-range`. Horizon is never shown to users.

Everything that differs between clouds is in `deploy/openstack/cloud.yaml`. It is copied from the committed `cloud.example.yaml`, ignored by git, and holds no secrets. It holds identity, networks and MTU, base image, zone, flavors, keys, the OPNsense release, and the platform's stack and ref.

- `platform/range/cloud.py` validates the file and reports every problem by key.
- `bin/platform-rebuild` and `bin/cloud` drive the openstack CLI and the Heat parameters from it. The stack writes the values into the platform's `openstack.env`.
- `bin/cloud up` creates the stack, then calls the fabric, images, slot and configure endpoints until `/api/range/ready/` is ready.
- `bin/cloud down` keeps the key, backs the store up (`bin/backup`, keeping `backups.keep` copies) and removes the slot, the fabric, any image builder and the stack.
- A `*_FAILED` stack is deleted (builders first). `up` creates it again, and `down` deletes it.
- A stack whose VM has no running `fsl-platform` container and no store file has nothing to back up. `down` and `up --replace` then skip the backup, though they still refuse when ssh to the VM does not answer. A store beside a stopped `fsl-platform` container is not a refusal: `down` starts the container (the backup runs through `docker exec`), backs up, waits for the API, then removes the range. Plain `up` asks the VM about its hand-over every time, whether or not the API answers, and a VM that never took it (no `FSL_OPENSTACK_PASSWORD` in its `openstack.env`) gets the hand-over then. It writes the password and the range key, making the key if it is missing and the VM holds no store. It restores the newest backup that holds rows when the VM holds no store.

### Built: the platform VM

`deploy/openstack/platform.yaml` is a Heat template. It creates:

- network and subnet `fsl-platform`;
- a router to the external network, and a floating IP. With `network.address` set, it associates one the project already holds instead. A stack delete leaves that address in place;
- a security group that opens tcp/22, tcp/8000, tcp/8002, tcp/3080 and ICMP to any address;
- the Nova server `fsl-platform`, with a config drive.

The template has no defaults. Every parameter comes from `deploy/openstack/cloud.yaml` (see `docs/OPENSTACK.md` §4).

cloud-init does the following on the platform VM:

- installs `docker.io`, `docker-compose-v2` and `git`;
- adds 4 GB of swap;
- sets Docker's MTU to the Neutron network's, for the default bridge (`mtu`) and for every new bridge network, compose's included (`default-network-opts`);
- clones `repository` at `ref` into `/opt/fsl`;
- writes `FSL_IMAGE_TAG=<the checkout's commit>` to `/opt/fsl/.env`;
- fetches the GeoIP database (`bin/fetch-geoip`). It needs no credential: Elastic's GeoIP endpoint serves GeoLite2 to anyone who accepts its terms in the URL;
- adds `ubuntu` to the `docker` group.

A systemd unit, `fsl-platform.service`, pulls the images of `compose.yaml` and `session.yaml` and runs `docker compose -f /opt/fsl/compose.yaml up -d` on every boot. It builds nothing. A failed pull does not stop the unit (`ExecStartPre=-`). `up` then builds what is missing from the checkout. `bin/platform-rebuild` avoids that by checking ghcr.io first.

On OpenStack the platform VM runs only the platform's containers (`compose.yaml`); no session stack starts there. The board's ground truth is read from the wargame host at its management address.

cloud-init sets `FSL_PUBLISH` to the VM's fixed address. Ports 8000, 8002 and 3080 are therefore published there and opened in the security group, and a browser reaches the console at the floating IP. `FSL_SYSLOG_PUBLISH=0.0.0.0` publishes 5140/udp on every address, for the edge's syslog. Port 9200 stays on loopback.

Every parameter of the template comes from `deploy/openstack/cloud.yaml` (`bin/platform-rebuild`, `bin/cloud`).

- cloud-init writes those values as `FSL_OPENSTACK_*` and `FSL_OPNSENSE`, plus `_PROJECT` (the stack's own project), `_SSH_USER=ubuntu` and `_SSH_KEY=/data/ssh/id_ed25519`. It writes them to `/root/openstack.env` with mode 0600, then moves the file to `/opt/fsl/openstack.env`, which git ignores.
- The password is not in the template. Nova keeps the user data, and its metadata service serves it to whatever runs on the VM, the range's containers included.
- `bin/platform-rebuild` appends `FSL_OPENSTACK_PASSWORD` over ssh once the VM is up. In the same way it writes the range ssh key into the platform's data volume (`README.md`).
- The platform service reads the file with `env_file` (`required: false`, `format: raw`). Compose passes it through without interpolating or unquoting.

The platform on the VM uses the OpenStack adapter (`FSL_SUBSTRATE=range.openstack.connect`, written by cloud-init). It builds the range's networks itself through `/api/range/fabric/`, planned by `range/fabric.py`:

- one `internet` network with a subnet per declared origin (DHCP off);
- `estate` and `mgmt` (no gateway), on the CIDRs that `cloud.yaml` gives. The loader refuses CIDRs that overlap each other, the platform's network, Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and 192.168.0.0/16; moby `daemon/libnetwork/ipamutils/utils.go`), a network that `compose.yaml` declares, or a declared origin;
- the keypair `fsl-platform`, from the key at `/data/ssh/id_ed25519`.

The platform makes that key only when it is absent at the first fabric POST. `bin/platform-rebuild` keeps a copy on the operator's machine and writes it into every new platform VM. A replaced VM therefore keeps the key that the keypair and the range's VMs trust.

`describe()` binds each origin to its subnet of the one Internet network by CIDR. The VM's router attaches only its own subnet. The platform reaches range hosts through its `mgmt` port (below).

The hosts boot from golden images. A golden image is a Glance image built once by a builder VM and reused for every boot. They are built through `/api/range/images/` and planned by `range/images.py`.

- The cloud holds one uploaded image, the stock Ubuntu 24.04 cloud image (`compute.base_image`). Every builder boots it.
- `declaration.yaml`'s `hosts:` gives each VM a setup script and the files it needs. The platform packs them into its builder's user data and boots the builder on its own network (the one with a router). It reads the builder's console for the line the setup prints when it ends, then stops and snapshots the builder.
- The image carries the bundle's digest. An edited script therefore shows up as an image of another bundle and not as a silently stale one.
- The digest hashes each file's name, content and mode. The mode is only the executable bit (0755 or 0644, as git tracks it), so a checkout's umask does not change the digest.
- A host that `uploads` (the edge) is different. Its builder gets no credential. It makes the disk, serves it over HTTP on the platform network and prints the disk's SHA256 on its console. The platform pulls the disk, checks the SHA256, creates the Glance record and uploads the disk with its own token. The builder is deleted once Glance says active, and is never snapshotted.
- The edge's builder downloads the OPNsense nano image. It checks its SHA256 and the release key's against `cloud.yaml`, and verifies the signature. It boots the image once under QEMU, answering its configuration importer so that it starts from `deploy/opnsense/config.xml`. It converts the result with `qemu-img` and serves it for the platform to upload as `fsl-opnsense-<version>` (`deploy/opnsense/build.sh`, `importer.py`).

The wargames have no image each. One host image, `fsl-wargame-host` (`deploy/wargame-host/setup.sh`), is the base image plus `docker.io` and `docker-compose-v2`. It runs every wargame that its declaration entry lists (`wargames: [board, corp]`) as the GHCR containers the docker substrate runs.

- `range/wargame_host.py` renders each `wargames/<id>/compose.yaml` for the host into the bundle. It drops `build:` and the session network, names each container by its service, and writes the platform's `FSL_IMAGE_TAG` into the image references. It publishes the ports that the WAF proxies to (`publish: {board: 8000, corp-wp: 80}`).
- `daemon.json` gives Docker's bridges the tenant MTU.
- The builder has the Internet and pulls the images into the image. The range has none.
- The tag is in the bundle's digest, so a platform on a new tag plans a new host image.
- The image count stays fixed as wargames are added: the base, the edge, the WAF, Kali and the wargame host.

A wargame image can be sideloaded onto the platform (`FSL_SIDELOADED`, the names that `bin/platform-rebuild --sideload` gave; `docs/OPENSTACK.md` §5.3). It then reaches the wargame host without GHCR:

1. `wargame_host.sideloaded_images` finds each service whose image is exactly `ghcr.io/nekonic/fsl-<name>:<FSL_IMAGE_TAG>`. The platform reads its image id from its own docker.
2. The bundle gains a generated `deploy/wargame-host/loaded` file (`<image> <image id> <name>` per line), so the id is in the bundle digest. It also gains `deploy/wargame-host/served-from`, the platform's base URL. The builder gets that file, but the digest leaves it out, so a new fixed IP for the platform does not rebuild the image.
3. `setup.sh` pulls from GHCR as before. Then for each `<name>` it fetches `<served-from><name>/`, which is `GET /api/range/images/sideloaded/<name>/` (`platform/api/sideloaded.py`). That endpoint streams `docker save` of the image. It answers 404 for a name that is not sideloaded or not run by a declared wargame, and on docker.
4. `setup.sh` runs `docker load` and refuses unless the loaded image's id equals the platform's. It prunes the GHCR copy.

With nothing sideloaded for a wargame, nothing changes. A slot standing before the new image is ready keeps its old wargame host until `POST /api/range/slot/rebuild/`, because a close resets that host in place.

The fabric also makes three security groups.

- `fsl-range`: every range port off `mgmt` joins it. It lets any IPv4 in. The WAF defends the range and Neutron does not. Anti-spoofing stays on.
- `fsl-reach`: it lets in only NTP (udp 123) from members of `fsl-mgmt`.
- `fsl-mgmt`: every range host's `mgmt` port joins it. It lets in only members of `fsl-reach`.

The platform attaches itself to `mgmt` through a port in `fsl-reach`, found by its own server id (`FSL_OPENSTACK_PLATFORM`, written at boot). It can therefore ssh to every host, while no host can open a connection to it but NTP. Kali's `mgmt` port reaches no other host. The runner reaches a host at its `mgmt` address unless the caller names a segment.

The range has no Internet and so no time source of its own. The scorer (the platform) compares target and sensor times with case windows on its own clock. The platform therefore serves time to the range:

- The platform VM runs chrony (cloud-init: `allow <network.mgmt>`, `local stratum 10`).
- Every range host keeps time by the platform's `mgmt` address. `range/clock.py` writes a `systemd-timesyncd` drop-in on the Ubuntu hosts and waits for the first answer (`keep_time()`, in every host's configure chain and before the wargames start).
- The edge's rendered `config.xml` names the platform in `system/timeservers`, with ntpd bound to `opt1`.
- On docker, every container reads the host kernel's clock, so nothing is needed there.

The slot is the set of range hosts. It is managed through `/api/range/slot/` and planned by `range/slot.py`.

- Each host has a port per declared segment, named `<host>.<segment>`, in `fsl-range` or, on `mgmt`, in `fsl-mgmt`. A standing `mgmt` port in another group is moved into `fsl-mgmt`.
- The host that fills `gateway` holds every origin's gateway address on one Internet port. Cloud-init configures only the first address, so the host's user data adds the rest at every boot.
- Every host's user data appends the `estate` names to `/etc/hosts`: the WAF's `board.com` and `corp.com`, and the wargame host's `board` and `corp-wp`. This is how the WAF finds each wargame's published port. Each database answers only inside its compose project on the host.

**Range slots.** `compute.slots` in `cloud.yaml` (default 1, `FSL_OPENSTACK_SLOTS` on the platform) sets how many copies of the range stand at once. `max_sessions` is that count.

- Slot 1 keeps the names above. Slot N>1 names its servers and ports `<host>-N` (`fsl-edge-2`, `fsl-waf-2.mgmt`) and tags its servers `fsl_slot=N` beside `fsl_host`.
- Each slot beyond the first has its own copy of the internet and estate networks (`fsl-internet-N`, `fsl-estate-N`, tagged `fsl.slot=N`) with the same subnets. Every edge therefore holds the same 30 origin gateways, every Kali the same origin addresses, and an alert's source is sorted to the same country in every slot. Neutron allows the same CIDR on two networks that share no router.
- `mgmt` is shared. Each slot's hosts take their own DHCP addresses there, and `fsl-mgmt` fences them as before.
- A slot adapter (`OpenStack.in_slot(n)`) reads only its own slot's servers, by their declared host name. Roles, runners, topology and the edge's rendered settings are therefore the same in every slot. Slot N's edge renders its hostname as `firewall-N`.
- Opening the collector for one slot keeps the other slots' sender rules.
- The platform binds a session to a slot at open (`Session.slot`, one open session per slot by a unique constraint). It takes the first free slot that is READY, chosen under a lock.
- Every per-session range call goes to that slot. The close resets only that slot and marks only its suppressions restored. Its reset state is its own (`api/reset.py`). Rule changes take that slot's turn, so one slot's reset does not hold the other slot's session.
- `run_on_role` takes `--session` or `--slot`, and it refuses to run with neither when there is more than one slot.
- The console's VM terminals take the session as `?arg=<id>` (ttyd `-a`) and open its slot's host.

**The edge.** The OPNsense edge `fsl-edge` (vtnet0 internet as WAN, vtnet1 estate as LAN, vtnet2 mgmt as opt1) boots in the slot. `POST /api/range/configure/` sets it up:

1. It renders `deploy/opnsense/config.xml` for the slot (`range/opnsense.py`). The file carries the defaults of the `dnsmasq`, `Syslog` and `unboundplus` models, which the early-boot template render needs before OPNsense's migrations run.
2. It stages the file, with the Suricata include `deploy/opnsense/suricata.yaml` and the starting rules, over the management ssh as root. It installs them and reboots the edge.
3. It waits for a new boot time and checks the edge's state:
   - it holds the 30 origin gateway addresses (one static, the rest as IP aliases);
   - it runs Suricata on the WAN in IDS mode, with the estate and mgmt as `HOME_NET`, and with EVE alerts and HTTP records going to syslog;
   - it sends syslog to the collector;
   - it has a WAN pass rule in pf that admits tcp 80 to the WAF's estate address and nothing else.

The rules editor writes the file that the include names and reloads with `suricatasc` on the socket it opens. The edge's syslog and the WAF's ModSecurity audit log reach the platform's Elasticsearch, with GeoIP enrichment.

**Kali.** One Kali image serves every origin. Its single Internet port holds the ~100 per-country addresses (the slot's `bootcmd` adds them to the NIC). `/usr/local/sbin/set-origin` SNATs the box's outgoing source per country, so every tool leaves as the chosen country. The marker-adding proxy and the ttyd terminal run on the Kali box.

**Rebuild and reset.** `rebuild_slot()` (`POST /api/range/slot/rebuild/`) rebuilds every standing slot VM from its golden image, keeping each server's id, flavour, ports and fixed IPs.

`POST /api/sessions/<id>/close/` calls `reset_slot()` instead.

- It rebuilds only the VMs that hand out a shell (Kali, the WAF).
- It leaves the edge and the wargame host to be reset in place (`docs/OPENSTACK.md` §6.1).
- A session therefore leaves the next one no edited rule or planted data.

A rebuild wipes the disk, so configure must follow once the VMs are ACTIVE.

On the wargame host, the in-place reset (`clear_wargames()`) runs `docker compose down -v` for each wargame and the estate sensor. It removes the sensor's eve log and rsyslog's imfile state. It leaves the images and no container or volume.

Configure's last step, `start_wargames()`, runs `sudo docker compose -p <id> -f /opt/fsl/wargames/<id>.yaml up -d --wait --pull never` for each wargame through the `wargames` role. Every session therefore starts on freshly seeded targets.

Then configure starts the estate sensor.

- It uses docker's Suricata image and `deploy/suricata/suricata.yaml`, which each start writes to the host from the platform's copy.
- It runs from `deploy/wargame-host/sensor.yaml` with host networking, on the interface that holds the host's estate address. It therefore sees the WAF-to-target leg, which docker's one sensor sees from the WAF's namespace.
- Once the sensor answers, `start_sensor()` seeds the baseline rules through `rules/suricata.py`, with the rule file and reload that the host entry names.
- Its role, `estate-sensor`, maps to the compose service `suricata`, so the runner execs into it.
- The host entry names its rule file and reload command (`settings.FSL_EXTRA_SENSORS`). Every rule seed, validation, change and baseline check goes to both sensors.
- The host's `logs:` entry has rsyslog forward `eve.json` to the collector, tagged `suricata` (`range/waf.py`'s forwarding, by tag).
- `fsl-reach` accepts syslog from the wargame host, as it does from the edge and the WAF.

After a close, the platform does the reset itself. `platform/api/reset.py` starts a background thread that, under one hold of the rules lock, runs two sides at once.

- One side is `reset_in_place()`:
  - the edge's in-place reset (`reset_edge()`): the baseline `fsl.rules` go back, the installed files are checked by sha256 against the hash the edge recorded after its last install and boot, range pf states are dropped, the filter is reloaded and Suricata is restarted. On any mismatch it falls back to `configure_edge()`'s install and reboot;
  - the collector's security group;
  - the wargame host: cleared, then its time source, wargames, sensor and log forwarding, in that order.
- The other side polls `plan_slot()` until each rebuilt VM has been seen out of ACTIVE and back to ACTIVE. Then it runs `configure_rebuilt()` (each rebuilt host's time source, and the WAF's log forwarding) from a fresh read of the cloud.

Both sides retry while a VM does not answer ssh (up to 30 minutes). The first failure fails the reset.

`configure_slot()` (the manual configure) runs every host's steps side by side, one thread per host: the edge (configure and reboot), the WAF, Kali, the wargame host, and the collector's security group. Every Ubuntu host's chain starts with its time source. It waits for all of them and fails with the first failure in that order.

The close answers at once. The reset state (idle, running, failed and why) is held in the platform process. `POST /api/range/configure/` stays the manual retry and clears a failed reset.

**Readiness.** On OpenStack, session create answers 409 while every slot is held or no free slot is ready.

`GET /api/range/ready/` reports every slot under `slots`:

- its number and the session holding it;
- its phase: `IN_USE` while a session holds it, `RESETTING` while its reset runs, `RESET_FAILED` with its reason if it failed, otherwise `NOT_STANDING`, `REBUILDING`, `CHECKING` or `READY`;
- its reset state;
- three checks: every VM ACTIVE, the board's ground truth readable, and the sensor rules at baseline with no suppression of that slot in force.

The top-level `ready` and `slot` are the slot that the next open would take.

`/api/range/slot/`, `slot/rebuild/` and `configure/` take `?slot=N`. Without it they act on every slot.

`POST /api/range/canary/` fires a marked case and reports whether Suricata and ModSecurity both alerted and how far their clocks differ. It is not part of the ready check. The landing page calls both.

### The range on OpenStack: the target structure

The user decided this on 2026-09-30, with the 2026-10-08 changes marked. Most of it is built (see above).

```
 OpenStack project fsl-range.

 platform VM: Ubuntu 24.04, floating IP, docker compose up
   console and /api/, scoring, Elasticsearch, Filebeat, Kibana
   landing page /: start and stop a session, the scoreboard after close
   blue console panes: Kibana, Website, Map, Alerts or IDS rules,
     WAF (ttyd in the platform, ssh to the WAF VM), Kali
   red console: Kali (ttyd, ssh to the Kali VM on mgmt), Website
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
         (SecRuleEngine On; the learner tunes CRS to block)
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

- Session lifecycle: check WAF mode and clock skew as part of readiness. Running `configure` again after the close-time rebuild is automatic since 2026-10-11.
- Blocking is built. The WAF runs `SecRuleEngine On` on both substrates. The learner tunes CRS in the WAF terminal or through `PUT /api/sessions/<id>/waf/`. A fired case is marked `meta["blocked"]` from its 403, not from the target side.
  - The starting paranoia level was measured on 2026-10-10 (`docs/DECISIONS.md`). PL1 already blocks the board SQLi and passes O'Brien.
  - A posture meant to over-block therefore starts above PL1 (the scenarios' `level2` and `level3`). The learner tunes it with a lower PL, a threshold or a rule exclusion.

`docs/STATE.md` lists the decisions still open for a person ("Decisions left for a person").

Built: the WAF VM forwards its ModSecurity audit log with rsyslog imfile over UDP to 5140 (`platform/range/waf.py`). Suricata on the OPNsense edge runs in IDS (pcap) mode (`deploy/opnsense/`). Both run on the `fsl-range` cloud (`docs/STATE.md`).
