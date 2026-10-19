# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-19 (foundations review loop, rounds 2-5, e4a467e deployed;
before it, foundations F1-F6 rebuilt as attack and defence lessons, 3aa49a5;
the red console is Kali and a browser, proven live on 51b28dd; foundations in
one session, proven live on 26c1c80; Korean-first learner text at 6b72876).
Written for a session that has the cloud (master@192.168.0.100, Keystone
http://192.168.0.110:5000) and the Internet.

## Where things stand

- Goal in flight: the scenario course. Design:
  `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`;
  rulings: the 2026-10-13 and 2026-10-14 entries in `docs/DECISIONS.md` (P4,
  P5 and P6 built).
- `origin/dev` = 8f9acb0. `claude/task-list-review-fc4953` (836ab11; local
  `dev` points there too) adds, not pushed: the GNS3 topology and its pane (P1), foundations F1-F6 (P2),
  customer traffic (P3), the scenario engine and console (P4), and the
  scenarios 1.1-1.3, 2.1-2.3, 3.1-3.4 and 4.1 on the board (P5), with the
  fixes the live runs forced, and P6: the older course (lessons 0-5 and 7,
  VERIFY, the lesson debrief, the Lesson / Practice / Wargame rungs,
  `Session.mode`) removed, migration 0026, tests 2052 -> 1981 (71 deleted,
  121 retargeted); and the request-path view on the map removed with F2 and
  F5 retargeted
  (2026-10-16), plus the three fixes its live run forced (F5 reads
  `rule_id`; a passed Kali step keeps its count; the popover is placed again).
  This branch (`ko-first`) adds on 836ab11, not pushed: the
  Korean-first learner text (6e3a2f0), its review (16e951d), the docs sweep
  and the Korean line-break fix its live sweep forced (6b72876); then the
  foundations in one session (74ce337, a9bab72) and the two Run in terminal
  fixes its live run forced (c7a69c5, 26c1c80); the red console as Kali and a
  browser (to 51b28dd); the foundations rebuilt (3aa49a5).
- Every scenario was run live on OpenStack (platform VM 192.168.0.210, both
  slots): each failed a final check with a wrong defence and passed one with
  a right defence. The table is in `docs/DECISIONS.md`, "P5 built".
- The platform VM (192.168.0.210) was rebuilt twice on 2026-10-15 and five
  times on 2026-10-16, ten times on 2026-10-17 and seven times on 2026-10-18 by `bin/cloud up --replace
  --sideload` (`docs/OPENSTACK.md` §5.3, `docs/DECISIONS.md` 2026-10-15 "The
  platform VM's rebuild runs an unpushed commit"): it runs e4a467e with all
  five images built from it, tagged 8f9acb0
  (`FSL_IMAGE_TAG`). Do not reboot it: `fsl-platform.service` can pull GHCR's
  8f9acb0 over the sideloaded images. The old VM's `/opt/fsl/backups` (P4 and P6 store copies) and both
  runs' store backups are in the main checkout's `backups/` on the operator's
  machine (`old-platform-vm-20261015-opt-fsl-backups.tgz`,
  `db-20261015T061630Z.sqlite3`, `db-20261015T073913Z.sqlite3`); this
  worktree's `backups/` keeps one (`backups.keep`), the 471 KB
  `db-20261017T125516Z.sqlite3` taken by the last rebuild; the 6 GB
  2026-10-16 copies are gone.
- The range keeps the platform VM's time over NTP (c4ee8d7, `docs/DECISIONS.md`
  2026-10-15 "The platform VM is the range's time source"). `bin/verify` there
  after it: unit passed; acceptance 74 passed, 0 failed in 765 s.
- F2 and F5 were walked live in Korean on 470b1bb (sessions 553, 554), every
  step passed through the real panes; `bin/verify` there after it: unit 2441
  passed; acceptance 74 passed, 0 failed, 71 skipped in 730 s; ratchet holds
  (`docs/DECISIONS.md` 2026-10-16 "The follow view is removed").
- The test audit (2026-10-16, `docs/DECISIONS.md` "Test audit"): test
  functions 2,061 -> 1,051, unit cases 2,459 -> 1,458; the test count is
  reported, not gated. Proven live on ee2e5b9 (deployed by the sideloaded
  rebuild in 27 min 37 s): `bin/verify` on the VM unit 1458 passed; acceptance
  45 passed, 0 failed, 0 errors, 30 skipped in 728 s; 876 s in all.
- Store retention (`docs/DECISIONS.md` 2026-10-16 "Retention is set by
  config") is live on the VM since the sideloaded rebuild to 6234510 (30 min
  5 s; its backup 5.93 GB in about 14 min): the first start deleted all 144
  closed sessions (1.9 M detections) in about 1 min 45 s, none was open; the
  store file stays 5.93 GB of free pages (no `VACUUM`), and the next backup
  was 336 KB in 0.8 s. `bin/verify` there: unit 1462 passed; acceptance 45
  passed, 0 failed, 30 skipped in 692 s; 838 s in all.
- Errors swept before the push (2026-10-17, `docs/DECISIONS.md` "Errors
  swept before the push"): the unit run with every warning, the platform VM's
  logs, every range host, the console in a browser and the acceptance skips;
  13 faults fixed at their cause (among them the retention lock, GNS3 display
  containers left running, Filebeat's first connection, Kibana's objects
  never imported on a fresh boot, the edge's early template pass), the rest
  third-party or expected. `bin/verify` there on fba99ae: unit 1469 passed, no
  warnings; acceptance 45 passed, 0 failed, 30 skipped (all Docker-only) in
  751 s; the sweep after it clean.
- The coach finds every step's target (2026-10-17, `docs/DECISIONS.md` "The
  coach finds every step's target"): a pane step is boxed on `#pane-body`
  whichever pane is open, the not-found line names the step's pane, the
  popover stays placed across pane switches, a pressed Kibana filter reloads,
  SQLite transactions begin IMMEDIATE (Next/Skip lost records to `database is
  locked`); Skip is the hint ladder's last rung and `.../do/` is removed. Live sweep on
  e331372, ko and en: 72 of 72 step views boxed, Skip 6 of 6 recorded.

- No acceptance test is skipped on OpenStack (2026-10-17, `docs/DECISIONS.md`
  "No acceptance test is skipped on OpenStack"): of the 30 tests skipped as
  compose-only, 25 run on both substrates and 5 are deleted;
  the run found that the OpenStack terminal's commands never reached the
  operator log (fixed in `deploy/kali/setup.sh`). Deployed 1fd5be3 by the
  sideloaded rebuild (platform, kali, gns3); `bin/verify` there on b324ba5:
  unit 1474 passed; acceptance 70 passed, 0 failed, 0 skipped in 997 s.

- Learner text is plain (2026-10-17, `docs/DECISIONS.md` "Learner text is
  plain"), proven live: deployed 9674d0e by the sideloaded rebuild (platform
  and gns3 from it, kali from 1fd5be3) in 9 min 26 s; `bin/verify` there:
  unit 1476 passed; acceptance 70 passed, 0 failed, 0 errors, 0 skipped in
  987 s. The ko/en sweep: 72 of 72 coach step views boxed, Skip 6 of 6, no
  forbidden learner word, console third-party only, platform log clean. Its
  first pass on 321f0c0 found and fixed the home page's English reset reason,
  nginx's temporary-file warnings and the Map pane's Google Analytics.

- Korean-first learner text (2026-10-17, `ko-first`): 6e3a2f0 rewrote 532
  Korean values of `strings.html` from the meaning in Korean practitioner
  usage and 183 English values to match, took the practitioner terms with
  their sources into `docs/vocabulary.md`, and renamed the Korean GNS3 pair's
  zones; 16e951d reviewed all 951 Korean values again (61 changed) and
  retitled F2 "Sending a web request and reading its status code" (Korean
  likewise). No answer key, check fact or placeholder
  changed. Proven live 2026-10-18 (`docs/DECISIONS.md` "Korean-first
  learner text and docs"): the sweep on 1fc2bc8 found Korean words broken
  mid-word in the coach and the red console's sqlmap labels cut to one
  prefix, fixed in 6b72876 (`word-break: keep-all` for Korean; the label
  wraps); the VM runs 6b72876 (platform from it, gns3 from 9674d0e, kali
  from 1fd5be3; 9 min 19 s); the sweep again: 72 of 72 step views boxed,
  Skip 6 of 6, no clipped text, no forbidden learner word, the Korean map
  captions drawn without overlap, console third-party only, platform log
  clean. No acceptance ran (drawing text and strings only).

- Foundations in one session (2026-10-18, `docs/DECISIONS.md` "Foundations
  run back to back in one session"): `POST /api/sessions/<id>/lesson/` moves
  an open foundation session to the next unit in place (F6's posture
  applied in place, its seed replayed), step records and hints per lesson
  (migration 0027), every check windowed from the unit's start; the console
  starts the next unit 2 s after the last step and closes the session after
  F6; a passed Kali step moves on and the next step shows its row. Proven
  live on 26c1c80 (9 min 45 s deploy): session 871, F1 opened from the
  catalogue, F1-F6 in one session in 5 min 13 s open to close, 27 of 27
  steps passed with no wrong answer, hint or skip, each next lesson started
  6.5-9.4 s after the last answer, F6's `missed` applied in place (3 of 3
  objectives lost), no reset until the close; `test/test_lesson.py` on the
  VM 1 passed. The run found "Run in terminal" dead since 2ea48a5 and its
  paste lost before the OpenStack WAF shell's prompt; both fixed.

- The red console is Kali and a browser (2026-10-18, `docs/DECISIONS.md`
  "The red console is Kali and a browser"): every prepared-attack control is
  gone from the red console (cases, Run all, run buttons, recording window,
  source picker); it is the objectives, the loot submission, Kali and the
  Website pane. The blue console has a divider and Kali below it for lesson
  and scenario sessions, hidden in a wargame. No `fsl-` in the terminals'
  prompts or the WAF banner; the host key is pinned per server generation, so
  no changed-key warning. P0: `/internal/auth-users` is not reachable from
  Kali or the Website pane (WAF `location` 404, `fsl-mgmt` group); nothing
  changed there. Proven live on 51b28dd; the terminal-related acceptance
  modules 10 passed.

- Foundations rebuilt as attack and defence lessons (2026-10-18, 3aa49a5,
  `docs/DECISIONS.md` "Foundations rebuilt as integrated attack and defence
  lessons"): F1 map, F2 DevTools, F3 Kibana, F4 XSS and an IDS rule, F5
  sqlmap on `sort`, F6 an over-broad exception; one highlighted element per
  step, nudge, hint, Skip, a solo last step.
- Foundations review loop (2026-10-19, `docs/DECISIONS.md` "Foundations
  review loop, rounds 2-5"): four live rounds of six reviewers (design, UI,
  terms, AI-tone, realism and leaks, first-time learner) on top of the
  instructor and UX pair; critical and high findings summed over the
  reviewers fell from 7 and 12 in round 2 to 0 and 1 in round 5; medium and
  low stay at 18 and 48 (round 5, five reviewers finished). Every walker run passed 48 of 48 steps. The round-5 fixes
  (9f1f39d..60243e6) are deployed as e4a467e on the platform VM
  (192.168.0.210; all five images sideloaded from it, both slots rebuilt and
  configured, `ready` true) but not re-reviewed: round 6 and the full
  `bin/verify` with acceptance were skipped at the user's request.
  `bin/verify --fast`: 1666 passed. Decided, not fixed, with reasons: in the
  same entry.
- Unverified and open: the round-5 fixes have had no panel review and no
  live acceptance since round 4's changes; Kibana's learner space still shows
  Home and Stack Management in its menu (their pages answer 403) and ad-hoc
  data views cannot be turned off in 8.15; no taste items were collected.
  The e4a467e smoke (session 907, F1-F3 with the walker fixed for its own
  artefacts) passed 20 of 20 steps, but F1 and F2 did not move to the next
  lesson by themselves within 4 minutes (the walker moved them through the
  API); F3 did move to F4 by itself. Cause not found yet; the "다음 레슨"
  button is shown on every finished lesson. Panes seen loading in the smoke
  and in the round-6 run: map, website, DevTools, Kibana, IDS rules, Kali
  and WAF terminals.
- To try it: open http://192.168.0.210:8000, open the catalogue, start the
  foundations course ("레슨 1") and go F1 to F6 in one session; about 30-40
  minutes by hand.

## Waiting for the user

1. Gate 2: push `ko-first` to `dev` (fast-forward).
2. After the push: the images workflow, then `bin/cloud up --replace`
   without `--sideload`. Proven already by the sideloaded runs: the Heat
   template (8002, 3080, `python3-venv`, `nodejs`, the syslog sysctl), the
   store backup and restore, the range key, `fsl-gns3`. Left for that run:
   the GHCR images of the new commit, and the `fsl-wargame-host` image
   rebuilt for its tag.
   Store retention is already pruned on the running VM, so that run's
   backup is small.
3. Release the leftover floating IP 192.168.0.220 in `fsl-range`.
4. The `/api/rules/suppressions/` rename, publishing the OPNsense image.

## Next, in order

0. Capture the learner map after f0bce06 (the VM is reachable only from the
   lab network).
1. 4.2, a person as the red team against the learner: the engine accepts
   `red: person`; needs a second person to run it live.
2. A corp scenario: corp's CVEs succeed but it has no customer
   traffic; needs a generator for WordPress first (P3's shape).
3. A range reset interrupted by a platform restart is not resumed at boot;
   deploy only when `/api/range/ready/` shows no slot resetting, or resume it.
4. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
