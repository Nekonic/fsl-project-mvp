# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-21 (the commits above 3da925e are on `dev`; the platform VM
runs dev's head with a sideloaded platform image built from this branch's
code). Written for a session that reaches the new cloud through the user's
VPN (Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet.

## Where things stand

- 2026-10-20: the product moved to a new OpenStack cloud. The old cloud
  (master@192.168.0.100, Keystone 192.168.0.110, platform VM 192.168.0.210,
  floating IP 192.168.0.220) is in other use by the user and must not be
  touched. The facts, the defects the move found and the fixes are in
  `docs/DECISIONS.md` "The product moved to a new OpenStack cloud"; the cloud's
  values are the "(this cloud)" passages of `docs/OPENSTACK.md` §2-§4.
- The platform VM is `fsl-platform` at 192.168.2.247. Its `/opt/fsl` is a git
  checkout of dev's head, sent to the VM over git (the `cloud` remote,
  ssh://ubuntu@192.168.2.247/opt/fsl, branch `work`). It runs a platform image
  built from this branch's code before the push guard was added, sideloaded
  (`FSL_SIDELOADED=platform`); the platform VM's other images come from GHCR.
  That image holds the fix that makes range subnets announce no DNS resolver.
  Its store was restored from `db-20261020T184152Z`. One
  slot (`compute.slots: 1`: the project quota allows no more), READY.
- 2026-10-21, decided by the user: the estate sensor's `HOME_NET` no longer
  holds the attacker origins, and a move to the lesson a session is
  already on changes nothing (re-checked under the lock, and it
  seeds the lesson's logs again only if they are missing, after the
  pre-push review). Proven on the VM: sensor acceptance 14 passed, and
  session 1077 kept `lessons` at `[f1]` on a repeated move (`docs/DECISIONS.md`
  "The estate sensor's HOME_NET and a repeated lesson move").
- 2026-10-21: the docker substrate removal is done in code (the removal
  commit, then the documents, the README laptop note, the two-session fixture
  fix and the terminal-isolation test fix) and proven live on this
  cloud. The record is in `docs/DECISIONS.md` "The docker substrate is removed",
  "Live proof on the new cloud": `bin/cloud up --replace --sideload` passed in
  19 min 44 s, and the full `bin/verify` on the VM, on the code with the docker substrate removed, passed with 8
  failures that all come from the single slot (next bullet).
- Full `bin/verify` runs on the new cloud are recorded in `docs/DECISIONS.md`:
  the 3da925e run (before the removal) in "The product moved to a new OpenStack
  cloud", the run after the removal in "The docker substrate is removed".
  - 3da925e: unit 1718 passed; acceptance 68 passed, 2 failed, 3 errors, 0
    skipped in 10024 s.
  - After the removal: unit 1575 passed; acceptance 65 passed, 2 failed, 6 errors, 0
    skipped in 10241 s; ratchet ok (core_loc 584, dependencies 6, services 5,
    wargame_services 4, product_loc 25016, tests 1198).
  - Every failure comes from the single slot, none from the removal. The
    errors are `409 "1 session is already open on the range; close one first"`
    in `test_concurrent_sessions` and `test_lesson`. The 2 failures are
    `test_strategy_honesty`: its shared session was deleted by retention
    (`FSL_RETAIN_CLOSED_MINUTES` 60), because a one-slot run takes about 2 h 50
    min (slot resets take 4-5 min on this cloud, 70-80 s on the previous one).
  - The unit count fell from 1718 to 1575 because the removal deleted tests of
    removed mechanisms.
- 2026-10-20: the user ruled the product OpenStack-only (Kolla-Ansible
  2026.1, kvm), superseding the 2026-10-11 first-class-substrate ruling
  (`docs/DECISIONS.md` 2026-10-20). The plan is
  `docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`. Docker
  stays on the platform VM (the platform's own services), the wargame host and
  the GNS3 display nodes.
- Goal in flight: none. The scenario course (design
  `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`,
  rulings in the 2026-10-13 and 2026-10-14 entries of `docs/DECISIONS.md`) is
  finished.
- The bring-up paths (`bin/cloud up`, `--replace`, `down`, resume, the first
  range key, the one-VM trial of `docs/OPENSTACK.md` §9) ran live on the old
  cloud before the move and are recorded in `docs/DECISIONS.md` ("Live checks
  of the bring-up paths", "The one-VM trial and the last bring-up fixes"). The
  first `bin/cloud up` on the new cloud ran the same code path again.
- Last full `bin/verify` before the move, on the old cloud's VM
  (2026-10-20): unit 1718 passed; acceptance 73 passed, 0 failed, 0 errors,
  0 skipped; ratchet ok; about 22 minutes. `bin/verify` refuses to run with an
  open session and restarts the platform container. The unit count is pytest
  items; the `tests` number in `metrics.json` counts test functions as
  `bin/measure` does, so the two differ. `bin/verify --fast` passed 1718 on
  the same code.
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
  20 of 20 steps (details under Next, 11).
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
- `walker/walk.py` is the lesson walker (Next, 11).
- The repository has a `cloud` git remote (the VM's `/opt/fsl`). Work goes to
  the VM with `git push cloud HEAD:refs/heads/work` and `git -C /opt/fsl
  checkout --detach work` on the VM. Claude Code asks the user before every push to GitHub
  or pull request (the `ask` rules in `.claude/settings.json`).

`bin/cloud` needs three gitignored files in the checkout that runs it:
`deploy/openstack/cloud.yaml`, `.venv` and the newest copy in `backups/`. The
main checkout (`/Users/nekonic/Documents/GitHub/fsl-project-mvp`) and this
worktree both have them for the new cloud (newest copy
`db-20261021T095201Z.sqlite3`); the old cloud's `cloud.yaml` is kept outside the
repo in `~/.cache/fsl-work/old-cloud/`. A worktree that is cleaned
up loses these files, so copy them before working in a new one. Older store
copies, among them the 59 MB `db-20261019T033253Z.sqlite3`, are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

1. The project quota: cores 24, RAM 65536 MB, instances 12 (now 20 cores, 51200
   MB, 10 instances, of which the user's VM `FSL-front` takes 4 cores and 8 GB),
   and `compute.slots: 2` in `deploy/openstack/cloud.yaml`.
2. Two open items in `docs/STATE.md`: renaming `/api/rules/suppressions/`
   (the API disables a rule by commenting it out, which Suricata calls
   something else; about line 1176) and publishing the OPNsense image
   (licence is fine, the trademark policy asks for a note to the project;
   about line 1008). Both are the user's call.

## Next, in order

1. After the user raises the quota and sets `compute.slots: 2`, rerun the full
   `bin/verify` on the VM with no open session. Expect the 8 one-slot
   failures and errors of the run after the removal to go.
   - An open session blocks `bin/verify`
     (`GET /api/sessions/?state=open`). A test session: back it up
     (`bin/backup`) and close it. One that may be the user's own (started by a
     person in the console): ask first.
   - To run it: `cd /opt/fsl && FSL_PLATFORM_URL=http://192.168.2.247:8000
     setsid nohup bin/verify > ~/verify-full.log 2>&1 &`. After a sideload the
     VM's /opt/fsl is the sideloaded HEAD (`docs/OPENSTACK.md` §5.3).
2. After the push: check the `images.yml` run for dev's head (`gh run list
   --workflow images.yml --branch dev --limit 3`), then rebuild the platform VM
   from the main checkout with `bin/cloud up --replace`, without `--sideload`,
   so the VM runs dev from GitHub and GHCR. The standing VM runs a sideloaded
   platform image.
3. Open items that need a decision (`docs/DECISIONS.md` "The docker substrate
   is removed"): `deploy/proxy/stamp.py` and `deploy/kali/setup.sh` still name
   `/var/lib/session/origin`, which nothing writes (editing them changes the
   Kali image digest once more).
4. A one-slot acceptance run outlives `FSL_RETAIN_CLOSED_MINUTES` (60): the
   shared session of `test_strategy_honesty` is deleted before the test reads
   it. Open question: either the harness keeps a session it still needs, or
   the retention window accounts for a long run.
5. Find the cause of the `test_corp_authz` nonce error (seen twice on the old
   cloud, passes on rerun; `docs/STATE.md` backlog 0).
6. Have a newcomer follow README on a clean machine, or run §9 on VirtualBox
   or VMware (the 2026-10-20 trial ran on the KVM test cloud).
7. 4.2, a person as the red team against the learner: the engine accepts
   `red: person`; needs a second person to run it live.
8. A corp scenario: corp's CVEs succeed but it has no customer traffic; needs
   a generator for WordPress first (P3's shape).
9. A range reset interrupted by a platform restart is not resumed at boot;
   deploy only when `/api/range/ready/` shows no slot resetting, or resume it.
10. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
11. Foundations rebuild, remaining (`docs/STATE.md` backlog 0, "Foundations
   rebuild, remaining work"): the F1/F2 "auto-advance" item was a walker
   race, fixed in the walker on 2026-10-21 (`docs/STATE.md`); the 2026-10-21 walk on the new cloud (session
   1070, F1-F6): 46 of 48 steps passed; the two misses are walker faults: F4
   replay waited for a search box on the 403 page the previous step left in
   the Website pane, and F6 replay never read the sqlmap command its card
   shows (walker shot 254); fix both in the walker and re-walk; a live review round of 9f1f39d..60243e6 (six reviewers, convergence
   rule, exit on zero countable findings); Kibana's Home and Stack Management
   menu entries; whether the walker (`~/.cache/fsl-work/walker/walk.py`)
   becomes a repo tool.
