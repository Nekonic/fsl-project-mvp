# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-16 (after the test audit's live run). Written for a session that has the cloud
(master@192.168.0.100, Keystone http://192.168.0.110:5000) and the Internet.

## Where things stand

- Goal in flight: the scenario course. Design:
  `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`;
  rulings: the 2026-10-13 and 2026-10-14 entries in `docs/DECISIONS.md` (P4,
  P5 and P6 built).
- `dev` = 8f9acb0. This branch (`claude/task-list-review-fc4953`) adds, not
  pushed: the GNS3 topology and its pane (P1), foundations F1-F6 (P2),
  customer traffic (P3), the scenario engine and console (P4), and the
  scenarios 1.1-1.3, 2.1-2.3, 3.1-3.4 and 4.1 on the board (P5), with the
  fixes the live runs forced, and P6: the older course (lessons 0-5 and 7,
  VERIFY, the lesson debrief, the Lesson / Practice / Wargame rungs,
  `Session.mode`) removed, migration 0026, tests 2052 -> 1981 (71 deleted,
  121 retargeted); and the follow view removed with F2 and F5 retargeted
  (2026-10-16), plus the three fixes its live run forced (F5 reads
  `rule_id`; a passed Kali step keeps its count; the popover is placed again).
- Every scenario was run live on OpenStack (platform VM 192.168.0.210, both
  slots): each failed a final check with a wrong defence and passed one with
  a right defence. The table is in `docs/DECISIONS.md`, "P5 built".
- The platform VM (192.168.0.210) was rebuilt twice on 2026-10-15 and four
  times on 2026-10-16 by `bin/cloud up --replace --sideload` (`docs/OPENSTACK.md`
  §5.3, `docs/DECISIONS.md` 2026-10-15 "The platform VM's rebuild runs an
  unpushed commit"): it runs ee2e5b9 with the platform image built from it
  and the gns3 image from 1814e5c, tagged 8f9acb0
  (`FSL_IMAGE_TAG`); every other image is GHCR's 8f9acb0. Do not reboot it:
  `fsl-platform.service` can pull GHCR's 8f9acb0 over the sideloaded
  images. The old VM's `/opt/fsl/backups` (P4 and P6 store copies) and both
  runs' store backups are in the main checkout's `backups/` on the operator's
  machine (`old-platform-vm-20261015-opt-fsl-backups.tgz`,
  `db-20261015T061630Z.sqlite3`, `db-20261015T073913Z.sqlite3`); the
  2026-10-16 runs' four are in this worktree's `backups/`
  (`db-20261016T112259Z`, `T121617Z`, `T124957Z`, 5.96 GB each;
  `T143237Z`, 6.02 GB).
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

## Waiting for the user

1. Gate 2: push this branch to `dev` (fast-forward).
2. After the push: the images workflow, then `bin/cloud up --replace`
   without `--sideload`. Proven already by the sideloaded runs: the Heat
   template (8002, 3080, `python3-venv`, `nodejs`, the syslog sysctl), the
   store backup and restore, the range key, `fsl-gns3`. Left for that run:
   the GHCR images of the new commit, and the `fsl-wargame-host` image
   rebuilt for its tag.
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
