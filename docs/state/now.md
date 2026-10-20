# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-20 (the platform VM runs 3da925e's code; 68efc7c is local, not
pushed). Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and the
Internet.

## Where things stand

- 2026-10-20: the product moved to a new OpenStack cloud. The old cloud
  (master@192.168.0.100, Keystone 192.168.0.110, platform VM 192.168.0.210,
  floating IP 192.168.0.220) is in other use by the user and must not be
  touched. The facts, the defects the move found and the fixes are in
  `docs/DECISIONS.md` "The product moved to a new OpenStack cloud"; the cloud's
  values are the "(this cloud)" passages of `docs/OPENSTACK.md` §2-§4.
- The platform VM is `fsl-platform` at 192.168.2.247. It runs dev's 3da925e code
  from GHCR images: nothing was sideloaded (`FSL_SIDELOADED` is unset), and its
  `/opt/fsl` checkout is 3da925e. Its store was restored from
  `db-20261020T111111Z`. One slot (`compute.slots: 1`, the project quota allows
  no more), READY.
- Today's bring-up on the new cloud used GHCR images only. That is the rebuild
  without `--sideload` the previous handover asked for. The `images.yml` run for
  3da925e was green (gh run 39421089777, 2026-10-20T12:17Z).
- 68efc7c (local, not pushed) makes every range subnet announce no DNS resolver
  (`dns_nameservers ["0.0.0.0"]`); without it each lookup in the range waited
  about 25 s (`docs/DECISIONS.md`, same entry). The standing cloud's 32 range
  subnets got the same setting by hand. The platform VM runs 3da925e, which lacks
  68efc7c, so subnets that its code makes would announce 127.0.0.53 again (Next,
  2).
- Full `bin/verify` on the new VM (3da925e): RESULT_PENDING
- 2026-10-20: the user ruled the product OpenStack-only (Kolla-Ansible
  2026.1, kvm), superseding the 2026-10-11 first-class-substrate ruling
  (`docs/DECISIONS.md` 2026-10-20). The docker substrate still exists in the
  code; its removal is planned and decided, not started
  (`docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`).
- Goal in flight: the docker substrate removal. The user passed gate 1 on
  2026-10-20 and chose to run it as the next task (Next, 1). The scenario course
  (design `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`,
  rulings in the 2026-10-13 and 2026-10-14 entries of `docs/DECISIONS.md`) is
  finished.
- Commit ids from 2026-10-20 such as 620592f, 8f19f43, 3834b61, e01b1f3 and
  8752a35 predate the squash into bf96876..1cc5d96. They are on the local
  backup/pre-squash-20261020* branches, not on dev.
