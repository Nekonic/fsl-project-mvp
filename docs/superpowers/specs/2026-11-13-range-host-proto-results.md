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
- Reset of one slot (`down -v` of both projects, `up`, addressing, pristine
  restore, board `up --wait`): **22.0 s**.
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
