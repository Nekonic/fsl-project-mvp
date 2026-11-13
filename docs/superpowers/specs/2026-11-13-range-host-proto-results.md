# Range-host prototype (option a2): results

Running log of the prototype measurements for the container range design
(one range-host VM, one docker compose project per slot). Prototype files are
under `deploy/range-host/proto/`. Nothing in the product was replaced.

## Setup as found

- `cr-range-proto`: flavor `m1.large` = **2 vCPU / 8 GB** (the design assumed
  4 vCPU / 8 GB), on `cr-platform` at 10.20.0.41, no floating IP; reached with
  the platform VM as ssh jump host. Docker 29.1.3, Ubuntu 24.04.
- Live slot today (read only): edge = OPNsense, Suricata 8.0.6 in pcap mode on
  `vtnet0` (WAN), MTU 1442, no offloads on vtnet; estate sensor =
  `jasonish/suricata` 8.0.7, af-packet on the wargame host's `ens3`, TSO/GSO/GRO
  off; Kali tools sqlmap 1.8.4, curl 8.5.0, mitmproxy 8.1.1 (same versions in
  the prototype Kali image).

## Baseline (today's VM range)

- Board: session 1559, slot 1, 18 cases (12 attack, 6 benign), 4.5 min.
  Platform score: 12 TP, 6 TN, every attack `corroborated: true`.
  The offline scorer `deploy/range-host/proto/score.py` (the platform's own
  `ingest.elastic.normalize_all`, `scoring.correlate` and
  `scoreboard.corroborated`) run on the Elasticsearch dump of the session
  reproduces the platform's per-case verdict, `corroborated` and detection
  count exactly for all 18 cases, so the same scorer is used on the prototype.
- Baseline observations: the estate leg raised no alert in the whole run (it
  saw 60 HTTP transactions, WAF to board with XFF = origin); every alert and
  source is origin 5.188.10.10 (`ru`, the default origin).
- Corp: session 1560, slot 1, 7 cases (3 attack, 4 benign), 67 s. 4 TN,
  3 FN (`corroborated: false`), no alert on any leg; every HTTP event on the
  edge leg has source 5.188.10.10 and on the estate leg WAF to corp-wp with
  XFF 5.188.10.10. Per-case results: `deploy/range-host/proto/results/baseline-*.json`.

## Prototype layout

- `slot.yaml` (project `s<N>`): kali, edge (busybox, ip_forward), waf,
  edge-sensor, estate-sensor. `board.yaml` / `corp.yaml` (projects
  `s<N>-board`, `s<N>-corp`): the targets, attached to `s<N>_estate` at
  session open and removed at close; each has its own internal backend network
  for its database, so the database is off the estate as on today's wargame
  host.
- Networks: `s<N>_internet` (bridge `s<N>-inet`, throwaway docker subnet
  172.30.N.0/24) and `s<N>_estate` (bridge `s<N>-estate`, 10.30.N.0/24), both
  `internal: true`, `gateway_mode_ipv4: isolated` (no host address on the
  bridge), MTU 1442 as on the OpenStack networks. No published ports, no NAT.
- Addresses (`slot.sh address_common`, nsenter from the host): Kali's docker
  address is flushed and the 100 origin addresses of `declaration.yaml` are
  added, default route via 36.128.0.1 as on today's Kali; the edge gets the
  30 origin `.1` gateways on its `wan` side and 10.30.N.1 on `lan`; WAF and the
  target front ends route via 10.30.N.1. Board is 10.30.N.59, corp-wp
  10.30.N.60, WAF 10.30.N.247 (today board and corp-wp share 10.30.0.59).
