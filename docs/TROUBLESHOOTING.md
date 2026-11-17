# Troubleshooting

Problems the range has had, how each was measured, what caused it and what
fixed it. Each case keeps the numbers it was decided on. The rulings are in
`docs/DECISIONS.md`; this file is the path from symptom to fix.

The two reset cases below were measured on the earlier range, where each slot
was four VMs (an OPNsense edge, Kali, the WAF and a wargame host) and a reset
rebuilt Kali and the WAF through Nova. That range is gone: every slot now runs
as containers on one range host, `cr-range`, and a reset is `slot.sh reset`
on it (`deploy/range-host/slot.sh`). The wargame host, `pristine.sh` and the
rebuild named below no longer exist. What carried over: the pristine copy of
the targets' volumes (now under `/opt/cr/pristine/`, taken by
`deploy/range-host/setup.sh`), the one-second healthchecks and
`--innodb-rollback-segments=1`.

## A slot reset took 272-314 s on the new cloud

### Symptom

Closing a session resets its slot (`docs/OPENSTACK.md` §6.1). On the cloud the
product ran on until 2026-10-20 (an all-in-one host), close to READY took
60-66 s. On the cloud it moved to (`con01`, `com01`, `stg01`, Kolla-Ansible
2025.2), the same code took 272-314 s. The full `bin/verify` opens about 20
sessions, so its acceptance stage grew to 4038 s, past the 60 minutes the
platform keeps a closed session (`CR_RETAIN_CLOSED_MINUTES`).

### How it was measured

Read-only, during a live `bin/verify` (2026-10-24, four resets):

- Nova instance action events for the rebuilt VMs (`openstack server event
  list`), for the rebuild and its timing;
- the platform's ssh commands, sampled once a second on the platform VM
  (`ps -eo args | grep '^ssh '`), for the start and end of every step;
- session open and close times from the store.

| Phase | Seconds |
|---|---|
| close to the rebuild request and the in-place reset start | 4-6 |
| Nova rebuild of the WAF and Kali | 16-19 |
| guest boot to ssh / cloud-init finished | about 45 / 55 |
| WAF and Kali path done after close (beside the wargame host) | about 75 |
| edge in-place reset | 3-5 |
| wargame host `down -v` | 12-17 |
| `up --wait` board | 115-120, 159-165 when the other slot starts board too |
| `up --wait` corp | 94-110 |
| sensor, rules, log forwarding | 9-11 |
| end of the chain to the next open | 17-32 |

The WAF and Kali path ran beside the wargame host and finished first. The
wargame host's chain was the whole reset.

### Cause

The code path was the one the previous cloud ran in 60-66 s. On `com01` the
same work ran about four times slower, and it was serial:

- Every reset initialised two empty MySQL data directories, then ran the
  board's `migrate` and `seed` and corp's `wp core install` and plugin setup.
  About 60-65 % of each wargame's `up` was MySQL initialising its datadir and
  about 25 % app setup.
- Each synced write on the wargame host took about 27 ms. The VM disks are qcow2
  overlays on `com01`'s local disk, a ServeRAID M1115 RAID volume. Nova's
  defaults open them with `cache=none` (O_DIRECT), so each `fsync` in the guest
  waits for that volume.
- board then corp started one after the other.
- The wargame healthchecks probed every 10 s, so a wargame that was ready
  waited up to 10 s to be seen.

Ruled out: the image format and the Nova rebuild, the guest boot, the
platform's polling, the edge reset, and the corp readiness fix of 2026-10-22
(the slowness was there before it). `com01`'s CPU virtualisation was checked
too: it is bare metal (`systemd-detect-virt` answers `none`), `virt_type =
kvm`, and the CPU has `vmx`. `hypervisor_type: QEMU` in `openstack hypervisor
show` is what libvirt reports for KVM too.

### Fix

Three changes, in order of size:

1. `start_wargames()` starts every wargame at once, one ssh command each, and
   names each one that failed. Two slots resetting together: 288 s to 245 s.
