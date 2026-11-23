# Now

The handover to the next session, kept short. The build record and backlog
are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md`; detail in `git log`.
The handover of the old tree up to 2026-11-18 is in this file's git history.

Updated: 2026-11-23.

## Where things stand

- The working branch is `restructure`, cut from `side-split`. `dev` and
  `main` still hold the old product; the cloud now runs `restructure`.
- `restructure` carries out the 2026-11-21 and 2026-11-22 rulings; the table
  is in `docs/STATE.md` "What exists on restructure". The rulings recorded on
  2026-11-23 (five attack origins, more benign kinds, Internet scanners, the
  board's attack paths, the response replay of the attack's own logged
  requests) are not built.
- The first cloud check of `restructure` ran on 2026-11-23
  (`docs/DECISIONS.md`, same date):
  - images `cr-infra-bake2`, `cr-waf-bake3`, `cr-target-bake2` baked from
    `restructure`, and `cr-kali-bake2`, whose role files match
    `restructure`'s;
  - the platform VM replaced from `restructure` with a fresh database, as
    stack `cr-platform2`; the pool converged;
  - `docs/OPENSTACK.md` §3.7-§3.10 checks 39 of 39 passed;
  - probes recorded, board 18 of 18 and corp 7 of 7, committed;
  - the final full `bin/verify` with acceptance: 101 passed, 0 failed.
- The run's product fixes: the attack API's body limit 256 KiB, the
  traversal case's path, the offline IDS test's `--runmode single`, the jump
  host in terminal grants, the declaration file's path.

## Not live-verified

Player vs AI rounds, a `pvp` round, a captured learner walk, a live review
round, a docs review, and the edge sets after an infra reboot. The list is
in `docs/STATE.md` "Not live-verified".

## Blockers for the user

- **Where `cr-dev` lives.** It holds a port and a floating IP on the
  platform stack's network, so stack `cr-platform` is `DELETE_FAILED` and
  `bin/cloud up --replace` cannot delete it (`docs/OPENSTACK.md` §5.3).
  Security groups are at 10 of 10. Move `cr-dev` to its own network and
  router, or have an admin raise the quota.
- **Why the kali snapshot failed.** `cr-kali-bake3` ended with Nova's
  `compute_snapshot_instance: Error`, whose cause a member user cannot see;
  free space on the compute node or the Glance store is a guess. An admin
  should read the logs before the next kali bake.

## Next, in order

1. The two blockers above.
2. A Player vs AI round per matchup (`def_vs_bot`, `atk_vs_bot`, with
   Claude Code as the bot player) and one `pvp` round.
3. A captured walk as a learner, a live review round with zero countable
   findings, a docs review.
4. Gate 2.

## Open points

- A benign case fires many times per round and the score lists one line per
  firing, against CLAUDE.md's "one case is one decision"; the acceptance
  harness reads a case as detected when any firing drew an alert. The user
  has not ruled.
- Four acceptance checks read Elasticsearch directly
  (`test/test_event_time.py`, `test_geoip_durable.py`,
  `test_origin_placement.py`, `test_waf_geolocation.py`); the seam scan
  lists them as named exceptions until they move behind `/api/`.
- A round no one calls on does nothing (the late judge included); a polling
  console or bot keeps it moving. The rest is in `docs/STATE.md` "Open
  points".

Written for a session that reaches the cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet.
