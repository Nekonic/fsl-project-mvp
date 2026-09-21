# Architecture

The mechanism: what the range is made of, how traffic and evidence move through
it, and how the two numbers are computed. The working rules are in `CLAUDE.md`.
What is true of the running system today is in `docs/STATE.md`.

Every structural claim carries the file that proves it. Where a document in this
repo disagrees with the code, the code is the fact; those are collected in §8.

---

## 1. What the range is made of

Nine compose services on six Docker networks. `compose.yaml` is the whole
definition: no Terraform, no provisioning step, no router.

| Service | Image | Networks | Host port |
|---|---|---|---|
| `fsl-juice-shop` | `bkimminich/juice-shop` | estate | — |
| `fsl-wiki` | `nginx:alpine`, alias `wiki.internal` | estate | — |
| `fsl-waf` | `owasp/modsecurity-crs:nginx` | edge, edge-br, edge-hk, edge-kp, estate | 8080 → 80 |
| `fsl-suricata` | `jasonish/suricata` | none of its own | — |
| `fsl-elasticsearch` | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-filebeat` | `filebeat:8.15.0` | mgmt | — |
| `fsl-kali` | built from `deploy/kali` | edge | 7681 |
| `fsl-proxy` | built from `deploy/proxy` | edge, edge-br, edge-hk, edge-kp | — |
| `fsl-platform` | built from `./platform` | all six | 8000 |

| Network | Subnet | `fsl.segment` | `fsl.origin` |
|---|---|---|---|
| `edge` | 5.188.10.0/24 | Internet | Moscow, Russia |
| `edge-br` | 177.54.144.0/24 | Internet | Sao Paulo, Brazil |
| `edge-hk` | 103.152.220.0/24 | Internet | Kwai Chung, Hong Kong |
| `edge-kp` | 175.45.176.0/24 | Internet | North Korea |
| `estate` | 172.30.0.0/24 | Application estate | — |
| `mgmt` | 172.31.0.0/24 | Management | — |

Labels are at `compose.yaml:3-48`. A segment is **outside** if and only if its
network carries a non-empty `fsl.origin` label — the only definition anywhere
(`platform/range/ports.py:38-39`, read off the network at
`platform/range/docker.py:80`) — and that label's text is the origin name the
console shows (`platform/attacker.py:38`).

Only the subnets are fixed. No service is given an `ipv4_address`, so every
address is DHCP-assigned and changes on recreate. `Substrate.describe()` reads
live addresses once per request — `platform/range/docker.py:20-35` for Docker,
the only file that asks it — which is why the API answers 503 rather than a
stale picture when the substrate is unreachable
(`platform/api/views.py:283-285`). `platform/topology.py` shapes that reading
into the response and makes no call of its own.

Three containers are multi-homed: the platform (all six), the WAF (four outside
plus estate), the proxy (four outside). `platform/topology.py:5-18` marks a
node as a crossing when it sits on both sides, so two are drawn as ways in: the
WAF and the platform itself. "The WAF is the only way across" is true of the
attacker's traffic, not of the stack.

Segmentation is Docker network membership. There is no firewall, no iptables
rule and no ACL anywhere in `deploy/`. The guarantee is what
`test/test_segmentation.py:30-64` asserts against the live stack: Kali cannot
reach `juice-shop:3000`, Kali can reach `shop.com`, and they share no network.

```
 OUTSIDE  (networks carrying fsl.origin)

 +---------------------------------------------------------------+
 | edge      5.188.10.0/24     "Internet" / Moscow, Russia        |
 |   kali --HTTP, http_proxy env--> proxy :8081 ------------+     |
 |      \                                                   |     |
 |       \--raw TCP (nmap, nc): no proxy, kali's own src ---+     |
 |   platform --console-fired case, Host: shop.com----------+     |
 |                                                          v     |
 |                              waf  (aliases waf-edge, shop.com) |
 +---------------------------------------------------------------+
 +------------------+ +------------------+ +--------------------+
 | edge-br          | | edge-hk          | | edge-kp            |
 | proxy, platform  | | proxy, platform  | | proxy, platform    |
 | waf =waf-edge-br | | waf =waf-edge-hk | | waf =waf-edge-kp   |
 +------------------+ +------------------+ +--------------------+
   no kali here: the "direct" route exists on edge only
   no shop.com here either: that alias is on edge alone
        |  HTTP :80, Host: shop.com, X-FSL-Case stamped by proxy
        v
 ########## fsl-waf #############################################
 #  nginx + ModSecurity CRS, DetectionOnly (never blocks)       #
 #  five interfaces: eth0 edge, eth1 br, eth2 hk, eth3 kp,      #
 #                   eth4 estate                                #
 #  fsl-suricata shares this netns (network_mode: service:waf)  #
 #  and sniffs all five with af-packet => sees BOTH legs        #
 ################################################################
        |  proxied to BACKEND http://juice-shop:3000
        v
 +---------------------------------------------------------------+
 | estate  172.30.0.0/24  (inside)                               |
 |   waf --> juice-shop --SSRF (imageUrl=...)--> wiki            |
 |   platform                                                    |
 +---------------------------------------------------------------+
 +---------------------------------------------------------------+
 | mgmt    172.31.0.0/24  (inside)                               |
 |   filebeat --bulk--> elasticsearch :9200                      |
 |   platform --_search fsl-logs-*--> elasticsearch              |
 +---------------------------------------------------------------+

 OFF-NETWORK EDGES (bind mounts, not traffic):
   suricata eve.json --> deploy/suricata/logs --> filebeat
   modsec audit.log  --> deploy/nginx/logs    --> filebeat
   wiki read.log     --> deploy/wiki/logs     --> platform (ro)
   platform --> data/label/{active,origin} --> proxy
   platform --> ./data:/data --> db.sqlite3
   platform --> /var/run/docker.sock --> docker run, topology, reload
