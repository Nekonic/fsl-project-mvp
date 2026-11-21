# Now

The handover to the next session, kept short. The build record and backlog
are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md`; detail in `git log`.
The handover of the old tree up to 2026-11-18 is in this file's git history.

Updated: 2026-11-22.

## Where things stand

- The working branch is `restructure`, cut from `side-split`. `dev` still
  holds the old product, which is what the live cloud runs; nothing on
  `side-split` or `restructure` has been deployed.
- `restructure` carries out the 2026-11-21 rulings (`docs/DECISIONS.md`):
  five units (`users/`, `sandbox/`, `telemetry/`, `training/`, `scoring/`)
  with fresh `0001` migrations; Seat is `Player` and Lease is
  `Allocation`; no periodic tick (reads run on the round's requests, the
  `rebuild` service only rebuilds slots); origin loss from the WAF error log
  in place of HP; the WAF as six files the defender edits; benign traffic
  from the infra VM; a random board secret each round; live verdict
  notices; the bots' shell and calls by `operationId` through
  `bots/rest.py` with no generated client; the lesson content gone and
  `training/lessons/` kept empty; and the 2026-11-22 ruling: the defence
  edits Suricata rules in a second terminal on the sensor (`analyst` on
  the infra), the IDS rule API and its console form are gone; a terminal
  reload, WAF or IDS, is recorded from the copy its sudo wrapper keeps in
  root-only `/var/lib/cr-reloaded` and installs root-only for the reload,
  so the engine loads exactly that copy and an edit after a reload is left
  alone. The table is
  in `docs/STATE.md` "What exists on restructure".
- The unit and API suite and `front/` (build, vitest) run against fakes.
  The docs (CLAUDE.md, README, ARCHITECTURE, OPENSTACK, STATE, this file)
  describe the new layout.

## Not live-verified

Everything on `restructure`; the list is in `docs/STATE.md` "Not
live-verified".

## Next, in order

1. Rebake `cr-infra`, `cr-waf`, `cr-kali` and `cr-target`, name them in
   `compute.images`, `bin/cloud up --replace`, and the checks of
   `docs/OPENSTACK.md` §3.7, §3.8, §3.9 and §3.10. Until `cr-target` is rebaked,
   every round start fails with `ground_truth_unavailable`.
2. Probe recordings: `bin/record-probes board` and `corp`, committed under
   `wargames/<id>/probes/`; `test/test_rule_test_isolation.py` fails until
   the board's manifest is in.
3. The full `bin/verify` with acceptance on the cloud.
4. A Player vs AI round per matchup (`def_vs_bot`, `atk_vs_bot`, with
   Claude Code as the bot player) and one `pvp` round, a captured walk as a
   learner, a live review round with zero countable findings, a docs review.
5. Gate 2.

## Open points

- Four acceptance checks read Elasticsearch directly
  (`test/test_event_time.py`, `test_geoip_durable.py`,
  `test_origin_placement.py`, `test_waf_geolocation.py`); the seam scan
  lists them as named exceptions until they move behind `/api/`.
- A round no one calls on does nothing; a polling console or bot keeps it
  moving. The rest is in `docs/STATE.md` "Open points".

Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet. Do not touch the live cloud from `restructure` before step 1.
