# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-20 (the platform VM runs bf96876's code). The commits after
bf96876 are documents only, so the test counts below were measured on
bf96876's code (as 8752a35 before the squash) and still hold for HEAD.
Written for a session that has the cloud (master@192.168.0.100,
Keystone http://192.168.0.110:5000) and the Internet.

## Where things stand

- Commit ids from 2026-10-20 such as 620592f, 8f19f43, 3834b61, e01b1f3 and
  8752a35 predate the squash into bf96876..1cc5d96. They are on the local
  backup/pre-squash-20261020* branches, not on dev.
- 2026-10-20: the user ruled the product OpenStack-only (Kolla-Ansible
  2026.1, kvm), superseding the 2026-10-11 first-class-substrate ruling
  (`docs/DECISIONS.md` 2026-10-20). The docker substrate still exists in the
  code; its removal is planned and decided, not started
  (`docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`).
  Newcomer bring-up fixed and documented (c321210, b231c6c, 7d8e3c2,
  5420d04, a662fdf: LF line endings, range key made by the first `bin/cloud
  up`, `openstack` CLI found in `.venv`, recovery when the platform VM never
  came up, README and `docs/OPENSTACK.md` as numbered steps). The one-VM
  trial (`docs/OPENSTACK.md` §9) ran end to end later the same day and its
  seven defects are fixed in the document (bullet after the next two). The
  changed bring-up paths ran live and are proven (next two bullets).
- Live checks of the bring-up paths (2026-10-20, `docs/DECISIONS.md` "Live
  checks of the bring-up paths"). Run 1, code 620592f: `bin/cloud up
  --replace --sideload` passed in 27 min 13 s; the full `bin/verify` on the VM
  passed (unit 1706; acceptance 73 passed, 0 failed, 0 errors, 0 skipped,
  1129 s; ratchet ok). It found three bugs: 35 orphan `fsl-platform.mgmt`
  ports made `down` fail with 409 SubnetInUse (older than this branch); plain
  `up` failed on a stopped container; the redone hand-over dropped
  `FSL_SIDELOADED`. Fixed in 8f19f43 (`bin/verify --fast` 1711 passed). Run 2,
  code 8f19f43: plain `up` with a stopped container and no password line
  passed (71 s, `FSL_SIDELOADED` kept); `up --replace --sideload` left no
  detached port (14 min 3 s); `down` passed with no hand work (32 s); `up
  --sideload` restored `db-20261020T050321Z` and the range was ready (15 min
  52 s).
- The four items left open by those runs are closed (7f6f31c, 3834b61; run
  live, `docs/DECISIONS.md` "The one-VM trial and the last bring-up fixes"):
  `down` beside a stopped container (40 s), `resume` checking the hand-over
  every time (89 s), the first range key made live (15 min 53 s), and the
  wargame host kept across `down` then `up` (8 min 56 s, nothing built).
  e01b1f3 then made an image digest take only the executable bit of each
  file's mode, so a sideloaded checkout and a clone of one commit plan the
  same image.
- The §9 one-VM trial, 2026-10-20 on e01b1f3 (on the KVM test cloud, so the
  VirtualBox and VMware settings were not exercised): `deploy` 11 min 39 s,
  README step 7 17 min 41 s from an empty cloud with four builders in
  parallel; the session page opened in 9.3 s and 6.9 s, the blue console
  showed the Map pane, and the range was ready again 80 s and 70 s after a
  close. The trial VM was deleted afterwards.
- Full `bin/verify` on the VM at e01b1f3 (2026-10-20), run twice: unit 1717
  passed both times. First: acceptance 72 passed, 1 failed (1257 s),
  `test_corp_authz`'s live content overwrite got WordPress's "Invalid nonce."
  and passed on rerun. Second: acceptance 73 passed, 0 failed, 0 errors, 0
  skipped in 1155 s; ratchet ok (`core_loc` 584, `dependencies` 6, `services`
  10). About 20 minutes each.
- Not run live: the GHCR images of the new commit; the VirtualBox and VMware
  settings of §9.1; a host browser reaching the floating IP of a one-VM
  cloud.
- Goal in flight: the docker substrate removal, not started. Plan:
  `docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`; the
  user passed gate 1 on 2026-10-20 and chose to run it as the next task (see
  Next, 1). The scenario course (design
  `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`,
  rulings in the 2026-10-13 and 2026-10-14 entries of `docs/DECISIONS.md`) is
  finished.
- History since 8f9acb0 is in `git log 8f9acb0..`: the GNS3 topology (P1),
  foundations F1-F6 (P2), customer traffic (P3), the scenario engine and
  console (P4), scenarios 1.1-1.3, 2.1-2.3, 3.1-3.4 and 4.1 (P5), the older
  course removed (P6), Korean-first learner text, the foundations in one
  session, the red console as Kali and a browser, the foundations rebuilt as
  attack and defence lessons, the review loop rounds 2-5.
- Full `bin/verify` on the VM at 8752a35 (2026-10-20), with the `.venv` the VM
  made itself: unit 1718 passed (pytest items; the plan's `tests` number,
  1,232, counts test functions as `bin/measure` does, so the two differ);
  acceptance 73 passed, 0 failed, 0 errors, 0 skipped; ratchet ok; about 22
  minutes. This is the last full run, on the code that became bf96876.
  `bin/verify` refuses to run with an open session and restarts the platform
  container. `bin/verify --fast` passed 1666 on e4a467e, 1706 on 620592f, 1711
  on 8f19f43, 1717 on e01b1f3 and 1718 on 8752a35; it has not been rerun on
  HEAD, whose later commits change documents only. Since 8752a35 the platform
  VM makes `/opt/fsl/.venv` itself at first boot and after a sideload checkout
  (proven on a fresh VM 2026-10-20). The GHCR images build
  (`.github/workflows/images.yml`) for the current `dev` has not been checked;
  check it with `gh run list --workflow images.yml --branch dev --limit 3`.
- Every scenario was run live on OpenStack (both slots): each failed a final
  check with a wrong defence and passed one with a right defence. Table:
  `docs/DECISIONS.md`, "P5 built".
- The platform VM (192.168.0.210) is rebuilt by `bin/cloud up --replace
  --sideload` (`docs/OPENSTACK.md` §5.3; `docs/DECISIONS.md` 2026-10-15 "The
  platform VM's rebuild runs an unpushed commit"). It runs bf96876's code
  (its /opt/fsl checkout is at 8752a35, the same code before the squash; show
  it with `sh s.sh 'git -C /opt/fsl rev-parse HEAD'`, see Operator tooling).
  The platform image is built from 8752a35's `platform/`, which is the same as
  HEAD's, and is the only sideloaded image
  (`FSL_SIDELOADED=platform`); `FSL_IMAGE_TAG` is 4fd2ab1, the `dev` commit
  the VM cloned, so board, corp and corp-db run GHCR's copies at that tag.
  Ready, both slots READY, no open session. Do not reboot it:
  `fsl-platform.service` can pull GHCR's copies over the sideloaded images.
  The newest store copy (about 0.4 MB, `db-20261020T111111Z.sqlite3`) is in
  `backups/` of this worktree and of the main checkout; older copies, among
  them the 59 MB `db-20261019T033253Z.sqlite3`, are in
  `~/.cache/fsl-work/backup-safe/`.
- Earlier full `bin/verify` on the VM: 9674d0e, unit 1476 passed; acceptance
  70 passed, 0 failed, 0 skipped in 987 s. Details of each are in `docs/DECISIONS.md`
  ("Learner text is plain", "Korean-first learner text and docs",
  "Foundations run back to back in one session", "The red console is Kali and
  a browser", "Foundations rebuilt as integrated attack and defence
  lessons").
- Foundations review loop (2026-10-19, `docs/DECISIONS.md` "Foundations review
  loop, rounds 2-5"): four live rounds of six reviewers on top of the
  instructor and UX pair; critical and high findings summed over the
  reviewers fell from 7 and 12 in round 2 to 0 and 1 in round 5; medium and
  low stay at 18 and 48. Every walker run passed 48 of 48 steps. The round-5
  fixes (9f1f39d..60243e6) were deployed as e4a467e and the VM's current code carries them (both slots
  rebuilt and configured, `ready` true) but not re-reviewed: round 6 was skipped at the
  user's request. Decided, not fixed, with reasons: in the same entry.
- Unverified and open: the round-5 fixes have had no panel review (the last full
  acceptance passed on 8752a35's code); Kibana's learner space still shows
  Home and Stack Management in its menu (their pages answer 403) and ad-hoc
  data views cannot be turned off in 8.15; no taste items were collected. The
  e4a467e smoke passed 20 of 20 steps (details under Next, 9).
- From a Wi-Fi that also uses 192.168.0.0/24 the lab answers only through the
  WireGuard tunnel: `docs/OPENSTACK.md` §8; the tooling is under "Operator
  tooling" below.
- To try it: open http://192.168.0.210:8000, open the catalogue, start the
  foundations course (its first lesson button) and go F1 to F6 in one session; about 30-40
  minutes by hand.

## Operator tooling

Outside the repo, in `/Users/nekonic/.cache/fsl-work/`. The scripts take the
repo root from the current git checkout (or `FSL_REPO`); run them from the
checkout you work in.

- `. net/env.sh` first: starts a proxy on 127.0.0.1:1088 bound to the
  WireGuard tunnel and puts the ssh and scp wrappers on PATH. Needed when the
  operator's Wi-Fi uses 192.168.0.0/24 (`docs/OPENSTACK.md` §8). The scripts
  below source it themselves.
- `sh reach.sh` checks the platform VM and Keystone.
- `sh build.sh platform` builds the image on the platform VM (the Mac's Docker
  daemon is off) and copies `images/fsl-platform-<HEAD>.tar` back. It knows
  `platform`, `board`, `kali`, `proxy` and `gns3`.
- `sh deploy.sh <tag> platform=<HEAD>` runs `bin/cloud up --replace
  --sideload` with the `openstack` CLI from `osc/bin`; the log is
  `deploy/<tag>.log`.
- `sh s.sh '<cmd>'` runs a command on the platform VM.
- `walker/walk.py` is the lesson walker (Next, 9).

`bin/cloud` needs three gitignored files in the checkout that runs it:
`deploy/openstack/cloud.yaml`, `.venv` and the newest copy in `backups/`.
Both this worktree and the main checkout
(`/Users/nekonic/Documents/GitHub/fsl-project-mvp`) have them now. A worktree
that is cleaned up loses them, so copy them before working in a new one.

## Waiting for the user

1. Release the leftover floating IP 192.168.0.220 in `fsl-range`. It is the
   old acceptance VM's floating IP, still allocated after that VM was deleted
   (`docs/STATE.md`, the "Floating IP 192.168.0.220" backlog item, about line
   988). The user's yes is needed because it is the user's cloud.
2. Two open items in `docs/STATE.md`: renaming `/api/rules/suppressions/`
   (the API disables a rule by commenting it out, which Suricata calls
   something else; about line 1159) and publishing the OPNsense image
   (licence is fine, the trademark policy asks for a note to the project;
   about line 991). Both are the user's call.
3. A rebuild without `--sideload` (`bin/cloud up --replace`) once the images
   workflow for the new commit is green. The sideloaded runs of 2026-10-20 ran
   the Heat template, the store backup and restore of a standing platform, the
   range key copy, `down` and `up` on the current bring-up code. Left for the
   run without `--sideload`: the GHCR images of the new commit and the
   `fsl-wargame-host` image rebuilt for its tag.

## Next, in order

1. Run the docker-substrate removal plan
   (`docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`;
   D1-D4 decided yes; ends with a rebuild of the platform VM and the full
   `bin/verify` on it).
   - Gate 1 is passed (the user decided D1-D4 on 2026-10-20 and chose to run
     it next): start at commit 1 without presenting the plan again. Done =
     commits 1-8 each green on `bin/verify --fast`, then the plan's section 5
     live rows, then the last commit rewrites this file and `docs/STATE.md`,
     then gate 2 (show the change and wait for the push approval).
   - Live steps: only the platform image's context differs from the ref the
     VM cloned, so sideload `platform` alone (`sh build.sh platform`, then
     `sh deploy.sh <tag> platform=<HEAD>`); `bin/platform-rebuild` refuses
     when another image differs.
   - An open session blocks the rebuild and `bin/verify`
     (`GET /api/sessions/?state=open`). A test session: back it up
     (`bin/backup`) and close it. One that may be the user's own (started by a
     person in the console): ask first.
   - To rerun the full suite on the VM, with no open session: `cd /opt/fsl &&
     FSL_PLATFORM_URL=http://192.168.0.210:8000 setsid nohup bin/verify >
     ~/verify-full.log 2>&1 &` (about 1160 s). After a sideload the VM's
     /opt/fsl is the sideloaded HEAD (`docs/OPENSTACK.md` §5.3).
2. Check the `images.yml` run for the current `dev`
   (`gh run list --workflow images.yml --branch dev --limit 3`).
3. Find the cause of the `test_corp_authz` nonce error (seen twice, passes on
   rerun; `docs/STATE.md` backlog 0).
4. Have a newcomer follow README on a clean machine, or run §9 on VirtualBox
   or VMware (the 2026-10-20 trial ran on the KVM test cloud).
5. 4.2, a person as the red team against the learner: the engine accepts
   `red: person`; needs a second person to run it live.
6. A corp scenario: corp's CVEs succeed but it has no customer traffic; needs
   a generator for WordPress first (P3's shape).
7. A range reset interrupted by a platform restart is not resumed at boot;
   deploy only when `/api/range/ready/` shows no slot resetting, or resume it.
8. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
9. Foundations rebuild, remaining (`docs/STATE.md` backlog 0, "Foundations
   rebuild, remaining work"): the F1 and F2 auto-advance that sometimes does
   not fire within 4 min (the e4a467e smoke, session 907, F1-F3: 20 of 20
   steps passed, but F1 and F2 did not move to the next lesson by themselves
   within 4 minutes and the walker moved them through the API; F3 did move to
   F4 by itself; cause not found); re-walk F4-F6 live on e4a467e or
   later; a live review round of 9f1f39d..60243e6 (six reviewers, convergence
   rule, exit on zero countable findings); Kibana's Home and Stack Management
   menu entries; whether the walker (`~/.cache/fsl-work/walker/walk.py`)
   becomes a repo tool.
