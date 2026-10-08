# Architecture

How the range is built, how traffic and evidence move through it, and the
design decisions behind it. How the score is defined is in `CLAUDE.md`; open
problems and measured quirks are in `docs/STATE.md`.

Everything up to "Decisions" describes what runs today: a Docker compose
range. The last section, "OpenStack", separates what is built there from what
is planned (`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`).

The hypothesis the repo started from: red team attacks can be labelled with
ground truth, and Suricata and ModSecurity alerts can be matched to those
labels automatically, so false positives and negatives can be scored
mechanically. The objective score was added once that held.

## The range

The compose services and networks are listed below; `bin/measure` counts them.
Each target is a wargame, a folder under `wargames/` whose `compose.yaml` the
top `compose.yaml` includes: `board` (Django and MySQL, `loot_verified`) and
`corp` (WordPress and MySQL, `effect_observed`). The platform discovers each
from `wargames/<id>/scenario.yaml` (`platform/wargames.py`; fields `name`,
`description`, `image`, `public_url`, `objective_model`, `case_file`). Nothing
reads `image` yet; compose still builds each app untagged (`build: ./app`). A
new wargame needs `scenario.yaml`, `objectives.yaml` and `compose.yaml` in its
folder, a case file under `redteam/cases/`, and an `include:` line.

| Service | Image | Networks | Host port |
|---|---|---|---|
| `fsl-wg-board` | `wargames/board/app` (Django under gunicorn, port 8000) | estate | |
| `fsl-wg-board-db` | `mysql` | estate | |
| `fsl-wg-corp-wp` | `wargames/corp/app` (WordPress 6.6.2, three pinned vulnerable plugins; `corp.com` by `Host` header) | estate | |
| `fsl-wg-corp-db` | `wargames/corp/db` (MySQL 8.4, binlog `ROW`) | estate | |
| `fsl-waf` | `owasp/modsecurity-crs` (nginx), alias `board.com` on edge | edge, edge-br, edge-hk, edge-us, estate | |
| `fsl-suricata` | `jasonish/suricata` | the WAF's namespace | |
| `fsl-elasticsearch` | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-filebeat` | `filebeat:8.15.0` | mgmt | 5140/udp |
| `fsl-kibana` | `kibana:8.15.0`, served at `/kibana/` | mgmt | |
| `fsl-kali` | `deploy/kali` | edge | |
| `fsl-proxy` | `deploy/proxy` (mitmdump) | the four edge networks | |
| `fsl-platform` | `platform/` (Django under waitress, behind nginx; nginx also serves Kibana at `/kibana/`, Kali's own ttyd at `/terminal/`, the VM terminals at `/vm-terminal/fsl-kali/` and `/vm-terminal/fsl-waf/`) | all six | 8000 |

8000 binds to `FSL_PUBLISH` and 5140/udp to `FSL_SYSLOG_PUBLISH`,
both defaulting to 127.0.0.1; 9200 binds to loopback only.

| Network | Segment | Subnet | Name | Origin |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | Internet | Russia |
| `edge-br` | `br` | 177.54.144.0/24 | Internet | Brazil |
| `edge-hk` | `hk` | 103.152.220.0/24 | Internet | Hong Kong |
| `edge-us` | `us` | 73.0.0.0/24 | Internet | United States |
| `estate` | `estate` | 172.30.0.0/24 | Application estate | |
| `mgmt` | `mgmt` | 172.31.0.0/24 | Management | |

The declaration lists thirty origins on one Internet segment, the top thirty
countries by Cloudflare Radar's share of HTTP requests, each with a /24 that
GeoIP places in it and a share of about 100 attack addresses. Docker builds
four of them, one network each, because a bridge holds one IPv4 subnet; the
OpenStack fabric builds all thirty as subnets of one network.
`bin/pick-origins` reproduces the table, and an acceptance test checks every
subnet against the pipeline scoring reads.

Segmentation is Docker network membership only: no firewall, no iptables, no
ACL. `test/test_segmentation.py` asserts it against the live stack (Kali
reaches `board.com` but not `board:8000`). Only the subnets are fixed;
container addresses are assigned by Docker and change on recreate. The views
build a new adapter and read them on every request. The rule that refuses
requests from range hosts caches their addresses for 30 s, and when it cannot
reach the substrate it treats the range as empty and lets the request through
(`docs/THREAT-MODEL.md`).

The platform, the WAF and the proxy are multi-homed. The attacker's traffic
enters the internal network (`estate`) only through the WAF, but the platform
is attached to every segment, so the API checks the caller itself
(`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --console-fired case--------------+
 edge-br                                              |
 edge-hk   proxy, platform (no kali, no board.com)    |
 edge-us                                              v
         fsl-waf: nginx + ModSecurity CRS, DetectionOnly, port 80
         fsl-suricata in the same network namespace, af-packet on all five
         interfaces, so it sees client->WAF and WAF->target
                                                      |
 estate    board:8000 <--any Host, /internal/ 404-----+
           board --> board-db (MySQL)
           platform --GET /internal/auth-users--> board:8000, past the WAF
 mgmt      filebeat --> elasticsearch <-- platform

 Not network traffic:
   eve.json --bind mount--> filebeat
   ModSecurity audit.log --volume waflogs--> filebeat
   ./data/label --bind mount--> proxy (read-write), kali (read-only)
   kali's shell --> /var/log/fsl/commands.log, each command with its marker
   platform --docker exec--> proxy (/label files), suricata (rules),
                             kali (command log), corp-db (mysql, mysqlbinlog)
   platform --docker run--> throwaway fsl-kali for tool cases
   platform --> volume platformdata --> /data/db.sqlite3