- The bring-up paths (`bin/cloud up`, `--replace`, `down`, resume, the first
  range key, the one-VM trial of `docs/OPENSTACK.md` §9) ran live on the old
  cloud before the move and are recorded in `docs/DECISIONS.md` ("Live checks
  of the bring-up paths", "The one-VM trial and the last bring-up fixes"). The
  first `bin/cloud up` on the new cloud ran the same code path again.
- Last full `bin/verify` before the move, on the old cloud's VM at 8752a35's
  code (2026-10-20): unit 1718 passed; acceptance 73 passed, 0 failed, 0 errors,
  0 skipped; ratchet ok; about 22 minutes. `bin/verify` refuses to run with an
  open session and restarts the platform container. The unit count is pytest
  items; the `tests` number in `metrics.json` counts test functions as
  `bin/measure` does, so the two differ. `bin/verify --fast` passed 1718 on
  8752a35.
- Not run live: the VirtualBox and VMware settings of `docs/OPENSTACK.md` §9.1;
  a host browser reaching the floating IP of a one-VM cloud.
- Every scenario was run live on OpenStack (both slots, on the old cloud): each
  failed a final check with a wrong defence and passed one with a right
  defence. Table: `docs/DECISIONS.md`, "P5 built".
- Foundations review loop (2026-10-19, `docs/DECISIONS.md` "Foundations review
  loop, rounds 2-5"): critical and high findings summed over the reviewers fell
  from 7 and 12 in round 2 to 0 and 1 in round 5. The round-5 fixes were not
  re-reviewed: round 6 was skipped at the user's request.
- Unverified and open: Kibana's learner space still shows Home and Stack
  Management in its menu (their pages answer 403) and ad-hoc data views cannot
  be turned off in 8.15; no taste items were collected. The e4a467e smoke passed
  20 of 20 steps (details under Next, 9).
- To try it: open http://192.168.2.247:8000 (through the VPN), open the
  catalogue, start the foundations course (its first lesson button) and go F1 to
  F6 in one session; about 30-40 minutes by hand.

## Operator tooling

Outside the repo, in `/Users/nekonic/.cache/fsl-work/`. The scripts take the
repo root from the current git checkout (or `FSL_REPO`); run them from the
checkout you work in. They target the new cloud (192.168.2.247 and 10.0.0.10)
and need the VPN up. They no longer source `net/env.sh`: that WireGuard proxy
was for the old lab. The old copies are `s.sh.old-cloud`, `reach.sh.old-cloud`,
`build.sh.old-cloud` and `deploy.sh.old-cloud`; do not use them.

- `sh reach.sh` checks the platform VM and Keystone.
- `sh build.sh platform` builds the image on the platform VM (the Mac's Docker
  daemon is off) and copies `images/fsl-platform-<HEAD>.tar` back. It knows
  `platform`, `board`, `kali`, `proxy` and `gns3`.
- `sh deploy.sh <tag> platform=<HEAD>` runs `bin/cloud up --replace
  --sideload` with the `openstack` CLI from `osc/bin`; the log is
  `deploy/<tag>.log`. A rebuild from images on GHCR needs no script: run
  `bin/cloud up --replace` from this worktree.
- `sh s.sh '<cmd>'` runs a command on the platform VM, for example `sh s.sh 'git
  -C /opt/fsl rev-parse HEAD'`.
- `walker/walk.py` is the lesson walker (Next, 9).

`bin/cloud` needs three gitignored files in the checkout that runs it. This
worktree has them for the new cloud: `deploy/openstack/cloud.yaml`, a `.venv`
symlink to the main checkout's `.venv`, and
`backups/db-20261020T111111Z.sqlite3`. The main checkout
(`/Users/nekonic/Documents/GitHub/fsl-project-mvp`) still has a `cloud.yaml` that
names the old cloud; do not run `bin/cloud` from it. A worktree that is cleaned
up loses these files, so copy them before working in a new one. Older store
copies, among them the 59 MB `db-20261019T033253Z.sqlite3`, are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

1. Two open items in `docs/STATE.md`: renaming `/api/rules/suppressions/`
   (the API disables a rule by commenting it out, which Suricata calls
   something else; about line 1176) and publishing the OPNsense image
   (licence is fine, the trademark policy asks for a note to the project;
   about line 1008). Both are the user's call.

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
   - Live steps run on the new cloud (192.168.2.247). Only the platform image's
     context differs from the ref the VM cloned, so sideload `platform` alone
     (`sh build.sh platform`, then `sh deploy.sh <tag> platform=<HEAD>`);
     `bin/platform-rebuild` refuses when another image differs.
   - An open session blocks the rebuild and `bin/verify`
     (`GET /api/sessions/?state=open`). A test session: back it up
     (`bin/backup`) and close it. One that may be the user's own (started by a
     person in the console): ask first.
   - To rerun the full suite on the VM, with no open session: `cd /opt/fsl &&
     FSL_PLATFORM_URL=http://192.168.2.247:8000 setsid nohup bin/verify >
     ~/verify-full.log 2>&1 &` (about 1160 s on the old cloud; not yet known
     here). After a sideload the VM's /opt/fsl is the sideloaded HEAD
     (`docs/OPENSTACK.md` §5.3).
2. After the user pushes 68efc7c to `dev` and the `images.yml` run for that
   commit is green (`gh run list --workflow images.yml --branch dev --limit 3`),
   rebuild the platform VM from it with `bin/cloud up --replace`, run from this
   worktree and without `--sideload`. The standing VM runs 3da925e, which lacks
   the DNS setting of 68efc7c.
3. Find the cause of the `test_corp_authz` nonce error (seen twice on the old
   cloud, passes on rerun; `docs/STATE.md` backlog 0).
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
