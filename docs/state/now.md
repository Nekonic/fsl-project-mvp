# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; detail in `git
log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-11-13 (the platform VM `cr-platform` runs 3a0df7d from GHCR
images, two range slots under the `cr` names).
Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and the
Internet.

## Where things stand

- Versions: commits, branches, tags and pushes to `dev` need no gate; `main`
  takes only a tagged best version after gate 2 (CLAUDE.md, "How work runs
  here").
- 2026-11-13: the code's names moved from `fsl` to `cr` (`docs/DECISIONS.md`,
  2026-11-13), and the live cloud was cut over the same day by
  `docs/OPENSTACK.md` §5.4: the old checkout's `bin/cloud down` (store backup
  `db-20261113T082150Z.sqlite3`, 60 MB, integrity ok), the Glance images
  `fsl-kali`, `fsl-waf`, `fsl-wargame-host` and the security group `fsl-build`
  deleted, then `bin/cloud up` with `platform.stack: cr-platform` (about 42
  min). It built the role images `cr-kali`, `cr-waf`, `cr-edge`,
  `cr-wargame-host` and replaced `fsl-opnsense-26.7` under the same name. Two
  things it needed: the `openstack` CLI on PATH, and a `platform.ref` with no
  `/` in it (the branch `cr-rename` was pushed for that).
- The platform VM is `cr-platform` at 192.168.2.247 (`m1.large`), checkout
  `/opt/cr` at 3a0df7d. Every image comes from GHCR: the `cr-*` images tagged
  with the commit SHA, built by `images.yml` through `workflow_dispatch` on the
  working branch; nothing is sideloaded. Containers: `cr-platform`,
  `cr-elasticsearch`, `cr-kibana`, `cr-collector`, `cr-gns3`. Both slots
  (`compute.slots: 2`) are READY: `cr-edge`, `cr-kali`, `cr-waf`,
  `cr-wargame-host` and their `-2` copies, all `m1.medium`. The store was
  restored from the backup (3 sessions listed).
- Quota: 17 instances, 24 cores, 57344 MB of RAM. com01's placement (checked by
  the user on con01): VCPU allocation_ratio 4.0, MEMORY_MB 1.5 (reserved 512),
  DISK_GB 1.5, set in `/etc/kolla/config/nova/com01/nova.conf`. The flavors
  `dba.edge` (1 vCPU, 3072 MB, 30 GB) and `dba.small` (1 vCPU, 2048 MB, 30 GB)
  exist and are not used yet.
- 2026-10-20: the product moved to a new OpenStack cloud. The old cloud
  (master@192.168.0.100, Keystone 192.168.0.110, platform VM 192.168.0.210,
  floating IP 192.168.0.220) is in other use by the user and must not be
  touched. The facts, the defects the move found and the fixes are in
  `docs/DECISIONS.md` "The product moved to a new OpenStack cloud"; the cloud's
  values are the "(this cloud)" passages of `docs/OPENSTACK.md` §2-§4.
- A rebuilt VM has new ssh host keys. Check the new fingerprints in the VM's
  console log (`openstack console log show cr-platform`, the cloud-init
  "SSH HOST KEY FINGERPRINTS" block) before replacing the operator machine's
  `known_hosts` entry for 192.168.2.247. The operator key is
  `~/.ssh/fsl_claude` (Nova keypair `fsl-claude`, kept through the cut-over).
- Slot reset, close to READY: 70-82 s for one slot and 98-99 s for two at once
  (`docs/TROUBLESHOOTING.md`). `bin/platform-rebuild`'s ssh sends keepalives
  and gives up on a dead connection.
- Full `bin/verify` on the VM at 3a0df7d (2026-11-13): unit and API 1663
  passed (4:53); acceptance 76 passed, 0 failed, 0 errors, 1 skipped (the c2
  course does not start with F1, by design) in 1945 s across 4 processes;
  ratchet no regression.
- History, 2026-10-26: `bin/acceptance --workers 1` on the two-slot range
  took 3948 s: 64 passed, 6 failed, 3 errors. Eight failures say "the range
  has 2 slots; name the one to run on", because one worker on a two-slot range
  does not name a slot for attacker commands; the ninth is a 409 from a test
  that needs both slots. None is a product fault.
- Acceptance harness: `full_run` records the red-team session's cases,
  detections and scores under both correlation strategies right after the
  session closes, and the tests read that record, so a long one-slot run no
  longer loses the session to retention.
- The product since the last record: two courses, c1, log analysis basics
  (F1-F3), and c2, attack detection practice (F4-F6), each with a briefing and
  a reference column; the product is Korean-only, branded as a cyber training
  range (the string table holds the Korean); the reference rows
  stack the code above its meaning (a5fa3ac); the address table carries each
  zone's network (3a0df7d), because the learner map labels bare addresses.
- Live review loop (six reviewers: lesson design, UI, terms, AI-sounding
  Korean, realism and leaks, first-time learner; exit on zero countable
  findings). Countable findings per round: r6 47, r7 6, r8 5, r9 3, r10 1,
  r11 2, r12 2, r13 4, r14 0 (one low that did not reproduce). Round 15
  (2026-11-13) walked c1 and c2 end to end; the walker's two reported problems
  were walker bugs, fixed in the walker outside the repo. Open from it: on the
  learner map the Internet and management zone captions overlap the labels
  `customers` and `log-server`, and the green flow arrow crosses the
  `board.com` label (Next 2).
