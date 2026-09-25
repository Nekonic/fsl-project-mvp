# fsl-project-mvp

A cyber attack/defence training range. A red team attacks OWASP Juice Shop, a
blue team defends it with Suricata and ModSecurity, and the platform scores
what each side achieved. This repo is the throwaway prototype; the production
project lives elsewhere.

- `CLAUDE.md`: what the repo is for, how the score works, the working rules
- `docs/ARCHITECTURE.md`: how the range is put together
- `docs/THREAT-MODEL.md`: what the range emulates and what it leaves out
- `docs/STATE.md`: where the work stands

## Bringing it up

On an arm64 host run Docker natively: Elasticsearch's amd64 JVM dies with
SIGSEGV under x86 emulation.

```bash
colima start --profile fsl
DOCKER_GID=$(bin/docker-gid) docker compose up -d --build
python3 -m venv .venv && .venv/bin/pip install -r platform/requirements.txt
```

Register the Elasticsearch ingest pipeline once. It adds geo data to source
addresses.

```bash
curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip \
  -H 'Content-Type: application/json' \
  --data-binary @deploy/elastic/ingest-pipeline.json
```

| Port | |
|---|---|
| 8000 | the console, and `/api/` |
| 8080 | the target, through the WAF |
| 7681 | the attacker's Kali shell, framed inside the red console |
| 9200 | Elasticsearch |

Every port is published on `127.0.0.1` only. Inside the range the target is
`http://shop.com` on port 80.

## Running a round

Open http://localhost:8000, start a session, and open the red and blue consoles
side by side. The language button in the header switches between English and
Korean.

- **Red** has the objectives, a Kali shell and the scripted cases. A fired
  case is labelled on the way out. Alternatively name a case, press start,
  work in the shell and press stop: everything sent in between is attributed
  to that name.
- **Blue** has a dashboard, live alerts, the scoreboard and the Suricata rules.
  It ingests on a timer. Any alert opens the Elasticsearch record behind it.

The scripted cases can also be fired from the command line, as the acceptance
tests do:

```bash
.venv/bin/python redteam/run.py
```

## Checking it

```bash
bin/verify --fast     # unit and API tests and the metrics, no stack needed
bin/verify            # also the acceptance tests in test/, against the live stack
```

The full run restarts the platform and resets the target, the rules and the
attacker's origin, so do not run it against a stack someone is using. It
deletes only the sessions its own run created. `bin/prune` deletes sessions by
hand and is a dry run without `--apply`:

```bash
bin/prune --keep 20 --apply      # keep the newest 20
bin/prune --ids FILE --apply     # only the closed sessions FILE lists
```

After adding a Tailwind class to a template, run `bin/build-css`. The
stylesheet is generated and committed so the console renders without internet
access, and a test fails when it is out of date.

## Backup and restore

The platform's store (sessions, cases, detections, objectives, rule sets,
suppressions) is one SQLite file, `/data/db.sqlite3` on the `fsl_platformdata`
volume. Raw logs stay in Elasticsearch's `esdata` volume and are not backed up.
`docker compose down -v` deletes both.

```bash
bin/backup      # writes backups/db-<UTC time>.sqlite3 while the platform serves
```

It uses SQLite's online backup API, checks the copy with `PRAGMA
integrity_check`, and keeps nothing if either step fails. To reach a platform
that is not in Docker, set `FSL_PLATFORM_EXEC` to a command that runs
`python -` with the platform's settings importable.

Restore by hand, with the platform stopped:

```bash
docker compose stop platform
docker run --rm --network none -v fsl_platformdata:/data \
  -v "$PWD/backups:/backups:ro" fsl-platform \
  sh -c 'rm -f /data/db.sqlite3-journal && cp /backups/db-20260925T020000Z.sqlite3 /data/db.sqlite3'
docker compose start platform
```

The copy runs in the platform's image so the file belongs to the platform's
user; `docker cp` would leave it owned by root and unwritable. The old
`-journal` has to go, or SQLite would replay it onto the restored file. On
start the platform applies any migration the backup predates. This procedure
has not been run yet.

## Local lab only

Elasticsearch runs without security and Django with `DEBUG=1`. Django answers
only to `localhost`, `127.0.0.1` and `[::1]` unless `DJANGO_ALLOWED_HOSTS`
names more; to use the range from another machine, tunnel to it. The Docker
socket is mounted into the platform, and the Kali shell on 7681 is an
unauthenticated root shell. Both are container escape paths.
