# fsl-project-mvp design

Written: 2026-09-18

## 1. Purpose

An MVP that tests one hypothesis behind a cyber attack/defence training
platform. The production project lives in a separate repository.

The hypothesis:

> Red team attacks can be labelled with ground truth, and Suricata/ModSecurity
> alerts can be matched to those labels automatically, so false positives and
> negatives can be scored mechanically.

If that loop does not turn, then on-demand OpenStack instances, several wargame
apps, and an agent standing where a human stands are all beside the point. So
the MVP builds that loop and nothing else.

## 2. Scope

### In

- A single-host Docker Compose stack: the app under defence, a WAF, an IDS, a
  log pipeline, and the platform.
- A red team harness that runs attacks and records ground truth.
- The false-positive/false-negative scoring engine and its REST API.
- A blue team console: read, edit, validate and apply rules; read the score.
- Tests that check the acceptance criteria.

### Out

- OpenStack Heat templates. A thin layer wrapping one VM that runs the compose
  stack contributes nothing to testing the hypothesis. Build it in the
  production repo once the hypothesis stands.
- Wargame apps other than Juice Shop. The `wargame/` layout leaves the space.
- Authentication, multi-tenancy, session isolation. One user, one session.
- Agents. The structural rule — every UI action exists as a REST API first —
  leaves the space for them.

## 3. The core of it: correlating ground truth

Scoring only means something if "this alert belongs to that attack" can be
established. Matching on a time window alone collapses as soon as traffic
overlaps. Two strategies, declared per case.

### 3.1 The marker header (the main path)

The harness injects `X-FSL-Case: <case_id>` into every HTTP request.

- ModSecurity: its JSON audit log records the whole request header block, so
  the marker comes straight off the alert.
- Suricata: setting `dump-all-headers: request` on the `http` output of
  `eve-log` puts the headers on the **http event**. But an **alert event
  carries no HTTP request headers at all**, so each alert has to be paired with
  the http event of the same transaction to get its marker.

Three things established by measurement, on Suricata 8.0.7:

1. `custom: [X-FSL-Case]` has no effect whatsoever.
   `dump-all-headers: request` works.
2. An alert event and its http event pair up exactly by `tx_id`.
3. **The join key is `(flow_id, tx_id)`, not `flow_id`.** Under HTTP
   keep-alive, dozens of requests travel over one TCP flow. Joining on
   `flow_id` alone pins that flow's first marker onto every alert in it and
   attributes them all to the wrong case. The score stays plausible while being
   quietly false — this happened during the MVP, and ModSecurity alerts
   carrying their markers directly kept the totals looking right for a long
   time before anyone noticed.

One request can produce two alerts, because Suricata sits inside the WAF's
namespace and sees both legs: attacker to WAF, and WAF to Juice Shop. Scoring
folds to one verdict per case, so this does not matter.

ModSecurity writes `time_stamp` in ctime format, not ISO
(`Fri Sep 18 15:25:02 2026`). There is no timezone, so it is read as UTC.

State the limit plainly: a real attacker does not label their traffic. But the
side that produces ground truth is the platform itself, so this holds. It is a
scoring device for a training range, not a detection technique.

### 3.2 Time window and source IP (the fallback)

Cases that are not HTTP — an nmap port scan, say — cannot carry a header.
They are matched on the case's `started_at`/`ended_at` interval and its source
IP, with two seconds of slack at each end.

A case uses exactly one of the two strategies, declared as
`correlation: marker|window`. There is no implicit fallback: if a case that
should have carried a marker lost it, letting window correlation quietly cover
for that hides the bug.

### 3.3 Checking the request went out as declared

`requests` normalises `/ftp/../../../../etc/passwd` to `/etc/passwd` before
sending. If the attack never left while ground truth still records "attack
sent", the score lies — it counts as a miss when in fact the harness, not the
defence, failed.

Before sending, the harness compares the declared path against the path that
will actually go on the wire and raises when they differ. Differences in
percent-encoding (`%2e` → `.`, `%2f` → `%2F`) are the same path under RFC 3986
and are ignored; what is caught is structural rewriting, where `..` segments
disappear.

## 4. Scoring

Folded per case. One case is one verdict even if it sent many requests.

|           | alert    | no alert |
|-----------|----------|----------|
| malicious | TP       | FN       |
| benign    | FP       | TN       |

Reported: precision, recall, F1, false positive rate, and the raw
TP/FP/FN/TN.

**Benign cases are required, not optional.** Without normal traffic, a rule
that blocks everything scores perfectly. Scoring false positives is the reason
this platform exists, so normal traffic is a first-class citizen of the case
file, and the score API carries a warning field when there are no benign cases.

Alert severity and rule type are not used in scoring in the MVP. The only
question is whether an alert fired. Weighting comes after the hypothesis
stands.

