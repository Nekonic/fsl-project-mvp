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