```

The eth0–eth4 mapping holds on the running stack and follows compose's network
priorities (`compose.yaml:91-106`), but nothing enforces it:
`deploy/suricata/suricata.yaml:26-46` hard-codes the interface names and the
association is an inference about Docker's attach order.

---

## 2. The path a request takes

Three things send traffic at the target, from three addresses, and a fourth
address shows up in the alerts.

| Route | Sent by | Source address in the alert | Marker |
|---|---|---|---|
| Terminal, HTTP | Kali via `http_proxy=http://proxy:8081` | the proxy's address on the current origin | stamped by the proxy |
| Terminal, raw TCP | Kali directly (nmap, nc) | Kali's own address, edge only | none |
| Console case | the platform container | the platform's address on that origin | set by the harness, or by sqlmap's `--headers=` |

`compose.yaml:184-188` sets the proxy env on Kali only, so `harness.fire` inside
the Django process goes straight to the WAF (`platform/api/views.py:408-426`).

The fourth address is the docker bridge gateway on `edge`: anything arriving
through the published host port 8080 rather than from a container — a browser,
`curl localhost:8080` — reaches the WAF from there, and
`platform/api/views.py:207-221` files it under the edge segment with no host name
and no geo.

Two different addresses are both called "the attacker". `GET /api/attacker/`
reports the proxy's address, because `ATTACKER_SOURCE_CONTAINER` is `fsl-proxy`
(`platform/fsl/settings.py:48`). A console-fired case does not come from there.
This matters only to window correlation, which matches on address.

**The proxy.** `deploy/proxy/stamp.py:13-28` does two things per request: if
`/label/active` is non-empty it sets `X-FSL-Case` to its contents; if
`/label/origin` is non-empty it rewrites the upstream host to `waf-<origin>`,
putting the client's original `Host` back. No TLS interception is configured, so
the proxy is an environment variable and not an enforcement point —
`curl --noproxy '*'` skips it, which is what `test/test_segmentation.py:18` does.
Both label files are written by the platform through the shared `./data/label`
mount (`platform/attacker.py:67-77`), the only channel between the two.

