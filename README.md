# fsl-project-mvp

A cyber attack/defence training range. A red team attacks a web app, a blue
team defends it with Suricata and ModSecurity, and the platform scores the
defence by its false positives and false negatives.

The production project lives in a separate repository. This one exists to test
a hypothesis:

> **Red team attacks can be labelled with ground truth, and Suricata/ModSecurity
> alerts can be matched to those labels automatically, so false positives and
> negatives can be scored mechanically.**

The design is in
[`docs/superpowers/specs/2026-09-18-fsl-mvp-design.md`](docs/superpowers/specs/2026-09-18-fsl-mvp-design.md).

## Bringing it up

```bash
docker compose up -d --build
```

| | |
|---|---|
| http://localhost:8000 | blue team console, and `/api/` |
| http://localhost:8080 | the target, behind the WAF |
| http://localhost:7681 | the attacker's shell, framed in the red window |
| http://localhost:9200 | Elasticsearch |

Register the Elasticsearch ingest pipeline once:

```bash
curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip -H 'Content-Type: application/json' --data-binary @deploy/elastic/ingest-pipeline.json
```

On an arm64 host (Apple Silicon), Docker has to run arm64 natively.
Elasticsearch's amd64 JVM dies with SIGSEGV under x86 emulation.

## Running a round

```bash
python redteam/run.py
```

It prints a session number. Enter that number in the console at
http://localhost:8000 to see TP/FP/FN/TN and the verdict for every case.

## Checking the acceptance criteria

```bash
python -m pytest test/ -v
```

These check section 9 of the design document as written. `TP > 0` and
`TN > 0` are where this MVP can be falsified.

The unit and API tests run without the stack:

```bash
cd platform && python -m pytest tests -q
```

`bin/verify` runs all of it, plus the size ratchet — see `CLAUDE.md`.

## Layout

| | |
|---|---|
| `deploy` | stack configuration |
| `wargame` | the apps under defence, one directory each |
| `redteam` | running attacks, and recording what was attacked and when |
| `blueteam` | the defender's console (`platform/blueteam`) |
| `platform` | scoring, rule validation and application, the API |
| `test` | the acceptance criteria |

## The structural rule

Every action available in the UI exists as a `platform` REST API first. Console
templates receive no server-rendered values; they fetch `/api/` from the
browser. When an agent takes a human's place later, there should be nothing to
change.

## A warning

This is for a local training lab only: Elasticsearch with security disabled,
Django with `DEBUG=1` and `ALLOWED_HOSTS=*`, and the Docker socket mounted into
the platform container. None of it belongs on a public network.
