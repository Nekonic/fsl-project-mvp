# Product flow design

Date: 2026-09-20. All of it is built; this records what the product is and why
it has this shape.

## What it is

One person runs attack and defence against the same session in two browser
windows, with no CLI step and no session number to type.

Out of scope, by decision:

- accounts, authentication, multi-tenancy;
- a second wargame (Juice Shop is the only one; the wargame list exists so a
  second has somewhere to go);
- realtime push (polling is enough for one person);
- agents. Every UI action is a REST call first, which leaves room for them.

## Screens

```
/                 wargames, open and recent sessions, New session
/session/<id>/    open the red window, open the blue window
/red/<id>/        objectives, case buttons, Kali terminal with start/stop labelling
/blue/<id>/       Dashboard, Live, Scoreboard and Rules as tabs on one page
```

The session id is in the URL. The first console took it from a text box, which
could not say whether the number was right, and a missing session rendered as
an empty page that looked broken. The URL also makes it plain that both
windows share one session.

The blue team's pages are tabs because defending means editing a rule, firing
again and reading the score, repeatedly.

## REST surface

The red team had no screen because firing an attack had no endpoint, so the
endpoint came first:

```
GET  /api/wargames/                 wargame cards
GET  /api/wargames/<id>/cases/      the catalogue: what can be fired
POST /api/sessions/<id>/attacks/    fire one catalogue case
GET  /api/sessions/<id>/cases/      the ground truth: what was fired, and its label
```

The catalogue and the recorded ground truth are different things and keep
different endpoints.

A labelled terminal window needed no new endpoint: it is
`POST /api/sessions/<id>/cases/` with `correlation: "window"`, the source
address and the start and end times. While it is open the proxy also stamps its
case id, so the same traffic can be scored by either strategy with
`GET /api/sessions/<id>/score/?correlation=marker|window|both`.

## Where attacks run

A console-fired case is sent by the platform container, which mounts
`redteam/` read-only and calls the same harness as the CLI, so a button sends
exactly what a CLI run would. The platform already stands on the outside
segments and has the Docker socket, so this needed no new infrastructure.
Catalogue cases use marker correlation, so the platform's address does not
matter. A terminal window uses the address its route had when it started.
