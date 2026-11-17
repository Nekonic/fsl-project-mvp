# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems and their measurements in `docs/TROUBLESHOOTING.md`; detail in `git
log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-11-18. The live cloud runs the Heat range from `dev`: the
platform VM and a pool of four slot stacks (`cr-slot-1`..`4`, three board and
one corp, sixteen `dba.small` VMs); the range host `cr-range` is deleted.
The first full `bin/verify` on it, before the readiness fix, was stopped
after 12 min: acceptance idle 4 passed, the corp group 3 errors (its opens
refused while slots were retargeted to corp), `test_concurrent_sessions.py`
3 errors (the ssh multiplexer, below), and 3 failures in the
`test_board_exfil.py` group whose detail the stop cut off; its log is
`~/.cache/fsl-work/verify-heat-run1.tgz`. The second, on the readiness fix,
writes `/tmp/verify-heat.log` on the platform VM (copied to
`~/.cache/fsl-work/verify-heat.log`). `bin/verify --fast` on `dev`: unit and
API 1928 passed in four processes, ratchet no regression (`core_loc` 604).
Written for a session that reaches the new cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and the
Internet.

## Where things stand

- 2026-11-18, the Heat range is live (P8; `docs/DECISIONS.md` "The first
  live pool fill"): a slot is one Heat stack `cr-slot-<n>` of four VMs (kali,
  waf, infra, target) on five Neutron LANs of its own, rendered by
  `range/openstack.py` from `wargames/<w>/topology.yaml` through
  `range/sandbox.py`; the pool is `compute.pool` (`{board: 3, corp: 1}`),
  flavors `dba.small`; images `cr-kali-bake1`, `cr-waf-bake2`,
  `cr-infra-bake1`, `cr-target-bake1` (the live `cloud.yaml` names
  `compute.images.waf`; `cr-waf-bake1` was baked on a 40 GB builder and does
  not fit `dba.small`'s 30 GB). The first fill found four faults, all fixed on
  `dev`: Heat refused the WAF image's 40 GB `min_disk` (re-baked, 12 min 53 s
  of `install.sh` on an `m1.medium` builder); five security groups per stack
  overran the project's quota of 10 (now three shared `cr-lan-<digest>`
  groups for the whole range, 9 of 10 used); the target's tag check refused
  the digest-pinned MySQL image; readiness read board's ground truth on the
  corp slot, so corp never became READY and corp opens retargeted board
  slots. Timings: `bin/cloud up --replace` rebuilt the platform VM in 8 to
  9 min each time (five runs); the first pool fill with nothing cached on
  com01 took 12-13 min to `CREATE_COMPLETE` (the 14 GB Kali image copied
  first); with the images cached the four stacks completed in under 2 min and
  three slots were READY 8 min 50 s after the create. Live checks on board
  slot 1 (session 2779, opened in 8.2 s): Kali `ping -c1 121.134.88.42`
  answered (ttl 64, 3.2 ms), `traceroute` reached it in one hop, `curl
  http://board.com/` gave 200 from 121.134.88.42, the WAF's 10.30.0.247 did
  not answer (curl timeout, ping lost); the learner map drew internet, dmz,
  web-inner, `board-backend` (172.18.0.0/16, board-db) and mgmt with the
  router, WAF, IDS, board.com, board-db, log server and Kali; an XSS search
  drew ModSecurity 941100 (403) in `logs-1-sensors`, and with the
  `xss-watched` defense (session 2780, slot 2, WAF in DetectionOnly) Suricata
  sid 9000003 on the same URL in `logs-2-sensors`; `POST
  /api/sessions/2779/ssh/` issued a key and `ssh -J` through 2222 landed on
  Kali as `kali`, while the jump itself gave no shell. Open:
  `test_concurrent_sessions.py`'s `PUT /api/sessions/<id>/waf/` answered 503
  in both full runs, once with the ssh multiplexer's `mux_client_request_session:
  read from master failed: Broken pipe Failed to connect to new control
  master` (`cr-waf` at 10.31.0.153) and once with `cr-waf stands on no mgmt
  address this platform can reach`; that the session's slot was being
  replaced, or that the call reached another slot, is **[unverified]**.
- 2026-11-18, fixes from the docs pass (`docs/DECISIONS.md` "The baked images
  as they are"): `compute.target_tag` (`CR_OPENSTACK_TARGET_TAG`, by default
  the commit `cr-target-bake1` was baked at), and the target's boot refuses
  ready on another wargame image tag; Suricata's commands run in the infra's
  `sensor` container, and the infra reports ready once `suricatasc -c uptime`
  answers; a slot the ensure deletes is created again by the refill, and the
  pool's assignment retargets a free slot; an open session holds only its own
  slot; the platform reattaches its `cr-platform.mgmt` port on `--replace`, so
  its `cr-mgmt` address and the slots stay; a missing role image blocks the
  slot before Heat is asked. `dba.small` (30 GB disk) stays: every role
  image has `min_disk` 30 GB.
- 2026-11-18, answer-blind walk round 28's fixes are live
  (`docs/TROUBLESHOOTING.md` "Answer-blind walk round 28"): the WAF logs
  the request body (audit part C) and the session view shows it as
  `request_body`; nginx's refused log ships its status as `http.status`;
  the Kibana gate's refusals and its 502 are Korean; step checks wait for
  their evidence; the console's flat pages. `uv run bin/cloud up --replace`
  took 25 min 59 s and replaced the range host (new `deploy/waf`; now
  10.31.0.147). The backup before it held 6 sessions, 25 cases, 67,280
  detections, 2,815 customer requests, 3 objectives, 661 rule sets and 169
  disabled rules (`db-20261117T170121Z.sqlite3`, also in
  `~/.cache/fsl-work/backup-safe/`); after the restore retention removed the
  four sessions closed more than 60 min before the start (2 sessions, 8
  cases, 28,787 detections, 1,784 customer requests, 0 objectives; rule sets
  and disabled rules unchanged). Live checks: scenario 3.4's comment case
  (DetectionOnly, board answered 302) has an audit record, since CRS rules
  941100/941120/941160/941390 and 949110 matched, with
  `transaction.request.body` holding the form body, and the learner's
  Discover shows it under `request_body` (`request_body : *onerror*`, 1
  hit); no `logs-N-sensors` maps a top-level `status`, and after a 404, a
  500 and a refused 400 sent in each slot `status : 404` and `status : 500`
  match them in all eight (slot 1 in the learner's Discover, the rest with
  Discover's query against Elasticsearch); the gate's refusals and its 502
  with Kibana stopped answer in Korean. Open: `request_body : *` and
  `request_header.user_agent : *` (an `exists` query on a runtime field
  that reads `_source`) fail in Elasticsearch with
  `index_out_of_bounds_exception` in the stored-fields reader, also when
  sent to Elasticsearch directly; a value query such as `request_body :
  *onerror*` works. nginx's own 502 page for a Kibana page is still
  English. The full `bin/verify` on it: acceptance 94 passed, 0 failed, 0
  errors, 1 skipped in 465 s; unit and API 1003 + 870; 519 s start to
  result; ratchet no regression (`core_loc` 604).
- 2026-11-18, answer-blind walk round 27's fixes are live
  (`docs/TROUBLESHOOTING.md` "Answer-blind walk round 27"): Kali's `ip addr`
  lists 5.188.10.10 first, as on the map; the result page, the accounts page
  and the map changed, and both consoles name the played item from the API;
  a Kali check passes 3 s after the run's last request once the tool has
  left the terminals, and answers after the 30 s reachability window wait
  for one slot's read; F5's first note opens the developer tools first, and
  an answer without the request's row selected is no wrong try. `uv run
  bin/cloud up --replace` with them took 10 min 59 s and kept the range host
  (10.31.0.242). The backup before it held 6 sessions, 25 cases, 67,281
  detections, 2,790 customer requests, 3 objectives, 652 rule sets and 168
  disabled rules (`db-20261117T150108Z.sqlite3`, also in
  `~/.cache/fsl-work/backup-safe/`); after the restore retention removed the
  four sessions closed more than 60 min before the start (2 sessions, 8
  cases, 28,787 detections, 1,723 customer requests, 0 objectives; rule sets
  and disabled rules unchanged). The full `bin/verify` on it: acceptance 94
  passed, 0 failed, 0 errors, 1 skipped in 500 s; unit and API 975 + 886;
  559 s start to result; ratchet no regression (`core_loc` 597).
- 2026-11-17, answer-blind walk round 26's fixes went live: on the result
  page each lesson lists only its own change, a scenario counts one customer
  total, and the header and breadcrumb name the course or scenario; the
  lesson console's developer tools ring keeps off the field below it; the
  edge forwards from `wan` only replies and port-forwarded connections, so
  Kali reaches the WAF only by the router's public address; the comment
  cases post the comment form with its CSRF cookie and token, so the board
  stores them. `uv run bin/cloud up --replace` with them took 11 min 0 s and
  kept the range host (10.31.0.242); the restore matched its backup (2
  sessions, 5 cases, 0 detections, 0 customer requests, 643 rule sets, 167
  disabled rules, before and after; `db-20261117T125650Z.sqlite3`, also in
  `~/.cache/fsl-work/backup-safe/`). The full `bin/verify` on it: acceptance
  94 passed, 0 failed, 0 errors, 1 skipped in 473 s; unit and API 964 + 884;
  542 s.
- 2026-11-17, answer-blind walk round 25's fixes on `dev`: lesson and
  scenario note text; the result page; Kali's hosts file, the document JSON
  tab, a Korean Kibana refusal, and a session that opens in about 10 s.
  `uv run bin/cloud up --replace` with them took 10 min
  24 s and kept the range host (10.31.0.242): `slot.sh` reaches each slot at
  `configure/`, not through the setup bundle, and all eight slots carried the
  new one. Its full `bin/verify`: acceptance 91 passed, 0 failed, 3 errors, 1
  skipped; the three were one `POST cases/` in the corp fixture past the
  client's 60 s, because every objective observation re-read and re-parsed
  the whole corp-db binary log (17 MB, about 3.7 s idle on the 2-vCPU VM).
  The fix reads it from a minute before the session start
  (`docs/TROUBLESHOOTING.md` "A corp case record timed out at 60 s"; 91 KB,
  0.3 s, the same changes). The replace with the fix took 10 min 24 s; the
  full `bin/verify` on it: acceptance 94 passed, 0 failed, 1 skipped in
  433 s; unit and API 975 + 863; 505 s. Each restore matched its backup
  (the first: 7 sessions, 39,582 detections, 2,860 customer requests, 622
  rule sets, 164 disabled rules, before and after); at the second, retention
  removed the backup's six sessions at start, closed 65-74 min before
  (`CR_RETAIN_CLOSED_MINUTES` 60). Both backups are in
  `~/.cache/fsl-work/backup-safe/`.
- 2026-11-17, the platform VM and the range host install from the Kakao
  mirror, an apt try is decided by the install, and a platform-only replace
  keeps the range host (`docs/DECISIONS.md` "An apt try is decided by the
  install"). An interrupted replace left a VM without Docker; the
  next replace failed the same way on the mirror's out-of-step
  `noble-security` index. Run 1, with the install fix, restored
  `db-20261117T042204Z.sqlite3` (the last good VM's store; also in
  `~/.cache/fsl-work/backup-safe/`) in 25 min 27 s, 16 min 36 s of it a new
  range host (10.31.0.242); run 2, docs only, took 10 min 14 s and
  kept the range host and every slot's targets, Kali, WAF and edge router.
  The full `bin/verify` on run 2: acceptance 94 passed, 0 failed, 1
  skipped in 492 s; unit and API 1024 + 783; 569 s.
- 2026-11-17, answer-blind walk round 24's result, scenario and run-check
  findings fixed (`docs/DECISIONS.md` "Answer-blind walk round 24",
  `docs/TROUBLESHOOTING.md` "Answer-blind walk round 24"): a Kali run the
  terminal shows ended passes after 3 s of quiet (live, F5 sqlmap: 7.7 s after
  the end line, was 22 s), and a press before that is no wrong try; the XSS a
  learner sends in F4 is an attack case of the result (live session 2514: TP,
  5 WAF alerts, "레슨 1 · 1단계"); a scenario lists the account objectives
  only when one of its attacks dumps them (3.1, 3.2, 3.4 none); 3.3 sends
  its plain run at 45 s and the variant at 120 s (live session 2513: 0:48 and
  2:02); one customer's flows take turns, so the board's CSRF refusals after
  a sign-in are gone (session 2513: 956 customer requests, no 4xx); the
  debrief counts customers up to the final check's end (956 when judged and
  956 after close). Live: `uv run bin/cloud up --replace` rebuilt the cloud
  (range host 10.31.0.212); the full `bin/verify` on it:
  acceptance 94 passed, 0 failed, 1 skipped in 462 s; unit and API 1011 +
  784; 537 s.
- 2026-11-17, answer-blind walk round 23's findings fixed
  (`docs/TROUBLESHOOTING.md` "Answer-blind walk round 23"): a Kali run the
  WAF refused in full now passes its check, since `_sent_by` reads the WAF's
  records with the marker as well as the sensor's; each fired sqlmap case
  writes to its own output directory, so two runs on one Kali no longer share
  a session file (3.3's tamper run had hit the 600 s timeout); the collector
  loads a lean index template with a 1 s refresh (Discover's query 2.4 s ->
  0.7-0.9 s). Staff can delete an approved learner, whose open sessions close
  through the close path (`docs/DECISIONS.md` "Staff delete an approved
  learner").

- 2026-11-16, Kibana keeps a learner to their open session's slot
  (`docs/DECISIONS.md` "Kibana keeps a learner to their open session's slot
  through a platform gate"): nginx hands every space API call to Django's
  `/kibana-gate/`; `kibana.refusal` allows Discover's calls only, in the
  learner's own session space, naming only that slot's `logs-N-*`. Live as
  a learner: own search 200; typed other patterns, `bsearch`, ES|QL, Dev
  Tools, other spaces, terms lookup, path tricks 403; the blue console's
  Discover showed the session's alert. Full `bin/verify` on the VM:
  acceptance 81 passed, 13 errors, 1 skipped; all 13 are one 500 from
  `/api/sessions/<id>/topology/` (`topology.py` `_boxed` KeyError `'x'`),
  outside this change; unit and API 943 + 818. The 500 is fixed
  (`docs/TROUBLESHOOTING.md`, "The session map answered 500"):
  reproduced live by stopping `s1-board-db`, 500 before the fix and 200
  after; the full `bin/verify` on the fix passed: acceptance 94 passed,
  0 failed, 1 skipped; unit and API 957 + 813; 506 s.
- 2026-11-16, F4 and 3.4 run the WAF in DetectionOnly mode and 3.1-3.3
  attack with `board-sqli-orderby-sqlmap-random-agent` (`docs/DECISIONS.md`
  "F4 and 3.4 run the WAF in DetectionOnly mode; 3.1-3.3 attack with
  sqlmap's `--random-agent`"): stock sqlmap is blocked in full at PL1 by its
  User-Agent; with the solution rules 3.1, 3.2 and 3.3 each passed live.
  Suricata's alert `xff` proven live. `core_loc` 592 -> 597.
- 2026-11-16, a session's slot runs only its own wargame (`docs/DECISIONS.md`
  "A session's slot runs only that session's wargame"): opening a session
  stops the other wargame's containers (`slot.sh play`); a reset starts both
  again. The map of a board session shows only board.com and board-db.
  Session open 8-17 s before and after. Full `bin/verify` on the VM: 494 s,
  acceptance 94 passed, 0 failed, 1 skipped in 417 s across 12 processes,
  unit and API 808 + 878.
- 2026-11-16, the IDS behind the WAF and the map redrawn (`docs/DECISIONS.md`
  "The IDS stands behind the WAF; nginx's own refusals are WAF evidence; the
  live map redrawn"): the sensor sniffs only `web` on `sN-web`; Suricata adds
  X-Forwarded-For as `xff` and ingest credits an alert to its transaction's
  address; nginx's own 400s reach Elasticsearch as WAF evidence
  (`refused.log`), and the traversal case is matched by address and time; a
  window case no longer takes records another request's marker names. The
  canary takes ModSecurity's alert on the blocked probe and Suricata's record
  of a passed one. The map draws switches, subnets as boxes, the WAF inside
  the DMZ, the servers inside the web segment, full addresses beside each
  link, no range host or platform. Parity with the two-leg sensor: board TP 12
  FP 0 FN 0 TN 6, corp TP 0 FP 0 FN 3 TN 4. `core_loc` 585 -> 592. Live: the
  platform VM runs `/opt/cr` at the branch `map-redraw` with images built from it;
  the range host 10.31.0.54. Full `bin/verify` on the VM: 563 s, acceptance
  94 passed, 0 failed, 1 skipped in 508 s across 12 processes, unit and API
  812 + 869. Next: one wargame per slot (the map then shows only the session's
  target).
- 2026-11-16, one sensor per slot (`docs/DECISIONS.md` "One sensor per slot
  on both legs of the WAF"): one Suricata container sniffs `dmz` on
  `sN-estate` and `web` on `sN-web` and stands on the 관제망 at .11; the WAF
  has a 관제망 interface (.12) and ships its own audit log from its network
  namespace; the edge router and `sN-inet` carry no sensor. Same verdicts as
  the two-sensor slots on board and corp, kernel_drops 0, RAM per slot about
  1,146 -> 1,126 MiB. A reset now empties `audit.log` before it recreates the
  WAF and its shipper (a shipper started at the end of a full log missed every
  later record). Live: range host 10.31.0.223, slots re-rendered in place,
  the platform VM at this commit. Full `bin/verify` on the VM: 550 s,
  acceptance 95 passed, 0 failed, 1 skipped in 488 s across 12 processes,
  unit and API 833 + 830, `core_loc` 585. A map redraw (both targets, host
  parts at the device end, the IDS under the DMZ switch) is being reviewed
  with the user as local renders on the branch `map-redraw`, not deployed.
- 2026-11-16, fake-risk measures removed (`docs/DECISIONS.md` "gVisor and
  Elasticsearch security removed"): no gVisor (every slot container on
  Docker's default runtime, Kali's origin rewrite and the targets' Docker DNS
  as before 2026-11-15), no Elasticsearch or Kibana authentication, and nginx
  keeps the session check five seconds per session cookie (Django's checks for
  three Kibana first loads 963 -> 16). Sign-up with admin approval and the
  abuse limits from `signup-approval` are merged. Live: the platform VM runs
  `/opt/cr` at that merge with its images; `bin/cloud up` replaced the range
  host (10.31.0.223) from the new bundle in 16 min. Eight idle slots leave
  5,674 MB available (4,869 MB with Kali on runsc); `slot.sh reset 8` 41.9 s
  and 46.8 s (50.1 s before). Full `bin/verify` on the VM: 563 s, acceptance
  95 passed, 0 failed, 1 skipped in 505 s across 12 processes, unit and API
  800 + 870, `core_loc` 587 -> 585, `dependencies` 6, `services` 4; nothing
  throttled by the new limits.
- 2026-11-16, the monitoring is real (`docs/DECISIONS.md` "Each slot's
  monitoring is real"): both Suricata sensors are slot containers on the
  bridge they watch (`sniff`, no address, every other port mirrored to them by
  `tc mirred`) and on the 관제망 `sN_mgmt` (172.29.N.0/24); a log server
  (`rsyslog/rsyslog-minimal`) on the 관제망 takes the sensors' and the WAF's
  logs from shippers over 514/tcp and forwards them to the collector on
  5140/udp as before; the range host's own rsyslog forwarding is gone. The
  live map shows the 관제망 band with the sensors and the log server. Live on
  the range host 10.31.0.248 (replaced by `POST slot/`, then `configure/`;
  the platform VM runs `/opt/cr` at the branch `monitoring-real`, images
  built from it). Same red-team file before and after: every verdict the same,
  kernel_drops 0; hub mode measured equal and not kept. RAM per slot 1,179
  MiB before, 1,183 after. The first full verify hung: `sudo` on the new
  range host waited 21.8 s on its own name (no `/etc/hosts` line, no DNS), so
  readiness reads piled up; `slot.sh` now writes `127.0.1.1 cr-range`. Three
  acceptance tests still read the estate where the WAF-only change put board
  on `sN-web` (F1's board address, the inside leg) or ran the probe in an
  image with no `timeout` (the log server, now probed through `nsenter`);
  fixed. Full `bin/verify` on the VM then: 553 s, acceptance 95 passed, 0
  failed, 1 skipped in 497 s across 12 processes, unit and API 849 + 814,
  ratchet `core_loc` 587, `dependencies` 6, `services` 4. During it, p95 of
  `GET /` 2.6 s and of `GET /api/range/ready/` 6.1 s (32 samples each, 15 s
  apart, eight slots).
- 2026-11-15, the hardening (`docs/DECISIONS.md` "Every surface signs in"):
  every console page and `/api/` needs a signed-in session (`admin` /
  `123456`, made at first start, never forced to change); `/vm-terminal/`,
  `/kibana/` and 8002 check the same session through nginx `auth_request`;
  the session cookie is HttpOnly, the CSRF token lives in the session, no
  CORS; the project password is `/opt/cr/openstack-password` mounted as a
  compose secret; `network.allowed` narrows the platform's ingress (the
  Elasticsearch security and gVisor of that day were removed on 2026-11-16).
  Checked live:
  `uv run bin/cloud up --replace --ref harden` end to end; the full
  `bin/verify` on the platform VM, acceptance 92 passed, 1 skipped (F1's
  course skip), unit 888 + 759, ratchet `core_loc` 584 -> 587 recorded; an
  unsigned browser got the login page on 8000, 8002, both terminals and
  `/kibana/`.

- Versions: commits, branches, tags and pushes to `dev` need no gate; `main`
  takes only a tagged best version after gate 2 (CLAUDE.md, "How work runs
  here").
- 2026-11-13: the container range (gate 1 approved the same day,
  `docs/DECISIONS.md` "The range is one range host; a slot is a compose
  project") replaced the four VMs per slot. The cloud holds two VMs:
  `cr-platform` (`m1.large`, 192.168.2.247) and `cr-range` (`dba.range`,
  6 vCPU, 16 GB), which runs slot N as the compose project `sN` (Kali, the
  nftables edge, the WAF, two Suricata sensors, board and corp, as of
  2026-11-13; a slot now has one sensor behind the WAF, and a session's slot
  runs only its own wargame). The old slot
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
  all twenty sensors. In this capacity measurement a slot reset
  (`slot.sh reset`) took 43 s alone and 101 s for three at once, with ten
  slots up. Ten configured from nothing in
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
- Full `bin/verify` on the platform VM (2026-11-14, four slots,
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
  platform runs `range-host-live`, images from GHCR built from it, the range host replaced by `POST slot/`). The stall on F4's last
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
  runs `range-host-live`, images from GHCR built from it, the
  range host replaced by `POST slot/` and four slots READY after
  `configure/` (store copied first to
  `~/.cache/fsl-work/backup-safe/db-20261114T1410Z-r18.sqlite3`). Full
  `bin/verify` on the platform VM then: 12 min 40 s start to result;
  acceptance 91 passed, 0 failed, 0 errors, 1 skipped in 706 s across 14
  processes; unit and API 1532 passed (815 + 717 in two processes beside it);
  ratchet no regression (`core_loc` 584, `dependencies` 6, `services` 5).
- Console slop removed (2026-11-14, `docs/DECISIONS.md` "Console text and
  UI slop removed"): the tone review's 101 strings and the UI review's 27
  items applied on the round-18 code, removal over rewording. The catalogue
  has no time estimates, chips, labels or pills and one `main.start` button per row; the
  session page is one console button; the result page explains each score
  once; lesson ends count steps passed. Two bugs fixed: a scenario's clock
  starts at the briefing's Start (`POST .../scenario/start/`), and a browser
  without its step record reopens the furthest reached step. Store copied
  first to `~/.cache/fsl-work/backup-safe/db-20261114T1502Z-slop.sqlite3`;
  the live platform runs `range-host-live` (pulled in `/opt/cr`, platform
  restarted; `POST slot/` found the range host standing, `configure/` left
  four slots READY). The platform listens on its own address, not
  127.0.0.1: drive the API from the operator machine. Before and after
  screenshots are in the session scratchpad (`slop-after/`). Full
  `bin/verify` on the platform VM: acceptance 91 passed,
  0 failed, 0 errors, 1 skipped in 693 s across 14 processes; unit and API
  1535 passed (853 + 682); ratchet no regression (`core_loc` 584,
  `dependencies` 6, `services` 5; `product_loc` 27256, 191 below round 18).
- Answer-blind walk round 19 and docs review round 4 (2026-11-15,
  `docs/DECISIONS.md` "Answer-blind walk round 19"): F2's DevTools answers
  need the row picked in DevTools (`dev`), F3's X-Forwarded-For and F5's
  record count need their own KQL condition, F6's loot needs the whole
  dumped table, the map ring leaves out link addresses, a reload keeps the
  Kali shell (tmux in the platform image) and an unapplied rule draft, the
  scenario session and result pages lost their contradictions, and the
  slop list (callouts, glosses, time estimates, the two-scores card,
  repeated cards) went. Left: the "n" lines (not reproduced), `/search`
  strict, the F6 dash, the scenario console's missing end button. Store
  copied first to `~/.cache/fsl-work/backup-safe/db-20261114T1740Z-r19.sqlite3`.
  Deployed: `range-host-live` with images built from it
  (`CR_IMAGE_TAG` in `/opt/cr/.env`), so `POST slot/` replaced the range
  host and `configure/` left four slots READY. Full `bin/verify` on the platform VM: the first run had 7
  setup errors in four modules (the platform did not answer `GET /` within
  3 s; the four passed when rerun alone), the second was all green: 12 min
  30 s start to result; acceptance 91 passed, 0 failed, 0 errors, 1 skipped
  in 704 s across 14 processes; unit and API 1546 passed (868 + 678);
  ratchet no regression (`core_loc` 584, `dependencies` 6, `services` 5).
  Live check: `vm-terminal.sh cr-kali` in a detached tmux session in the
  platform container reached the slot's Kali and kept a command's output
  with no client attached; a browser reload through ttyd was not tried.
- Answer-blind walk round 20 (2026-11-15, `docs/DECISIONS.md`
  "Answer-blind walk round 20"): three blockers fixed and checked live with
  Playwright. F1: the shown check carries `dev: true`, so c1 L2's DevTools
  answers send the picked row (method, path, status and parameter each
  failed with DevTools closed and passed with the search row picked,
  session 1867). F2: GNS3 maps load with fresh node ids per import and only
  the platform opens them (`provision.py` opens nothing); after a reset all
  four slots drew their own map (DMZ 10.30.1-4.0/24, 11 nodes, sessions
  1863-1866). F3: silent polls wait 90 s, not 15 min; c2 L3 step 8 passed
  26 s after the sort change made after sqlmap ended, with no reload
  (session 1868). The other 25 findings and the slop list are in the
  entry; scoring meaning unchanged. Store copied first to
  `~/.cache/fsl-work/backup-safe/db-20261114T2113Z-r20.sqlite3`. Deployed:
  `range-host-live` with images built from it, so `POST slot/`
  replaced the range host and `configure/` left four slots READY; `cr-gns3`
  was recreated, which cleared slot 1's wedged switch TAPs. Full
  `bin/verify` on the platform VM: 782 s start to result;
  acceptance 91 passed, 0 failed, 0 errors, 1 skipped in 726 s across 14
  processes; unit and API 1562 passed (896 + 666); ratchet no regression
  (`core_loc` 584, `dependencies` 6, `services` 5).
- Answer-blind walk round 21 (2026-11-15, `docs/DECISIONS.md`
  "Answer-blind walk round 21"): its 17 findings fixed; scoring meaning
  unchanged, `core_loc` still 584 (the unread-sid check lives in
  `disable.py`: Suricata 8 loads `sid:N rev:1;`, measured live). Store
  copied first to `~/.cache/fsl-work/backup-safe/db-20261115T0019Z-r21.sqlite3`.
  Deployed: `range-host-live` with images built from it, so
  `POST slot/` replaced the range host and `configure/` left four slots
  READY. Checked live (Playwright and the API, sessions 1898-1903): scenario
  1.1 listed an item that arrived 16 s after the attack verdict without a
  reload, refused the final check with one item unjudged
  (`scenario.done.unjudged`), then passed; the guided steps said "items so
  far", passed the last step on the started check and ended with
  `scenario.note.done`; the debrief counted 11 of 11 like the headline; a
  second close on a stale page said the session is closed and hid the
  button; labels read passed/failed in Korean; no `no_benign` warning.
  c1 L3's and-not query with board.com's address failed and with the waf's
  passed; c2's `%3C` and sort answers failed without the DevTools row and
  passed with it; the unsplit-sid rule got 400 `unread_sid` at the syntax
  check and apply; the example word got its line at once; `Total Score: 20`
  and `(Total Score: 20)` passed; f4's first ring sat on the DevTools toggle
  with no callout; a lesson's Start opened `/blue/<id>/`; the WAF shell's
  `TZ=KST-9` printed 09:38 KST where `TZ=Asia/Seoul` printed 00:38 "Asia".
  Full `bin/verify` on the platform VM: 770 s start to result;
  acceptance 91 passed, 0 failed, 0 errors, 1 skipped in 719 s across 14
  processes; unit and API 1578 passed (904 + 674); ratchet no regression
  (`core_loc` 584, `dependencies` 6, `services` 5).
- Answer-blind walk round 22 (2026-11-15, `docs/DECISIONS.md`
  "Answer-blind walk round 22"): its 12 findings and the second-browser
  briefing fixed; scoring meaning unchanged, `core_loc` 584. #7 was not a
  double count: in the store each sqlmap run of session 1929 has its own
  20687 alerts from 1973 requests; the rows now carry the run's time. Store
  copied first to `~/.cache/fsl-work/backup-safe/db-20261115T0434Z-r22.sqlite3`.
  Deployed: `range-host-live` with images built from it, so
  `POST slot/` replaced the range host and `configure/` left four slots
  READY. Checked live with Playwright (sessions 1930-1935): customer
  verdicts on the attack step left no tries, no hint offer and no red line;
  step 3 passed, then went back to unpassed 24 s later when a new item came
  in; step 3's text has no refresh button and there is none; with 2 items
  unjudged the final check was refused with the full line under the strip
  and the note on step 4 showed no raw key after the rest were judged;
  after the pass the strip hid the final check, hint offer and clock and
  showed the end button, customer traffic stopped (`stopped_at` set,
  998 then 1008 pulled), a second `verify-window` got 409, the open session
  page showed the verdict and the debrief, ending from the console asked
  with `session.close.consequence` and opened the result, whose two sqlmap
  rows read 13:56 and 14:00; a second browser on the running scenario got
  no briefing; no `.badge` on the scenario screens or the result; none of
  the listed glosses left in the string table. The answer queue and the
  stale-line suppression are unit-tested; live, c1 L1 s1 checked in 0.5 s,
  too fast to show the race. Full `bin/verify` on the platform VM:
  745 s start to result; acceptance 91 passed, 0 failed, 0 errors,
  1 skipped in 693 s across 14 processes; unit and API 1593 passed (904 +
  689); ratchet no regression (`core_loc` 584, `dependencies` 6, `services` 5).
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
- uv, the Nova keypair and the RC file (2026-11-15, `docs/DECISIONS.md`
  "Virtualenvs are made with uv", "The platform VM's key is a Nova keypair",
  "Example addresses are 10.10.10.0/24", "KVM is recommended, not required",
  "The identity comes from an RC file on the controller node"). Store copied
  first to `~/.cache/fsl-work/backup-safe/db-20261115T032144Z.sqlite3`.
  Checked live: the sideload path's `VENV_COMMAND` on the standing VM made a
  uv `/opt/cr/.venv` (uv 0.13.8, CPython 3.12.3, no `pip`) and
  `bin/verify --fast` passed on it (909 + 669); `bin/cloud up --replace`
  at the uv commit (25 min) and again at the RC commit (37 min 49 s, the
  RC file loaded, `bin/cloud` refused first without it, naming all eight
  `OS_*` variables) left four slots READY and the platform answering at
  :8000. On the rebuilt VM cloud-init installed uv 0.13.8 (checksum OK) and
  no `python3-venv`, `cr-venv` made `.venv`, `openstack.env` has
  `CR_OPENSTACK_DOMAIN=fsl` and the platform signs in by domain name;
  `ensure_keypair` found `fsl-claude` matching `~/.ssh/fsl_claude.pub`; the
  password is in neither run's log.
- The four-command bring-up and the uv project (2026-11-15,
  `docs/DECISIONS.md` "Four commands on the controller" and "The repo is a
  uv project"). Store copied first to
  `~/.cache/fsl-work/backup-safe/db-20261115T055518Z-uvproject.sqlite3` and
  `db-20261115T060144Z-uvreplace.sqlite3`. The live setup moved to the new
  flow: the clouds.yaml entry `fsl-range` written from the RC file's
  password (not reset), `cloud: fsl-range` added to the live `cloud.yaml`.
  CI built all eight images (platform and gns3 from the repo
  root, `uv sync --frozen`: 10 and 167 packages). From an archive of HEAD
  with no `.venv`, `uv run bin/cloud up --replace --ref uv-project` synced
  65 packages, rebuilt the platform VM and left four slots READY (24 min
  22 s); the password is not in its log. On the new VM `cr-venv` ran
  `uv sync --frozen` (Result=success, `uv sync --check`: no changes); the
  sideload command, run through `cr-venv-checkout` after deleting
  `.venv`, made it again. Then plain `uv run bin/cloud up` (27 s, READY)
  and the full `bin/verify` on the VM: acceptance 91 passed, 0 failed, 1
  skipped in 728 s across 14 processes, unit and API 827 + 771, ratchet
  `core_loc` 584, `dependencies` 6, `services` 5, 782 s in all. `bin/cloud
  init` was not run as admin: no admin credentials are on this Mac (no
  `/etc/kolla/clouds.yaml`; admin commands run on con01); with the
  member's `OS_*` it stopped with "not an admin's" and changed nothing.
  The live platform runs the branch `uv-project`; `dev` and
  `range-host-live` hold the same commit and later docs.
- The learner map is the slot's live wiring (2026-11-15, `docs/DECISIONS.md`
  "The learner map is the slot's live wiring"): one ssh read per map
  (`rangehost.WIRING`), drawn by `/map/<session>/` with cytoscape.js; the
  `gns3` service, port 3080 and the platform's Docker socket are gone
  (`services` 4). Store copied first to
  `~/.cache/fsl-work/backup-safe/db-20261115T070528Z-livemap.sqlite3`.
  `uv run bin/cloud up --replace --ref range-host-live` ran twice untouched
  (24 min 10 s and 23 min 44 s), both exit 0 with four
  slots READY; the VM runs four containers (no `cr-gns3`), no Docker socket
  mount, no Docker client in the platform image, nothing listening on 3080.
  The first run found the edge's and Kali's interfaces held none of the
  internet network's subnet (the slot rewrites them), so legs now join by
  MAC. Checked live with Playwright on sessions 1988-1991 (slots 1-4, three
  board and one corp): every link address equals `docker network inspect`
  on the range host, nodes cannot be dragged, zoom works, the map reads the
  topology once and nothing requests port 3080. Live wiring before the slot
  agent's WAF-only change: board and corp-wp stand on `sN-estate` beside the
  edge's `lan`, and the edge forwards everything; the map draws it so.
  Full `bin/verify` on the VM with eight slots (`compute.slots` 8 in the live `cloud.yaml`): first the new map acceptance test failed (it read `full_run`'s topology after that session closed, when its slot was being reset), fixed to read its own open session; then run 2 lost the red-team fixture (`POST /cases/` read timeout 15 s, 15 errors) and run 3 lost every group's `GET /` reach check (3 s, 73 errors), and run 4 passed: acceptance 92 passed, 0 failed, 1 skipped in 591 s, unit and API 881 + 666, ratchet `core_loc` 584, `dependencies` 6, `services` 4, 654 s. Runs 2 and 3 are one defect, not a flake: py-spy on the platform during run 4 showed `waitress` at one full core, `GET /` stalling up to 15.8 s, and 54 % of the GIL in `rangehost.compose` YAML parsing, mostly from `reachability.scored_hosts` (a 30 s cache with no lock, refreshed by every waiting request, each refresh one `describe` per slot) and `range/ready/`'s `plan_slots` bundle; neither changed here, and eight slots doubles both (Next, item 4).
- The live map's layout (2026-11-15, `docs/DECISIONS.md` "The live map is
  laid out by the platform"): `topology.laid_out` places zones left to right
  in traffic order, two-zone devices on the boundary, sensors outside every
  zone under the bridge they sniff, and log edges at right angles; layout
  only, nothing drawn without a counterpart in the slot. Deployed:
  `uv run bin/cloud up --replace --ref range-host-live` (26 min,
  exit 0; store kept in
  `~/.cache/fsl-work/backup-safe/db-20261115T150353Z-maplayout.sqlite3`).
  Checked live with Playwright on sessions 2127 (board, slot 1) and 2128
  (corp, slot 2), both closed: zones in order, no label on another label, an
  icon, a line or a zone border.
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
- The slot VMs have no address the operator reaches: run their commands
  through the platform, `sh
  s.sh "sudo docker exec -i cr-platform ssh -i /data/ssh/id_ed25519
  ubuntu@<cr-mgmt address> '<cmd>'"`, or through `manage.py run_on_role
  <role> '<json argv>' --slot N`.

`uv run bin/cloud` needs two gitignored files in the checkout that runs it,
`deploy/openstack/cloud.yaml` (now with `cloud: fsl-range`) and the newest
copy in `backups/`, and the clouds.yaml entry `fsl-range` in
`~/.config/openstack/clouds.yaml` (mode 0600, written from the old RC file's
password, which was not reset). No RC file and no `OS_*` variables: `os.sh`
and `known-hosts.sh` sign in with `OS_CLOUD=fsl-range`; the old
`fsl-range-openrc.sh` is unused, and the scripts' copies before are in
`~/.cache/fsl-work/backup-safe/cloud-yaml-20261115-clouds/`. `uv run` makes
`.venv` itself. This worktree has them (the newest copy from the last `bin/cloud up --replace`); the old cloud's `cloud.yaml` is kept outside the repo in
`~/.cache/fsl-work/old-cloud/`. A worktree that is cleaned up loses these
files, so copy them before working in a new one. Older store copies are in
`~/.cache/fsl-work/backup-safe/`.

## Waiting for the user

Nothing. Gate 2 is only for `main` (Next, item 7).

## Next, in order

1. The rest of P8 on the live Heat range: the full `bin/verify` with
   acceptance green (the second run above); the WAF tuning 503 above (a
   stale or racing `ControlMaster` on `/tmp/cr-ssh-%C` after a slot VM is
   replaced at the same `cr-mgmt` address is one thing to check
   **[unverified]**); an answer-blind walk. Unknowns still to measure: how
   long a closed session's slot takes to be READY again **[unverified]**
   (two retargeted slots went from stack create to READY in about 4 min);
   RAM per slot on com01 **[unverified]**.
   Seen live: the platform's `cr-mgmt` port kept 10.31.0.158 across five
   replaces, and the last platform-only replace kept the two slots whose
   template and wargame were unchanged (slots 3 and 4).
2. The stack digest covers the template, images and flavors, not the LAN
   group ids: a change to `_lan_rules` alone makes a new `cr-lan-` group for
   new stacks and leaves standing slots on the old one until they are
   replaced; the old group stays until `bin/cloud down`. Run `uv run bin/cloud
   init` once as admin on con01 (`/etc/kolla/clouds.yaml`) to see it report
   everything present; it does not check `security_groups`.
3. Answer-blind walk round 29 of both courses and scenarios 3.1-3.4 on the
   fixes of round 28 (live); fix its findings, rebuild, verify and walk again
   from the start; then tag the state and take it through gate 2 (item 7).
   The `exists` failure on `_source` runtime fields (above) is open.
4. sid 9000001 misses sqlmap's ORDER BY payloads that carry no quote, `-- `
   or `union select` even where it is loaded: a detection gap to measure
   (round 16, `docs/DECISIONS.md`).
5. The platform's CPU under many slots: on the range host, with eight slots
   two of four full verifies on 2026-11-15 lost requests to 3-15 s stalls (the
   live map entry above). Ingest re-reads the whole window: `POST /ingest/`
   took 22-42 s on a closed red-team session while the suite ran, and every
   score wait calls it. On the Heat range the pool is four slots, the whole
   instance quota with the platform; a slot reset is the stack's delete and
   refill **[unverified]**.
6. MySQL `performance_schema=OFF`: on the Heat range it is the target VM's
   memory (`docs/STATE.md` backlog 4).
7. Promotion to `main`: a tagged state, the full `bin/verify`, a live review
   round with zero countable findings and a docs review with no drift
   (CLAUDE.md), through gate 2.

Also open, unordered: the intermittent `test_corp_authz` nonce error; a
newcomer following README on a clean machine; scenario 4.2 and a corp
scenario; whether the walker becomes a repo tool.