2. The four wargame healthchecks probe every second for their first 120 s
   (`start_interval: 1s`, Docker Engine 25 and later).
3. The wargame host's image build starts each wargame once, lets it finish its
   setup, stops it and keeps a copy of every container's volumes under
   `/opt/fsl/pristine/` (`deploy/wargame-host/pristine.sh keep`). Every start
   creates the containers, copies that data into the new empty volumes
   (`pristine.sh restore`) and then starts them. MySQL skips its
   initialisation, the board skips creating its tables and posts, and corp
   skips `wp core install`. 245 s to 117 s.

Copying the same data into every session must not let a learner carry
anything from one session to the next. The board's `seed` sets each seeded
account's password on every start, so the hashes get new salts. corp deletes
`wp-config.php` before the WordPress entrypoint runs, so each start gets new
keys and salts, and it sets the admin password again. Live check: the hashes
of session 1247, submitted to session 1249 as loot, matched no account.

### Result

| | Close to READY, two slots at once | Full `bin/verify` acceptance |
|---|---|---|
| Before | 288 s | 4038 s |
| Wargames started together | 245 s | 3564 s |
| Pristine data restored | 117 s | 2186 s |

## A slot reset still took 86 s

### Symptom

After the fix above, one slot alone took 86 s from close to READY
(2026-10-24, session 1274).

### How it was measured

The platform's ssh commands sampled once a second as before, the wargame
containers' `Created`, `StartedAt` and log timestamps (`docker inspect`,
`docker logs -t`), and `systemd-analyze` on the rebuilt Kali and WAF.

| Path | Step | Seconds |
|---|---|---|
| wargame host | close request to the reset start | 8 |
| | `down -v` of board, corp and the sensor, one after the other | 11 |
| | create the containers and restore the pristine data | 5 |
| | MySQL start, of which InnoDB initialisation | 24, 19 |
| | board start: `makemigrations` 3.5, `migrate` 3, `collectstatic` 3, `seed` 5.5, first healthy probe 3 | 18 |
| | estate sensor (Suricata) start, after the wargames | 8 |
| | rules, log forwarding, READY | 6 |
| WAF and Kali, beside it | Nova rebuild and boot; done at | 78 |

Both rebuilt VMs took about 52 s to boot. `systemd-analyze blame` on each:
`snapd.seeded.service` 15-18 s, `snapd.service` 14-16 s, `cloud-config.service`
12 s, `cloud-init-local.service` 8-9 s, `ModemManager.service` 7 s. `snap list`
showed no snap installed.

### Cause

The wargame host chain was still the critical path, and the WAF and Kali path
ended 8 s behind it, so both had to shrink:

- The board ran `makemigrations` and `collectstatic` at every start, work that
  belongs to the image build.
