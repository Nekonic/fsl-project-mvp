# fsl-project-mvp

A cyber attack/defence training range. A red team attacks a web app; a blue team
defends with Suricata and ModSecurity; the platform scores the defence by false
positives and false negatives.

This repo exists to test one hypothesis, and nothing else:

> Red team attacks can be labelled with ground truth, and Suricata/ModSecurity
> alerts can be matched to those labels automatically, so false positives and
> negatives can be scored mechanically.

The hypothesis holds as of v1.0. The work now is to reach the **simplest code
that still proves it**. The production project lives in a separate repo.

## Working language

Everything in this repo is written in English: code, comments, commit messages,
documents. The user is Korean and talks to you in Korean; reply in Korean, but
never write Korean into a file. Korean costs roughly twice the tokens per line,
and every session pays to re-read it.

## Session protocol

Follow this whether a human started you or `/loop` did. To run it unattended:

```
/loop Follow the session protocol in CLAUDE.md. Do exactly one backlog item.
```

1. Read this file and `docs/STATE.md`. That is the whole briefing.
2. `bin/verify --fast` — prove the baseline is green before touching anything.
3. Take **the top item** of the backlog in `docs/STATE.md`. One item, not two.
4. Implement it test-first.
5. `bin/verify` — full run: unit, acceptance against the live stack, ratchet.
6. If it is red, or any metric grew: `git reset --hard`, append what you learned
   to `docs/DECISIONS.md`, and stop. A failed attempt that is written down is
   worth more than a half-finished one that is not.
7. If it is green: `bin/measure --save`, update `docs/STATE.md`, commit.

Leave `docs/STATE.md` true. It is the entire handover to the next session.

## The measure of progress

`bin/measure` prints three numbers. All three may only go down.

| | |
|---|---|
| `production_loc` | non-blank lines of shipped source and config |
| `dependencies` | direct pip packages |
| `services` | compose services |

Tests, docs and `bin/` are not counted: growing the test suite must never look
like a regression. `metrics.json` holds the record and `bin/verify` refuses any
change that grows a number. If growth is genuinely unavoidable, edit
`metrics.json` by hand and write down why in `docs/DECISIONS.md` — but treat
that as a last resort, not an escape hatch.

## What must not break

- **The acceptance criteria.** `test/` must stay green. In particular TP > 0 and
  TN > 0: attacks are detected, benign traffic passes. That is the hypothesis.
- **Benign cases in `redteam/cases/`.** Deleting them is the easiest way to make
  the score look good and the platform pointless.
- **These stay, by the user's decision:** OpenStack, Docker, Suricata, nginx,
  Elasticsearch. Everything else — Django, Kibana, Filebeat, ModSecurity,
  Juice Shop, the API shape, the scoring design — may be replaced if it makes
  the project smaller without breaking the above.
- **Every UI action exists as a REST API first.** Console templates fetch
  `/api/`; they never receive server-rendered data. This is what lets an agent
  take a human's place later.

## Layout

| | |
|---|---|
| `platform/scoring/` | the hypothesis itself: pure functions, no I/O, no Django |
| `platform/ingest/elastic.py` | the only file that knows Elasticsearch |
| `platform/rules/suricata.py` | the only file that knows the Suricata process |
| `platform/api/`, `platform/blueteam/` | REST surface and the console |
| `redteam/` | attack execution and ground truth |
| `deploy/`, `compose.yaml` | the stack |
| `test/` | acceptance criteria, over HTTP only |

`platform/` is **not** a Python package — `platform` is a stdlib module name.
Never add `platform/__init__.py`. Run Python with `platform/` as the working
directory. Same for `test/`.

## Running it

```bash
colima start --profile fsl          # arm64 host: ES crashes under x86 emulation
docker compose up -d --build
docker compose --profile tools build
curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip \
  -H 'Content-Type: application/json' \
  --data-binary @deploy/elastic/ingest-pipeline.json
.venv/bin/python redteam/run.py
```

See `README.md` for what each port is. `docs/superpowers/specs/` holds the
design; the plan beside it is a finished historical record, not a to-do list.
