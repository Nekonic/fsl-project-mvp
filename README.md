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
hands the run a file in `FSL_ACCEPTANCE_SESSIONS`, the run writes there the id
of every session it creates and closes them when it is done, and verify then
deletes only the closed sessions that file lists (`bin/prune --ids`), so
nothing a person made or still has open is touched. `bin/prune` does it by
hand:

```bash
bin/prune --keep 20           # says what it would delete
bin/prune --keep 20 --apply   # deletes it
bin/prune --ids run.txt --apply # only the closed sessions whose ids run.txt lists
```

## The store

Everything the platform records — sessions, cases, detections, objectives,
rule sets, suppressions — is one SQLite file, `/data/db.sqlite3` in the
`platformdata` volume (`fsl_platformdata` to Docker), mounted into
`fsl-platform`. The raw logs stay in Elasticsearch's volume, `esdata`, which
this does not copy.

`bin/backup` copies it while the platform keeps serving:

```bash
bin/backup      # backups/db-<UTC time>.sqlite3, then its row counts
```

It runs SQLite's online backup API inside the platform, so the copy holds every
committed transaction and nothing of one still in progress, and the bytes come
back over the `docker exec` pipe; no copy is left inside the container. The
file gets its `.sqlite3` name only after `PRAGMA integrity_check` has passed on
the host. `backups/` is ignored by git. If the platform is down, or the copy
fails the check, it exits 1, says why and keeps nothing. A store the platform
has not yet migrated to the checkout, such as one taken between a pull and the
restart that applies the pull's migration, is kept all the same; a table it does
not have yet is listed as `absent`. A platform that does
not run in Docker is reached by pointing `FSL_PLATFORM_EXEC` at any command that
runs `python -` with the platform's settings importable; the default is
`docker exec -i fsl-platform python -`.

Restoring is by hand. Stop the platform so nothing writes, copy the file into
the volume as the platform's own user, and start it again:

```bash
docker compose stop platform
docker run --rm --network none -v fsl_platformdata:/data \
  -v "$PWD/backups:/backups:ro" fsl-platform \
  sh -c 'rm -f /data/db.sqlite3-journal && cp /backups/db-20260925T020000Z.sqlite3 /data/db.sqlite3'
docker compose start platform
```

The copy runs in the platform's image because that image runs as the user the
store belongs to; `docker cp` would leave the file owned by root and the
platform unable to write it. A `-journal` left by the old file must go with it,
or SQLite would replay it onto the restored one. On start the platform applies
any migration the backup predates.

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
`DEBUG=1` (it answers only to `localhost`, `127.0.0.1` and `[::1]` unless
`DJANGO_ALLOWED_HOSTS` names more), the Docker socket is mounted into the platform
container so it can validate rules, and the Kali shell on 7681 is an
unauthenticated root shell. Both of those last two are container escape paths.
None of this belongs on a network you do not own.