- Kibana 8.15 has no supported setting that hides Home and Stack Management,
  so they stay (`docs/DECISIONS.md` "Kibana's Home and Stack Management
  entries"). It cannot switch off ad-hoc data views either.
- 2026-10-21, decided by the user: the estate sensor's `HOME_NET` no longer
  holds the attacker origins, and a move to the lesson a session is already on
  changes nothing (`docs/DECISIONS.md`).
- 2026-10-20: the user ruled the product OpenStack-only (Kolla-Ansible 2025.1
  or later, kvm; `docs/DECISIONS.md` 2026-10-20 and 2026-10-24). Docker stays
  on the platform VM (the platform's own services), the wargame host and the
  GNS3 display nodes.
- Goal in flight: a container-based range to replace the four VMs per slot
  (Next 1); gate 1 is pending.
- Not run live: the VirtualBox and VMware settings of `docs/OPENSTACK.md` §9.1;
  a host browser reaching the floating IP of a one-VM cloud.
- Still open, not this branch's work: `stg01`'s cinder-backup is down (a Ceph
  driver without Ceph; a cloud admin action); `com01`'s Nova `cpu_mode`
  (guests see a Sandy Bridge model); a 52,689-detection ingest holds the SQLite
  write lock for about 15 s (measured, not fixed).
- To try it: open http://192.168.2.247:8000 (through the VPN), open the
  catalogue and start course c1, then c2.

## Operator tooling

Outside the repo, in `/Users/nekonic/.cache/fsl-work/`. The scripts take the
repo root from the current git checkout (or `FSL_REPO`); run them from the
checkout you work in. They target the new cloud (192.168.2.247 and 10.0.0.10)
and need the VPN up. The `*.old-cloud` copies are for the old lab; do not use
them.

- `sh reach.sh` checks the platform VM and Keystone.
- `sh build.sh` and `sh deploy.sh` build images on the platform VM and run
  `bin/cloud up --replace --sideload`. The VM now runs GHCR images only, so a
  rebuild needs neither: run `bin/cloud up --replace` with the `openstack`
  CLI on PATH.
- `sh known-hosts.sh` replaces the operator's `known_hosts` entry for
  192.168.2.247 with the keys cloud-init printed to the VM's console log,
  after checking their fingerprints; run it after every rebuild.
- `live/resume-proof.sh` is the live check of a reset resumed after a
  platform restart (`docs/DECISIONS.md` "A reset cut short by a restart, and
  corp's readiness").
- `sh s.sh '<cmd>'` runs a command on the platform VM, for example `sh s.sh 'git
  -C /opt/cr rev-parse HEAD'`.
- `walker/walk.py` is the lesson walker.
- The repository's `cloud` git remote is `ssh://ubuntu@192.168.2.247/opt/cr`.
  Work goes to the VM with `git push cloud HEAD:refs/heads/work` and `git -C
  /opt/cr checkout --detach work` on the VM. Claude Code asks the user before
  every push to GitHub or pull request (the `ask` rules in
  `.claude/settings.json`).

`bin/cloud` needs three gitignored files in the checkout that runs it:
`deploy/openstack/cloud.yaml`, `.venv` and the newest copy in `backups/`. This
worktree has them (newest copy `db-20261113T082150Z.sqlite3`, 60 MB, from the
cut-over); the old cloud's `cloud.yaml` is kept outside the repo in
`~/.cache/fsl-work/old-cloud/`. A worktree that is cleaned up loses these
files, so copy them before working in a new one. Older store copies are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

1. Gate 1 for the container-based range (Next 1).
2. Publishing the OPNsense image (`docs/STATE.md` backlog 0): the licence is
   fine, the trademark policy asks for a note to the project. The user's call.

## Next, in order

1. A container-based range to replace the four VMs per slot. The user asked
   for it to merge the duplication, be as fast as containers and fully replace
   what exists. Candidates: a range-host VM with per-session containers, k3s
   pods, or a bigger platform VM that runs the sessions. Gate 1 is pending; the
   planned switch to four slots on the `dba` flavors is on hold for it.
2. The learner map's caption overlaps (Where things stand, round 15).
3. An answer-blind review round of both courses, then the user's own test.
4. sqlmap variant cases: drop those with no distinct meaning (in progress on
   the branch `sqlmap-variants`).
5. Acceptance run time, and ingest re-reading the whole window (paged since
   f07919f, up to about 205k records).
6. MySQL `performance_schema=OFF`.
7. The first configure after a slot rebuild fails once: `POST
   slot/rebuild/?slot=N` followed at once by `POST configure/?slot=N` failed
   on the first try for both slots on 2026-11-12 and passed on the second.
   Slot 1: the rebuilt edge did not hold its WAN aliases or log to the
   collector. Slot 2: the platform's `known_hosts` still held the rebuilt
   WAF's old host key. The cause is not confirmed.
8. `allow_resize_to_same_host` doc drift (`docs/OPENSTACK.md`).
9. Promotion to `main`: a tagged state, the full `bin/verify`, a live review
   round with zero countable findings and a docs review with no drift
   (CLAUDE.md), through gate 2.

Also open, unordered: the intermittent `test_corp_authz` nonce error (watch
the runs; `docs/STATE.md` backlog 0); a newcomer following README on a clean
machine, or §9 on VirtualBox or VMware; scenario 4.2 (a person as the red
team) and a corp scenario (needs a WordPress customer-traffic generator);
whether the walker becomes a repo tool; `bin/acceptance --workers 1` on a
range with more than one slot does not name a slot for attacker commands.