## 5. Architecture

```
redteam harness ──attack/benign + X-FSL-Case──▶ nginx+ModSecurity+CRS ──▶ juice-shop
      │                                                  │
      │ POST cases (ground truth)              Suricata (sniffing the interface)
      ▼                                                  │
  platform (Django)  ◀── Filebeat ─▶ Elasticsearch ◀─ EVE JSON / ModSec audit
      ▲                                                  │
  blueteam console ──edit / validate / apply / reload────┘
```

The flow:

1. The red team opens a session and runs its cases, POSTing ground truth to the
   platform around each one.
2. Requests pass through nginx with ModSecurity and reach Juice Shop. Suricata
   sniffs the same traffic.
3. Filebeat ships Suricata's EVE JSON and ModSecurity's audit log to
   Elasticsearch.
4. On a scoring request the platform queries Elasticsearch for detections,
   correlates them with the cases, and computes the score.
5. When the blue team changes and applies a rule, the next run scores
   differently.

## 6. Components

### 6.1 platform — Django

The platform does the scoring, validates and applies rules, and serves the API.

Models:

- `Session` — one training session. `started_at`, `ended_at`, `scenario`.
- `Case` — one piece of ground truth. `session`, `case_id` (uuid), `name`,
  `malicious` (bool), `technique`, `correlation` (marker|window), `source_ip`,
  `started_at`, `ended_at`, `meta` (json).
- `Detection` — one alert pulled from Elasticsearch. `session`, `source`
  (suricata|modsecurity), `signature`, `severity`, `timestamp`, `src_ip`,
  `marker`, `raw` (json).
- `RuleSet` — one version of the Suricata rule file. `content`, `created_at`,
  `applied_at`, `validation_output`.
- `ScoreSnapshot` — a computed result. `session`, `tp/fp/fn/tn`, `precision`,
  `recall`, `f1`, `false_positive_rate`, `warnings`, `per_case` (json),
  `computed_at`.

API (`/api/`):

| Method | Path | |
|--------|------|---|
| POST   | `/sessions/` | start a session |
| GET    | `/sessions/{id}/` | read a session |
| POST   | `/sessions/{id}/close/` | end a session |
| POST   | `/sessions/{id}/cases/` | record ground truth |
| GET    | `/sessions/{id}/cases/` | list cases |
| POST   | `/sessions/{id}/ingest/` | pull detections from Elasticsearch |
| GET    | `/sessions/{id}/score/` | score (computed after ingest) |
| GET    | `/sessions/{id}/detections/` | list ingested alerts |
| GET    | `/rules/` | the current rule set |
| POST   | `/rules/validate/` | check syntax with `suricata -T`, apply nothing |
| POST   | `/rules/apply/` | on success, write the file and reload Suricata |

Split by concern:

- `platform/scoring/correlate.py` — matches cases to detections. Pure
  functions. In: a list of cases and a list of detections. Out: what matched
  per case. It knows neither Elasticsearch nor the database, so it unit-tests
  without the stack.
- `platform/scoring/metrics.py` — TP/FP/FN/TN and the metrics, from the match
  result. Pure functions as well.
- `platform/ingest/elastic.py` — queries Elasticsearch and normalises
  detections. The only file that knows Elasticsearch.
- `platform/rules/suricata.py` — rule validation (`suricata -T`) and reload.
  The only file that knows the Suricata process.

There is no `suricata` binary in the platform container. The platform has the
Docker socket mounted and runs
`docker exec suricata suricata -T -S <candidate>` to validate; on success it
writes the rule file into the shared bind mount and reloads the same way.

Mounting the Docker socket is a container escape path. It is accepted in a
local training lab, but the production repo has to remove it — a small sidecar
in front of Suricata that exposes nothing but validate and apply. Confining it
to `platform/rules/suricata.py` is exactly so that the swap touches one place.

That the scoring logic — `correlate` plus `metrics` — knows nothing about I/O
is the heart of this design. The hypothesis itself lives in those two files,
and it has to be checkable without the stack.

### 6.2 redteam — running attacks and recording ground truth

Cases are declared in `redteam/cases/*.yaml`.

```yaml
- name: sqli-login-bypass
  malicious: true
  technique: SQLi
  correlation: marker
  request:
    method: POST
    path: /rest/user/login
    json: {email: "' OR 1=1--", password: "x"}

- name: normal-product-search
  malicious: false
  technique: null
  correlation: marker
  request:
    method: GET
    path: /rest/products/search
    params: {q: "apple juice"}
```

`redteam/run.py` reads the cases, opens a session, sends each request with its
`X-FSL-Case` header, and POSTs ground truth to the platform.

