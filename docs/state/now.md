# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; detail in `git
log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-24 (nothing is pushed; the platform VM runs this branch with
the platform, board and corp images sideloaded, two range slots). Written for
a session that reaches the new cloud through the user's VPN (Keystone
http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and the Internet.

## Where things stand

- Push state: the branch `claude/cloud-vm-status-report-45aefd` holds about 50
  commits over `dev` and none is pushed. A push goes to `dev` as a fast-forward,
  and only when the user approves it.
- 2026-10-20: the product moved to a new OpenStack cloud. The old cloud
  (master@192.168.0.100, Keystone 192.168.0.110, platform VM 192.168.0.210,
  floating IP 192.168.0.220) is in other use by the user and must not be
  touched. The facts, the defects the move found and the fixes are in
  `docs/DECISIONS.md` "The product moved to a new OpenStack cloud"; the cloud's
  values are the "(this cloud)" passages of `docs/OPENSTACK.md` §2-§4.
- The platform VM is `fsl-platform` at 192.168.2.247. It was rebuilt on
  2026-10-24 from this branch with `bin/cloud up --replace --sideload
  platform=... --sideload board=... --sideload corp=...` (the rebuild that
  built the three new VM images took 65 min). It runs `FSL_SIDELOADED=board,corp,platform`; the other images come
  from GHCR. Both slots (`compute.slots: 2`) are READY. All three VM images
  (Kali, WAF, wargame host) were rebuilt without `snapd` and `ModemManager`,
  and the wargame host image holds a pristine copy of the wargame data made
  with `--innodb-rollback-segments=1`. The wargame hosts run on `m1.medium`
  (a trial on the 4-vCPU `dba.medium` changed nothing).
- Quota (the user raised it on 2026-10-24): 24 cores, 57344 MB of RAM, 12
  instances. The project uses 18 cores, 40 GB and 9 instances
  (`docs/OPENSTACK.md` §3.2).
- A rebuilt VM has new ssh host keys. Check the new fingerprints in the VM's
  console log (`openstack console log show fsl-platform`, the cloud-init
  "SSH HOST KEY FINGERPRINTS" block) before replacing the operator machine's
  `known_hosts` entry for 192.168.2.247. The operator key is
  `~/.ssh/fsl_claude` (Nova keypair `fsl-claude`).
- Slot reset, close to READY: 70-82 s for one slot and 98-99 s for two at once.
  It was 272-314 s on this cloud before the pristine restore. What was
  measured and changed is in `docs/TROUBLESHOOTING.md`. A copy-on-write
  restore on an XFS loop file was measured and rejected (commits 2-2.5 times
  slower). Open: `com01`'s disk and Nova `cpu_mode`, which are the cloud
  admin's.
- F4 step 3 (the tester report): the Kibana coach rings the row that has the
  field, asks for the field name when the panel scrolled it under the footer,
  moves off a document without the field, and asks for a new query after a
  closed document lacked the field. The first help for the step is KQL advice,
  and the step 6 coach says an empty result is a result. One live run passed
  all five checks. The last fix (the new query after a closed document) is
  unit-tested and deployed, and was not walked live.
- `bin/platform-rebuild`'s ssh now sends keepalives (`ServerAliveInterval=15`,
  `ServerAliveCountMax=4`) and gives up on a dead connection; a dead VPN
  connection had hung one rebuild for 3 hours.