```

`deploy/suricata/suricata.yaml` names the interfaces eth0 to eth4 and relies on
Docker attaching the WAF's networks in the priority order set in
`compose.yaml`. Nothing checks that mapping.

The WAF routes `board.com` to `board:8000` and answers `/internal/` itself
with a 404 (`deploy/nginx/board.conf`); `corp.com` is a second vhost to
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

Docker is the MVP's substrate; OpenStack is the target. The platform does not
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

Segments are found by a label; hosts are still found by name. Each segment
carries `fsl.segment.id` as a Docker label or a Neutron tag, and the adapters
fetch only labelled networks. Matching by name broke on compose prefixes and
overrides, Heat stack suffixes and non-unique Neutron names. A role is the
container or server name the declaration gives: Docker runs `docker exec
<name>`, and OpenStack lists every server in the project and matches
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
`_SSH_USER` and `_SSH_KEY`, each refused by name when missing; `_REGION`
defaults to `RegionOne` and `_INTERFACE` to `public`. `redteam/harness.py` is handed a launcher and
`platform/rules/suricata.py` a runner, so neither imports `subprocess` or
names a substrate.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| shape | `docker network ls/inspect`, label filter | Keystone v3, Neutron with `tags-any`, Nova |
| sensor | refuses to describe the range unless each declared sensor shares the declared gateway's network namespace (`docker ps`, `.HostConfig.NetworkMode`) | reports a sensor whenever both named servers exist; nothing confirms it sees the gateway's traffic |
| runner | `docker exec` | `ssh` to the instance |
| launcher | `docker run --rm --network <segment>` | `runner("attacker")`: runs the tool over ssh to the declared attacker's mgmt address (the origin only checks that the attacker stands on that segment; the source country comes from `fsl-origin` SNAT); any other image is refused, because Nova cannot boot a host, return its output and delete it |
| tested against | the live stack | unit tests on fakes built from the published API reference and a local sshd; on the `fsl-range` cloud, the platform VM built the fabric, the images and the slot through `/api/range/`, `describe()` read back the WAF on the thirty origins and the four hosts on estate and mgmt, and `runner()` ran on each host over ssh to its mgmt address; `launcher()` fired sqlmap from the `ru` and `tw` origins on 2026-10-08 |

Compose mounts the Docker socket into the platform whatever the substrate, and
the entrypoint adds the platform user to its group. It is a container escape
path. The OpenStack adapter would make it removable; nothing removes it yet.
What is left before the adapter can drive a range is listed in
`docs/STATE.md` under "The substrate seam".

## Isolation seams

Each concern has one owning file. The exceptions below exist in code today.

| Concern | Owning file | Known exceptions |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py` PUTs the `fsl-geoip` ingest pipeline at bring-up |
| The Suricata process | `platform/rules/suricata.py` | `platform/range/pfsense.py` and `deploy/pfsense/configure.php` stop and start Suricata on pfSense (OpenStack) |
| The attacker box | `platform/attacker.py` | `platform/operator_log.py` reads `/var/log/fsl/commands.log`; the terminal wiring (`settings.py`, `nginx.conf`, `entrypoint.sh`) names `fsl-kali` |
| The target's own records | `platform/api/loot.py` (board), `platform/api/effect.py` (corp) | none |

## Where requests come from