**Origins.** `platform/attacker.py:21-47` derives the list from the same
reading of the range: the segments the proxy stands on that carry an
`fsl.origin` label. Choosing one writes
the id to `/label/origin` for the terminal, and makes `fire_attack` target
`http://waf-<id>` with a `Host` header of `PUBLIC_TARGET_URL`'s netloc so the
target still sees `shop.com` (`platform/api/views.py:408-420`). That re-adding is
necessary because the `shop.com` alias is on `edge` alone (`compose.yaml:92-103`).
`origin: "rotate"` is a round robin on `session.cases.count()`, not a random pick
(`platform/api/views.py:457-466`).

**Through the WAF.** It listens on 80 and proxies to `juice-shop:3000`.
ModSecurity runs CRS at paranoia 1, anomaly threshold 5, in `DetectionOnly` — it
never blocks. The one local override stops CRS rule 920273 firing on the marker
header the platform itself adds (`deploy/nginx/modsecurity-overrides.conf:2`).

**The estate is reached only through the application.** The documented path to
the wiki is SSRF: post `imageUrl=http://wiki.internal/runbooks/deploy.html` to
`/profile/image/url` and juice-shop fetches it (`test/test_inside.py:69-97`). No
case in `redteam/cases/default.yaml` does this; from the console it is a
hand-typed terminal action.

---

## 3. The path an alert takes

```
[kali shell] --http_proxy--> [mitmdump stamp.py] ---+
   X-FSL-Case read from /label/active               |
[harness / sqlmap] -- sets X-FSL-Case itself ------>+
                                                    v
                    [nginx :80 + ModSecurity DetectionOnly]
                          |                          |
        audit.log (JSON, Serial)              wire traffic
        deploy/nginx/logs/                          |
              |                 [Suricata, netns of waf, af-packet]
              |                 eve.json: alert + http events
              |                 deploy/suricata/logs/
              +--------> [Filebeat] <----------------+
                 filestream + ndjson; adds fsl_source
                            |
                            v
          [ES 8.15] index fsl-logs-YYYY.MM.dd
                    pipeline fsl-geoip: src_ip -> src_geo
                            |
      POST /api/sessions/<id>/ingest/   (blue console timer)
                            |
              elastic.fetch: _search on fsl-logs-*,
              @timestamp range, size 5000, sort asc
                            |
              normalize_all: fsl_source picks the parser;
              (flow_id, tx_id) join lifts the marker
              from the http doc onto the alert doc
                            |
                            v
              [SQLite] Detection(session, detection_id)
```

**The sensor sees both legs.** `network_mode: "service:waf"` puts Suricata in the
WAF's namespace (`compose.yaml:137`), so af-packet on eth0–eth4 is the WAF's own
five interfaces. One proxied request is seen twice: client→WAF on an edge
interface, WAF→juice-shop on estate. `HOME_NET` covers all six subnets and the
rules are written `$EXTERNAL_NET any -> $HOME_NET any`, so both legs alert.
`deploy/suricata/rules/local.rules` holds four `alert` rules, sids 9000001–9000004
(SQLi in URI, SQLi in body, XSS, path traversal). None is a `drop`.

**Why the marker needs a join.** The eve log emits two event types: `alert`
(payload off, http on) and `http` with `dump-all-headers: request`
(`deploy/suricata/suricata.yaml:17-24`). Only the second dumps headers, so an
alert document carries an `http` object **without** `http.request_headers` and can
never yield a marker on its own. `platform/ingest/elastic.py:60-80` therefore
builds a map from `(flow_id, tx_id)` to the marker found on the http documents and
copies it onto the alerts. Filtering the fetch to `event_type: alert` would leave
every alert unattributed and collapse the score.

**Caps.** `elastic.fetch` takes `size=5000` and sorts ascending, and nothing
compares `hits.total` against it (`platform/ingest/elastic.py:20-56`). The query
has no `event_type` filter, so http records count against the same 5000. A busy
session silently loses its newest evidence.