- Sensors: both `jasonish/suricata` 8.0.7 (the estate sensor's pinned digest),
  host network, af-packet on the slot's bridge. Edge leg config =
  the live OPNsense effective `suricata.yaml` with `conf.d/cr.yaml` merged
  (HOME_NET adjusted to the slot's estate, pcap/netmap replaced by af-packet).
  Estate leg config = `deploy/suricata/suricata.yaml` plus a BPF filter on the
  board and corp-wp addresses, because the estate bridge also carries
  edge-to-WAF traffic that the wargame host's NIC never sees.
- Firing: `fire.py` uses `redteam.harness.fire` with a launcher that runs the
  argv by `docker exec -u kali s<N>-kali` after `set-origin 5.188.10.10` (the
  live session's default origin). `collect.py` turns EVE and the audit log
  into documents shaped like the Elasticsearch ones, and `score.py` scores them.

## Measurements

- Image build on the VM: WAF image (ModSecurity compiled) about 20 min on
  2 vCPU; pristine keep (first start of the target, stop, copy volumes):
  board 94 s (198 MB), corp 224 s (286 MB, WordPress install), both with no
  egress from the internal networks.
- (i) Cold up to healthy, one slot, images and pristine present: common part
  13.5 s + board attach 25.4 s = **39 s**.
- Reset of one slot: the 22.0 s first logged here was wrong (`slot.sh` reused
  one timer variable across nested functions, so it timed only the attach);
  the corrected numbers are in "Reset" below.
- RAM, board session idle: 683 MiB of container memory (common part
  144 MiB: kali 46, waf 37, edge-sensor 37, estate-sensor 24, edge 1; board
  115 + board-db 424).

### Detection, prototype run 1 (s1, board)

- 18 cases in 252 s (baseline 4.5 min including session open and close);
  sqlmap cases 33.5-47.9 s against 37.0-47.8 s on the VM range.
- Compared with the baseline per case: verdict, `corroborated`, the
  signature-id sets of the edge leg, the estate leg and ModSecurity, the alert
  source addresses, the edge-leg HTTP source and the estate-leg XFF are
  **identical for all 18 cases** (`compare.py`: 0 differences;
  `results/proto-board-s1.json`).
- Counts differ, not sets: edge-leg alerts per sqlmap case are 1-14 % higher in
  the prototype (for example 936 against 901); the two dump cases give exactly
  936 each in the prototype against 901 and 927 on the VM range, so the VM
  range is the one losing alerts (the OPNsense counters were reset with the
  slot, so whether pcap drops or UDP syslog loss could not be told).
  ModSecurity counts are equal except random-agent (7546 against 7544, random
  User-Agent).
- Pitfall found in this run: the offload switch-off in `slot.sh` listed
  interfaces with `ls /sys/class/net` under `nsenter -n`, which reads the
  host's sysfs, so container interfaces kept TSO/GSO on. Suricata turns
  offloads off on the bridge it captures, not on the veths feeding it: the
  edge leg had 0 truncated packets (small requests), the estate leg 13
  `afpacket.trunc_pkt` (large board responses as GSO super-packets), with
  `capture.kernel_drops` 0 on both and `tcp.invalid_checksum` 0. Detection was
  still identical, but the fix (list interfaces with `ip -o link` in the
  netns) is applied for every later run.

### Detection, prototype run 2 (s1 board, offloads off on every sniffed veth)

- `show_offloads` after the fix: TSO, GSO and GRO off on every container
  interface on the two sniffed bridges (kali, edge `wan`/`lan`, waf, board,
  corp-wp) and on the bridges; tx checksumming left on. The databases'
  backend interfaces keep the defaults (not sniffed).
- Board 18 cases, 249.5 s: **0 differences** against the baseline
  (`results/proto-board-s1-run2.json`); `capture.kernel_drops` 0,
  `afpacket.trunc_pkt` 0, `tcp.invalid_checksum` 0 on both legs.
- RAM during sqlmap: common part peak 313 MiB, board 559 MiB, so about
  0.87 GB per board session under sqlmap; host available memory never below
  5.7 GB with s1 (board, sqlmap) and s2 (corp) up.

### Corp target: hidden egress dependency found

- The first corp run in the prototype failed at `corp-normal-registration`:
  `/register/` served the home page. Cause: WordPress's `wp core install`
  enables pretty permalinks only if a loopback HTTP request to the site URL
  (`http://corp.com`) succeeds. On today's wargame host the corp network has
  egress, so that request leaves for the real Internet name corp.com and the
  install ends with `/%year%/%monthnum%/%day%/%postname%/`; on the prototype's
  internal network it fails and the site keeps plain permalinks, so
  `/register/` falls through to the home page.
- Prototype fix (no product change): `corp.yaml` gives corp-wp
  `extra_hosts: corp.com:127.0.0.1`, so the loopback test reaches its own
  Apache. The pristine keep was redone (permalinks now as on the live slot).
  Worth fixing in the product regardless: the live corp install sends a
  request to a real third-party host at every pristine build.

### Isolation (v)

- `isolation.sh 1 2`: from s1-kali and s1-waf, s2's estate (WAF, board), the
  range host (10.20.0.41:22, 172.17.0.1:22), the estate bridge's gateway
  address, the platform (10.31.0.88, 10.20.0.74, 192.168.2.247 on 8000), the
  metadata service and the Internet (1.1.1.1:443, ghcr.io) are all refused;
  board.com through the WAF and board directly through the edge are reached;
  board-db does not resolve from Kali. 28/28 checks hold.
- Gap found and closed: the targets' backend networks (internal, but default
  gateway mode) put a host address on their bridge (172.18.0.1), and board
  reached the range host's sshd through it. With
  `com.docker.network.bridge.gateway_mode_ipv4: isolated` on the backend
  networks too, no docker bridge carries a host address and the target-side
  probes (range host sshd, Internet) are refused.
- `br_netfilter` is not loaded by Docker 29 here, so bridged frames do not
  traverse iptables and Docker's `DOCKER-INTERNAL` drops (which would drop the
  origin addresses, being outside the docker subnet) do not apply.
  `slot.sh` still adds `DOCKER-USER` same-bridge accepts so that loading
  `br_netfilter` later would not break the slot.

### Detection, run 3: board in s1 and corp in s2 at the same time

- Both started together; corp 7 cases in 6.8 s, board 18 cases in 257.6 s.
  `kernel_drops` 0, `trunc_pkt` 0, `invalid_checksum` 0 on all four sensors.
- Corp: **0 differences** against the baseline (4 TN, 3 FN with
  `corroborated: false`, no alert on any leg, edge-leg source and estate XFF
  5.188.10.10) (`results/proto-corp-s2.json`).
- Board: 17 of 18 cases identical; `board-sqli-orderby-sqlmap-skip-waf` drew
  one extra estate-leg alert, sid 9000001, source the WAF (10.30.1.247).
  Cause: sqlmap's heuristic probe appends a random string of `'"().,` to the
  parameter, and the WAF passes these probes to the board in every run (the
  estate leg sees two per run in the baseline and in all three prototype runs).
  In run 3 the random string was `').(").(..`, which contains `')`, matched by
  9000001's `\x27[\s+]*\x29`; in the baseline and runs 1-2 it did not
  (baseline `.'.(,,."((` and `(((.,('.)"`). The verdict and `corroborated` are
  unchanged. This is the tool's randomness, not the substrate: the same
  probe would raise the same alert on today's estate sensor.

### Attach and detach of a scenario's targets

| step | times measured (s) |
|---|---|
| attach board (pristine restore, `up --wait`, route, offloads) | 25.4, 24.3, 25.8, 26.2, 27.8, 25.4, 25.7 |
| detach board (`down -v`) | 3.9, 3.7, 4.5 |
| attach corp | 22.2, 24.3, 20.7 |
| detach corp | 5.0, 4.8, 5.2 |
| common part `up --wait` + addressing (one nsenter per address) | 13.5-15.0 |
| common part `up --wait` + addressing (`ip -batch`) | 8.0 |

Board's attach is MySQL start on the restored datadir plus Django start and
its healthcheck; the common part is not on that path.

### Reset (ii)

Full reset = detach target, `down -v` of the common part, `up --wait`,
addressing, attach target; wall clock from the first to the last slot done.

| slots at once | wall (s), one nsenter per address | wall (s), `ip -batch` |
|---|---|---|
| 1 | 52.6 | 42.9 (down 4.9, up 8.0, attach 25.7) |
| 2 | 75.7 | see below |
| 3 | 107.6 | see below |
| 4 | 129.3 | see below |

`reset_fast` (a variant, not in the design): keep edge and both sensors
running (truncate the logs and `suricatasc -c reopen-log-files`), recreate
only kali and waf (the two root shells) while the target is detached and
re-attached in parallel, flush the edge's neighbour table. One slot: 34.3 s
(kali and waf 8.2 s, target 34.2 s), isolation 28/28 afterwards.

Multi-slot resets, first pass (2 vCPU; a stray memory sampler from run 2 was
still polling `docker inspect` every 5 s, so these are pessimistic and are
re-measured below):

| slots at once | full reset wall (s) | `reset_fast` wall (s) |
|---|---|---|
| 1 | 42.9 | 34.3 |
| 2 | 67.6 | 55.6 |
| 3 | 101.4 | 87.2 (77.1 on a repeat) |
| 4 | 123.9 | 113.2 |

`vmstat` during three `reset_fast` at once: 61 % user, 25 % system, 5 % idle,
7 % iowait: CPU-bound on 2 vCPU, not disk-bound. The board attach (MySQL and
Django start) grows linearly with the number of slots resetting.

sqlmap scaling, first pass (`board-sqli-orderby-sqlmap` from 1-4 Kalis at
once, 4 board sessions up): 48.1 s alone, 70 s with 2, 101 s with 3, 129 s
with 4. `capture.kernel_drops` 0 on all 8 sensors in every step, including 4
slots running sqlmap at once. Lowest available memory 4.0 GB with 4 sessions
running sqlmap.

### Clean re-measurement on 2 vCPU (4 board sessions up, stray sampler killed)

Idle CPU with 4 board sessions up: about 30 % of 2 vCPU (8 Suricata
instances, healthchecks, 4 MySQL). Raw output `results/scaling-2vcpu.txt`.

| slots at once | sqlmap dump case (s) | growth vs 1 | full reset wall (s) | `reset_fast` wall (s) | kernel_drops | min available |
|---|---|---|---|---|---|---|
| 1 | 40.1 | 1.00 | 46.3 | 36.0 | 0 | 4209 MiB |
| 2 | 53.0-54.1 | 1.35 | 72.3 | 58.9 | 0 | 4114 MiB |
| 3 | 77.5-79.8 | 1.99 | 99.9 | 89.7 | 0 | 4068 MiB |
| 4 | 103.4-105.4 | 2.63 | 122.3 | 104.3 | 0 | 3996 MiB |

(VM range reference: the same sqlmap case took 37.0 s; a slot reset 70-82 s,
two at once 98 s.)

### Rule reload (vi)

Through `docker exec`, idle slot, 4 local rules (edge leg) / ModSecurity with
CRS 4.25.1 (846 rules):

- `suricatasc -c reload-rules` on the edge-sensor: 0.40, 0.41, 0.61 s; on the
  estate-sensor: 0.40, 0.38, 0.38 s. A rule appended to the edge rules file
  and reloaded fired on the next request (1 alert, sid 9900001), then removed.
- WAF `nginx -t && nginx -s reload`: 0.70, 0.87, 0.91 s.

### 4 vCPU not measurable

Resizing `cr-range-proto` to `dba.medium` (4 vCPU / 8 GB, the size the
design assumed) was refused by Nova: the flavor's 40 GB disk is below the
Ubuntu image's 60 GB minimum. No other 4-vCPU flavor exists and no new VM was
to be created, so every number above is for 2 vCPU.

## Settings the container range needs (record of what was set)

| pitfall | setting |
|---|---|
| TSO/GSO super-packets truncated by af-packet (`afpacket.trunc_pkt`) | `ethtool -K <if> tso off gso off gro off` inside every container whose interface is on a sniffed bridge (kali, edge both legs, waf, target front ends), on the host veths and the bridges; Suricata only turns offloads off on the capture interface itself |
| checksum offload | tx checksumming left on; af-packet `checksum-checks` default and `stream.checksum-validation: yes` (as on OPNsense): `tcp.invalid_checksum` 0 in every run, because af-packet marks partial-checksum packets as not to be validated |
| capture point | the slot's bridge (`s<N>-inet`, `s<N>-estate`), promiscuous (Suricata's default), one fanout `cluster-id` per sensor; the estate leg needs `bpf-filter: host <board> or host <corp-wp>` because the bridge also carries edge-to-WAF traffic that the wargame host's NIC never sees |
| NAT, userland proxy, published ports | none: no `ports:`, `internal: true` networks, no masquerade; origin addresses arrive unchanged at the WAF and both sensors |
| host address on bridges | `com.docker.network.bridge.gateway_mode_ipv4: isolated` on every network, the targets' backend networks included (otherwise the target reaches the range host's sshd) |
| overlapping origin CIDRs across slots | docker gets a throwaway 172.30.N.0/24 per internet bridge; the 100 origin addresses and 30 gateways go in with `nsenter ... ip -batch` (one call per container, 8 s for the common part instead of 13.5-15 s) |
| `br_netfilter` | not loaded by Docker 29; if loaded, Docker's `DOCKER-INTERNAL` would drop origin-address frames, so `DOCKER-USER` same-bridge accepts are added |
| MTU | 1442 on all networks, as on the OpenStack networks |
| stats | `stats.interval: 5` so `capture.kernel_drops` can be read with `dump-counters` (the OPNsense value of 300 s returns "stats not yet synchronized") |
| corp first install | `extra_hosts: corp.com:127.0.0.1` on corp-wp so WordPress's pretty-permalink loopback test succeeds without egress |

