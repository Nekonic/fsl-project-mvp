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
  to the generated client, the `bots/` code, the repo side of the step-5
  deploy files, the new `nginx.conf` with per-seat terminals, and `front/`
  in the v4 design, built against its mock API only. The table is in
  `docs/STATE.md` "What exists on side-split".
- The docs (README, ARCHITECTURE, CLAUDE.md, STATE, this file) describe the
  new layout.

## Not live-verified

Nothing on `side-split` has run on a range: the rule test on a sensor and on
cr-waf, multi-sensor apply and rollback, the HP charge from the access log
and the spend at the edge, the jump grants for kali and for `analyst`, the
follower, `bin/cloud up`/`down` through the staff range routes, the bot
rounds driven by Claude Code, `front/` against a live platform, and the
ported acceptance suite.

## Next, in order

1. `front/` on a range: built and checked against `front/mock/` only (the
   Dockerfile's node stage builds it into `/app/front/dist`). The new
   `nginx.conf` (per-seat terminals through `terminal-auth`, the site
   listener keyed by round) and `vm-terminal.sh` (kali as `kali`, cr-waf as
   `analyst`, only for a seat with a jump grant) are tested offline, not on
   a range.
2. Cloud step 5: the deploy files are written and tested offline (edge
   `pool`/`spent` sets and both drops, emptied at round start and end, the
   WAF JSON access log shipped as `nginx_access` with only a marker-shaped
   `request_id`,
   `probe.conf`, `probe-upstream.py`, `analyst.sh`, infra `conntrack` and
   `tcpdump`); bake `cr-infra-bake2` and `cr-waf-bake3` and run the step's
   checks on a slot (`docs/OPENSTACK.md` §3.7).
3. Cloud step 12: `bin/record-probes board` and `corp` through the staff
   route, copy `CR_PROBES_OUT/<id>/probes/` off the platform VM, commit
   `wargames/<id>/probes/`.
4. Full live verify: the full `bin/verify` with acceptance, one Claude Code
   bot round per matchup, a captured walk as a learner, a live review round
   with zero countable findings, a docs review.
5. Gate 2.

## Open points

- Four acceptance checks read Elasticsearch directly
  (`test/test_event_time.py`, `test_geoip_durable.py`,
  `test_origin_placement.py`, `test_waf_geolocation.py`); the seam scan
  lists them as named exceptions until they move behind `/api/`.
- The 8002 listener's sign-in redirect lands on the home page, not the
  site (`Login.tsx` refuses a `next` on another origin).
- The rest (the scratch rule-test guesses, the comment scan's reach,
  `bin/carry-users` mid-load) is in `docs/STATE.md` "Open points".

Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet. Do not touch the live cloud from `side-split` before step 2.