**What Elasticsearch is used for, and what it is not.** The ingest pipeline does
geoip at index time (`deploy/elastic/ingest-pipeline.json`), which is why there is
no Logstash; a failed lookup sets `src_geo.error` rather than dropping the doc.
Nothing else uses Elasticsearch's query engine: there is no aggregation anywhere
in `platform/`, so the map and the four top-N tables are recomputed in Python over
the Django copy (`platform/api/views.py:191-251`). `src_geo.location` is mapped as
two floats rather than a `geo_point` — there is no index template — so the geo
aggregations would not work as things stand.

---

## 4. The two numbers

`GET /api/sessions/<id>/score/` is the only place they meet
(`platform/api/views.py:639-682`). It is GET-only and writes nothing;
`ScoreSnapshot` was deleted in migration `0004`, so there is no score history.

### Number one — what the red team took

Computed by the pure function `scoreboard.tally()` (`platform/scoreboard.py:79-98`)
and served under `objectives`.

| Quantity | Formula |
|---|---|
| `coverage` | `detected_difficulty / total_difficulty`, and `1.0` when the total is 0 |
| `damage` | `undetected_difficulty + 0.5 * detected_difficulty` |

Coverage weighs by difficulty, not count (`platform/tests/test_scoreboard.py:36`).
An untouched session reads coverage 100% and damage 0. "A lost objective nobody
detected counts double" lives in `damage`: there is no `* 2`, only the 1.0
against 0.5 ratio.

**The target judges itself.** `platform/objectives.py:52-65` GETs the target's
`/api/Challenges/` and reads each challenge's own `solved` flag and `updatedAt`.
The platform applies no rule of its own; an unreachable target raises
`ObjectivesUnavailable` and the API answers 503 rather than reporting zero.

The exception is `internalRunbookRead`, which the platform judges by scanning the
wiki's nginx access log for `WIKI_SECRET_PATH` (`platform/objectives.py:16-50`).
The ground truth is still orthogonal to the detector — it is the wiki's own
record — but the judging is the platform's. Its difficulty is hard-coded to 6 and
its category to "Lateral Movement"; the code gives no reason for 6.

**Baseline.** A session snapshots the already-solved keys at creation
(`Session.baseline`) and never credits them. Nothing in `platform/` truncates the
wiki's `read.log`, so after one successful SSRF every later session baselines
`internalRunbookRead` out until the file is cleared — which `test/conftest.py:47-50`
does and nothing else does.

**Attribution is purely temporal.** `scoreboard.attribute()` keeps attempts within
`started_at - 100ms .. started_at + 2min` of the deed and takes the latest
(`platform/scoreboard.py:47-55`). No candidate means the breach is built with
`detected=False`. A case's `takes:` key is displayed but nothing in the scoring
path reads it, so a case can be credited with an objective it never claimed.

### Number two — what the defence got wrong

`platform/scoring/metrics.py:5-38`, from the correlation result alone:

```
tp = malicious AND detected      fp = benign AND detected
fn = malicious AND NOT detected  tn = benign AND NOT detected
precision = tp/(tp+fp)   recall = tp/(tp+fn)   f1 = 2pr/(p+r)
false_positive_rate = fp/(fp+tn)
```

Every ratio returns `0.0` on a zero denominator.

**One case is one verdict.** `correlate()` collects every matching detection id
per case and sets `detected = bool(hits)` (`platform/scoring/correlate.py:32-43`);
`platform/scoring/metrics.py:6-9` counts one per `CaseMatch`.
`sqlmap-boolean-blind` produces many alerts and counts once. The converse is
unconstrained: each case is scanned against the full detection list independently,
so two window cases whose intervals overlap both claim the same alert.

**Two correlation strategies.** `marker` matches on the `X-FSL-Case` header;
`window` matches on source address and time. Only terminal cases carry both, so
only they can disagree, and a disagreement is a result about the scoring method
rather than about the defence. `fire_attack` does not validate the `correlation`
value it is given; `session_cases` does (`platform/api/views.py:488-490,534-539`).