- The sensor waited for the wargames although it does not depend on them.
- The three `down -v` ran one after the other.
- MySQL still spent 19 s in InnoDB initialisation on the restored datadir.
  The copy was clean (no crash recovery: "Applying a batch of 0 redo log
  records", and each binlog ends with a `Stop` event). `strace` of a start on a
  copy of the pristine data counted about 810 synchronous I/O calls in that
  window, one after another, of which 718 were 16 KB reads of the undo
  tablespaces, 359 per file: the headers of its 128 rollback segments per undo
  tablespace (`innodb_rollback_segments`, default 128) and their cached undo
  segments. MySQL logged
  "Time taken to initialize rseg using 2 thread: 2156-2613 ms" on an idle disk.
  During a reset the WAF and Kali are rebuilt on the same `com01` disk, and with
  a writer beside it the same start took 10-19 s (the live run: 19 s).
- The Ubuntu cloud image starts `snapd` and `ModemManager`, which these VMs do
  not use, and the boot waits for `snapd.seeded`.

### Fix

1. The board no longer runs `makemigrations` (its migration is now in the
   repo) and runs `collectstatic` at build; a start runs only `migrate` and `seed`.
2. The sensor starts alongside the wargames, and log forwarding after both.
3. `down -v` of every wargame and the sensor run at once; the clear fails if
   any of them fails.
4. board-db and corp-db start with `--innodb-rollback-segments=1`, so the
   datadir is made with one rollback segment per undo tablespace when the
   pristine copy is taken. The option must stay set: a datadir made with one
   segment gets the other 127 created at a start without it. MySQL 8.4 manual,
   17.6.3.4: "The innodb_rollback_segments variable defines the number of
   rollback segments allocated to each undo tablespace and to the global
   temporary tablespace." With one segment InnoDB still allows 1024 concurrent
   read-write transactions that both insert and update (17.6.6), far above
   what a session sends. Measured on scratch datadirs: 27 undo reads instead of
   645-718, rollback segment initialisation 25 ms instead of 2.2-2.9 s, InnoDB
   initialisation 2.2-4.1 s idle and 3.2-9.3 s with a writer beside it.
5. The Kali, WAF and wargame host images purge `snapd` and `modemmanager` and
   pin them out (`/etc/apt/preferences.d/no-snapd-modemmanager`).

Not done: deleting the 31 spare redo files (`#innodb_redo/#ib_redoN_tmp`) from
the pristine copy shortened the start further on the scratch datadirs, but
the manual does not say the spare files may be removed. A smaller
`innodb_redo_log_capacity` shrinks the copy but keeps 32 files and the same
number of syncs, so it does not shorten the start.

### Result

Measured live on 2026-10-24 after `bin/cloud up --replace` with these
changes (65 min, exit 0; all three VM images rebuilt).

| | Close to READY, one slot | Close to READY, two slots at once |
|---|---|---|
| Before | 86 s | 117 s |
| After | 70 s and 82 s (two runs) | 98 s |

| Step, one slot | Before | After |
|---|---|---|
| `down -v` | 11 s | 8 s |
| board start, from MySQL ready to healthy | 18 s | 13 s |
| estate sensor | 8 s after the wargames | beside them |
| Kali, WAF and wargame host boot | about 52 s | about 48 s; `snap` is gone |
| MySQL InnoDB initialisation | 19 s | 18.5 s |

The rollback segment change did not shorten MySQL's start on the range,
though it did on the scratch datadirs. `vmstat 1` on the wargame host during a
reset showed why. The restore wrote about 0.5 GB into the page cache. Its
writeback (50-75 MB/s for a few seconds) and MySQL's synchronous I/O then
shared the disk, with 45-86 % iowait for 14 s. After that both vCPUs were
busy for about 10 s while the board ran `migrate` and `seed` and corp ran
`wp`.

### What is left

- Tried and rejected: a copy-on-write restore (`cp --reflink=always`). The
  wargame host's root is ext4, so the only way on the current VM is an XFS
  file system in a file on the root, attached as a loop device (`mkfs.xfs -m
  reflink=1`, `losetup --direct-io=on`). Measured on slot 1's wargame host
  (2026-10-25, scratch MySQL containers with the live images and options,
  both wargames restored at once, caches dropped, five runs each), from the
  restore's start to both servers ready:

  | | idle, median | with a direct-I/O writer beside it, median |
  |---|---|---|
  | `cp` on ext4 (today) | 25.2 s | 33.6 s |
  | `cp --reflink` on the XFS loop | 17.0 s | 29.2 s |
  | `cp` on the XFS loop | 29.3 s | 41.8 s |

  The reflink copy took 0.3-3.6 s against 4.6-16 s, but the loop device made
  every commit slower for the whole session: 200 autocommit inserts took
  16 s instead of 6.4 s (about 81 ms per commit against 32 ms), with or
  without reflink, direct I/O or a preallocated file. Saving 4-8 s per reset
  is not worth commits 2-2.5 times slower while a learner attacks. A real XFS
  block device (a second disk for the wargame host) would avoid the loop, but
  it changes the VM and its commit cost is not measured.
- Tried and reverted: the wargame host on a 4-vCPU flavor (`dba.medium`, 8 GB),
  after the core quota was raised to 24. One slot took 79 s and 78 s, two at
  once 99 s, the same as on 2 vCPUs: the CPU-bound 10 s was not on the
  critical path's longest part, MySQL's start waiting on the disk.

## The session map answered 500 (`KeyError: 'x'`) while a slot container was down

Symptom, 2026-11-16: a full `bin/verify` had 13 acceptance
errors, every one `GET /api/sessions/<id>/topology/` -> 500 from
`topology._boxed`. The verify before it was green.

Cause: `topology.captions` named a zone only by the containers running on it
(the attacker makes it the Internet, the router the DMZ, the log server the
management network, a database the backend). With `board-db` stopped, its
`board-default` network held only board.com and was captioned `web`; the
layout places one web segment, so the second was never given a position.
The same followed for the router, the attacker or the log server being down.
Reproduced live on slot 1 by stopping `s1-board-db` under an open board
session: 500 before the fix, 200 after.

Fix: a zone is captioned by its network first (`internet`,
`estate`, `mgmt`, a `-default` backend) and by its members only after;
`test_a_slot_with_any_one_container_down_still_draws_every_node_in_its_own_subnet`
draws the slot with each container stopped in turn.

## Every `status` query in Kibana found nothing

Symptom, 2026-11-17, answer-blind walk round 23: `status : 404`,
`status >= 500` and F6 step 5's `log_source : modsecurity and status : 500`
returned no results while the WAF log held about 1,300 records with response
code 500; the `status` column showed `-` on every row.

Cause: the data view's runtime field `status` ends in
`doc['status']`, the field nginx's refused log writes. Once a document with
that field was indexed, `status` became a mapped field the runtime field of
the same name shadows, so `doc['status']` read the runtime field itself.
Elasticsearch fails the shard on any document without `http.status` or
`transaction.response.http_code` (`script_exception` in
`SearchLookup.forkAndTrackFieldReferences`); 8 of 9 shards failed. Reproduced
read-only against the cloud Elasticsearch: the same script under another
name aggregates 403, 200, 500, 302, 400, 404; under `status` 8 shards fail.

Fix: the last branch reads `params['_source']['status']`; under the name
`status` all 9 shards answer with the same buckets. A new session's data view
takes the field from `deploy/kibana/objects.ndjson`.

## Answer-blind walk round 23: a refused Kali run, a 600 s sqlmap run, slow Discover

### F5 step 4 waited forever on a run the WAF refused in full

Symptom, 2026-11-16: the learner's stock sqlmap run ended with 1,973
responses 403; the step stayed on "checking" for 8 minutes, then said no
request was logged; steps 5-9 were unreachable and the result page had no
attack case for the run. Elasticsearch held 1,973 `modsecurity` records with
the step's `X-Request-ID` and 0 `suricata` records.

Cause: `_kali_run` found a learner's run only in Suricata's `http` events.
Since the sensor sniffs the web segment behind the WAF, a request the WAF
refuses never reaches it.

Fix: `_sent_by` reads the run from both the sensor's `http` events and the
WAF's records carrying the marker (the tool is checked against either's
User-Agent). Live: the same command on slot 1 passed the check 27 s after its
last request (15 s of `RUN_SETTLED` included) and the score listed it as a TP.