- Full `bin/verify` on this branch (unit and acceptance against
  http://192.168.2.247:8000): unit 1626 passed; acceptance 73 passed, 0 failed, 0 errors, 0 skipped in 1867 s; ratchet ok (run on the platform VM, 2026-10-24).
- Last completed full `bin/verify` (2026-10-24, on the image with the pristine
  wargame restore, before the later image and coach changes): unit 1618 passed;
  acceptance 73 passed, 0 failed, 0 errors, 0 skipped in 2186 s; ratchet ok. It
  was 4038 s (unit 1607) before the reset speed-ups. The earlier runs on this
  cloud with two slots gave acceptance 73 passed in 3759-4083 s
  (`docs/STATE.md`); the one-slot runs and the old cloud's last run follow.
- 2026-10-21, decided by the user: the estate sensor's `HOME_NET` no longer
  holds the attacker origins, and a move to the lesson a session is
  already on changes nothing (`docs/DECISIONS.md` "The estate sensor's HOME_NET
  and a repeated lesson move").
- 2026-10-21: the docker substrate removal is done in code and proven live on
  this cloud (`docs/DECISIONS.md` "The docker substrate is removed", "Live proof
  on the new cloud").
- The one-slot runs on this cloud (3da925e, then after the docker removal)
  failed 2 tests and errored on 3 and 6 others because only one session fits
  one slot, and `test_strategy_honesty` lost its session to retention in a run of
  about 2 h 50 min. None came from the removal. Numbers: `docs/DECISIONS.md` "The
  product moved to a new OpenStack cloud" and "The docker substrate is removed".
- 2026-10-20: the user ruled the product OpenStack-only (Kolla-Ansible
  2026.1, kvm; widened on 2026-10-24 to 2025.1 or later, `docs/DECISIONS.md`),
  superseding the 2026-10-11 first-class-substrate ruling
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
- Unverified and open: ad-hoc data views cannot be turned off in 8.15; no
  taste items were collected. Kibana's Home and Stack Management menu entries
  stay: 8.15 has no supported setting that hides them (`docs/DECISIONS.md`
  "Kibana's Home and Stack Management entries"). The e4a467e smoke passed
  20 of 20 steps (details under Next, 10).
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
  `platform`, `board`, `corp`, `kali`, `proxy` and `gns3`.
- `sh deploy.sh <tag> platform=<HEAD> board=<HEAD> corp=<HEAD>` runs `bin/cloud
  up --replace --sideload` for each pair with the `openstack` CLI from `osc/bin`;
  the log is
  `deploy/<tag>.log`. A rebuild from images on GHCR needs no script: run
  `bin/cloud up --replace` from the main checkout.
- `sh known-hosts.sh` replaces the operator's `known_hosts` entry for
  192.168.2.247 with the keys cloud-init printed to the VM's console log,
  after checking their fingerprints; run it after every rebuild.
- `live/resume-proof.sh` is the live check of a reset resumed after a
  platform restart (`docs/DECISIONS.md` "A reset cut short by a restart, and
  corp's readiness").
- `sh s.sh '<cmd>'` runs a command on the platform VM, for example `sh s.sh 'git
  -C /opt/fsl rev-parse HEAD'`.
- `walker/walk.py` is the lesson walker (Next, 10).
- The repository has a `cloud` git remote (the VM's `/opt/fsl`). Work goes to
  the VM with `git push cloud HEAD:refs/heads/work` and `git -C /opt/fsl
  checkout --detach work` on the VM. Claude Code asks the user before every push to GitHub
  or pull request (the `ask` rules in `.claude/settings.json`).

`bin/cloud` needs three gitignored files in the checkout that runs it:
`deploy/openstack/cloud.yaml`, `.venv` and the newest copy in `backups/`. The
main checkout (`/Users/nekonic/Documents/GitHub/fsl-project-mvp`) and this
worktree both have them for the new cloud (newest copy: the main checkout's
`db-20261021T130039Z.sqlite3`, 22.8 MB; this worktree's
`db-20261024T132318Z.sqlite3`, 537 KB); the old cloud's `cloud.yaml` is kept outside the
repo in `~/.cache/fsl-work/old-cloud/`. A worktree that is cleaned
up loses these files, so copy them before working in a new one. Older store
copies, among them the 59 MB `db-20261019T033253Z.sqlite3`, are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

1. Publishing the OPNsense image (`docs/STATE.md` backlog 0): the licence is
   fine, the trademark policy asks for a note to the project. The user's call.

## Next, in order

1. When the user approves, push to `dev`. After the push: check the `images.yml` run for that push (`gh run list
   --workflow images.yml --branch dev --limit 3`; the run for ee5e641 was
   green), then rebuild the platform VM
   from the main checkout with `bin/cloud up --replace`, without `--sideload`,
   so the VM runs dev from GitHub and GHCR. Then refresh the operator's
   `known_hosts` from the console log (`~/.cache/fsl-work/known-hosts.sh`).
2. Done: `deploy/proxy/stamp.py` and `deploy/kali/setup.sh` no longer name
   `/var/lib/session/origin`, which nothing wrote (`docs/DECISIONS.md` "The
   docker substrate is removed"). The Kali image digest changes once, so the
   next `bin/cloud up` rebuilds `fsl-kali`.
3. An acceptance run longer than `FSL_RETAIN_CLOSED_MINUTES` (60) loses
   the shared session of `test_strategy_honesty` to retention. A one-slot run
   took about 2 h 50 min and failed there. With two slots a run took 64 min on
   2026-10-21 and 36 min (2186 s) after the pristine restore, so only a
   one-slot run still outlasts the window. Still open for a one-slot run: the
   harness keeps a session it needs, or the window accounts for a long run.
4. The `test_corp_authz` nonce error: the likely cause (corp healthy before
   its forms existed) is fixed and one full `bin/verify` passed with it. The
   error was intermittent, so watch the next runs for it (`docs/STATE.md`
   backlog 0).
5. Have a newcomer follow README on a clean machine, or run §9 on VirtualBox
   or VMware (the 2026-10-20 trial ran on the KVM test cloud).
6. 4.2, a person as the red team against the learner: the engine accepts
   `red: person`; needs a second person to run it live.
7. A corp scenario: corp's CVEs succeed but it has no customer traffic; needs
   a generator for WordPress first (P3's shape).
8. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
9. Walk F4 step 3 live once more: the coach's new query after a closed document
   lacked the field is unit-tested and deployed but was not walked live.
10. Foundations rebuild, remaining (`docs/STATE.md` backlog 0, "Foundations
   rebuild, remaining work"): the F1/F2 "auto-advance" item was a walker
   race, fixed in the walker on 2026-10-21 (`docs/STATE.md`); the walker's
   two F4/F6 faults are fixed and the 2026-10-22 re-walk (session 1137)
   passed F4-F6, 28 of 28 steps; the Kali and WAF terminals' last column no
   longer sits under the lesson notes (fixed in `blue.html`, `docs/STATE.md`);
   a live review round of 9f1f39d..60243e6 (six reviewers, convergence
   rule, exit on zero countable findings); whether the walker (`~/.cache/fsl-work/walker/walk.py`)
   becomes a repo tool.
