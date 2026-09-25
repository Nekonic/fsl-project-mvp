# Architecture

How the range is built, how traffic and evidence move through it, and the
design decisions behind it. How the score is defined is in `CLAUDE.md`; open
problems and measured quirks are in `docs/STATE.md`.

The hypothesis the repo started from: red team attacks can be labelled with
ground truth, and Suricata and ModSecurity alerts can be matched to those
labels automatically, so false positives and negatives can be scored
mechanically. The objective score was added on top once that held.

## The range

Nine compose services on six Docker networks.

| Service | Image | Networks | Host port |
|---|---|---|---|
| `fsl-juice-shop` | `bkimminich/juice-shop` | estate | |
| `fsl-wiki` | `nginx`, alias `wiki.internal` | estate | |
| `fsl-waf` | `owasp/modsecurity-crs` (nginx), alias `shop.com` on edge | edge, edge-br, edge-hk, edge-kp, estate | 8080 |
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
container addresses are assigned by Docker and change on recreate, so the
platform reads them live on every request and answers 503 when it cannot
reach the substrate.

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
         fsl-waf: nginx + ModSecurity CRS, DetectionOnly
         fsl-suricata in the same network namespace, af-packet on all five
         interfaces, so it sees client->WAF and WAF->juice-shop
                                                      |
 estate    juice-shop:3000 --SSRF--> wiki.internal <--+
 mgmt      filebeat --> elasticsearch <-- platform

 Not network traffic:
   eve.json, ModSecurity audit.log --bind mounts--> filebeat
   platform --docker exec--> wiki (read log), proxy (/label files), suricata (rules)
   platform --docker run--> throwaway fsl-kali for tool cases
   platform --> volume platformdata --> /data/db.sqlite3
