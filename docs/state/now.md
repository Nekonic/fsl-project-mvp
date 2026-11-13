# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; detail in `git
log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-11-14 (the range is one range host, `cr-range`, running four
slots as compose projects; branch `range-host`, waiting for gate 2).
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
  `bin/cloud up --replace`'s leftovers step. The work is on the branch
  `range-host`; the live platform runs the branch `range-host-live` (no `/`
  in `platform.ref`), images from GHCR by its commit.
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
  from Kali. With it,
  `test/test_attacker_reach.py`'s two tests passed, but its port scan covers
  only Kali's interfaces other than the one with its default route, and in a
  slot Kali has only `eth0`, so it scans nothing and is not containment
  evidence; its other test (no target reached past the WAF by name) holds.
- Full `bin/verify` on the platform VM at be49cf5 (2026-11-13, four slots):
  unit and API 1498 passed (4:47); acceptance 90 passed, 0 failed, 0 errors,
  1 skipped in 950 s across 6 processes; ratchet no regression (`core_loc`
  584, `dependencies` 6, `services` 5). The acceptance red-team run now may
  take 15 minutes: beside three other workers' slots on one host it passed
  300 s once.
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

1. Gate 2 for the container range (branch `range-host`): the evidence is in
   the report of 2026-11-14 and in this file.

## Next, in order

1. Gate 2, then `dev` and the live cloud on `dev` (set `platform.ref` back to
   `dev` and `compute.slots` as the user wants; four now).
2. The learner map was rendered in the live GNS3 web UI with this file's
   positions and shows no overlapping text; the string table calls the edge
   라우터. Open: the router still wears the firewall icon (`host-firewall.svg`),
   and the live platform VM still serves the map from before that layout fix.
3. An answer-blind review round of both courses, then the user's own test.
4. Acceptance run time, and ingest re-reading the whole window.
5. MySQL `performance_schema=OFF`: memory caps the slots a range host holds
   (`docs/STATE.md` backlog 4).
6. Promotion to `main`: a tagged state, the full `bin/verify`, a live review
   round with zero countable findings and a docs review with no drift
   (CLAUDE.md), through gate 2.

Also open, unordered: the intermittent `test_corp_authz` nonce error; a
newcomer following README on a clean machine; scenario 4.2 and a corp
scenario; whether the walker becomes a repo tool.
