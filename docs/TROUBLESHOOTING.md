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
platform keeps a closed session (`FSL_RETAIN_CLOSED_MINUTES`).

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
