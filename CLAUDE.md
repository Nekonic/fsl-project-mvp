# fsl-project-mvp

A cyber attack/defence training range. A red team attacks a web app; a blue
team defends with Suricata and ModSecurity; the platform scores the defence.

**This repo is where the product gets built cheaply enough to throw away.** The
real one lives in a separate repo. Everything here exists to find out, before
that repo pays for it, what the thing should actually be - which screens, which
scoring, which stack. Build it, run it, measure it, keep what survives and
write down what did not.

That is why `docs/DECISIONS.md` is the main output and not a graveyard. A
Django replacement was built in full, measured, and discarded in a day; a
twelve-case run was measured to achieve zero objectives while reporting `TP=6`,
and the scoreboard was rebuilt around what it took instead. Neither was a
failure. Both were answers bought at a price the production repo would not have
wanted to pay.

A hypothesis does get tested along the way, because building the thing is what
tests it:

> Red team attacks can be labelled with ground truth, and Suricata/ModSecurity
> alerts can be matched to those labels automatically, so false positives and
> negatives can be scored mechanically.

It holds, and `platform/scoring/` is it. But proving it is not the job, and it
is not the game. **Objectives lead the score**: Juice Shop's own challenges,
which the application judges itself, so the platform labels nothing about
whether an attack achieved anything. Losing one always costs and losing one you
never saw costs double - detection is mitigation, the shape every cyber defence
exercise settled on. False positives stay beside the damage, never inside it.

What the product currently is: a shell one person can run attack and defence in,
two browser windows, no accounts. See
`docs/superpowers/specs/2026-09-20-product-flow-design.md`.

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
   **If the backlog is empty, stop and say so.** Do not invent an item. Every
   item on that list so far came from a human deciding what this should be,
   not from reading the code — a loop that writes its own backlog is choosing
   the project's direction, which is not its to choose.
4. Implement it test-first.
5. `bin/verify` — full run: unit, acceptance against the live stack, ratchet.
6. If it is red, or any metric grew: `git reset --hard`, append what you learned
   to `docs/DECISIONS.md`, and stop. A failed attempt that is written down is
   worth more than a half-finished one that is not.
7. If it is green: `bin/measure --save`, update `docs/STATE.md`, commit.

**Commit, never push.** Pushing and merging are the human's, whether or not a
loop is driving. A session that cannot ask is a session that must stop at the
commit.

Leave `docs/STATE.md` true. It is the entire handover to the next session.

## What a score counts

One red team case is one decision: TP, FP, FN or TN, however many alerts it
drew. `sqlmap-boolean-blind` produces 94 alerts and counts once. State this
whenever the numbers are reported - per-alert counting would measure
`threshold.config` rather than the defence, and McHugh's complaint about the
DARPA evaluations ("It is up to them to specify 0.1% of what") is the reason
it has to be said out loud.

A true positive also has to survive `expect`: each attack case declares a
substring of the signature that should be able to find it, and an alert that
does not mention the attack's own mechanism is reported as
`corroborated: false`. A rule set that catches everything for unrelated
reasons would otherwise score exactly as well as one that works. See
`docs/DECISIONS.md`.

## The measure of progress

`bin/measure` prints four numbers. Three of them may only go down.

| | gated | |
|---|---|---|
| `core_loc` | yes | the hypothesis: `scoring/`, `ingest/`, `rules/`, `redteam/harness.py` |
| `product_loc` | no | the shell: UI, API surface, compose, deploy |
| `dependencies` | yes | direct pip packages |
| `services` | yes | compose services |

One number could not serve both jobs, and the split follows what this repo is
for. `core_loc` is the part that has survived and would be worth carrying to
the production repo, so it stays small and keeps getting smaller.
`product_loc` is the disposable surface where things are tried, so it grows -
that is what building one looks like - and is reported rather than blocked.
Anything that stops being disposable should be earning its way into `core_loc`
or out of the repo.

`tests` runs the other way: it counts `def test_` definitions and may only go
**up**. Deleting a test is the cheapest way to make any change here pass, and
without a floor nothing else in a verify run would notice.

Docs and `bin/` are not counted, and tests are not counted as production code:
growing the suite must never look like a regression.

`metrics.json` holds the record and `bin/verify` refuses any change that grows
a gated number or shrinks the floor. If it is genuinely unavoidable, edit
`metrics.json` by hand and write down why in `docs/DECISIONS.md` — but treat
that as a last resort, not an escape hatch. **`bin/verify` enforces the second
half of that sentence**: a run that moves a baseline by hand and changes no
line of `docs/DECISIONS.md` is refused, because the reason was written down
nowhere. A new dependency or service costs a line there, not silence.

## What must not break

- **The acceptance criteria.** `test/` must stay green. In particular TP > 0 and
  TN > 0: attacks are detected, benign traffic passes. That is the hypothesis.
- **Benign cases in `redteam/cases/`.** Deleting them is the easiest way to make
  the score look good and the platform pointless.
- **The target decides whether it was beaten.** Never mark an objective from
  the platform's own belief about what an attack did. The whole value of the
  objective layer is that its ground truth is orthogonal to the detector.
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
| `platform/objectives.py` | the only file that knows the target's challenge API |
| `platform/scoreboard.py` | what each side achieved: pure, no I/O |
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