**Corroboration.** A case declares `expect`, a substring the raising signature
should contain. An alert that does not mention the attack's own mechanism is
reported `corroborated: false` — still a TP, but flagged, so a rule set that
catches everything for unrelated reasons does not score as well as one that works.

### What keeps them apart

They are returned side by side and never combined. A defence that blocks
everything scores perfectly on number two and loses every objective on number one.

---

## 5. The console and the API

Four screens, all fetching `/api/` from the browser: `/` (start or resume),
`/session/<id>/` (the two links), `/red/<id>/`, `/blue/<id>/`
(`platform/fsl/urls.py:32-35`). The REST-first rule holds: the only
server-rendered strings are the `<title>` blocks.

A **session** is a time window plus a baseline. Open means new traffic is
correlated into it; closed sets `ended_at` and nothing else changes.
`GET /api/sessions/` takes `?state=open|closed` and `?limit=`, capped at 25
(`platform/api/views.py:97-114`); the landing page asks for open sessions
uncapped and the last 10 closed ones, so a running session is never hidden behind
finished ones.

Django models are `Session`, `Case`, `Detection`, `Objective`, `RuleSet`,
`Suppression`. `Detection.raw` holds a copy of the Elasticsearch document, so
every alert exists twice.

**The string table.** Every visible string is a key in
`platform/console/templates/console/strings.html`, which holds `en` and `ko`
tables and the `t()` helper. Markup carries `data-t="key"` on an empty element and
`applyLanguage()` fills it on load; a missing key renders as the key itself rather
than blank. Korean lives in that file and nowhere else, which
`platform/tests/test_strings.py` enforces along with key-set parity, placeholder
parity, and a check that no string was left untranslated.

---

## 6. The ratchet

`bin/measure` prints five numbers. `core_loc` (`platform/scoring/`,
`platform/ingest/`, `platform/rules/`, `redteam/harness.py`), `dependencies` and
`services` are gated and may only fall. `tests` counts `def test_` definitions and
may only rise. `product_loc` is reported and not gated. Docs, `bin/` and tests are
excluded from both LOC numbers.

`bin/verify` runs unit and API tests, then — unless `--fast` — checks the stack is
up, validates the Suricata config through the API, runs `test/` against the live
stack, prunes old sessions, and refuses the change if a gated number grew or the
test floor fell. `metrics.json` holds the baseline.

`bin/prune` deletes all but the newest N sessions and everything cascading off
them. It is a dry run unless given `--apply`, and `bin/verify` runs it after a
full pass.

---

## 7. Absences

- **No score history.** `ScoreSnapshot` was removed; nothing records what a
  session scored before a rule changed.
- **No blocking.** ModSecurity is `DetectionOnly` and every Suricata rule is
  `alert`. Nothing in the range ever stops a request.
- **No code execution on the target.** The estate is reached through the
  application, so there is no foothold and nothing to escalate.
- **No operator log of what was typed.** The proxy sees HTTP requests; nothing
  sees `nmap`. A window case records that an attack happened, not what it was.
- **No aggregation in Elasticsearch**, and no `geo_point` mapping (§3).
- **One user, one session.** No accounts, and nothing stops two people opening
  the same session.
- **The console needs the internet.** `platform/console/templates/console/base.html:7` loads Tailwind from
  `cdn.tailwindcss.com` on every page, so an isolated range renders unstyled.

---

## 8. Where the repo's own docs are not true

| Claim | Where | Reality |
|---|---|---|
| "`bin/measure` prints four numbers" | `CLAUDE.md` | Five. |
| The no-comments rule exempts only `deploy/suricata/rules/` | `CLAUDE.md` | `deploy/nginx/allow-low-port.sh:2-12` is an eleven-line rationale comment in a non-exempt file. It explains why the image's port check is overridden and is worth keeping; the rule has not caught up with it. |
| "Two browser windows" | `CLAUDE.md`, `README.md` | Four screens; the console calls them consoles, not windows. |

`docs/superpowers/specs/` holds the design documents. They are a finished
historical record, not a description of the current system.