### 3.3's tamper run hit the 600 s tool timeout

Symptom: the variant attack ended "run failed" after 600 s, the final check
could not judge it, and the timer sat at 0:00 for about 13 minutes.

Cause: the final check's own attack (`board-sqli-orderby-sqlmap-random-agent`)
fired on the same Kali while the tamper run was going; both wrote to
`~/.local/share/sqlmap/output/board.com/session.sqlite`, and the second's
`--flush-session` removed the first's. The tamper run's records: 1,440 in its
first minute, then 20 a minute (one every 3 s) until the timeout. Alone it
takes 51 s; two runs at once with one session file on slot 8 broke the first
(`disk I/O error`, `no such table: storage`).

Fix (the directory named in `attacker.py`): a
fired sqlmap case writes to `/tmp/sqlmap-runs/<case id>`
(`attacker.SQLMAP_RUNS`, handed through `harness.fire` to `redteam/tools.py`). The same overlap with separate directories: 52 s and
51 s, each run complete. Live, 3.3 with the final check pressed at 3:45 as in
the walk: the tamper run 53.5 s overlapped by the window's run 48.0 s, both
`held`, the window judged 5.2 s after it ended (failed as undetected, no rule
was written).

### Discover asked for 7,575 fields; a record took 4-8 s to be searchable

