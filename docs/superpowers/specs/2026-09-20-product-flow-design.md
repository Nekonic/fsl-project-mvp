# Product flow design

Date: 2026-09-20

## 1. Purpose

v1.0 proved the hypothesis. What it did not do is let anyone *use* the thing:
the red team has no screen at all, and the blue team console is three pages
that only come alive once you have run a CLI script and typed its session
number into a box.

This design takes the MVP from "a proved hypothesis" to "a product one person
can run attack and defence on, in two browser windows". The production project
still lives in a separate repo; this repo stays the place where the loop is
tested cheaply before it is built there for real.

The user's words: it has to reach beta, and right now it is not even alpha.

## 2. Scope

### In

- A shell: main page, wargame list, session creation, role choice.
- A red team window: fire catalogue cases by button; later, a labelled Kali
  terminal.
- A blue team window: today's three pages, merged into one screen.
- Session identity in the URL, not in a text box.
- Both correlation strategies exercised against the live stack, and compared.
- A ratchet that distinguishes the hypothesis core from the product shell.

### Out

- Authentication, accounts, multi-tenancy. One person, two windows.
- More than one wargame. Juice Shop stays the only target; the list exists so
  the second one has somewhere to go.
- Realtime push. Polling is enough for one user.
- Agents. The rule that every UI action is a REST call first still holds the
  space open.

## 3. What is actually missing

`redteam/harness.py` already splits correctly: `fire()` sends one case,
`_record()` records one piece of ground truth, and `run()` is the loop around
them. What is missing is not a screen. It is a REST endpoint that calls that
loop body once.

CLAUDE.md's structural rule says every UI action exists as a REST API first.
The blue team console exists because rule read/validate/apply had endpoints.
The red team console does not exist because firing an attack does not.

So the spine of this work is the REST surface, and the screens sit on it.

## 4. Phases

Each phase ends with `bin/verify` green and something a person can use.

| Phase | Content | What it unlocks |
|---|---|---|
| 0 | Split the ratchet into core and product | Phase 1 can be committed at all |
| 1 | Session REST, shell, red team case buttons | The whole loop in two windows |
| 2 | Kali terminal, time-window labelling | Free-form attacks; `window` runs live |
| 3 | Marker-stamping proxy, strategy comparison | A/B experiments on the score |

## 5. Screens

```
/                    Main: wargame cards, recent sessions, [New session]
     | POST /api/sessions/
/session/<id>/       Role: [Open red team window] [Open blue team window]
     |                          |
/red/<id>/                 /blue/<id>/
 case buttons               Score / Alerts / Rules as tabs on one screen
 fired-case log
 [phase 2] terminal + start/stop labelled attack
```

The session number moves into the URL. Today's nav input cannot tell you
whether the number is right, and an absent session renders as an empty page
that looks broken — which is exactly the confusion that started this work.
A session in the URL also makes it obvious that the two windows share one.

The blue team's three pages become tabs on one screen. Defending means editing
a rule, re-ingesting and reading the score repeatedly; today that is a page
round trip each time.

## 6. REST surface

New in phase 1:

```
GET  /api/wargames/                 wargame cards
GET  /api/wargames/<id>/cases/      the case catalogue (the buttons)
GET  /api/sessions/                 recent sessions
POST /api/sessions/<id>/attacks/    fire one case: {"case": "<name>"}
```

The catalogue and the recorded ground truth are different things and keep
different endpoints: `/api/wargames/<id>/cases/` is what can be fired,
`/api/sessions/<id>/cases/` is what was fired and what it was labelled.

Phase 2 needs **no new endpoint**. `POST /api/sessions/<id>/cases/` already
accepts `started_at`, `ended_at`, `correlation` and `source_ip`. A labelled
terminal window is that call with `correlation: "window"` and the Kali
container's address. The window strategy has always had a complete API and no
caller.

Phase 3 adds a forced strategy to scoring:

```
GET /api/sessions/<id>/score/?correlation=marker|window|both
```

`correlate()` follows each case's own `correlation` field today. Comparing the
strategies means scoring the same cases twice with the strategy overridden.

## 7. Data model

Phase 1 changes nothing. `Session.scenario` already holds `"juice-shop"` and
becomes the wargame id.

## 8. Where the code runs

`redteam/` is mounted into the platform container (one compose volume). The
harness is not moved: mounting changes less.

The platform container already has the Docker socket and sits on the `fsl`
network, so it can run the tool containers and reach the target without new
infrastructure.

Attacks therefore leave the platform container rather than the host, so their
source IP changes. Marker correlation does not care. Window correlation does,
which is why phase 2 labels against the Kali container's address instead.

## 9. An open question, to be answered by measurement

`run()` keeps one `requests.Session` for a whole run, and says why: the traffic
has to keep HTTP keep-alive, because a shared TCP flow is what the
`(flow_id, tx_id)` correlation exists to cope with.

Firing one case per HTTP request may break that — each case would get its own
flow, and the hardest case for correlation would stop being reproduced. The
score would improve, falsely.

This is not resolved in advance. Phase 1 fires per case, then the same case set
is scored both ways and compared. If the score moves, the platform holds one
`requests.Session` per FSL session and the reason is recorded. If it does not
move, nothing is added. Measuring it is cheaper than arguing about it, and this
repo exists to measure things like it.

## 10. The ratchet

`production_loc` as one number cannot survive this work: a product shell grows.
Retiring the ratchet loses the discipline that refused a Django rewrite on the
day this was written. So it splits:

| | |
|---|---|
| `core_loc` | `platform/scoring/`, `platform/ingest/`, `platform/rules/`, `redteam/harness.py` — the hypothesis. May only go down. |
| `product_loc` | UI, API shell, compose, deploy. Reported every run, not gated. |

`dependencies` and `services` stay gated as they are: both will grow in phases
2 and 3, and each increment should cost a line in DECISIONS.md rather than
passing unnoticed.

## 11. Tests

Unchanged in kind. Unit and API tests for every new endpoint; the acceptance
criteria in `test/` stay green throughout and keep TP > 0 and TN > 0. Phase 2
adds the first acceptance test that scores a `window` case against the live
stack, which closes the known gap recorded in STATE.md.
