# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; detail in `git
log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-11-14 (the range is one range host, `cr-range`, running four
slots as compose projects; on `dev`).
Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and the
Internet.

## Where things stand

- Versions: commits, branches, tags and pushes to `dev` need no gate; `main`
  takes only a tagged best version after gate 2 (CLAUDE.md, "How work runs
  here").
- 2026-11-13: the container range (gate 1 approved the same day,
  `docs/DECISIONS.md` "The range is one range host; a slot is a compose
  project") replaced the four VMs per slot. The cloud holds two VMs:
  `cr-platform` (`m1.large`, 192.168.2.247) and `cr-range` (`dba.range`,
  6 vCPU, 16 GB), which runs slot N as the compose project `sN` (Kali, the
  nftables edge, the WAF, two Suricata sensors, board and corp). The old slot
  VMs, their networks, the role images and the OPNsense image were removed by
  `bin/cloud up --replace`'s leftovers step. The work is on `dev`; the live
  platform runs the branch `range-host-live` (no `/` in `platform.ref`),
  images from GHCR by its commit.
- Detection against the VM range (the prototype's offline scorer on the live
  range, `deploy/range-host/proto/score.py` and `compare.py`): board 18 cases
  and corp 7 cases have the same verdict, `corroborated` and signature sets
  on every leg; the only field that differs is the WAF's own estate address
  (10.30.0.247 before, 10.30.N.247 now), and with it ignored 0 differences.
  `capture.kernel_drops` 0 on both legs.
- Capacity on `dba.range` (Kibana queries running throughout): a slot takes
  about 1.15 GB idle (both targets up). Ten slots fit with 3.3 GB available;
  twelve leave under 0.5 GB; fifteen do not fit (about 17.5 GB). The
  `board-sqli-orderby-sqlmap` run took 59 s alone, 71 s with three at once,
  98 s with five and 171 s with ten (2.9x, CPU 8 % idle), kernel_drops 0 on
  all twenty sensors. A slot reset (`slot.sh reset`) took 43 s alone and
  101 s for three at once, with ten slots up. Ten configured from nothing in
  4 min 14 s. Ten learners at once is the supported number; twelve fit with
  no headroom.
- Live containment: `test/test_range_isolation.py` passed on the live range
  (14 passed): no container of a slot reaches the range host, the platform,
  the Internet, the metadata service or another slot, and a SYN scan works
  from Kali. `test/test_attacker_reach.py`'s port scan scanned nothing in a
  slot (Kali has only `eth0`) and was replaced by a scan from Kali of the
  range host, the platform and the `mgmt` network in
  `test_range_isolation.py`; its other test (no target reached past the WAF
  by name) holds.
- 2026-11-14: the WAF mounted its log directory, so root in it could plant a
  symlink that `slot.sh reset` (root) truncated through and rsyslog read
  through. Shown live on the old layout: a reset emptied a root-owned host
  canary the WAF had linked to. The WAF now mounts only its `audit.log`
  (`docs/DECISIONS.md` "The WAF mounts its log file, not its log
  directory"); `test_range_isolation.py`'s last test plants the links and
  checks the canary after a reset.
- Full `bin/verify` on the platform VM at 89b528c (2026-11-14, four slots,
  the range host replaced by `POST slot/` with the WAF log fix):
  unit and API 1498 passed (5:07); acceptance 91 passed, 0 failed, 0 errors,
  1 skipped in 1047 s across 6 processes; ratchet no regression (`core_loc`
  584, `dependencies` 6, `services` 5). The acceptance red-team run now may
  take 15 minutes: beside three other workers' slots on one host it passed
  300 s once.
- Answer-blind walk round 16 (2026-11-14): its nineteen findings were fixed
  and deployed (the live platform runs `range-host-live` at that work, images
  from GHCR by its commit; the range host was replaced by `POST slot/` for
  the new tag). Full `bin/verify` on the platform VM after it: unit and API
  1506 passed (5:00); acceptance 91 passed, 0 failed, 0 errors, 1 skipped in
  1101 s across 6 processes; ratchet no regression (`core_loc` 584,
  `dependencies` 6, `services` 5).
- Answer-blind walk round 17 (2026-11-14): its fifteen findings were fixed
  (`docs/DECISIONS.md` "Answer-blind walk round 17") and deployed (the live
  platform runs `range-host-live` at e11eef8, images from GHCR by that
  commit, the range host replaced by `POST slot/`). The stall on F4's last
  check was the server: an alert was matched to any request within 5 s, so a
  plain search 3.5 s after an attack inherited its alert; alerts now match a
  request by URL. The full `bin/verify` below ran with that deploy live.
- Answer-blind walk round 18 (2026-11-14): its findings were fixed
  (`docs/DECISIONS.md` "Answer-blind walk round 18"): every Kibana answer
  needs the learner's own query (`kql`), F5's source step now asks the
  record count Kibana alone shows, F4 refuses a rule that alerts on every
  plain search, F6 keeps the paranoia level line, run steps say one thing at
  a time, course 1's result shows no score, ttyd raises no leave-site
  dialog. Left by ruling: Next skipping steps, XSS not scored (wording only),
  wrong attempts shown on the result but not penalised. Deployed: the live platform
  runs `range-host-live` at 8304864, images from GHCR by that commit, the
  range host replaced by `POST slot/` and four slots READY after
  `configure/` (store copied first to
  `~/.cache/fsl-work/backup-safe/db-20261114T1410Z-r18.sqlite3`). Full
  `bin/verify` on the platform VM then: 12 min 40 s start to result;
  acceptance 91 passed, 0 failed, 0 errors, 1 skipped in 706 s across 14
  processes; unit and API 1532 passed (815 + 717 in two processes beside it);
  ratchet no regression (`core_loc` 584, `dependencies` 6, `services` 5).
- Test speed (on `dev`, `docs/DECISIONS.md` "The acceptance
  suite runs one sqlmap case and fills the slots as they free"): the
  red-team run fires one sqlmap case (the dump; `CR_SQLMAP_VARIANTS=1` fires
  all six), `bin/acceptance` starts a group per free slot, the containment
  probes run side by side, and the unit suite runs beside the acceptance
  suite. Two full `bin/verify` runs on the platform VM (2026-11-14, four
  slots): 13 min 18 s and 11 min 54 s from start to result, against about
  25 min before; acceptance 91 passed, 0 failed, 0 errors, 1 skipped in
  746 s and 665 s across 14 processes (1101 s before); unit and API 1517
  passed in two processes beside it; ratchet no regression (`core_loc` 584,
  `dependencies` 6, `services` 5).
- Live paths run end to end on 2026-11-13: `bin/cloud up --replace` from the
  VM range (25 min, the range host replaced as stale, the leftovers removed
  after READY); a stale range host replaced by `POST slot/`; `bin/cloud down`
  (1 min: the slots, the range host, the fabric and the stack) and then
  `bin/cloud up` from nothing; slot resets on every acceptance close.

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
  /opt/cr checkout --detach work` on the VM; the platform's code and `deploy/`
  are mounted from `/opt/cr`, so `docker compose restart platform` runs it.
- The range host has no address the operator reaches: run its commands
  through the platform, `sh s.sh "sudo docker exec -i cr-platform ssh -i
  /data/ssh/id_ed25519 ubuntu@<cr-range mgmt address> '<cmd>'"`, or through
  `manage.py run_on_role wargames '<json argv>' --slot N`.

`bin/cloud` needs three gitignored files in the checkout that runs it:
`deploy/openstack/cloud.yaml`, `.venv` and the newest copy in `backups/`. This
worktree has them (the newest copy from the last `bin/cloud up --replace`); the old cloud's `cloud.yaml` is kept outside the repo in
`~/.cache/fsl-work/old-cloud/`. A worktree that is cleaned up loses these
files, so copy them before working in a new one. Older store copies are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

Nothing. Gate 2 is only for `main` (Next, item 6).

## Next, in order

1. The live cloud on `dev`: set `platform.ref` back to `dev` and
   `compute.slots` as the user wants (four now).
2. A fresh answer-blind review round of both courses on the round-18 fixes
   (`docs/DECISIONS.md` "Answer-blind walk round 18"), checking on the range
   that the new `kql` patterns accept the queries learners write and why
   course 2's DevTools dropped the 403 row opened after the search, then the
   user's own test. The live map now shows the router's own symbol (`host-router.svg`)
   and F1's DMZ callout outside the zone.
3. sid 9000001 misses sqlmap's ORDER BY payloads that carry no quote, `-- `
   or `union select` even where it is loaded: a detection gap to measure
   (round 16, `docs/DECISIONS.md`).
4. Ingest re-reading the whole window: `POST /ingest/` took 22-42 s on a
   closed red-team session while the suite ran, and every score wait calls it.
   More slots (`compute.slots`; ten fit on `dba.range`) would shorten the
   acceptance run further; a slot reset (53 s alone) is now its floor.
5. MySQL `performance_schema=OFF`: memory caps the slots a range host holds
   (`docs/STATE.md` backlog 4).
6. Promotion to `main`: a tagged state, the full `bin/verify`, a live review
   round with zero countable findings and a docs review with no drift
   (CLAUDE.md), through gate 2.

Also open, unordered: the intermittent `test_corp_authz` nonce error; a
newcomer following README on a clean machine; scenario 4.2 and a corp
scenario; whether the walker becomes a repo tool.