| Route | Sender | Source address in the alert | Marker |
|---|---|---|---|
| Terminal, HTTP | Kali, through `proxy:8081` | the proxy, on the chosen origin | added by the proxy |
| Terminal, raw TCP | Kali directly | Kali, on `edge` only | none |
| Console case, HTTP | the platform | the platform, on the chosen origin | added by the harness |
| Console case, tool | a throwaway `fsl-kali` container | that container, on the chosen origin | sqlmap `--headers=` |
| CLI run, HTTP | the platform, `redteam/run.py` | the platform, on `edge` (where `board.com` resolves) | added by the harness |
| CLI run, tool | a throwaway `fsl-kali` container, from `launcher(<declared default origin>)` | that container | sqlmap `--headers=` |

The proxy is a `mitmdump` script. It sets `X-FSL-Case` from `/label/active`
and, when `/label/origin` names an address, forwards the request there with the
original `Host`. The platform writes both files with `docker exec`. There is no
TLS interception, so the proxy is an environment variable and does not enforce
anything: `curl --noproxy '*'` skips it.

The terminal also records what the operator types. Kali's shell appends each
command, with the current `/label/active` marker, to
`/var/log/fsl/commands.log`. The platform reads it through
`runner("attacker")` and serves it at `GET /api/sessions/<id>/commands/`.
The red console frames `/vm-terminal/fsl-kali/`, a ttyd inside the platform
that connects over ssh to the host's mgmt address; on compose, Kali and the
WAF have no mgmt address, so the red console's terminal and the blue console's
WAF terminal do not connect there.

A console HTTP case carries the `Host` of the session's wargame, `board.com`,
whether or not an origin was chosen. Choosing an origin points traffic at the
WAF's address on that origin's segment, by IP; the name resolves on the `edge`
network, which the platform uses when no origin is set.
`rotate` is a per-session round robin, not a random pick.

A console tool case is pointed at the origin's target URL, or, with no origin
chosen, at `TARGET_URL` (`http://board.com`) from the declared default origin.
The target is not host-published, so the command-line harness reaches it from
inside the range too: `redteam/run.py` runs on the platform (the way the
acceptance suite drives it), has no origin option, and its `--target` defaults to the `public_url` of the
scenario its `--cases` file belongs to (`http://board.com` for board), which
resolves to the WAF on port 80. `--tool-target` defaults to `http://board.com`.

The WAF runs CRS at paranoia level 1, anomaly threshold 5, in `DetectionOnly`
(`deploy/waf/modsecurity.conf`), and every Suricata rule is `alert`. Nothing
in the range blocks a request.

