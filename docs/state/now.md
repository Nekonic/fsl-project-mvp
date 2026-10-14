# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-14. Written for a session that has the cloud
(master@192.168.0.100, Keystone http://192.168.0.110:5000) and the Internet.

## Where things stand

- Goal in flight: the scenario course. Design:
  `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`;
  rulings: the 2026-10-13 entries in `docs/DECISIONS.md` (P4 built, P5 built).
- `dev` = 8f9acb0. This branch (`claude/task-list-review-fc4953`) adds, not
  pushed: the GNS3 topology and its pane (P1), foundations F1-F6 (P2),
  customer traffic (P3), the scenario engine and console (P4), and the
  scenarios 1.1-1.3, 2.1-2.3, 3.1-3.4 and 4.1 on the board (P5), with the
  fixes the live runs forced. The older course (lessons 0-5 and 7, the
  Lesson / Practice / Wargame rungs) is still in the code beside it.
- Every scenario was run live on OpenStack (platform VM 192.168.0.210, both
  slots): each failed a final check with a wrong defence and passed one with
  a right defence. The table is in `docs/DECISIONS.md`, "P5 built".
- The platform VM runs this branch's platform image, built on the VM; its
  pre-course store backup is in `/opt/fsl/backups/*-pre-course/`. The UDP
  receive-buffer sysctl was applied there by hand (the same file cloud-init
  now writes).

## Waiting for the user

1. Gate 2: push this branch to `dev` (fast-forward).
2. After the push: the images workflow, then `bin/cloud up --replace` run
   untouched. It proves what cannot run before the images exist on GHCR: the
   8002 rule and the `python3-venv`/`nodejs` packages from the Heat template,
   the store restore under the new migrations, the GNS3 service from its
   GHCR image, and the syslog sysctl from cloud-init on a rebuilt VM.
3. Release the leftover floating IP 192.168.0.220 in `fsl-range`.
4. Test audit (2026-10-10 list), the `/api/rules/suppressions/` rename,
   publishing the OPNsense image.

## Next, in order

1. P6 cleanup: remove lessons 0-5 and 7 and the rungs now that the
   foundations and scenarios replace them; docs; a live run.
2. 4.2, a person as the red team against the learner: the engine accepts
   `red: person`; needs a second person to run it live.
3. A corp lesson or scenario: corp's CVEs succeed but it has no customer
   traffic; needs a generator for WordPress first (P3's shape).
4. A range reset interrupted by a platform restart is not resumed at boot;
   deploy only when `/api/range/ready/` shows no slot resetting, or resume it.
5. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
