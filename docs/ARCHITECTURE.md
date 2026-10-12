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
Two compose files hold them. `compose.yaml` is the control plane (project
`fsl`, one long-lived copy): the platform, Elasticsearch, Kibana, the
`collector`, the four edge networks and `mgmt`. `session.yaml` is one
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
aims the session's proxy at the session's own WAF (`/label/origin`); the
baseline is read after that. Sessions run concurrently: opening a session runs
`down -v` only on `fsl-<n>` projects whose session ended more than three
minutes ago (leaving their `estate` first), deciding which under one lock so
two opens at once cannot take down each other's new stack. Docker opens at most `FSL_MAX_SESSIONS` sessions (default 2,
`platform/fsl/settings.py`) and answers 409 past that; OpenStack opens one per range slot.
Closing a session leaves its stack until an open at least three minutes
later, while its Filebeat ships the last alerts. The OpenStack substrate has
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
console's scenario card, and `defense` and `lessons`, described under "The WAF
lesson"). Nothing
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
(`fsl-platform`, `fsl-elasticsearch`, `fsl-kibana`, `fsl-collector`). The
first table below gives each session service under its declared host name,
which `platform/range/docker.py` maps the container back to.

Every endpoint that acts on the range (rules, validate, suppressions,
`/api/attacker/`, origin, label, canary) takes `session` from the query or
body. Without one, a write goes to the newest open session and answers 409
when none is open, and a read uses the newest session; a write naming a closed
session is refused. Suppressions are stored with their session (migration
0014). The red console sends its session id. Each
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
| `fsl-kali` | session | `ghcr.io/nekonic/fsl-kali` from `deploy/kali`; `http_proxy` is `http://fsl-<id>-proxy-1:8081` | edge | |
| `fsl-proxy` | session | `ghcr.io/nekonic/fsl-proxy` from `deploy/proxy` (mitmdump); `/label` is the project's named volume | the four edge networks | |
| `fsl-elasticsearch` | control | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-collector` | control | `filebeat:8.15.0`, the syslog input only (the OpenStack range) | mgmt | 5140/udp |
| `fsl-kibana` | control | `kibana:8.15.0`, served at `/kibana/` | mgmt | |
| `fsl-platform` | control | `platform/` (Django under waitress, behind nginx; nginx also serves Kibana at `/kibana/`, each session's Kali ttyd at `/terminal/<session id>/`, each session's WAF shell at `/waf-terminal/<session id>/`, the VM terminals at `/vm-terminal/fsl-kali/` and `/vm-terminal/fsl-waf/`); carries the compose plugin and mounts `session.yaml` at `/src/session.yaml` | the edge networks, mgmt, and each open session's estate | 8000, 8002 |

8000 and 8002 bind to `FSL_PUBLISH` and 5140/udp to `FSL_SYSLOG_PUBLISH`,
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

Segmentation is Docker network membership only: no firewall, no iptables, no
ACL. `test/test_segmentation.py` asserts it against the live stack (Kali
reaches `board.com` but not `board:8000`), and `test/test_concurrent_sessions.py`
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
   kali's shell --> /var/log/fsl/commands.log, each command with its marker
   platform --docker exec--> proxy (/label files), suricata (rules),
                             waf (CRS tuning, nginx reload),
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
label in the session's project. Two places bypass that lookup and name the
session's WAF container by the compose naming convention instead:
`platform/api/site.py` (`http://fsl-<id>-waf-1`, the site proxy) and
`platform/api/views.py` (`fsl-<id>-waf`, the lesson's WAF box), recorded in the
exceptions table below. Each segment
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
| launcher | `docker run --rm --network <segment>`, with `--add-host` for the session WAF's names | `runner("attacker")`: runs the tool over ssh to the declared attacker's mgmt address (the origin only checks that the attacker stands on that segment; the source country comes from `fsl-origin` SNAT); any other image is refused, because Nova cannot boot a host, return its output and delete it |
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
| The Kibana HTTP API, its saved objects and the Discover link | `platform/kibana.py` | none |
| CRS configuration and the nginx reload | `platform/rules/crs.py` | the WAF terminal (`waf-terminal.sh`) opens a shell in `fsl-<id>-waf-1` for the person (on OpenStack, `vm-terminal.sh fsl-waf` an ssh shell on the WAF VM), and the lesson's WAF-pane step text names the exclusion file and the audit log for them to read, its command filled in by `wargames.lesson` from the declared exclusion file and reload (`settings.FSL_WAF`); the platform reads neither |
| The session's WAF container (docker) | `platform/range/docker.py`, by compose label | `platform/api/site.py` builds `http://fsl-<id>-waf-1` and `platform/api/views.py` builds `fsl-<id>-waf` by the compose naming convention |
| The Suricata process | `platform/rules/suricata.py` | `platform/range/opnsense.py` and `deploy/opnsense/` configure and restart Suricata on the OPNsense edge (OpenStack); each sensor host in `declaration.yaml` (the edge, and the wargame host for `estate-sensor`) names the rule file and reload command `suricata.py` is handed; `platform/range/wargame_host.py` (with `deploy/wargame-host/sensor.yaml`) stops and starts the estate sensor's compose service on the wargame host when a slot is configured or reset (OpenStack), and its baseline rules then go through `suricata.py` |
| The attacker box | `platform/attacker.py` | `platform/operator_log.py` reads `/var/log/fsl/commands.log`; the terminal wiring (`settings.py`, `nginx.conf`, `entrypoint.sh`) names `fsl-kali` and `fsl-<id>-kali-1` |
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
| Site browser | the learner's browser, through the platform's nginx on port 8002 and `platform/api/site.py` | the platform, on `edge` | the session's secret `browse-<hex>`, set by `site.py`; the API shows it as `browse` |

The proxy is a `mitmdump` script. It sets `X-FSL-Case` from `/label/active`
and, when `/label/origin` names an address, forwards the request there with the
original `Host`. The platform writes both files with `docker exec`. There is no
TLS interception, so the proxy is an environment variable and does not enforce
anything: `curl --noproxy '*'` skips it.

The terminal also records what the operator types. Kali's shell appends each
command, with the current `/label/active` marker, to
`/var/log/fsl/commands.log`. The platform reads it through
`runner("attacker")` and serves it at `GET /api/sessions/<id>/commands/`.
On compose the red console frames `/terminal/<session id>/`, which nginx
proxies to Kali's own ttyd in `fsl-<id>-kali-1:7681`. On OpenStack it frames
`/vm-terminal/fsl-kali/?arg=<session id>`, a ttyd inside the platform that
connects over ssh to the mgmt address of the host in the session's slot; on compose, Kali and the WAF have no mgmt address, so
`/vm-terminal/` does not connect there.

The blue console's WAF pane frames the URL the session API names
(`waf_terminal` in `GET /api/sessions/<id>/`). On compose it is
`/waf-terminal/<session id>/`: nginx takes the session from the path, drops the
client's query and proxies to a ttyd inside the platform
(`ttyd -a -b /waf-terminal -p 7693 /app/waf-terminal.sh`) with `?arg=<session id>`;
ttyd's `-a` passes that as the script's argument, and the script, after checking
it is a number, runs `docker exec -it fsl-<id>-waf-1 bash`. The WAF image has
no ttyd of its own. The same `auth_request /terminal-allowed` guards it. On
OpenStack the pane frames `/vm-terminal/fsl-waf/?arg=<session id>`.

The blue console's Website pane is a browser inside the console: back,
forward, reload, an address bar that shows the full URL
(`http://board.com/<path>`) with Chrome's "Not secure" marker for http and
takes a URL or a path and Enter, the page in an iframe, and a "Developer
tools" toggle. The target is not published, so nginx on 8002 passes
`/site/<session>/<host>/<path>`, behind the same `auth_request
/terminal-allowed` as the terminals, to the platform's recorder
(`/site-proxy/<session>/<host>/`, `platform/api/site.py`, with the exact path
and query in `X-Site-Uri`), which sends it on to that session's WAF
(`fsl-<id>-waf-1:80`, reached on the shared `edge` network) with `Host:
<host>`, no redirect following and no compression. It passes on only
`Accept`, `Accept-Language`, `Content-Type`, `User-Agent`, `Referer` and
`Origin`; `X-Forwarded-For` is not among them, so the target and its audit log
see the platform, never the learner's LAN address. It answers 404 for a
session that does not exist and 409 for a closed one, without calling the
WAF; when the WAF does not answer within 3 s to connect or 20 s to read, it
answers 502 with a plain sentence that names no internal host. The page is
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
reachable this way. It appends a script before
`</body>` that posts `location.pathname + search` to the parent, which is how
the address bar and the history follow a link clicked inside the page.

The route is served on its own port, 8002, a different origin from the
console's 8000, and every response carries `Content-Security-Policy: sandbox
allow-forms allow-scripts allow-same-origin`. The target is the red team's to
plant script in; on the console's origin that script could read and drive the
console and its APIs. A sandbox without `allow-same-origin` (an opaque origin)
would do that on 8000 alone, but Chromium-based embedded browsers refuse such a
frame (`ERR_BLOCKED_BY_CLIENT` in the Claude desktop browser). `SITE_PORT` is
8002 on docker and `None` on OpenStack, where there is no session WAF to name;
the session API gives `site: {port, path}` or `null`, and the console hides
the pane without it. A platform VM on substrate docker needs a security-group
rule for 8002 (`docs/OPENSTACK.md` §3.5).

The recorder keeps each session's last 200 requests in the platform's memory
(lost on restart): method, `http://<host><path>`, status, whether the WAF
blocked it (403), the time taken, the request and response headers and the
bodies, each cut to 64 KB (the response is streamed and only its first 64 KB
kept), and forgets a session's requests when it closes. `GET /api/sessions/<id>/site/requests/?after=<id>`
lists them and `.../site/requests/<id>/` gives one in full. The Developer tools
panel is docked under the page (its top edge drags taller or shorter); while
open, the tab visible and the session open, it polls the list every 2 s (a
closed session answers 409 and the polling stops) and shows method, URL, status (403 in red
with "blocked by the WAF") and time; a selected row shows both header sets,
the request body and the response body, the first 2000 characters with "Show
more". "View source" shows the recorded body of the page in the address bar.
The panel says that no cookies are kept.

Browsing is marked with the session's own secret (`Session.browse_marker`,
`browse-` and 32 random hex digits, made when the session is created; the
recorder replaces whatever `X-FSL-Case` the browser sent), and the request
comes from the platform's `edge` address. Its alerts are ingested and listed
like any other, so the learner finds them in Kibana and in `/detections/`, but
`/score/` leaves out detections carrying that session's secret the way it
leaves out the lesson's own replays (seed, VERIFY, check, replay): browsing is not a case, so it is neither a
true or false positive nor an unattributed alert. A literal `X-FSL-Case:
browse` sent by hand is just an unknown marker and is scored, and `POST
/api/attacker/label/` refuses labels that start with `browse`. The API never
shows the secret: `/detections/`, `/api/detections/<id>/` (including `raw`)
and the Network panel show `browse` in its place. Kibana shows it, which is
the blue team's tool. The red console has no site pane.

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
changed through `/api/sessions/<id>/waf/` ("The WAF lesson"). `GET` reads the
file with a 10 s timeout so a poll never holds a server thread longer. Every Suricata
rule is `alert`, so the WAF is the only part of the range that blocks. The
OpenStack WAF VM blocks the same way (`SecRuleEngine On` in
`deploy/waf/modsecurity.conf`, CRS's default threshold 5 and Paranoia Level 1).

## Where alerts go

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-<session>-<day>
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
- reads `fsl-logs-<session>-*` on docker (`ELASTIC_SESSION_INDEX`; each
  session's Filebeat writes its own index) and `fsl-logs-slot<N>-*` on
  OpenStack, where the shared collector tags each syslog line with the slot
  its sender's hostname names (`-N` before the domain, slot 1 otherwise) and
  writes it to that slot's index;
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
  substrate cannot be reached. Ingest and `/detections/` reuse a session's
  segments for 30 s instead of running `docker network ls` and `inspect` on
  every lesson poll; `/top/`, `/map/` and `/topology/` read them fresh.

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
up). waitress serves the platform with 16 threads.

## The WAF lesson

A session is opened with `POST /api/sessions/` `{scenario, guidance, lesson,
mode, defense}`, stored on the session (migrations 0015, 0022, 0023).
`defense` names one of the scenario's `defense` entries (default `full`);
`guidance` (default off, on when `lesson` is given) needs the scenario to
declare `lessons`. A scenario declares a `lessons:` list in `scenario.yaml`,
each lesson with an `id`, an `order` and optionally `level` (easy, medium,
hard), `minutes` and `prerequisites` (ids of the scenario's other lessons),
checked at discovery; a descriptor still carrying a single `lesson:` is
refused. The board has seven, listed under "The course on the board" below.
`lesson` (default the scenario's `default_lesson`, else the first by `order`;
the board's default is `waf-exclusion`) is kept as `Session.lesson` and
reported as `lesson_id`; `mode` is `guided` (default, or the lesson's own
`mode`) or `self` (`Session.mode`), refused on a wargame, and switched on an
open lesson by `PATCH /api/sessions/<id>/ {mode}`. The board declares
`minimal` (CRS paranoia level 4, `local.rules`), `full` (paranoia level 1,
the same `local.rules`) and `ids` (paranoia level 1, `no-uri-sqli.rules`:
`local.rules` without sid 9000001). A lesson declares the defense it
starts from (`defense`, `minimal` for the board's lesson, checked against the
scenario's `defense` at discovery); a guided open that names no defense takes
it. `GET /api/wargames/` lists each scenario's `lessons` with `id`, `order`,
the `title` and `goal` string keys, `minutes`, `level`, `defense`,
`prerequisites` and the step count, and keeps `lesson_defense`,
`lesson_text` and `lesson_steps` for the first lesson. `GET
/api/sessions/?ids=1,2` narrows the session list to the ids given. On
every substrate, after the stack is up, the open path seeds the sensor with the
defense's rule file, or `local.rules` without a defense (`suricata.seed`), and
writes the CRS tuning when there is a defense (`crs.apply`); a guided session
then replays the lesson's cases once (`meta.seed`), so its ModSecurity and
Suricata records are in Kibana when the learner arrives. On a slotted
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
exclusion per entry (`ctl:ruleRemoveTargetById=<id>;<target>` or
`ctl:ruleRemoveById=<id>`, scoped by `SecRule REQUEST_FILENAME "@beginsWith
<path>"` when a path is given). It writes the file into the session's WAF with
`runner("gateway")`, runs `nginx -t && nginx -s reload`, and restores the
previous file if nginx refuses. It returns once a worker that was not there
before the reload is up (worker PIDs read from `/proc` by parent PID), so new
connections meet the new tuning; old workers may still drain a slow request.
If no new worker appears within 5 s the reload did not happen: it restores the
previous file, reloads and refuses. Input is validated before anything is written:
paranoia 1-4, rule id 900000-999999, target `ARGS`, `ARGS_GET`, `ARGS_POST`,
`ARGS_NAMES`, `REQUEST_COOKIES` or `REQUEST_HEADERS` with an optional
`:name`, a path of `[A-Za-z0-9_./-]`, at most 20 entries.
`PUT /api/sessions/<id>/waf/` changes it (the agent path); `GET` reads the
file in the session's WAF back through `crs.read`, which parses the paranoia
level and every `ctl:ruleRemove*` line (commented lines skipped, continued
lines joined), so it reports an edit made in the WAF terminal. Each VERIFY,
and each close before the slot is rebuilt, snapshots what `crs.read` reads
(`Session.waf_snapshots`, migration 0021: `{at, run|closed, waf}`); the latest
is also `Session.waf`, so a closed session reports the learner's last
configuration, file included (`file: null` when none was ever read). A WAF
that cannot be read takes no snapshot and stops neither. The learner tunes in
the WAF terminal; a lesson that declares `controls: [paranoia]` also shows a
level control in the note, which calls the same `PUT`.

`POST /api/sessions/<id>/verify/` replays the session's lesson's `cases`
through the same path as `/attacks/`, marked `meta.verify=<run>` and
`meta.mode` (the mode it ran in), and judges only that run. An sqlmap case is leaked when the rows sqlmap dumped (`redteam/tools.py`
`dumped`) match a `(username, hash)` of the session's snapshot
(`loot.matched`); a leak is reported in the diagnosis and credits no
objective (ruling D7, 2026-10-13): the learner's own check is not a lost
objective. Loot a red player submits through `/loot/` still credits. It is held
only on positive evidence: no matching row, sqlmap exited 0, printed its
`[*] ending` line and no crash (traceback, user abort, a host that does not
exist), no dumped row at all, and sqlmap's own conclusion "all tested
parameters do not appear to be injectable" (`tools.found_not_injectable`). A
dump that matches no snapshot account is neither a leak nor a block: it is
inconclusive. VERIFY answers 409 for a session with no snapshot, and a docker
board session whose accounts cannot be read at open is refused with 503 and
closed. A
connection error sqlmap recovered from does not void the conclusion: behind
the WAF they are ModSecurity cutting the board's 500 responses (nginx "header
already sent"); a connection error that stops sqlmap before it concludes
leaves no conclusion line and is inconclusive. Anything else is inconclusive and fails VERIFY.
The sqlmap cases run with `--disable-hashing`, so sqlmap does not offer to
crack the pbkdf2 hashes (which `--batch` accepts and never finishes) and the
dumped cells are the raw hashes. The 403 count
sqlmap reports is kept as `meta.forbidden` and is not judged. A benign case is
served when curl reports a 2xx `http_code`. PASS needs every attack held and
every benign case served (`platform/lesson.py`); the reply carries
`diagnosis` keys that the console renders from `strings.html`, never TP/FP
labels; it also carries `waf`, the snapshot taken before the run, `mode`, and
`fix`, the class of the learner's fix read from that snapshot
(`lesson.fix_class`, ruling D1): `level` when the paranoia level is below the
lesson's posture (a file with no level counts as CRS's default 1), else
`rule` when an exclusion the posture lacks removes a whole rule, `target`
when one removes a target on no path or on a path wider than the lesson's
`waf` step path, `path_target` when every added exclusion is a target within
that path, and null when nothing was added. It is reported beside the
verdict and never changes it. A case
marked with any of `views.REPLAY_MARKS` (`seed`, `verify`, `check` for a
step's check, `replay` for the Check tab's Replay) is left out of `/score/`
(TP/FP/FN/TN, the alerts it drew, and the game) and out of the windows corp's
effect observation attributes changes to. The Check tab replays through
`POST /attacks/ {case, lesson: true}`, which takes only the lesson's cases in a
guided session, judges the case like VERIFY and answers its `diagnosis` and a
`replay` row: the outcome, sqlmap's conclusion lines (`tools.conclusions`,
the injectable or not-injectable verdicts and critical stops, without the
clock, at most four), the declared command, the 403 count labelled "not
judged", and a Kibana `discover` link narrowed to the case's marker
(`kibana.marked`).
The board's lesson replays `board-sqli-orderby-sqlmap`,
`board-sqli-orderby-sqlmap-tamper` and four benign cases, among them the
O'Brien search and `board-normal-sort` (`?sort=-created_at`), which fails a
tuning that over-blocks the `sort` argument.

The console is five screens, every one filled from `/api/` (a static mockup
the user approved, with two rulings on top; `docs/DECISIONS.md`, 2026-10-11,
console redesign). The palette and component classes are in `base.html` and
`platform/console/components.css`, which `bin/build-css` puts into
`tailwind.css`. The header carries the breadcrumb, the range state and the
language switch.

- Main (`/`): running sessions with their kind (`lesson` or `wargame`), the
  step a lesson reached and whether opening has finished (`ready`, from
  `Session.ready_at`; "preparing n s / about 80 s" until then); scenario cards
  with category, difficulty and minutes from `scenario.yaml`, and counts of
  attack cases, benign cases, objectives and lesson steps from
  `GET /api/wargames/`, and under each card every lesson with its goal,
  level, minutes and prerequisites and three start buttons: Lesson (guided),
  Practice (`mode: self`) and Wargame (no guidance, the full defense). Each
  lesson also shows its newest run among the sessions this browser opened
  (`fsl-opened-sessions` in localStorage, written by the session and blue
  pages, newest first, at most 20; read through `?ids=`): the rung and
  PASS/FAIL, still open, or closed without a VERIFY. Finished sessions with
  their `result`: PASS/FAIL from
  the last VERIFY run, or objectives lost of the total and how many went
  unnoticed. The result is scored once and stored (`Session.result_cache`,
  migration 0018) with the inputs it was scored from: `ended_at`, the hint
  count, and each of detections (last id, rows, rows with a marker), cases and
  objectives (last id, rows). A list reads three aggregates per session and
  scores again only a session whose inputs changed, such as a late ingest. A
  refused start is said under the button that was pressed; on
  409 "Close open sessions" lists the open ones, each closed through
  `ingest/` then `close/`. `GET /api/range/ready/` names `max_sessions`.
- Session (`/session/<id>/`): header figures (lesson step, objectives lost,
  target), the blue and red console cards, recent cases from
  `GET /api/sessions/<id>/cases/`. Once closed: the lesson verdict with its
  last diagnosis and the fix class, the debrief when it passed (below), then
  the primary score (every tier, lost or kept, noticed or
  not, penalty difficulty x1 or x2), then plain sentences on what the defence
  judged: "caught 7 of 8 attacks, missed 1 (name)", "3 of 4 benign requests
  passed, wrongly blocked 1 (O'Brien search)", and that a case counts once
  however many alerts it drew. TP/FP/FN/TN and the game's balance stay in the
  API; no string a person reads names them (`test_strings.py`).
- Blue (`/blue/<id>/`): a rail (Kibana, WAF, Red) and the pane. On the WAF
  pane a banner names only the box (`waf_box`, `fsl-<id>-waf`) and the CRS
  rules directory (`waf_rules`, derived from `crs.EXCLUSIONS`).
- Red (`/red/<id>/`): objectives (Korean names under `objective.<key>`) and
  "Submit stolen hashes" at the top, cases grouped into attacks and benign
  with what their last run did, the Kali terminal taking the rest. Narrow
  widths stack the panels; the red and blue pages do not scroll sideways.

In a guided session the lesson note floats over the pane at its top right,
below the site toolbar or the WAF banner when one is shown (40 px plus 8 px),
folded by default to a pill ("Lesson note · step n/N"); open, it is 360 px wide
and holds five tabs: Steps (the current step, Back/Next, every step to jump
to), Goal (the summary, the done conditions, the four paragraphs), Theory,
Hints and Check. The goal line (`<lesson.text>.summary`) is pinned under the
header, above the tabs. It opens when the learner opens it or when a step points at
one of its own controls (and folds again when the guide moves off such a step);
while open, its tab follows the step (Check for Replay and Verify, Steps
otherwise). The first time a browser opens a session's blue console
(`fsl-lesson-landed-<id>`) the note opens on Goal; every later load starts
folded; only the tab is kept per viewer in
localStorage (`fsl-lesson-note`), and the step shown in `fsl-lesson-step-<id>`, which the
main and session pages read for "step n/N". Progress itself is the
session's (`Session.lesson_steps`, migration 0020): per step `reached`,
`passed`, `skipped` (times), `hint` (the level shown, 0-4) and `done_for_me`,
reported as `progress` in `GET /api/sessions/<id>/`. `POST
/api/sessions/<id>/lesson/steps/<step>/ {state: reached|skipped}` records a
step reached (which also fixes the newest detection id an alert check must
pass) or left unpassed; the console sends `skipped` on Next or a list jump
from a step not passed, never on Back or a pass. The step list ticks a step
only when `progress` says it passed, marks one left unpassed with a hollow
circle and "skipped", and says "n of N steps passed" above it. A step that a
theory card `shows` gets a "Why?" link in the popover that opens that card.

Goal leads with a customer ticket (`<lesson.text>.ticket`) whose second line
is read from `GET /waf/` (paranoia level and exclusion count) and states
nothing else, then the summary, then the starting verdict: `start` in `GET
/api/sessions/<id>/` judges the seed replay with VERIFY's rules (on the
board, PL4 fails it on the O'Brien search, the one red row). Goal also holds
the switch between the guided lesson and practice. In practice (`mode:
self`) the payload carries no step command, hints and "Do it for me" answer
409, and the console hides the Steps and Hints tabs, the guide and the
"Show me where" links; Goal, Theory and Check stay and the learner types
every command.

Theory holds five folded cards (`lesson.theory` in `scenario.yaml`; text under
`<lesson.text>.theory.<card>.title|body`): paranoia levels, anomaly scoring
(why a 403 names 949110 and 920273), finding a false positive's rule, lowering
the level versus a rule exclusion, and reading a `ctl:ruleRemoveTargetById`
line. A card that names something on screen has "Show me where", which moves
the guide to that step. Hints holds reasoning only, folded one by one (why
920273, why only ARGS:q, why the 900 file; `lesson.hints` in `scenario.yaml`,
text under `<lesson.text>.hint.*`), then a
folded Solution: every step's command in order, with a copy button. Check
replays one case, listing each run's `replay` row (newest five) with its
Kibana link, and runs VERIFY; the verdict is PASS or FAIL, the cases that
held or passed are listed in green with a tick, each failing diagnosis in red
with a cross, and the fix class in grey beneath. After a PASS the Check tab
shows the debrief. The note holds no exclusion form; the level control and
the Suricata rule editor appear only for a lesson that declares them.

The debrief is `GET /api/sessions/<id>/lesson/debrief/` (a lesson session,
open or closed), in the Igloo/ASEC report order: `overview` (the last
VERIFY's verdict, the number of runs, its mode and fix class, steps passed
of the total, and steps with a hint, skipped and done for the learner),
`evidence` (at most 20 of the session's own detections whose marker is a
seed or last-VERIFY case, with rule, request, phase and case; no
Elasticsearch read), `change` (the declared opening posture against the
last VERIFY snapshot: exclusions added and removed, both levels, and a line
diff of the exclusion file against what `crs.rendered` writes for the
posture), `cases` (each lesson case at open and at the last VERIFY), and
`risk` (string keys named by the fix class, and that only the lesson's
attack cases were replayed). `at` carries the open and last VERIFY times for
agents; the console does not show them. `debrief_script.html` renders it in
the Check tab and on the closed session's page.

The steps are declared in the lesson definition (`lesson.steps` in
`scenario.yaml`): an `id`, a `check` whose `kind` is one of `alert`, `click`,
`answer`, `choice`, `waf`, `served`, `replay`, `verify`, `level`, `rules` or
`detect` (`wargames.CHECK_KINDS`, validated at discovery; a `replay` names a
case of its lesson and an `expect` of `held` or `served`; the last three are
described under "The course on the board"), and as the step needs a `site`
path, a Kibana `query` or the terminal `command`. The session API adds a `discover` link to a step
with a `query` (`kibana.discover_path(..., narrowed)`) and shows a check's
`kind` only, plus a choice's `options` and the `path` an alert or served
check listens for, and a replay's `case`: no answer key reaches the browser.
The board has eight steps, each advanced by its check; Back and Next stay as
the way around one:

| Step | Where | Check |
|---|---|---|
| search: search O'Brien as a customer | Website pane | `alert`: the platform ingests the last 600 s and passes on a record marked with the session's browse secret whose path holds `O'Brien`, newer than the step's `reached` |
| find: that request in Kibana | Kibana, filter button `url : *Brien* and status : 403` | `click`: the row's expand toggle |
| rule: which rule | answer box | `answer`: `920273`; `949110` gets "that is the score total rule" |
| target: what it caught | four choices | `choice`: `ARGS:q` (address, cookie and header are the others) |
| exclude: add the exception | WAF terminal, "Run in terminal" | `waf`: the WAF file holds 920273 `ARGS:q` `/search/`, then the O'Brien case, replayed with `meta.check`, is answered 2xx (the reload took effect); a poll replays once per file version |
| retry: search O'Brien again | Website pane | `served`: when the pane shows the O'Brien search, the same case is replayed with `meta.check` and must be 2xx |
| sqlmap: is sqlmap still held | the popover's "Run board-sqli-orderby-sqlmap again" | `replay`: on the press only (about 15 s, never polled), the case is replayed with `meta.check` and passes when held; a leak fails, and a run with no conclusion says so in its own message (`lesson.check.inconclusive`); the reply carries the `replay` row |
| verify: are attacks still blocked | the note's Check tab | `verify`: VERIFY passes |

Every check is judged by the platform, `POST
/api/sessions/<id>/lesson/steps/<step>/check/` (`{answer}` for an answer or a
choice, `{poll: true}` for a background poll), which records `passed` and
answers `{passed, reason, hint, hints, progress}` (plus `fix` from a `waf`
check and `replay` from a `replay` check); `reason` is a
`strings.html` key with its values. `click` is the console's word. A failed
check that is not a poll counts as wrong; two raise the step's hint level and
record the hint.

Checks run by themselves; there is no Check button. `alert` and `waf` are
polled every 5 s while their step is shown, the tab is visible and the session
open (the page re-reads the session every 30 s to notice a close), `served` runs when the Website
pane shows the step's path. A status line in the popover says "Checking...",
then what is still missing ("the 920273 exception is not in the file yet",
"in the file but not loaded"), and on a pass "✓" and what was found
(`<lesson.text>.ok.<step>`); 1.2 s later the guide moves on and shows the
step's line (`<lesson.text>.line.<step>`), and on the last step "Lesson
complete". A wrong answer says what is wrong. A recent ingest
(`within`) reads the newest records of the window first and records no
truncation, because a VERIFY run alone leaves more than 5000.

The terminal step's command uses absolute paths only, since a reopened ttyd
starts a fresh shell. Rules written by hand take ids 10100-10199; `crs.rendered`
writes 10000 to 10020 (the paranoia `SecAction` and at most 20 exclusions), so
the two never collide. The command copies the file to `.bak`, drops any earlier
`"id:10100,` line, appends the exclusion with id 10100, prints the file's last
line, and runs `nginx -s reload` only if `nginx -t` passes; otherwise it copies
the `.bak` back, so the WAF is never left on a file nginx refused. Running it
twice leaves one copy. Its text
is folded under "Show command"; "Run in terminal" opens the WAF pane if needed,
waits for ttyd's `term`, calls `term.paste(command + "\n")` and then
`term.input("\r")`, because bash keeps a bracketed paste's newline as text.

Help climbs a ladder per step (`<lesson.text>.nudge|answer.<step>`): a nudge,
then "look where the red box is", then the answer,
then "Do it for me". It climbs on the Hint button or after two wrong answers
or failed checks; each press is `POST /api/sessions/<id>/lesson/hints/ {step,
level: "hint"}`, which raises the step's `hint` level, and the first is
recorded in `Session.hints` (migration 0017; 400 for a step or level the
lesson does not have, 409 when closed). After 60 s on a step the Hint button
only says "Hint available"; nothing is recorded until the learner presses it.
"Do it for me" is `POST /api/sessions/<id>/lesson/steps/<step>/do/`, recorded
as `done_for_me` and `{step, level: "do"}` in `hints`: the platform enters the
answer, adds the exclusion through `crs.apply` with the current paranoia
level, replays the case, or marks the click, then judges the step; the
console still opens the site at the step's path, opens the filtered Kibana
and clicks the first row's toggle, or runs VERIFY. The steps done for the
learner are marked in the step
list from `hints` and `progress` in `GET /api/sessions/<id>/`, and `result.lesson.helped`
(`["hint", "do"]`, either or neither) puts "hints used" / "Do it for me used"
beside PASS or FAIL on the main page and the closed session's page.

"Do it yourself" (a checkbox under the step list, `fsl-lesson-stretch`)
removes the filter button and the Run button and shows the command: the
learner writes the KQL and types the rule. The checks are the same.

Where each step points is the step's `point` in `scenario.yaml` (`panel`,
`kibana` with an optional `first` fallback, or `pane`; `opens`; `tab`), so the
console names no board step and no Kibana selector, and the red box is drawn
from the start of every step. A step names the pane it needs (`opens`: site,
Kibana or WAF); while that pane is not shown, the box is on its rail button
and the popover says only "Open Website on the left" (or Kibana, or WAF).
Once it is shown: the site's address bar, a `data-test-subj` in the
same-origin Kibana frame (`docTableExpandToggleColumn`, `field-rule`,
`field-transaction.messages.details.data` with `field-rule` as fallback), the
WAF pane as a whole, or the note's Verify button. Nothing is ever looked up
inside the site frame, which is another origin. The popover is the one place
for the current step's words and Back/Next; the note's Steps tab lists the
steps with the current one marked "in progress" and its status, and shows
"Show the guide" only after the popover is closed. The popover
is in the manner of driver.js: anchored to the target with an arrow, below,
above, left or right of it (under the right end of a target wider than 480 px,
such as the address bar), never over the open note, and on a terminal step
in the pane's bottom right. The box has `pointer-events: none` and is placed
every animation frame; with no target for about 2 s the popover says where to
look. Theory (five cards) and Hints (reasoning, then the folded solution) stay
in the note, out of the path.

### The course on the board

`wargames/board/scenario.yaml` declares Package 2 of
`docs/superpowers/specs/2026-10-13-blue-team-course-design.md` (rulings D1-D11)
as one recommended path, open order, skipping allowed:

| order | lesson | defense | judged by | to solve |
|---|---|---|---|---|
| 0 | `console-tour` | `full` | its steps | send a request the WAF blocks, find its record, name the rule |
| 1 | `read-the-block` | `minimal` | its steps | name the rule that blocked O'Brien and the parameter it fired on |
| 2 | `waf-exclusion` | `minimal` | VERIFY | the narrow exclusion (above) |
| 3 | `choose-the-level` | `minimal` | VERIFY and the level | the highest paranoia level that serves every ordinary request and holds both sqlmap variants, no exclusions |
| 4 | `ids-signature` | `ids` | detection (D2) | a Suricata rule that alerts on both sqlmap `?sort=` variants and not on `?sort=-created_at` |
| 5 | `ids-body-xss` | `full` | detection (D2) | alert on the comment XSS in the body, not on an ordinary comment |
| 7 | `assessment` | `minimal` | VERIFY | O'Brien and the Korean search served, both sqlmap variants held, no guidance (`mode: self`, no steps) |

Lesson 6 (corp) is not built (`docs/STATE.md` backlog 0).

A lesson whose steps include no `verify` is judged by its steps alone:
`POST /verify/` answers 400 for it and the session payload says
`verifies: false`, so the console hides VERIFY and its Goal says "answered
from this session's own records". A lesson with no steps (the assessment)
is judged by VERIFY.

An `answer` check may read its accepted answers from the record instead of an
`accept` list: `of: rule` or `of: target` with the `path` of the request (and
`marker: browse` for the learner's own request). The platform ingests the last
600 s, takes the session's ModSecurity detections of that request, drops the
CRS totals (rule ids starting 949, 959 or 980) and accepts each remaining
`ruleId`, or the variable each names (after "against variable" in
`details.match`, or "found within X:" or "X=" in `details.data`;
`lesson.read_from`). Answers compare without case. With nothing recorded the
reason is `lesson.check.unrecorded`, and "Do it for me" answers the first
accepted value.

`choose-the-level` declares `solved_at: {paranoia: 2}` (kept on the server)
and `controls: [paranoia]`. Its `level` step passes when the WAF in force
runs below the posture's level with no exclusion the posture lacks
(`lesson.level_refused`; reasons `.unchanged` and `.excluded`); done for the
learner it applies `solved_at`. Its VERIFY passes when every case passes, the
snapshot holds no added exclusion and its level is not below `solved_at`
(`lesson.unsolved`: `lesson.diag.level_low`, `lesson.diag.excluded`); a higher
level that passes every case also passes. PL2 is the measured answer with
`board-normal-search-korean` in the lesson (`docs/DECISIONS.md` 2026-10-13).

`ids-signature` and `ids-body-xss` declare `detected_by: suricata` and
`controls: [rules]`. Their completion is detection (ruling D2): VERIFY fires
every case, then reads the session's detections from that source until every
attack case has one or `FSL_LESSON_ALERT_WAIT` (30 s, polled every
`FSL_LESSON_ALERT_POLL`) runs out. An attack case is `detected` when one of
its alerts mentions the case's `expect` (`scoreboard.corroborated`, signatures
that also fired on a benign case of the run left out), `uncorroborated` when
it alerted without it, `missed` without an alert; a benign case is `quiet` or
`alerted`. Each case row also carries `verdict` TP, FN, FP or TN. PASS needs
every attack detected and every benign case quiet. The replays stay out of
`/score/` and no objective is marked; ModSecurity's detections do not count.
A `rules` step passes once the sensor's file (`GET /api/rules/`) holds a sid
the posture's rule file does not (`suppress.sids`); done for the learner it
appends the step's `rule` (kept on the server) and applies it. A `detect` step
`{case, expect: alert|quiet}` fires the case marked `meta.check`, waits as
VERIFY does (a `quiet` waits the whole time) and answers a `detected` row:
outcome, verdict, the alert signatures and a Kibana link narrowed to the
alerts carrying the marker (`kibana.sensed`). The step's reason on a fail is
`lesson.check.missed|uncorroborated|alerted`.

The rule editor (D3) reads `GET /api/rules/?session=<id>`, checks with
`POST /api/rules/validate/` and writes with `POST /api/rules/apply/` on the
version it loaded. Validate answers `errors`: the lines carrying Suricata's
`Error` from every sensor that refused, and `output` is the refusing sensor's
output with the most of them. The OPNsense edge's Suricata logs to syslog only
(its template has no console output), so its `-T` output carries no error
line; the wargame host's estate sensor prints them.

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
  blue console frames it. At bring-up `platform/kibana.py` (in the background,
  retrying while Kibana cannot be reached or answers 502/503/504, and reporting
  any other HTTP error once with its status and body) imports `deploy/kibana/objects.ndjson` with
  overwrite: the data view `fsl-logs-*` on `@timestamp`, whose runtime fields
  fold each Suricata/ModSecurity pair into one column (`rule`, `rule_id`,
  `source_ip`, `destination`, `url`, `status`), the "FSL alerts" search and the
  "FSL overview" dashboard. It sets `defaultRoute` to that search. A data view
  existing is what keeps Kibana's Welcome screen away. `GET /api/sessions/<id>/`
  carries `discover`: an unsaved Discover state on the `fsl-logs` data view
  with the alert search's columns, query and sort, narrowed to the session's
  index on docker (`_index : fsl-logs-<id>-*`) and to its window; the ELK pane
  opens it. It is not the saved search with an overriding query, which Kibana
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
ready; `bin/cloud down` keeps the key, backs the store up and removes slot,
fabric, any image builder and the stack. A `*_FAILED` stack is deleted (builders
first) and created again by `up`, and deleted by `down`.

### Built: the platform VM

`deploy/openstack/platform.yaml` is a Heat template. It creates:

- network and subnet `fsl-platform`;
- a router to the external network, and a floating IP (or, with
  `network.address` set, an association to one the project already holds,
  which a stack delete leaves in place);
- a security group opening tcp/22, tcp/8000 and ICMP to any address;
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
`FSL_PUBLISH` to the VM's fixed address, so 8000 is published there
and opened in the security group, and a browser reaches the console at the
floating IP. `FSL_SYSLOG_PUBLISH=0.0.0.0` publishes 5140/udp on every address
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

The fabric also makes three security groups: `fsl-range`, which every range
port off `mgmt` joins and which lets any IPv4 in (the WAF defends the range,
not Neutron; anti-spoofing stays on); `fsl-reach`, which lets nothing in; and
`fsl-mgmt`, which every range host's `mgmt` port joins and which lets in only
members of `fsl-reach`. The platform attaches itself to `mgmt` through a port
in `fsl-reach`, found by its own server id (`FSL_OPENSTACK_PLATFORM`, written
at boot), so it can ssh to every host while no host can open a connection to
it, and Kali's `mgmt` port reaches no other host. The runner reaches a host
at its `mgmt` address unless the caller names a segment.

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
its hostname as `fsl-edge-N`. Opening the collector for one slot keeps the
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
`deploy/opnsense/config.xml` for the slot (`range/opnsense.py`), stages it
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
`bootcmd` adds them to the NIC) and `/usr/local/sbin/fsl-origin` SNATs the
box's outgoing source per country, so every tool leaves as the chosen country.
The marker-adding proxy and the ttyd terminal run on the Kali box.
`GET /api/range/console/<host>/` returns the Nova console URL of the server
filling that host.

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
`deploy/suricata/suricata.yaml`, from `deploy/wargame-host/sensor.yaml` with
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
and the wargame host (cleared, then wargames, sensor and log forwarding, in
that order). The other polls `plan_slot()` until each rebuilt VM has been seen
out of ACTIVE and back to ACTIVE, then runs `configure_rebuilt()` (the WAF's
log forwarding) from a fresh read of the cloud. Both retry while a VM does not
answer ssh (up to 30 minutes) and the first failure fails the reset.
`configure_slot()` (the manual configure) runs every host's steps side by
side, one thread per host: the edge (configure and reboot), the WAF, the
collector's security group, and the wargame host; it waits for all of them
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
  SQLi and passes O'Brien, so the lesson starts at PL4, which over-blocks
  O'Brien, and the learner tunes it (a lower PL or a rule exclusion). Whether a case was
  blocked is read from the target side into `meta["blocked"]`. The earlier
  plan, switching Suricata drop rules in the pfSense GUI, is superseded.

Decisions still open for a person are in `docs/STATE.md` ("Decisions left for
a person").

Built: the WAF VM forwards its ModSecurity audit log with rsyslog imfile over
UDP to 5140 (`platform/range/waf.py`), and Suricata on the OPNsense edge runs
in IDS (pcap) mode (`deploy/opnsense/`), not built against a cloud yet. What has to be tested on this
cloud before building is in the placement spec, "To test on this cloud before
building".