External tools are declared with a `tool:` field. Rather than building the HTTP
request itself, the harness runs the tool as a one-shot container on the stack
network. A case writes its target as the `{target}` placeholder and the harness
substitutes the internal address, because a tool running inside the network
cannot reach the target through `localhost`.

The MVP supports one tool, sqlmap: correlating ground truth requires injecting
the marker, and `--headers` is the mechanism. Non-HTTP tools such as nmap need
window correlation instead, which requires knowing the tool container's IP.

Published sqlmap images are mostly amd64-only, so `redteam/Dockerfile` builds
one.

A tool that never runs at all — no image, no docker — raises. If no attack went
out while ground truth says it did, it counts as a miss when the harness, not
the defence, failed. A tool exiting non-zero is different: sqlmap does that
whenever it finds no injection point, and the attempt still went out, so ground
truth stands.

Attack and benign traffic share one case file. Separating them makes it easy to
forget the benign half.

### 6.3 blueteam — the defender's console

A Django app inside the platform. Tailwind CSS from a CDN, for the MVP only.

Three pages:

1. Score — TP/FP/FN/TN, the metrics, and a per-case verdict table with the
   misses and false alarms called out.
2. Alerts — the ingested detections and whether each matched a case.
3. Rules — the Suricata rule editor: validate, show the result, apply.

Every page calls the project's own REST API. No template touches the ORM. That
is how the rule "an agent takes a human's place later" is enforced rather than
merely intended.

### 6.4 deploy — the stack

`compose.yaml` services:

| Service | Image | |
|---------|-------|---|
| juice-shop | bkimminich/juice-shop | the app under defence |
| waf | owasp/modsecurity-crs:nginx | reverse proxy and WAF |
| suricata | jasonish/suricata | IDS |
| elasticsearch | elasticsearch:8 | log storage |
| filebeat | elastic/filebeat:8 | log shipping |
| platform | built locally (Django) | scoring, API, console |

- Suricata joins the WAF container's network namespace with
  `network_mode: "service:waf"` and sniffs its `eth0`; it needs `NET_ADMIN` and
  `NET_RAW`. `network_mode: host` is not used — under Docker Desktop on macOS
  that attaches to the Linux VM's namespace rather than the host's, so
  behaviour varies by platform. The WAF's `eth0` carries both the attacker-to-
  WAF and WAF-to-Juice-Shop legs, so everything needed is visible. This is the
  same reasoning as running containers inside a VM to avoid needing Neutron
  port mirroring, applied once more a layer down.
- Kibana was removed. The blue team console already lists detections and
  Elasticsearch stays, so curl still answers ad-hoc questions. It is genuinely
  useful to a defender digging through logs, but it contributes nothing to this
  repository's hypothesis. The production repo can bring it back.
- Elasticsearch is a single node with security disabled, for the MVP only:
  `discovery.type=single-node`, `ES_JAVA_OPTS=-Xms512m -Xmx512m`. The whole
  stack has to come up inside a default Docker Desktop memory allowance.
- Filebeat reads the EVE JSON and the ModSecurity audit log through shared
  volumes. GeoIP is an Elasticsearch ingest pipeline. There is no Logstash.
- Rule files and logs are bind mounts rather than named volumes, because the
  platform writes the rules and Suricata reads them.

## 7. Error handling

- Elasticsearch not up yet, or no index → `/ingest/` returns 503 and the
  reason. It does not turn the score into a zero. No data and no detection are
  different things.
- Rule validation fails → `/rules/apply/` returns 400 and the raw
  `suricata -T` output. A rule that failed validation is never written to the
  file.
- Reload fails → roll back to the previous rule set and return the reason.
- No benign cases → a warning on the score.
- A case declared a marker but no detection carries one → a warning on the
  score. Silently counting them all as misses would read a broken pipeline as
  a detection failure.

## 8. Tests

Three layers.

1. **Unit** — `correlate.py`, `metrics.py`. No stack needed. Synthetic case and
   detection lists covering every TP/FP/FN/TN boundary: marker correlation,
   window correlation, duplicate alerts, the edges of the time window.
2. **API** — Django's test client, with Elasticsearch and Suricata mocked. The
   round trip: session, case, ingest, score.
3. **Acceptance** (`test/`) — against the real compose stack, checking the
   criteria below. Bring the stack up, run `redteam/run.py`, read the score.

## 9. Acceptance criteria

1. `docker compose up -d` brings every service up healthy.
2. `python redteam/run.py` runs to completion and prints a session id.
3. `GET /api/sessions/{id}/score/` returns a score with TP > 0 and TN > 0 —
   attacks that are detected and normal traffic that is not.
4. Adding and applying one rule from the blue team console moves the next run's
   score in the predicted direction.
5. `test/` checks 1 through 4 automatically.

Criterion 3 is where this MVP can be falsified. TP of zero means alert-to-case
correlation failed. TN of zero means scoring false positives is meaningless.
