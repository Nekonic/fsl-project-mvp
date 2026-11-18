# A general attacker-proven objective model

Date: 2026-10-03. Decided with the user; not built yet.

## Why

`platform/objectives.py` is overfit to Juice Shop. It fetches
`/api/Challenges/`, reads Juice Shop's self-flipped `solved`/`updatedAt`,
carries a Juice-Shop-specific `CHECKED_ON_A_LATER_REQUEST` set and the wiki-SSRF
`INTERNAL` objective, and every objective path is gated on a single
`wargames.judged` boolean. The seam was never forced: when only Juice Shop
existed, prior sessions built the objective layer to Juice Shop's shape.

Juice Shop's model is *self-judging*: the target decides it was beaten by
flipping its own flag. That is a CTF convenience, not how a real target
behaves. The general, realistic model the user wants is *attacker-proven
possession*: the attacker exfiltrates a real secret and proves it, and the
platform credits the objective only after checking the proof against the
target's real value. The ground truth still comes from the target side and
stays orthogonal to the detector — the hypothesis the project exists to prove
survives intact — but the trigger is the attacker's proof, not the target's
self-report.

The guiding constraint from the user: **nothing may exist solely for Juice
Shop.** The objective model must be target-agnostic and serve every target
(the Django board, a new PHP company site, future targets). Juice Shop's
self-judging does not fit that model, so Juice Shop is removed rather than kept
behind a Juice-Shop-only adapter.

## Scope of this spec (sub-project A)