Measured on slot 1: a WAF record reaches the collector 0.4 s after its
request (file, log server, UDP 5140), is searchable in Elasticsearch 4-8 s
after it (six samples), and Discover took 4.9 s for a `log_source :
"modsecurity"` query and 10-13 s for its first load. The minute the walk saw
was not reproduced: Kibana showed the new record 7 s and 21 s after the
request before the fix.

Cause: the template filebeat loaded was built from its whole `fields.yml`,
every module's fields included (netflow 1,324, zeek 616, ...): 7,575 mapped
fields, of which the documents carry 171. Discover asks for `fields: *` on 500
rows; that query took 2.4 s against 0.16 s without it. Filebeat's template also
sets a 5 s refresh.

Fix: the collector filters `fields.yml` to the `ecs`, `beat`, `cloud`,
`docker`, `host`, `kubernetes`, `process` and `log` groups before it starts
(`compose.yaml`, written to `fields-lean.yml`) and loads that template over the old one, with a 1 s refresh. The same
6,000 documents reindexed under both templates map each of their 171 fields
the same; 1,821 fields; the Discover-shaped query 2.4 s -> 0.7-0.9 s. Live
after the change and a rollover of each `logs-N-sensors`: searchable 3.3-5.0 s
after the request (four samples, about 2 s of it the SSH hop of the
measurement), Discover showed the record 4.8-7.8 s after it (three runs), the
same query 2.5 s, first load 7.9-8.9 s. A data stream that already exists
keeps the old mapping until it rolls over.

### What is left (measured, not changed)

- The F6 dump is about 1,150 requests at 13 a second, 4 min 41 s: sqlmap runs
  one request at a time and each takes about 40 ms through the WAF; the lesson
  command is left as taught.
- A final check lasts the scenario's `window_minutes` (3 or 4) by design; the
  windows of 3.1, 3.2 and 3.4 were judged 1.0-1.4 s after they ended.
- Closing a session took 11.4 s (F5 lesson) and 20.7 s (3.3 scenario).
- A Kali step's check reads every record of the window and took 0.7-9 s per
  press during a 2,000-request run. Resolved: a poll now reads
  the last 25 s (walk round 27 below).

## Answer-blind walk round 24: a slow Kali check, two customer counts, 4xx from the board

### A finished sqlmap run took about 20 s to pass its check

Symptom, 2026-11-17: after sqlmap's `[*] ending @` line the F5 check passed
18.8 and 19.3 s later, and a press in between was counted as a wrong try
("틀린 뒤 통과 3개" for lesson 2).

How it was measured: the same command from a browser on session 2494, polled
every 2 s: the terminal showed the end 66.9 s after Enter and the step passed
at 89.0 s, 22 s later, without a press.

Cause: the server records a run only when its newest request is
`RUN_SETTLED` (15 s) old, because sqlmap's time-based tests leave gaps of
several seconds; the console polled every 5 s. Every non-passing press of a
Kali check added to the step's `tries`.

Fix: once the terminal shows the step's end line the console checks at once
and then every second with `ended: true`, and the server waits
`RUN_ENDED_SETTLED` (3 s) for such a check; a Kali check that has no recorded
run yet is never a wrong try.

### The console's report said 729 customer requests, the result page 737

Session 2490 (3.1): the final check was judged at 20:14:02, the customers were
stopped at 20:14:13, and 7 requests were sent after the judgment. The report
the console read at the judgment counted what had been pulled by then; the
result page read later counted everything. Fix: the debrief now
counts requests sent before the end of the last final check.

### "4xx-5xx responses not from the WAF" in 3.2 and 3.3

