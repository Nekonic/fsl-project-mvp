# Now

The handover to the next session, kept short. The build record and backlog
are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md`; detail in `git log`.
The handover of the old tree up to 2026-11-18 is in this file's git history.

Updated: 2026-11-20.

## Where things stand

- The side-split rebuild lives on the working branch `side-split`. `dev`
  still holds the old product, which is what the live cloud runs; nothing on
  `side-split` has been deployed.
- Built and green against fakes: `domain/`, every seam, `accounts`, `events`,
  `content`, `match`, `referee`, `defence`, `attack`, `lessons`, the
  committed OpenAPI contract and generated clients, `test/` and `bin/` ported
  to the generated client, and the `bots/` code. The table is in
  `docs/STATE.md` "What exists on side-split".
- The docs (README, ARCHITECTURE, CLAUDE.md, STATE, this file) describe the
  new layout.

## Not live-verified

Nothing on `side-split` has run on a range: the rule test on a sensor and on
cr-waf, multi-sensor apply and rollback, the HP charge from the access log
and the spend at the edge, the jump grants for kali and for `analyst`, the
follower, `bin/cloud up`/`down` through the staff range routes, the bot
rounds driven by Claude Code, and the ported acceptance suite.

## Next, in order

1. `front/` in the design the user picks, with the new `nginx.conf` and a
   rewritten `vm-terminal.sh` (today it imports the deleted
   `api.models.Session` and opens cr-waf as root, and nginx does not call the
   per-seat `terminal-auth` routes).
2. Cloud step 5: the deploy changes (edge `pool`/`spent` sets, the WAF JSON
   access log shipped as `nginx_access`, `probe.conf`, `probe-upstream.py`,
   `analyst.sh`) and new infra and waf images. None of those files is changed
   yet.
3. Cloud step 12: write `bin/record-probes`, record board and corp through
   the staff route, commit `wargames/<id>/probes/`.
4. Full live verify: the full `bin/verify` with acceptance, one Claude Code
   bot round per matchup, a captured walk as a learner, a live review round
   with zero countable findings, a docs review.
5. Gate 2.

## Open points

- A fresh store has no first account (the old `admin` / `123456` migration
  is gone; `bin/carry-users` or `createsuperuser`), against the 2026-11-15
  ruling.
- The seam scan covers `platform/` only and there is no comment scan; the
  spec asks for both over `front/src`, `bots/`, `test/` and `bin/` too.
- `docs/DECISIONS.md` still quotes rulings in Korean, allowed by name in
  `test_no_hangul.py` until translated.

Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet. Do not touch the live cloud from `side-split` before step 2.
