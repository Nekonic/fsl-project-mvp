# fsl-project-mvp

A cyber attack/defence training range. A red team attacks a web app; a blue team
defends with Suricata and ModSecurity; the platform scores the defence by false
positives and false negatives.

This repo exists to test one hypothesis, and nothing else:

> Red team attacks can be labelled with ground truth, and Suricata/ModSecurity
> alerts can be matched to those labels automatically, so false positives and
> negatives can be scored mechanically.

The hypothesis holds as of v1.0. The work now is to build the **smallest
product that demonstrates it** - a shell one person can run attack and defence
in, two browser windows, no accounts. See
`docs/superpowers/specs/2026-09-20-product-flow-design.md`.

The hypothesis core underneath must still get simpler, and `bin/verify` still
enforces that. The production project lives in a separate repo; this one stays
where the loop is tested cheaply first.

## Working language

Everything in this repo is written in English: code, comments, commit messages,
documents. The user is Korean and talks to you in Korean; reply in Korean, but
never write Korean into a file. Korean costs roughly twice the tokens per line,
and every session pays to re-read it.

The one exception is `docs/superpowers/plans/`, which is archived and should
not be read. Do not spend tokens translating it.

## Session protocol

Follow this whether a human started you or `/loop` did. To run it unattended:

```
/loop Follow the session protocol in CLAUDE.md. Do exactly one backlog item.
```

1. Read this file and `docs/STATE.md`. That is the whole briefing.
2. `bin/verify --fast` — prove the baseline is green before touching anything.
   If the stack is down, bring it back before step 5: `colima start --profile
   fsl`, `docker compose up -d`. If it will not come up, say so and stop —
   never commit on the strength of `--fast` alone.
3. Take **the top item** of the backlog in `docs/STATE.md`. One item, not two.
4. Implement it test-first.
5. `bin/verify` — full run: unit, acceptance against the live stack, ratchet.
6. If it is red, or any metric grew: `git reset --hard`, append what you learned
   to `docs/DECISIONS.md`, and stop. A failed attempt that is written down is
   worth more than a half-finished one that is not.
7. If it is green: `bin/measure --save`, update `docs/STATE.md`, commit.

Leave `docs/STATE.md` true. It is the entire handover to the next session.

## The measure of progress

`bin/measure` prints four numbers. Three of them may only go down.

| | gated | |
|---|---|---|
| `core_loc` | yes | the hypothesis: `scoring/`, `ingest/`, `rules/`, `redteam/harness.py` |
| `product_loc` | no | the shell: UI, API surface, compose, deploy |
| `dependencies` | yes | direct pip packages |
| `services` | yes | compose services |

One number could not serve both jobs. A product shell grows — that is what
building one looks like — but the hypothesis underneath must not, or the thing
being demonstrated quietly becomes something else. So `product_loc` is
reported every run and never blocks, and everything else ratchets as before.

Tests, docs and `bin/` are not counted: growing the test suite must never look
like a regression. `metrics.json` holds the record and `bin/verify` refuses any
change that grows a gated number. If growth is genuinely unavoidable, edit
`metrics.json` by hand and write down why in `docs/DECISIONS.md` — but treat
that as a last resort, not an escape hatch. A new dependency or service should
cost a line in `docs/DECISIONS.md`, not pass unnoticed.

## What must not break

- **The acceptance criteria.** `test/` must stay green. In particular TP > 0 and
  TN > 0: attacks are detected, benign traffic passes. That is the hypothesis.
- **Benign cases in `redteam/cases/`.** Deleting them is the easiest way to make
  the score look good and the platform pointless.
- **These stay, by the user's decision:** OpenStack, Docker, Suricata, nginx,
  Elasticsearch. Everything else — Django, Filebeat, ModSecurity, Juice Shop,
  the API shape, the scoring design — may be replaced if it makes the project
  smaller without breaking the above.
- **Every UI action exists as a REST API first.** Console templates fetch
  `/api/`; they never receive server-rendered data. This is what lets an agent
  take a human's place later.

## Layout

| | |
|---|---|
| `platform/scoring/` | the hypothesis itself: pure functions, no I/O, no Django |
| `platform/ingest/elastic.py` | the only file that knows Elasticsearch |
| `platform/rules/suricata.py` | the only file that knows the Suricata process |
| `platform/api/`, `platform/console/` | REST surface and the console |
| `platform/wargames.py` | the case catalogue the console fires from |
| `platform/attacker.py` | the only file that knows the attacker box and its marker |
| `redteam/` | attack execution and ground truth |
| `deploy/`, `compose.yaml` | the stack |
| `test/` | acceptance criteria, over HTTP only |

`platform/` is **not** a Python package — `platform` is a stdlib module name.
Never add `platform/__init__.py`. Run Python with `platform/` as the working
directory. Same for `test/`.

## Running it

```bash
colima start --profile fsl          # arm64 host: ES crashes under x86 emulation
docker compose up -d --build          # includes kali, the attacker's terminal
docker compose --profile tools build
curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip \
  -H 'Content-Type: application/json' \
  --data-binary @deploy/elastic/ingest-pipeline.json
.venv/bin/python redteam/run.py       # or drive it from the console at /
```

The console is the point now: open `/`, start a session, and open the red and
blue windows side by side. The terminal in the red window is on 7681, and its
traffic goes out through the stamping proxy - so the address alerts carry is
the proxy's, not Kali's. See DECISIONS.

See `README.md` for what each port is. `docs/superpowers/specs/` holds the
design; the plan beside it is a finished historical record, not a to-do list.
