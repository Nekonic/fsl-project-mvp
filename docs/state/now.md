# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-13. Written for a session that has the cloud
(master@192.168.0.100, Keystone http://192.168.0.110:5000) and the Internet.

## Where things stand

- Goal in flight: the blue-team course. Design and rulings D1-D11:
  `docs/superpowers/specs/2026-10-13-blue-team-course-design.md` and the
  2026-10-13 entries in `docs/DECISIONS.md`.
- `dev` = 8f9acb0. This branch (`claude/task-list-review-fc4953`) adds the
  course on top: the lesson foundation (server-side steps and checks, replays
  out of both scores, WAF snapshots, ungated open path), the existing lesson
  made honest (Lesson / Practice / Wargame rungs, ticket, start card,
  debrief), lessons 0, 1, 3, 4, 5, 7, and the fixes the first live run forced.
  Not pushed.
- Platform VM 192.168.0.210 runs this branch's platform image, built on the
  VM under the dev tag; `/opt/fsl` git index is re-pointed at the branch. Its
  pre-course store backup is in `/opt/fsl/backups/*-pre-course/`. The 8002
  rule on the `fsl-platform` security group was added by hand (the Heat
  template now has it).
- Live on 2026-10-13: full `bin/verify` on the VM, unit 2003 passed,
  acceptance 77 passed / 0 failed / 0 errors / 71 skipped in 1,448 s; every
  lesson walked end to end over the API on a slot.

## Waiting for the user

1. Gate 2: push this branch to `dev` (fast-forward).
2. After the push: the images workflow, then `bin/cloud up --replace` run
   untouched. It proves the 8002 rule and the `python3-venv`/`nodejs`
   packages from the Heat template and the store restore under migrations
   0020-0023; none of these can run before the images exist on GHCR.
3. Review of the lesson text (now seven lessons; theory and hint cards still
   name the answers by design).
4. Release the leftover floating IP 192.168.0.220 in `fsl-range`.
5. Test audit (2026-10-10 list), the `/api/rules/suppressions/` rename,
   publishing the OPNsense image.

## Next, in order

1. Lesson 6 (corp, "make the option flip noticed"): needs a red actor outside
   the lesson and repeatable corp replays (per-replay logins, reset before
   VERIFY).
2. At PL4, excluding 920273, 920272 and 942460 on `ARGS:q` under `/search/`
   did not serve the Korean search (hypothesis: 920272 also matches the
   request URI); measure, so the assessment has a narrow fix as well as the
   level.
3. The unexplained `test_corp_*` "no `_wpnonce`" error (once, passed on
   rerun).
4. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