The rows (platform DB): 3.2, two `POST /posts/<n>/comments/` and 3.3, one
`POST /accounts/login/`, all customer u01, status 403, `refused_by: app` (the
board's CSRF refusal). u01 signs in and comments; the generator ran several
flows of one customer at once on one cookie jar, and Django rotates the CSRF
token at sign-in ("For security reasons, CSRF tokens are rotated each time a
user logs in", Django 5.2 reference, "Cross Site Request Forgery
protection", "Why might a user encounter a CSRF validation failure after
logging in?"), so a form token fetched by one flow went stale when another
flow of the same customer signed in. Fix: a customer's flows take turns
(`Customers.turns`); a test board that rotates the token at sign-in refused
none of 30 posts with the fix and some without it.

## A corp case record timed out at 60 s in the full verify

### Symptom

The full `bin/verify`, the first run on the rebuilt platform VM:
acceptance 91 passed, 0 failed, 3 errors, 1 skipped. All three errors are the
setup of `test/test_corp_authz.py`: `POST /api/sessions/2655/cases/` (the
option-flip window, 09:42:37 UTC) read nothing for 60 s
(`requests.exceptions.ReadTimeout`). No earlier kept verify log has this
timeout.

### How it was measured

`POST cases/` records the case, then observes the objectives:
`effect.read_changes` runs `mysqlbinlog` over every binary log of the slot's
corp-db and parses the decoded text in Python, and only then drops changes
before the session start. On slot 2 after the run, inside `cr-platform`
(2 vCPUs), idle: 17,345,172 bytes, read 0.8-5.0 s, parse 2.9 s, 22 changes.
Most of it is the target's set-up at the range host's boot (`binlog.000002`,
2,997,096 bytes). The corp fixture runs two sessions side by side, and each
fires `cases/` twice and then `POST objectives/`, `GET objectives/` and
`GET score/` together, each with the same read and parse, beside eleven other
acceptance processes; the red console polls the same read every 10 s.

### Cause

Every observation re-read and re-parsed the whole binary log, so its cost
grew with the range host's age, not with the session, and under the
acceptance load one record went past the client's 60 s.

### Fix

Fix: `mysqlbinlog --start-datetime` from a minute before the session start, in
UTC (`TZ=UTC`: `mysqlbinlog` reads the value in its own local time zone; with
`TZ=Asia/Seoul` the same value read the whole log, with `America/New_York`
none of it). The Python filter by session start stays. Same slot, same
window: 91,277 bytes, read 0.28 s, parse 0.004 s, the same 22 changes.

## Answer-blind walk round 27: a late Kali pass, slow answers, F5's first note

### F6's sqlmap steps passed 20-30 s after sqlmap exited

Symptom, 2026-11-17: in F6 step 2 (`dump`) sqlmap printed `[*] ending @
22:47:14`; 20 s later the step still showed "아직 실행 중입니다" and it passed
20-30 s after the exit. F5's Kali steps passed within 6 s. Step 8 (`replay`)
behaved like step 2.

Cause, from the code: "아직 실행 중입니다" (`lesson.kali.running`) is the
console's own line, shown until it reads the step's end line after the
command in the Kali terminal; only then does it check with `ended: true` and
the server wait `RUN_ENDED_SETTLED` (3 s). Without it the server waited for
`RUN_SETTLED` (15 s) of quiet after the run's last request, then the next 5 s
poll, then the passing check's own work: 20-25 s and more. Step 8's point
names no terminal, so it never sends `ended`. Why the console missed step 2's
end line was not reproduced here; F6's command is about 240 characters and
F5's about 120, and the command line is matched as one logical terminal line.

Measured in `test_lesson_steps.py`, first second after the run's last request
at which a poll passes, terminal end not reported: 15 s before, 3 s after
when the Kali box shows no sqlmap on a terminal; 15 s while it still does.

Fix: a check without `ended` asks the Kali box (`attacker.typed_tool_running`,
`ps -eo tty=,args=`) whether the step's tool still runs on a terminal; once
it does not, 3 s of quiet is enough. A tool the platform fired has no
terminal and does not count; a box that does not answer keeps the 15 s rule.

### Each Kali poll read the whole run; the pass ingested the whole session

Measured in the same file: late in a 5-minute run a poll read records from
the step's start, a 6 min 10 s window, every 5 s; the passing check then
ingested the session from its start. Now a poll reads `RUN_SETTLED` plus the
5 s slack on each side (25 s) and the whole run only once that is quiet, and
the passing check and the replay check ingest from the run's first request.
Round 23 measured 0.7-9 s per press during a 2,000-request run, which this
read was.

### Answer submissions took 3.9-5.7 s now and then

Symptom: 6 of about 35 submissions in F5 and F6 waited over 2.5 s on
"확인 중…" (F5 step 2 3.9 s, step 7 5.7 s); the rest were quick.

Profiled locally with `platform/` as the working directory: the check for F5
step 2 (`error`) does no Elasticsearch, Kibana or range call and took 1-7 ms;
step 7 (`scanner`) reads the run's WAF detections from the platform database
and took 0.12 s with 8,000 such rows held. Neither explains seconds.

What every request pays, by the code: `api.reachability` runs on every
request and caches the range's addresses for 30 s. The first request after
that rebuilt the list by reading each slot's shape from the cloud API
(networks, servers, the carried segments' subnets, and the slot's compose
document) one slot after another, and every request arriving meanwhile waited
on the same lock. A refresh of R seconds every 30 s delays about R/30 of all
requests by up to R; 6 of 35 over 2.5 s fits R of 5-6 s. The live refresh
time was not measured here (no sign-in to the live platform from this
change), so this is the likely cause, not a proven one.

Fix: the slots are read at once (`ThreadPoolExecutor`, one worker per slot).
Measured in `test_judge_reachability.py` with 8 stub slots of 0.2 s each:
1.63 s before, 0.21 s after.

Not changed: a moved-to lesson sends its benign seed case on the learner's
first hint, skip or pass there, inside that request (`_seed_once_worked`,
one harness fire through the range host), and the platform database is
SQLite with no journal mode set in `cr/settings.py` (a rollback journal by
default), where a write waits for the reads running at the time.

### F5's first answer counted as a wrong try

Symptom: a fresh F5 opens with the developer tools closed, and its first note
did not say to open them; a request sent before they open is not listed, so
a learner who answered the right sort value got `lesson.check.wrong.dev`,
which counted as a try, and the result page showed the step failed, then
passed.

Fix: the note opens the developer tools before the sort request
and says why, and the row-not-selected reply records no try, as the
address-side reply already did (`UNTRIED_REASONS` in `api/views.py`).

## Answer-blind walk round 28: early rule checks, late passes, a slow verdict and open

### F4 step 7 judged a correct rule wrong a second after the search

Symptom, 2026-11-18: with a correct rule, "내 룰 경보 확인" pressed about
1 s after the search answered `lesson.xss.fail.write.silent` ("content를
확인하세요"); 3 s later it passed, and the result page showed the step as
failed, then passed.

Cause, from the code: `_rule_fired` ingested and, finding no alert for the
learner's sid, judged at once: `silent` when the sensor's `http` event was
already searchable, `unrecorded` when it was not, both counted as a wrong
try. Round 23 measured a record searchable 3.3-5.0 s after its request, so a
check a second after the search could not see the alert yet.

Fix: while the newest matching request is younger than `ALERT_ARRIVES`
(10 s), a check with no alert answers `lesson.check.alert_pending`, records
no try (`UNTRIED_REASONS`), and the console checks again every 2 s in the
same way; only after the 10 s does a missing alert fail the rule. Test:
`test_a_check_pressed_before_the_alert_could_be_collected_waits_for_it_and_is_no_wrong_try`.

### F6 step 8 passed 11.7 s after sqlmap exited

Symptom: "공격 요청 차단: 확인됨" appeared about 11.7 s after sqlmap exited;
step 2 passes in 7.3 s.

Cause, from the code: step 8 (`replay`) has no terminal end line, so the
console polled it every 5 s. A poll less than 3 s after the run's last
request answered "settling" without asking the Kali box, so the pass waited
for the next 5 s poll. The passing check then read the run from
Elasticsearch three times: `_run_seen`, the ingest when the run is recorded,
and a second ingest in `_kali_replayed`.

Fix: a check whose tool has left the Kali terminal (`ps`) or whose end line
was seen answers `kali.ending` while the 3 s of quiet run out, and the
console then checks every second; the replay passes the run's `settling`
state through and a press meanwhile is no wrong try; `_kali_replayed`
ingests again only when the run's 949110 is not in the session yet.
Measured in `test_lesson_steps.py` over each phase of the 5 s poll, worst
second after the last request at which the replay passes: 7 before, 4 after
(plus the check's own work); ingests of the run in the passing check: 2 ->
1. Test:
`test_the_f6_replay_passes_within_a_few_seconds_of_sqlmap_s_exit_whenever_the_console_s_poll_falls`.

### F6 step 7 passed before nginx reloaded

Symptom: the step passed the moment nano saved the exclusion file, before
`nginx -t` and `nginx -s reload` ran; a file nginx refuses passed as well.

Cause: `_waf_changed` read only the file.

Fix: the step's note already says nano's exit runs the config test and the
reload, so the check now needs both: the exception gone from the file and an
nginx worker started after the file was last written
(`crs.reloaded_since_written` compares the file's `date -r` time with the
start of the master's children from `/proc/<pid>/stat`). A failed `nginx -t`
stops the `&&` before the reload, so no new worker starts. Meanwhile the
check answers `lesson.miss.fail.narrow.reload` (`loud`). Test:
`test_narrowing_passes_once_the_declared_exception_is_gone_from_the_waf_s_file_and_nginx_reloaded_it`.

### 3.2 said "최종 점검 중" 18 s after 0:00

One observation (3.1 about 5 s, 3.3 about 3 s, 3.4 about 6 s). The window's
own attack in 3.2 runs about 50 s from the window's midpoint, so it had
settled long before the end; the judgment was not waiting on it.

What the verdict waits on after the time is up, by the code: the engine's
next tick (`CR_SCENARIO_TICK`, 2 s); in that tick, when the 15 s observation
is due, `_observe` ran before the judgment: a customers refresh (a range
call), `_ingest` of the last 180 s (one 5,000-document page, with a sqlmap
run in it), and every 20 s a WAF read; then `judge_window` with its own
customers refresh and WAF snapshot; then the console's next 5 s poll. A due
observation, the judgment and a full poll interval together fit 18 s; which
part was slow on the live range was not measured here.

Fix: the tick judges a finished window before a due observation, and once
the window's time is up the console reads the status every second and the
button says `scenario.done.judging` ("결과 판정 중"). Test:
`test_a_window_whose_time_is_up_is_judged_before_the_engine_s_slower_observation_of_the_range`.

### Start to an open console took 14-18.6 s

What the open does after choosing the slot, by the code, one after another:
aim the attacker (a cloud read of the slot's shape and a proxy write), the
WAF posture (`crs.apply`: read, list workers, write, `nginx -t` and reload,
poll for new workers), the sensor's rule file when the posture has its own
(write, `reload-rules`), the baseline (the board's accounts), then the
lesson's seed case (one curl from Kali); the Kibana space was already set up
beside these. Before the session row, the readiness check read the ground
truth and the sensor rules one after the other.

Fix: the attacker, the baseline, the WAF and the sensor run side by side;
the seed waits for the WAF, the sensor and the attacker, so it still sees
the lesson's posture; the readiness reads run side by side. Nothing the
slot reset does was skipped; the slot is set up the same way. Measured in
`test_lesson_api.py` with every range call costing one 0.2 s round trip, a
guided open with its own sensor rules: 10.3-10.4 rounds before, 6.3 after
(10 calls; the WAF's 5 calls and the seed are the chain left). The live
cost of each call and the console's own load after the 201 (Kibana iframe,
first reads) were not measured here. Test:
`test_a_guided_open_sets_up_the_waf_the_sensor_the_attacker_and_the_ground_truth_side_by_side`.