## Against the pass bar (2 vCPU / 8 GB)

| criterion | bar | measured | verdict |
|---|---|---|---|
| one reset | <= 45 s | full 46.3 s (42.9 s on a repeat); `reset_fast` 36.0 s | pass with `reset_fast`; full reset marginal |
| three resets at once | <= 60 s | full 99.9 s; `reset_fast` 89.7 s | fail on 2 vCPU (CPU-bound) |
| RAM per session | <= 2 GB | 0.68 GB idle, about 0.87 GB under sqlmap | pass |
| sessions on 8 GB | >= 4 | 4 ran sqlmap at once with 4.0 GB still available (memory would allow about 8) | pass on memory; CPU limits useful concurrency to 2 on 2 vCPU (sqlmap growth 1.35x at 2, 1.99x at 3) |
| isolation | holds | 28/28 from Kali and WAF; target-side probes refused after the backend-network fix | pass |
| detection identical | identical per case | board runs 1 and 2: 0 differences; run 3: one extra estate alert from sqlmap's random heuristic string; corp: 0 differences | pass |
| kernel_drops | 0 | 0 with 1 slot busy and with 4 slots running sqlmap at once | pass |
| cold up | (measure) | 39 s for one slot | - |
| rule reload | (measure) | Suricata 0.4-0.6 s, nginx 0.7-0.9 s | - |
| attach / detach | (measure) | board 24-28 s / 4-5 s; corp 21-24 s / 5 s | - |

## Not measured

- A 4 vCPU or 16 GB range host (see above); the time bars that failed are
  CPU-bound and were measured on half the CPUs the design assumed.
- Resets while other slots are under load (resets and sqlmap were measured
  separately).
- The production paths that the prototype replaces with local tooling: log
  shipping by rsyslog to the collector and Elasticsearch (the offline scorer
  reads the files), the platform's session open/close and reset state machine,
  ttyd terminals through `docker exec`, the background customers traffic, and
  objectives / loot ground truth.
- Container escape from the learner's root shells (the shared-kernel risk
  in the design stays a ruling for the user).

## Clean-up

- `cr-range-proto` deleted (its Nova-created port went with it; it had no
  volumes). Baseline sessions 1559 and 1560 were closed by the harness; both
  live slots are READY with no session. Nothing on the platform VM was
  changed apart from `/tmp/proto-baseline` (logs and the dump script).