This spec designs **the general attacker-proven objective model, proves it on
the Django board (target #1), and ends by removing Juice Shop** (phase 4 below).
It is one design delivered in four green phases.

One further sub-project follows under **its own spec and plan**:

- **B — a PHP company website (target #2)** that plugs into this model with no
  model change, taking over Juice Shop's role as the second, richer target. The
  model here is designed so B plugs in by declaration alone; B's own
  vulnerabilities and structure are B's spec.

Sequencing note: Juice Shop's removal (phase 4) is safe once the board's
`loot_verified` objective is green (the board keeps the objective layer alive),
so A does not block on B. If the user prefers a second rich target to exist
before Juice Shop leaves, B lands before phase 4; either order is sound.

## The model

An objective is **possession of a declared secret set**. For each judged
target, a wargame declares an *objective spec*: the secret's scope, a tiered
ladder of objectives over that secret, and how the platform reads the target's
real values.

Flow, per session:

1. **Snapshot ground truth at session start.** The platform reads the target's
   real secret through a *target-owned read channel* and stores it on the
   session. `Session.baseline` generalizes from "solved keys" to a per-objective
   ground-truth payload (for the board: the live `auth_user` set of
   `username -> stored salted-PBKDF2 hash`). The snapshot survives the
   close-time slot rebuild because it is stored on the session row, not re-read
   from a wiped target.

2. **Attacker exfiltrates, then submits proof.** The red team runs an attack
   that leaks the secret, captures the loot, and submits it to a new
   `POST /api/sessions/<id>/loot/`. The platform never sniffs the HTTP response
   itself (`redteam/harness.py` keeps discarding response bodies), so the take
   is proven by the attacker, never inferred by the platform from traffic or
   alerts. The submission optionally carries the originating `case_id`.

3. **Verify against the snapshot.** A pure, product-space verifier canonicalizes
   the submission to an unordered set of `(username, hash)` tuples and
   intersects it with the snapshot. Only rows whose **exact stored salted-hash
   string** matches are credited. The per-row random PBKDF2 salt makes the
   stored string unforgeable from the public seed, so a match can only mean the
   attacker read the row — this defeats seed-reading, plaintext guessing,
   cross-instance loot, and (because salts rotate on rebuild) replay.

4. **Credit tiers as ordinary objectives.** Coverage = `|submitted ∩ truth| /
   |truth|` decides which tiers of the ladder fire. Each fired tier is written
   as an ordinary `Objective` row with its own integer difficulty, attributed
   by time to the exfil case and marked detected iff that case was detected.

### The tiered ladder (whole vs partial)

Partial-vs-whole extraction is modeled as **discrete objectives on the same
secret**, not a fractional score:

- `board-auth-user-partial` — fires at ≥1 matched account. Low difficulty.
- `board-auth-user-full` — fires at coverage == 1.0. High difficulty.
- `board-auth-user-admin` — fires when the superuser's hash matches. High.

A whole-table dump fires all three; a single non-admin row fires only partial;
one admin row fires partial + admin. This maps onto the existing discrete
`Objective`/`Breach`/`Taken` machinery with **zero change to `game.py` or
`scoreboard.py`**: `attacker_take` and `at_stake` already sum per-objective
integer difficulty. It sidesteps the integer-difficulty/`at_stake` pool-shrink
trap (encoding "partial" by lowering a difficulty would wrongly shrink the
defender's pool) and the `unique_together(session, key)` upgrade problem (a
later, larger dump fires a higher tier instead of mutating a row).

### The target plug-in seam

`judged: bool` becomes an `objective_model` enum on each wargame. `objectives.py`
becomes a thin dispatcher: `none` returns no objectives (detection-only);
`loot_verified` drives the snapshot/verify/credit flow above against a declared
objective spec.

**The end state is `loot_verified | none` only** — there is no `self_judged`,
because it would exist solely for Juice Shop. During the transition a
`self_judged` value carries Juice Shop's existing self-reporting behavior
unchanged, so the dispatcher refactor (phase 2) is a no-behavior-change step and
Juice Shop's tests stay green; phase 4 (sub-project C) removes Juice Shop and the
`self_judged` value together. After C, nothing Juice-Shop-only remains.

A target declares (as data beside its cases, e.g. `wargames/<id>/objectives.yaml`):
- the secret scope (board: `auth_user(username, password_hash)`),
- the tier ladder with difficulties,
- the ground-truth read channel.

**Ground-truth read channel — decided:** the target exposes an internal,
off-WAF HTTP endpoint that returns its current secret set (for the board, the
`auth_user` `(username, hash)` list), reachable only from the platform over
`estate`/`mgmt` — never through the WAF and never from the origin/attacker
networks, so the attacker cannot read it to shortcut the exfil. This mirrors
exactly how `objectives.py` already reads Juice Shop's internal
`/api/Challenges/`, so it adds no new runner role and no new OpenStack
dependency. The platform snapshots this set at session start and compares
submissions against the snapshot (fetch-and-compare). A considered alternative —
relay-and-verify, where the platform posts the submitted loot to the board and
the board returns a per-username verdict so the real hashes never leave the
target — is more faithful to "the target decides" but needs the board to hold
verification logic and re-introduces the rebuild-timing question; it is recorded
as a possible later refinement, not the chosen design. A direct MySQL connection
from the platform is rejected (it puts schema, credentials, and the decision on
the platform).

The PHP company site (B) plugs in by declaring its own secret, tiers, and read
channel; no code in the dispatcher or verifier changes.

## The board as target #1

### Exfiltration paths (both)

The board is plain Django 5.2 on MySQL with ORM-parameterized search — not
injectable today, so the existing `board-sqli-union-search` leaks nothing and
stays as a loud-but-ineffective detection probe. Two real leaks are added:

- **Option 1 — unpatched Django + idiomatic `order_by` (CVE-2021-35042), a
  LOUD, detected take.** `post_list` gains an ordinary `?sort=` param passed to
  `Post.objects.order_by(sort)` — no authored SQL. The board is pinned to
  `Django==3.2.4`, where `order_by()` fails to sanitize the column reference
  (CVE-2021-35042, backend-agnostic, applies to MySQL). Extraction is blind, so
  a new `board.yaml` sqlmap tool case (`-p sort --technique=BT --dbms=mysql
  --dump -T auth_user -C username,password`) reconstructs the exact stored
  hashes. The pin forces `python:3.9-slim` and replacing the 4.2-only
  `STORAGES` setting with `STATICFILES_STORAGE` (verified against Django release
  notes). This is a detected take (TP) — sqlmap's blind payloads trip CRS +
  Suricata — exercising the "one case, many alerts" correlation.

- **Option 2 — over-permissive `User.objects.values()` JSON endpoint, a QUIET,
  undetected take.** A new `members.json` view returns `list(User.objects.
  values())`, which includes `password` verbatim (textbook excessive-data
  exposure). A quiet benign-looking GET draws no alert → an undetected
  malicious case (FN), which the objective layer scores double ("a lost
  objective nobody detected counts double"). No downgrade, one view + one URL.

Shipping both gives the range one detected take and one undetected
(double-counted) take — the two halves of the scoring story.

### Anti-replay

Salts must be fresh each session or a dump saved from a prior session could be
resubmitted. `seed.py` uses idempotent `get_or_create`, so a persisted MySQL
volume keeps old salts. The slot rebuild must genuinely wipe the board's MySQL
so re-seed regenerates salts; comparison is only ever against the current
session's snapshot. As belt-and-suspenders, crediting requires ≥1 malicious
attempt recorded in-session (so empty-session seed-knowledge submissions are
refused).

## Scoring integration

- **Attribution / `achieved_at`.** The loot POST happens after the exfil
  request. The submission optionally carries the originating `case_id` for exact
  attribution; absent it, attribution uses submission time with the widened
  `ATTRIBUTION_WINDOW` (the existing `stamped_late` path), never submission time
  with the narrow `CLOCK_SKEW` (which would push the real exfil case out of
  window and read every take as undetected).
- **Detected.** `detected` on a loot `Taken` is the detection of the attributed
  case via `correlate()`, never whether the exfil response itself was alerted —
  preserving orthogonality.
- **Unattributed take.** If possession is proven but no malicious case overlaps
  the window (e.g. raw-TCP exfil bypassing the stamping proxy), the take is
  credited as undetected (the worst case, counted double) and surfaced as an
  "unattributed take" warning for a human. Detection is never synthesized from
  stray alerts.

## Juice Shop removal (phase 4, sequenced)

Removal is sequenced **after** the board's `loot_verified` objective is green,
so the objective and zero-sum-game layers never go empty. The core hypothesis,
the detector scoring (TP/FP/FN/TN, the `corroborated` gate), and the game math
are all target-agnostic and survive untouched; `core_loc`, gated `services`,
and `dependencies` are unaffected; `wargame_services` drops 4 → 2 and
`product_loc` drops (both desirable). The binding constraint is the `tests`
floor: ~40–44 Juice-Shop/wiki tests must be **rewritten** onto the board's
attacker-proven objective (floor preserved), not deleted.

**Genuinely lost by removal** (recorded so the decision is honest): the
multi-hop wiki-SSRF lateral-movement objective (`internalRunbookRead`) has no
board analogue, and Juice Shop's 100+-challenge breadth collapses to the
board's single secret. The PHP company site (B) is what restores a second,
richer target; lateral-movement as an objective type would need a separate,
later design if wanted.

## What changes (end state of A)

Added (all product_loc / tests / wargame data — nothing gated grows):
- board: a `?sort=` `order_by` path + the `Django==3.2.4` pin (+ `python:3.9`,
  `STATICFILES_STORAGE`), and a `members.json` `values()` endpoint;
- a board objective spec (tiers, difficulties, secret columns, read channel);
- a board-owned ground-truth read channel (management command via a new `board`
  runner role, or an internal off-WAF endpoint);
- `POST /api/sessions/<id>/loot/` + a product-space loot verifier that
  snapshots truth, canonicalizes the submission, intersects, and writes
  `Objective` rows the way `_observe_objectives` does, then settles;
- a new `board.yaml` sqlmap case for the blind dump;
- per-build salt rotation (or a confirmed MySQL wipe on rebuild);
- a guard that no hash literal is committed and the hasher stays salted;
- loot tests (match credits; fabrication/plaintext denied; partial/full/admin
  tiers; outage neither credits nor denies; replay fails after rebuild).

Changed: `wargames` `judged: bool` → `objective_model` enum at its call sites;
`objectives.py` → a thin `loot_verified | none` dispatcher; `Session.baseline`
generalized from solved-keys to a per-objective ground-truth snapshot.

Deleted in A: nothing (Juice Shop removal is C).

Gated numbers stay flat in A: `core_loc` 461 (nothing added to `scoring/`,
`ingest/`, `rules/`, `redteam/harness.py` — the attacker submits, the platform
never sniffs; the verifier lives in product space), `services` 7, `dependencies`
6. `product_loc` and `tests` rise.

## Testing

Test-first, each phase independently green under `bin/verify`:

1. board exfil + salt rotation: the `order_by` path is injectable only on the
   pin; `members.json` leaks the hash; benign search + `?sort` default keep
   TN > 0; rebuild regenerates salts.
2. dispatcher refactor: `objective_model` enum replaces `judged` with no
   behavior change; every existing test stays green (Juice Shop runs on the
   transitional `self_judged` value until phase 4).
3. `loot_verified` on the board: a submitted real-hash set credits the right
   tiers; fabricated/plaintext/cross-instance/replayed loot is denied; a
   partial dump fires only partial; a full dump fires all tiers; the admin hash
   fires admin; an unreadable ground-truth channel neither credits nor denies;
   attribution and detected follow the attributed case; an unattributed take
   reads undetected with a warning.
4. retarget the ~40–44 Juice-Shop/wiki tests onto the board objective and
   remove Juice Shop; the `tests` floor only rises.

## Phased plan (each step green)

1. Board exfil paths (Option 1 + 2) + per-build salt rotation.
2. `objective_model` dispatcher refactor (introduce the transitional
   `self_judged` value; no behavior change; Juice Shop stays green).
3. `loot_verified` adapter + `POST /loot/` + verifier + board objective spec +
   ground-truth read channel + generalized `Session.baseline`.
4. Retarget tests + remove Juice Shop and the `self_judged` value.

Sub-project B (the PHP company site) is a separate spec that plugs into the
model from step 3.
