# fsl-project-mvp

A cyber attack/defence training range. A red team attacks OWASP Juice Shop, a
blue team defends it with Suricata and ModSecurity, and the platform scores
what each side achieved.

The production project lives in a separate repository. This one exists to find
out what the thing should be before that one pays for it. Things get built
here, measured, and thrown away.

**The score is two numbers, and the first one is the point.** Juice Shop flips
its own `solved` flag when a challenge falls, so the target — not the platform
— decides whether an attack achieved anything. That is the first number: which
objectives were lost, and whether the defence saw each one go. The second is
TP/FP/FN/TN per attack case. It is reported beside the first, never folded into
it: a defence that blocks everything scores perfectly on the second and loses
every objective on the first.

The console's stylesheet is generated from its own templates and committed, so
the range needs no internet to render: `bin/build-css` regenerates it after a
class is added, and a test says when that has been forgotten.

`CLAUDE.md` is the working brief. `docs/ARCHITECTURE.md` is how it is put
together. `docs/THREAT-MODEL.md` is which threat the cases stand for and which
five of the eight life cycle stages never happen here. `docs/STATE.md` is where
the work currently stands.

## Bringing it up

On an arm64 host, run Docker natively — Elasticsearch's amd64 JVM dies with
SIGSEGV under x86 emulation.

```bash
colima start --profile fsl
DOCKER_GID=$(bin/docker-gid) docker compose up -d --build
```

Register the Elasticsearch ingest pipeline once. It attaches geo data to the
source address, which is why there is no Logstash.

```bash
curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip \
  -H 'Content-Type: application/json' \
  --data-binary @deploy/elastic/ingest-pipeline.json
```

| | |
|---|---|
| http://localhost:8000 | the console, and `/api/` |
| http://localhost:8080 | the target, through the WAF |
| http://localhost:7681 | the attacker's shell, framed inside the red console |
| http://localhost:9200 | Elasticsearch |

Inside the range the target is `http://shop.com` on port 80 — no appliance name
in the URL, no port to remember. That alias lives on the `edge` network, where
Kali is (`compose.yaml:94`); the other three attacker networks reach the same
WAF through the stamping proxy.

## Running a round

Open http://localhost:8000, start a session, then open the red and blue
consoles side by side.

- **Red** holds the objectives, a Kali shell, and the scripted cases. Fire a
  case and it is labelled on the way out. Or name a case, press start, work in
  the shell, press stop — everything sent in between is attributed to that name.
- **Blue** is the defender's console: dashboard, live alerts, scoreboard, and
  the Suricata rules. It ingests on a timer, so alerts arrive while you watch.
  Any alert opens the whole Elasticsearch record behind it.

The console is bilingual. The language button in the header switches between
English and Korean; every visible string lives in
`platform/console/templates/console/strings.html`.

The scripted cases can also be fired from the command line, which is what the
acceptance tests do:

```bash
.venv/bin/python redteam/run.py
```

There are 16 cases — 10 attacks and 6 benign. The benign ones are not padding:
without normal traffic a rule that blocks everything scores perfectly.

## Checking it

```bash
bin/verify --fast     # unit and API tests, and the metrics, without the stack
bin/verify            # the above, plus the acceptance tests against a live stack
```

`test/` is the acceptance criteria, over HTTP only. `TP > 0` and `TN > 0` are
where this can be falsified: attacks are detected, benign traffic passes.

`bin/verify` also refuses any change that grows a gated number or shrinks the
test floor. `bin/measure` prints the numbers; `CLAUDE.md` explains what each
one is for.

Sessions accumulate — every acceptance run creates about twenty. `bin/verify`
records the newest session before the run and afterwards deletes only the
closed sessions newer than it, so nothing a person made or still has open is
touched. `bin/prune` does it by hand:

```bash
bin/prune --keep 20           # says what it would delete
bin/prune --keep 20 --apply   # deletes it
bin/prune --after 812 --apply # only the closed sessions newer than 812
```

## Layout

| | |
|---|---|
| `platform/scoring/` | the hypothesis: pure functions, no I/O, no Django |
| `platform/ingest/` | the only code that knows Elasticsearch |
| `platform/rules/` | the only code that knows the Suricata process |
| `platform/api/`, `platform/console/` | the REST surface and the four screens |
| `redteam/` | attack execution and ground truth |
| `wargame/` | the applications under defence |
| `deploy/`, `compose.yaml` | the stack |
| `bin/` | verify, measure, prune, and the world map generator |
| `test/` | the acceptance criteria |
| `docs/` | architecture, threat model, state, vocabulary |

`platform/` is not a Python package — `platform` is a stdlib module name. Run
Python with `platform/` as the working directory.

## The structural rule

Every action in the UI exists as a REST API first. Console templates fetch
`/api/` from the browser and never receive server-rendered values. When an
agent takes a human's place later, there should be nothing to change.

## A warning

Local lab only. Elasticsearch runs with security disabled, Django with
`DEBUG=1` and `ALLOWED_HOSTS=*`, the Docker socket is mounted into the platform
container so it can validate rules, and the Kali shell on 7681 is an
unauthenticated root shell. Both of those last two are container escape paths.
None of this belongs on a network you do not own.
