# A second wargame: the Django board

Date: 2026-09-28. Decided with the user; not built yet.

## Why

The platform assumes Juice Shop. A session stores `scenario`, and the case
catalogue already honours it, but `objectives.py` reads Juice Shop's
`/api/Challenges/` for every session whatever its scenario. A second target
proves where the seam belongs by forcing it, instead of designing an
abstraction first. A WordPress company site (PHP) and a Java school
management system come later and should plug in at the same place.

## What the board is

An ordinary Django application, built the way a developer builds one without
thinking about security either way: default ORM, default auth, no planted
vulnerability and no extra hardening.

- post list, post detail, write a post, comment
- search
- login
- MySQL as its database

## Its place in the score

The board is a detection target. The defence's numbers (TP, FP, FN, TN per
case) apply to it unchanged, and they are its whole score.

It has no objectives. It ships no challenges and flips no `solved` flag, and
the platform never marks an objective on its behalf, because the target
decides whether it was beaten. A board session reports no objectives, and the
console says the target is detection-only.

## Placement

- Behind the existing WAF as a second server name, `board.com`. Suricata
  watches the WAF's traffic, so no new sensor is needed.
- MySQL sits on `estate` and only the board can reach it.

## Changes to the platform

- `WARGAMES` gains `board`, with its own case file `redteam/cases/board.yaml`.
- Objectives are observed per scenario: `juice-shop` reads as it does today,
  and `board` reads nothing and returns no objectives.
- Whatever else turns out to assume Juice Shop (a single `TARGET_URL`, the
  WAF's single backend, verify waiting on one target) is split only as far as
  the board needs it.

## Cases

- Attacks: SQL injection attempts against search and login, XSS attempts in
  comments and search, path traversal.
- Benign: an ordinary search, one that contains an apostrophe, and posting a
  normal comment. Without them a rule that blocks everything scores perfectly.
- `expect` values are read off the signatures the engines actually produce on
  a first run, not guessed.

## Platform constraints

**x86_64 only.** Production is OpenStack on x86_64, and a second architecture
would mean a second development environment. Every image is `linux/amd64`;
the Mac runs them under emulation inside the aarch64 colima VM, which was
measured working on 2026-09-20 at a cost in speed (Elasticsearch starts in
about 60 s against 6 s native). Switching the existing stack is its own item
and comes before the board, so the board is built on amd64 from the start.

**Not Mac-only.** The board must run on OpenStack as it runs on Docker:

- `board` and `board-db` are declared as roles in
  `platform/range/declaration.yaml`, and `test_declaration.py` holds
  `compose.yaml` to them.
- The platform reaches them only through the `range` port.
- Configuration comes from the environment; no host-specific paths.
- `board.com` joins the name resolution item in `docs/STATE.md` (OpenStack
  item 1).

A kolla-ansible OpenStack test cloud is available on the VPN at `10.0.0.100`,
with `10.0.0.200` as its external address.

## The measure

| | change | |
|---|---|---|
| `services` | 9 to 11 | the board and MySQL; approved by the user on 2026-09-28, so `metrics.json` is edited by hand |
| `dependencies` | none | it counts `platform/requirements.txt` only; the board's packages live in its own image |
| `core_loc` | none expected | `objectives.py` and `wargames.py` are not core |
| `product_loc` | grows | the board, its image, compose, cases |

## Out of scope

WordPress, the Java system, objectives on the board, planted vulnerabilities.

## Order

1. Switch the stack to x86_64 and measure what it costs `bin/verify` on the
   Mac.
2. Build the board on top of it.

## Tests

- A board session observes no Juice Shop objectives and makes no request to
  Juice Shop.
- Acceptance: a board attack case is a true positive and a benign case a true
  negative, over HTTP.
- `test_declaration.py` covers the two new roles.