```

`deploy/suricata/suricata.yaml` names the interfaces eth0 to eth4 and relies on
Docker attaching the WAF's networks in the priority order set in
`compose.yaml`. Nothing checks that mapping.

## The declaration and the substrate seam

Docker is the MVP's substrate; OpenStack is the target. The platform never
asks Docker what the range means. It is told, by
`platform/range/declaration.yaml`: per segment an id, a display name and an
attack origin; a role table (attacker, scorer, gateway, proxy, sensor, target,
wiki); which host the sensor watches; the default origin; and the defended
site the map draws lines to (Seoul). A segment is outside if and only if it
declares an origin.

**Identity is declared, allocation is reported.** The declaration holds no
subnet, gateway or address. Those come from the substrate, because Docker and
Neutron both hand them out, and a declared subnet that disagreed with the real
one would bin alerts by a subnet nothing lives on. `compose.yaml` repeats the
identity in network labels; `platform/tests/test_declaration.py` holds the two
files to each other, but never checks the running range.

**Objects are bound by a mark, never by name.** Each segment carries
`fsl.segment.id` as a Docker label or a Neutron tag, and the adapters fetch only
marked objects. Name rules broke on compose prefixes and overrides, Heat stack
suffixes and non-unique Neutron names.

`platform/range/ports.py` is the port. Core code and most of the platform see
only its four verbs:

- `describe()` returns the shape: segments, their nodes and addresses, sensors;
- `segments()` returns who stands where, without asking about the sensor;
- `runner(role, segment)` runs a command on a standing host (the sensor, the
  wiki, the proxy);
- `launcher(segment)` runs a one-shot tool on a segment and returns its output.

`range.substrate()` builds the adapter named by `FSL_SUBSTRATE`.
`redteam/harness.py` is handed a launcher and `platform/rules/suricata.py` a
runner, so neither imports `subprocess` or names a substrate.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| shape | `docker network ls/inspect`, label filter | Keystone v3, Neutron with `tags-any`, Nova |
| runner | `docker exec` | `ssh` to the instance |
| launcher | `docker run --rm --network <segment>` | runs the tool over ssh on the declared attacker; any other image is refused, because Nova cannot boot a host, return its output and delete it |
| tested against | the live stack | fakes built from the published API reference and a local sshd; never a cloud |

The OpenStack adapter also removes the Docker socket from the platform, which
is a container escape path. What is left before it can run on a cloud (name
resolution, sensor placement, one attacker or four, roles by server name, how
the operator's address appears through a router, SNAT) is listed in
`docs/STATE.md` under "The substrate seam".

## Where requests come from

| Route | Sender | Source address in the alert | Marker |
|---|---|---|---|
| Terminal, HTTP | Kali, through `proxy:8081` | the proxy, on the chosen origin | added by the proxy |
| Terminal, raw TCP | Kali directly | Kali, on `edge` only | none |
| Console case, HTTP | the platform | the platform, on the chosen origin | added by the harness |
| Console case, tool | a throwaway `fsl-kali` container | that container, on the chosen origin | sqlmap `--headers=` |
| CLI run, browser | the host, through port 8080 | the `edge` bridge gateway | added by the harness; none from a browser |

The proxy is a `mitmdump` script. It sets `X-FSL-Case` from `/label/active`
and, when `/label/origin` names an address, forwards the request there with the
original `Host`. The platform writes both files with `docker exec`. There is no
TLS interception, so the proxy is an environment variable, not an enforcement
point: `curl --noproxy '*'` skips it.

Choosing an origin points traffic at the WAF's address on that segment with
`Host: shop.com`, because the `shop.com` alias exists on `edge` only. `rotate`
is a per-session round robin, not a random pick.

The WAF runs CRS at paranoia 1, anomaly threshold 5, in `DetectionOnly`, and
every Suricata rule is `alert`. Nothing in the range blocks a request.

The wiki is reached only through the application, by SSRF: Juice Shop fetches
`imageUrl` posted to `/profile/image/url`. No scripted case does this.

## Where alerts go

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-*
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

Elasticsearch is used for storage and for geoip at index time, which is why
there is no Logstash. Nothing uses its query engine beyond a time-range
search: the map and top-N tables are computed in Python over the SQLite copy,
and `src_geo.location` is mapped as two floats, not a `geo_point`. The world map
is an Equal Earth projection cut at 60 degrees south, generated by
`bin/worldmap`.

## How the scores are computed

**Objectives.** The platform reads the target's `/api/Challenges/` and uses its
`solved` flags and timestamps as they are; an unreachable target is a 503,
never a zero. The one objective the platform judges itself is
`internalRunbookRead`: a successful read of a secret wiki page in the wiki's
own access log. Its difficulty of 6 has no recorded reason. A session
snapshots the objectives already solved when it starts and never credits them.
Nothing clears the wiki log except the acceptance tests, so after one
successful SSRF later sessions start with the runbook already read.

A taken objective goes to the malicious case that started latest among those
running when the target stamped it. Attribution is by time only: a case's
`takes:` field is shown in the red console but not read by scoring.

`coverage` is detected difficulty over total difficulty, `null` when nothing
was taken. `damage` is undetected difficulty plus half of detected
difficulty; that ratio is where "an undetected loss counts double" lives.

**Detection.** A case is matched to alerts by one of two strategies, declared
per case:

- `marker`: the alert carries the case's `X-FSL-Case` value;
- `window`: the alert's source address matches the case's and its time falls
  within the case's start and end, with two seconds of slack each side.

There is no fallback from one to the other. A marker case whose marker was
lost should show up as a miss, not be covered for by the window. Terminal cases
carry both, and `?correlation=marker|window|both` on the score endpoint forces
a strategy so the two can be compared. A disagreement is a finding about the
scoring method, not the defence.

A case's `expect` is stored with the case when it is fired, so editing the
case file does not re-judge a finished session. Alert severity and rule type
are not used.

The score endpoint is read-only and keeps no history.

## Decisions

- **One case file for attacks and benign traffic.** Separate files make it easy
  to forget the benign half.
- **The harness refuses to send a rewritten path.** `requests` turns
  `/ftp/../../etc/passwd` into `/etc/passwd`; sending that would record an
  attack that never left and score the harness's failure as the defence's.
  Percent-encoding differences are allowed.
- **A tool that cannot start raises; a tool that exits non-zero counts.**
  sqlmap exits non-zero when it finds nothing, but its traffic went out.
- **Suricata shares the WAF's network namespace** rather than using host
  networking, whose meaning varies with the Docker host (on macOS it is the
  VM's). The WAF's interfaces carry both legs of every request.
- **No Kibana.** The blue console lists detections and Elasticsearch still
  answers ad-hoc queries. The production repo can add it back.
- **Elasticsearch is a single node with a 512 MB heap** so the whole stack fits
  in a default Docker memory allowance.
- **Missing data is an error, not a zero.** An unreachable Elasticsearch,
  target or substrate is a 503. A score with no benign cases, or with marker
  cases and no marker on any alert, carries a warning.
- **Console-fired cases send one case per HTTP connection**, while the CLI
  keeps one connection for a whole run. Measured on the same twelve cases,
  both gave identical scores and per-case alert counts. The acceptance tests
  drive the CLI, so the shared-connection case stays tested.
