# Now

The handover to the next session, kept short. The build record and backlog
are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`; the design in
`docs/superpowers/specs/2026-11-19-side-split-design.md`; detail in `git log`.
The handover of the old tree up to 2026-11-18 is in this file's git history.

Updated: 2026-11-26.

## Where things stand

- The tree is `bundle-1126` (2026-11-26): `defence-watch` with the bot
  polling the rule test as a detached job, the rule test replayed in one
  curl over one SSH call, the attack prompt rewritten to name the round's
  attack profile for the debrief, and the watch check timed from the last
  start and capped. On the cloud: one replace; rounds 309 (`atk_vs_bot`
  step 2, all three lost, detection O, response O, the bot's WAF version
  live 118 s after the first alert), 310 (`def_vs_bot` step 2 Sonnet 5.5,
  2 refusals, the bot went on, no objective lost) and 311 (step 3 Opus 5.5,
  2 refusals, no objective lost, 7/0/0/42) at once; the full acceptance
  from the platform VM 101 of 101.
- Before that the tree was `defence-watch`: `waf5` with the defence bot kept in the
  round until it ends, fed by the launcher every `watch_s` of its step
  (`docs/DECISIONS.md` 2026-11-25). It runs on the cloud since the early
  morning of 2026-11-26 (`docs/STATE.md` "Where things stand"): one
  replace (exit 0); two WireGuard `atk_vs_bot` rounds by the bare address
  with the attack held 200 s after the start (rounds 277 at step 2, 278 at
  step 1): both defence runs lasted the round, the feeds came 31 s and 75 s
  apart, both bots wrote a `deny` of the attack's origin, and in both the
  WAF rule test (6 min 36 s and about 3 min) went past Claude Code's 120 s
  Bash timeout into the background, so nothing was applied and all three
  objectives were lost, detection O, response X; `bin/verify --changed --live` from the platform VM: acceptance
  101 of 101, the unit and API suites green.
- Before that the tree was `waf5`: `integrate` (`bot-rounds`, the Player vs AI rounds
  cut from `restructure`, with `pg-store`, the PostgreSQL store, and
  `access-address`, the access page's target address, and the fixes of
  their reviews) with CRS 920350 removed at the WAF (`cr-waf-bake5`)
  and the attack bot's prompt rewritten as an engagement brief. `main`
  still holds the old product. `waf5` ran on
  the cloud from the evening of 2026-11-25 (`docs/STATE.md` "Where things
  stand"): one `bin/cloud up --replace` (exit 0, every slot on
  `cr-waf-bake5`); a WireGuard `atk_vs_bot` round by the bare address with
  no 920350 alert and no origin spent before the attack (round 245, all
  three objectives lost, detection X, response X: the step-2 defence bot
  ended its run 35 s in, with nothing alerting); acceptance 101 of 101 from
  the platform VM; the attack bot stopped by its safeguards in 4 of 4 runs
  (Sonnet 5.5 2 of 2, Opus 5.5 2 of 2), no fall back, no objective taken.
- Before that the cloud ran `integrate` (2026-11-25, `docs/STATE.md` "Where
  things stand"): `cr-waf-bake4` and `cr-target-bake3` baked from it, one
  `bin/cloud up --replace` that loaded the SQLite store into PostgreSQL
  with every row count equal, the console from the image with no hand copy,
  an `atk_vs_bot` round through WireGuard by the bare address (all three
  objectives lost, detection O, response X), corp by the bare address, and
  the full `bin/verify` from the platform VM: acceptance 101 of 101, every
  unit and API suite green.
- On 2026-11-25 the Player vs AI build ran live (`docs/STATE.md` "Where
  things stand", `docs/DECISIONS.md` 2026-11-25): `cr-kali-bake4`, two
  replaces from `bot-rounds`, rounds from a PC through WireGuard (an
  objective lost through the tunnel; an origin spent by the defence bot
  through it), the learner reach check (only the round's kali and WAF
  answered), a two-round baseline, four fixes, then acceptance 101 of 101
  from the platform VM.
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
- On 2026-11-24:
  - `bin/cloud up --replace` ran end to end on `cr-platform2` (exit 0,
    12 min) after two fixes: it refuses before deleting a stack whose
    network holds another server's port, and the store restore stops the
    `rebuild` service too;
  - the third kali bake passed as `cr-kali-bake3`, from `restructure`; a
    second replace (exit 0, 29 min 32 s) put every slot on it;
  - probes recorded again on that range, board 18 of 18 and corp 7 of 7
    (not committed: the committed set of 2026-11-23 stays);
  - the full `bin/verify` with acceptance on that range: acceptance 99
    passed and 2 errors (`test/test_block_everything.py`, both at setup: no
    board slot came free within the 1800 s room wait while 15 processes
    shared three board slots), the unit and API suites green; that module
    alone then passed 2 of 2;
  - one Player vs AI round per matchup ran with Claude Code as the bot
    (round 143 `def_vs_bot`, round 144 `atk_vs_bot`, board): no objective
    lost in either, TP/FP/FN/TN 9/0/0/66 and 6/0/0/84; the defence bot
    applied two WAF versions, spent the attack's first origin by `deny` and
    reloaded the IDS from its terminal.
- The run's product fixes: the attack API's body limit 256 KiB, the
  traversal case's path, the offline IDS test's `--runmode single`, the jump
  host in terminal grants, the declaration file's path.

## Not live-verified

A `pvp` round, a captured learner walk, a live review round, a docs
review, the edge sets after an infra reboot. The list is in
`docs/STATE.md` "Not live-verified".

## Blockers for the user

- **The name `cr-platform`.** Heat's abandon ran (an admin turned it on)
  and `cr-platform`'s network and router were renamed `cr-dev`, but the
  abandoned stack's record stays (`DELETE_COMPLETE`, with its four resource
  rows), so Heat refuses a new stack of that name and `bin/cloud up
  --replace` under it stops, naming `cr-dev` (`docs/OPENSTACK.md` §5.3).
  An admin removes that record from Heat's database; until then the
  platform runs as `cr-platform2`, which works.

## Next, in order

1. The blocker above, when an admin can.
2. The attack bot still meets 2 refusals a run on Sonnet and Opus 5.5
   and goes on; it took no objective in rounds 310 and 311.
3. A platform read now and then takes over 5 s with three rounds at once
   (the watch skips that check); the ingest inside each read is the
   suspect (`docs/STATE.md` "Open points").
4. One `pvp` round.
5. A captured walk as a learner, a live review round with zero countable
   findings, a docs review.
6. External learners, the last task of the Player vs AI work: the
   public-IP forwards (UDP 51820-51919, TCP 2222, the console) and
   `CR_VPN_HOST`.
7. Gate 2.

## Open points

- The attack bot is Haiku, Sonnet and Opus 5.5 again (DECISIONS 2026-11-25:
  the 2026-11-24 Haiku-only ruling is superseded; those refusals came from
  runs without the range context). The defence bot was not refused on any
  model.
- The bot no longer runs in the repo: the `bots` service starts Claude Code
  from an empty directory with no setting sources, from an image holding only
  `bots/` and the schema (live on 2026-11-25).
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