## Where alerts go

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-<day>
                                     (fsl_source)   pipeline fsl-geoip
                                                          |
             POST /api/sessions/<id>/ingest/ (called by tests and by the session page's close)
                                                          |
             parse per fsl_source, copy the marker onto alerts, store
             as Detection rows in SQLite
```

`test/conftest.py` and the session page's confirm-close call `ingest/`;
`redteam/run.py` prints the curl. A browser round ingests its detections once,
at close; alerts that arrive after the click are not ingested.

ModSecurity's audit log carries the request headers, so its alerts carry the
marker directly. Suricata's alert events carry no request headers; only its
`http` events do (with `dump-all-headers: request`; `custom: [X-FSL-Case]` has
no effect). Ingest copies the marker from the `http` event onto the alert with
the same `(flow_id, tx_id)`. Joining on `flow_id` alone attributed every alert
on a keep-alive connection to its first case.

Each ingest call:

- first restores rule suppressions that have expired;
- asks Elasticsearch for `@timestamp` from the session's start minus a minute
  to its end (or now) plus a minute. The `fsl-geoip` pipeline sets `@timestamp`
  from the event's own clock (Suricata's `timestamp`, ModSecurity's
  `transaction.time_stamp`), so the window selects events by when they
  happened, not when Filebeat read them;
- reads at most 5000 hits, oldest first. Beyond that the reply carries
  `truncated` and the session records `read_of`, which adds
  `score.warning.truncated` to the score;
- keeps Suricata's `alert` events, and turns ModSecurity's record into one
  Detection per matched rule message, with id `<Elasticsearch _id>:<n>`;
- drops alerts whose own event time falls outside the window, counted as
  `stale`;
- writes markers found later onto stored rows that had none;
- fills `src_host` and `dest_host` from the substrate's segments, empty if the
  substrate cannot be reached.

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
the pipeline at bring-up (`platform/register_pipeline.py`).

## How the scores are computed

Objectives. The board is a `loot_verified` target. Its
`wargames/board/objectives.yaml` names the secret (the `auth_user` username and
password columns, read from `/internal/auth-users`) and three tiers by how much
of it the attacker holds: any one hash (difficulty 2), the `admin` account's
(4), every account's (5). The attacker exfiltrates hashes and submits them with
`POST /api/sessions/<id>/loot/`. The platform credits a tier only for submitted
`(username, hash)` pairs that match the session's start-of-session snapshot
exactly, and only once the session has fired a malicious case. It never credits
an objective from its own belief about what an attack did. The ground truth is
the target's own records, which the detectors do not see.

A credited tier becomes an Objective row dated by the submission. If the
submission names a malicious case (`case_id`), its window runs from 100 ms
before that case started to 100 ms after it ended; otherwise it runs from 2
minutes before the submission to 100 ms after.

The snapshot is taken once, when the session starts. If the board cannot be
read then, the session is still created, with no snapshot, and
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
`takes:` field is shown in the red console but not read by scoring.

In the score's `objectives` block, `coverage` is detected difficulty over total
difficulty, `null` when nothing was taken, and `false_positives` is FP.
`damage` is undetected difficulty plus half of detected difficulty, which is
how an undetected loss counts double.

Detection. A case is matched to alerts by one of two strategies, declared
per case:

- `marker`: the alert carries the case's `X-FSL-Case` value;
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
terminal cases: the red console sends none. A detected case that is not
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

The score endpoint is read-only and keeps no history.

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
  platform's port 8000 at `/kibana/` and publishes no port of its own. The
  blue console frames it.
- Elasticsearch is a single node with a 512 MB heap so the whole stack fits
  in a default Docker memory allowance.
- Missing data is an error, not a zero, with stated exceptions. An
  unreachable Elasticsearch or substrate and an unreadable rule file answer
  503. Session create tolerates an unreachable target (the session starts with
  no snapshot, and the board's `loot/` answers 409); firing or recording a case and close
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

### Built: the platform VM

`deploy/openstack/platform.yaml` is a Heat template. It creates:

- network and subnet `fsl-platform`;
- a router to the external network, and a floating IP;
- a security group opening tcp/22, tcp/8000 and ICMP to any address;
- the Nova server `fsl-platform`, with a config drive.

Its parameters and their defaults are in `README.md`.

cloud-init installs `docker.io`, `docker-compose-v2` and `git`, adds 4 GB of
swap, sets Docker's MTU to the Neutron network's for the default bridge
(`mtu`) and for every new bridge network, compose's included
(`default-network-opts`), clones `repository` at `ref` into `/opt/fsl` and
adds `ubuntu` to the `docker` group. A systemd unit, `fsl-platform.service`,
runs `docker compose -f /opt/fsl/compose.yaml up -d --build` on every boot.

So the whole compose stack above runs inside one Nova VM. cloud-init sets
`FSL_PUBLISH` to the VM's fixed address, so 8000 is published there
and opened in the security group, and a browser reaches the console at the
floating IP. `FSL_SYSLOG_PUBLISH=0.0.0.0` publishes 5140/udp on every address
for pfSense's syslog; 9200 stays on loopback.

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

The platform on the VM uses the OpenStack adapter
(`FSL_SUBSTRATE=range.openstack.connect`, written by cloud-init) and builds the
range's networks itself through `/api/range/fabric/`, planned by
`range/fabric.py`: one `internet` network with a subnet per declared origin
(DHCP off), `estate` on 10.30.0.0/24 and `mgmt` on 10.31.0.0/24 with no
gateway, outside every compose and platform-VM subnet, and the keypair
`fsl-platform` from a key the platform makes at `/data/ssh/id_ed25519`.
`describe()` binds each origin to its subnet of the one Internet network by
CIDR. The VM's router attaches only its own subnet; the platform reaches range
hosts through its `mgmt` port (below).

The hosts boot from golden images, built through `/api/range/images/` and
planned by `range/images.py`. `declaration.yaml`'s `hosts:` gives each VM a
setup script and the files it needs; the platform packs them into its
builder's user data, boots the builder on its own network (the one with a
router), reads the builder's console for the line the setup prints when it
ends, then stops and snapshots it. The image carries the bundle's digest, so
an edited script shows up as an image of another bundle rather than a
silently stale one.

The fabric also makes two security groups: `fsl-range`, which every range
port joins and which lets any IPv4 in (the WAF defends the range, not
Neutron; anti-spoofing stays on), and `fsl-reach`, which lets nothing in.
The platform attaches itself to `mgmt` through a port in `fsl-reach`, found
by its own server id (`FSL_OPENSTACK_PLATFORM`, written at boot), so it can
ssh to every host while no host can open a connection to it. The runner
reaches a host at its `mgmt` address unless the caller names a segment.

The slot is the set of range hosts, managed through `/api/range/slot/` and
planned by `range/slot.py`. Each host has a port per declared segment, named
`<host>.<segment>`, all in `fsl-range`. The host filling `gateway` holds
every origin's gateway address on one Internet port, and since cloud-init
configures only the first, its user data adds the rest at every boot.
Every host's user data appends the `estate` names (`board`, `board-db`) to
`/etc/hosts`, which is how the WAF finds the board and the board its database.

The pfSense CE edge (golden image `fsl-pfsense-edge`: base + Suricata 8.0.5 +
sshd + an OPT1 management NIC) boots in the slot. `POST /api/range/configure/`
replays `deploy/pfsense/configure.php` over the management ssh so pfSense
holds the 30 origin gateway addresses (one static, the rest as IP-alias VIPs),
runs Suricata on the WAN with the range as `HOME_NET` and EVE going to syslog,
keeps one WAN pass rule that survives the Suricata package's filter reload,
and ships its syslog and the WAF's ModSecurity audit log to the platform's
Elasticsearch, with GeoIP enrichment. One Kali image serves every origin: its
single Internet port holds the ~100 per-country addresses (the slot's
`bootcmd` adds them to the NIC) and `/usr/local/sbin/fsl-origin` SNATs the
box's outgoing source per country, so every tool leaves as the chosen country.
The marker-adding proxy and the ttyd terminal run on the Kali box.
`GET /api/range/console/<host>/` returns the Nova console URL of the server
filling that host.

`rebuild_slot()` (`POST /api/range/slot/rebuild/`) resets
the slot: Nova rebuilds every standing slot VM from its golden image, keeping
each server's id, flavour, ports and fixed IPs, so a session leaves the next
one no edited rule or planted data. `POST /api/sessions/<id>/close/` calls
it. A rebuild wipes the disk, so `POST /api/range/configure/` must follow once
the VMs are ACTIVE; nothing calls it automatically.

On OpenStack, session create answers 409 while another session is open or the
range is not ready. `GET /api/range/ready/` reports the slot's phase
(`NOT_STANDING`, `REBUILDING`, `CHECKING`, `READY`) and three checks: every VM
ACTIVE, the board's ground truth readable, and the sensor rules at baseline
with no suppression in force. `POST /api/range/canary/` fires a marked case
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
     Kibana    framed directly, reading the same Elasticsearch (full)
     terminal  ttyd in the platform, ssh to the Kali VM on mgmt
     |
     +--OpenStack API, as member fsl-range--> networks, VMs, consoles
     +--management network, ssh-------------> Kali VM, target VMs

 Internet network: one subnet per origin country (30), no Neutron router
   Kali VM: one port holds every attack address; the source is rewritten
            to the chosen country's address as packets leave
     |
     v
 pfSense CE VM: edge router; its WAN holds each subnet's gateway address
                and routes on without NAT, so country sources survive
   Suricata package: IDS (detects; no firewall lesson, per 2026-10-08)
     |
     v
 WAF VM: nginx + ModSecurity v3 + CRS
         (planned: SecRuleEngine On, blue tunes CRS to block)
     |
     v
 estate network
   board VM (Django on MySQL)

 Evidence:
   pfSense: Suricata EVE, filterlog --syslog, UDP--> Filebeat --+
   WAF VM: ModSecurity audit log --------------------------------+
                                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch ----------------> Kibana --> blue team
```

Left to build:

- Session lifecycle: after the rebuild, re-run `configure`, check WAF mode and
  clock skew as part of readiness, and start the next session only on READY
  without manual steps.
- Blocking (planned, 2026-10-08 spec): the WAF runs `SecRuleEngine On` and the
  blue team tunes CRS (paranoia level, rule exclusions) so the attack is
  blocked and benign traffic passes; Suricata detects. Whether a case was
  blocked is read from the target side into `meta["blocked"]`. The earlier
  plan, switching Suricata drop rules in the pfSense GUI, is superseded.

Decisions still open for a person are in `docs/STATE.md` ("Decisions left for
a person").

Built: the WAF VM forwards its ModSecurity audit log with rsyslog imfile over
UDP to 5140 (`platform/range/waf.py`), and Suricata on pfSense runs in legacy
mode (`deploy/pfsense/configure.php`). What has to be tested on this
cloud before building is in the placement spec, "To test on this cloud before
building".
