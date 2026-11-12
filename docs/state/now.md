# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; detail in `git
log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-26, morning (nothing is pushed; the platform VM runs this
branch with the platform, board and corp images sideloaded, two range slots).
Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and the
Internet.

## Where things stand

- Push state: the branch `claude/cloud-vm-status-report-45aefd` holds 71
  commits over `dev` (ee5e641) and none is pushed. A push goes to `dev` as a
  fast-forward, only when the user approves it, and only as the very last step.
- 2026-10-20: the product moved to a new OpenStack cloud. The old cloud
  (master@192.168.0.100, Keystone 192.168.0.110, platform VM 192.168.0.210,
  floating IP 192.168.0.220) is in other use by the user and must not be
  touched. The facts, the defects the move found and the fixes are in
  `docs/DECISIONS.md` "The product moved to a new OpenStack cloud"; the cloud's
  values are the "(this cloud)" passages of `docs/OPENSTACK.md` §2-§4.
- The platform VM is `fsl-platform` at 192.168.2.247. It was rebuilt on
  2026-10-24 from this branch with `bin/cloud up --replace --sideload
  platform=... --sideload board=... --sideload corp=...` (the rebuild that
  built the three new VM images took 65 min). It runs
  `FSL_SIDELOADED=board,corp,platform`; the other images come from GHCR. Both
  slots (`compute.slots: 2`) are READY. The wargame hosts run on `m1.medium`.
- Quota (the user raised it on 2026-10-24): 24 cores, 57344 MB of RAM, 12
  instances. The project uses 18 cores, 40 GB and 9 instances
  (`docs/OPENSTACK.md` §3.2).
- A rebuilt VM has new ssh host keys. Check the new fingerprints in the VM's
  console log (`openstack console log show fsl-platform`, the cloud-init
  "SSH HOST KEY FINGERPRINTS" block) before replacing the operator machine's
  `known_hosts` entry for 192.168.2.247. The operator key is
  `~/.ssh/fsl_claude` (Nova keypair `fsl-claude`).
- Slot reset, close to READY: 70-82 s for one slot and 98-99 s for two at once
  (`docs/TROUBLESHOOTING.md`). `bin/platform-rebuild`'s ssh sends keepalives
  and gives up on a dead connection.
- Full `bin/verify` on the platform VM, on the code before the last wording
  fix: unit 1669 passed; acceptance 73 passed, 0 failed, 0 errors, 0 skipped
  in 2003 s across 4 processes; ratchet ok. A one-worker acceptance run is
  run on 2026-10-26 (`bin/acceptance --workers 1` on the two-slot range, while a
  lesson walk held one slot) took 3948 s: 64 passed, 6 failed, 3 errors. Eight
  failures say "the range has 2 slots; name the one to run on", because one
  worker on a two-slot range does not name a slot for attacker commands; the
  ninth is a 409 from a test that needs both slots. None is a product fault,
  and the run is not the one-slot case the harness fix is for; the unit test
  holds that fix.
- Acceptance harness: `full_run` records the red-team session's cases,
  detections and scores under both correlation strategies right after the
  session closes, and the tests read that record, so a long one-slot run no
  longer loses the session to retention. Retention for real sessions is
  unchanged.
- Live review loop of the foundations (six reviewers: lesson design, UI, terms,
  AI-sounding Korean, realism and leaks, first-time learner; convergence rule,
  exit on zero countable findings). Countable findings per round: r6 47, r7 6,
  r8 5, r9 3, r10 1, r11 2, r12 2 (both wording, fixed). Round 13 is running:
  round 13 found 4 (a refused open explained off screen in operator English, Kibana's search-session popover over the KQL bar, option names wrapping in the dump hint, the F4 slipped pass line contradicting a yes answer), all fixed; round 14 is next. The fixes of rounds 6-12 are on the branch and the VM; what
  they changed is in `git log`. Behind them:
  - Answer checks keep the slot's range reads for the session, so a wrong
    answer comes back in 0.2-3 s.
  - A session open reads the range before it takes the slot choice, so a
    close no longer waits behind an open (the cause of one acceptance
    timeout).
  - The slot maps load at platform start, with retries; no map is published
    from a partial read.
- Kibana 8.15 has no supported setting that hides Home and Stack Management,
  so they stay (decided, `docs/DECISIONS.md` "Kibana's Home and Stack
  Management entries"). It cannot switch off ad-hoc data views either.
- The dead `/var/lib/session/origin` path is gone from the stamp proxy and the
  Kali setup. The Kali image digest changed once, so the next `bin/cloud up`
  rebuilds `fsl-kali`.
- 2026-10-21, decided by the user: the estate sensor's `HOME_NET` no longer
  holds the attacker origins, and a move to the lesson a session is already on
  changes nothing (`docs/DECISIONS.md` "The estate sensor's HOME_NET and a
  repeated lesson move"). The docker substrate removal is done in code and
  proven live on this cloud.
- 2026-10-20: the user ruled the product OpenStack-only (Kolla-Ansible 2025.1
  or later, kvm; `docs/DECISIONS.md` 2026-10-20 and 2026-10-24). The plan is
  `docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`. Docker
  stays on the platform VM (the platform's own services), the wargame host and
  the GNS3 display nodes.
- Goal in flight: none beyond the review loop above. The scenario course
  (design `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`)
  is finished, and every scenario was run live with a wrong and a right
  defence (`docs/DECISIONS.md`, "P5 built").
- Not run live: the VirtualBox and VMware settings of `docs/OPENSTACK.md` §9.1;
  a host browser reaching the floating IP of a one-VM cloud.
- Still open, not this branch's work: `stg01`'s cinder-backup is down (a Ceph
  driver without Ceph; a cloud admin action); `com01`'s Nova `cpu_mode`
  (guests see a Sandy Bridge model); a 52,689-detection ingest holds the SQLite
  write lock for about 15 s (measured, not fixed).
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
- `walker/walk.py` is the lesson walker (Next, 6).
- The repository has a `cloud` git remote (the VM's `/opt/fsl`). Work goes to
  the VM with `git push cloud HEAD:refs/heads/work` and `git -C /opt/fsl
  checkout --detach work` on the VM. Claude Code asks the user before every push to GitHub
  or pull request (the `ask` rules in `.claude/settings.json`).

`bin/cloud` needs three gitignored files in the checkout that runs it:
`deploy/openstack/cloud.yaml`, `.venv` and the newest copy in `backups/`. The
main checkout (`/Users/nekonic/Documents/GitHub/fsl-project-mvp`) and this
worktree both have them for the new cloud (newest copy: the main checkout's
`db-20261021T130039Z.sqlite3`, 22.8 MB; this worktree's
`db-20261025T222220Z.sqlite3`, 569 KB); the old cloud's `cloud.yaml` is kept
outside the repo in `~/.cache/fsl-work/old-cloud/`. A worktree that is cleaned
up loses these files, so copy them before working in a new one. Older store
copies, among them the 59 MB `db-20261019T033253Z.sqlite3`, are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

1. Publishing the OPNsense image (`docs/STATE.md` backlog 0): the licence is
   fine, the trademark policy asks for a note to the project. The user's call.

## Next, in order

1. Finish the review loop with round 14. Round 13's four findings are fixed on
   the branch; the platform was being redeployed with them on 2026-10-26 09:35
   KST (`~/.cache/fsl-work/deploy/round14-*.log`). If that deploy did not end
   with "exit 0", run it again (`deploy.sh` with platform, board and corp
   sideloaded; the store backup is also in `~/.cache/fsl-work/backup-safe/`).
   Then walk F1-F6 and the F1+F2 session with the walker into
   `~/.cache/fsl-work/live/round14/` (round 13's INDEX.md shows the shape;
   check the refused-open message, no Kibana search-session popover, the dump
   hint's options on one line, and the F4 slipped pass line), run the six
   reviewers with a round-14 brief (copy `round13/REVIEW-BRIEF.md`), fix what
   counts, and repeat until a round has zero countable findings. Then run the
   full `bin/verify` on the platform VM once more.
2. When the user approves, push to `dev`. After the push: check the `images.yml`
   run for that push (`gh run list --workflow images.yml --branch dev --limit
   3`; the run for ee5e641 was green), then rebuild the platform VM from the
   main checkout with `bin/cloud up --replace`, without `--sideload`, so the VM
   runs dev from GitHub and GHCR. Then refresh the operator's `known_hosts`
   from the console log (`~/.cache/fsl-work/known-hosts.sh`).
3. The `test_corp_authz` nonce error: the likely cause (corp healthy before
   its forms existed) is fixed and full `bin/verify` runs have passed with it.
   The error was intermittent, so watch the next runs for it (`docs/STATE.md`
   backlog 0).
4. Have a newcomer follow README on a clean machine, or run §9 on VirtualBox
   or VMware (the 2026-10-20 trial ran on the KVM test cloud).
5. 4.2, a person as the red team against the learner: the engine accepts
   `red: person`; needs a second person to run it live. A corp scenario: corp's
   CVEs succeed but it has no customer traffic; needs a generator for
   WordPress first (P3's shape).
6. Whether the live walker (`~/.cache/fsl-work/walker/walk.py`, headless
   Playwright, F1-F6) becomes a repo tool. Undecided (`docs/STATE.md`
   backlog 0, "Foundations rebuild, remaining work").
7. `bin/acceptance --workers 1` on a range with more than one slot does not
   name a slot for attacker commands (8 failures on 2026-10-26); pass the slot,
   or refuse that mode with a clear message.
8. Acceptance run time and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
9. `POST slot/rebuild/?slot=N` followed at once by `POST configure/?slot=N`
   failed on the first try for both slots on 2026-11-12 and passed on the
   second. Slot 1: the rebuilt edge did not hold its WAN aliases or log to the
   collector. Slot 2: the platform's `known_hosts` still held the rebuilt WAF's
   old host key. The cause is not confirmed; find it so the documented order
   (§6.1, rebuild then configure) works on the first try.
