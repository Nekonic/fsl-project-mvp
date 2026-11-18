# Container-based range: design and gate-1 summary

## Gate-1 summary

**Recommendation: (a2).** One range-host VM, `cr-range`, which is today's wargame host grown. Each slot is one docker compose project `s<N>` on it. The OPNsense edge is replaced by a per-slot router container plus two host-network Suricata containers, one per leg. No k3s. The platform VM is not grown.

- **What the code already supports.** The adapter already runs some roles as containers on a VM. The declaration's `compose:` map plus `wargame_host.inside()` wrap commands in `sudo docker exec <service>` over ssh. That covers board, board-db, corp, corp-db and the estate sensor. (a2) extends the same map to attacker, proxy, gateway, sensor and edge, and turns a slot from 4 VMs into a compose project.
- **What the user sees stays the same.** The REST API, `Session.slot`, the readiness and reset state machine, the `logs-<slot>-sensors` indices, `reset-owed` and acceptance all keep their shape.
- **(b) k3s: rejected.** k3s runs on containerd, not Docker, and Docker is fixed tech. The range needs multi-homed pods on identical origin CIDRs in every session, which takes Multus plus a bridge CNI per namespace. Suricata would still have to sniff host bridges, as in (a). It adds about 0.5-0.7 GB for the k3s server, a second image store, and manifests that duplicate `wargames/*/compose.yaml`. Nothing gets simpler.
- **(c) grow the platform VM: rejected.** All of its blockers are isolation and memory problems (detail in section 2). Fixing them means a separate daemon and a separate kernel, which is (a).
- **Ratchet impact.**
  - `core_loc` 584: unchanged. `rules/suricata.py` and `rules/crs.py` already take the rule path and reload command as parameters; ingest and scoring are untouched.
  - `dependencies` 6: unchanged.
  - `services` 5: unchanged by `bin/measure`'s current definition, because the per-slot compose file lives under `deploy/` as `deploy/wargame-host/sensor.yaml` does today. **The user must rule** whether that counts as honest. The 2026-10-21 removal counted `session.yaml` (10 to 5) because the root `compose.yaml` included it.
- **Isolation trade (user ruling needed).** Learners' root shells in Kali and the WAF would share one kernel with the other sessions' containers. Today each session has its own VMs. A container escape reaches the other slots on that host: their board secrets, so loot. It does not reach the control plane. One gain: Kali is no longer on `mgmt` at all. `THREAT-MODEL.md` has to say this.
- **What the learner sees differently.**
  - Nothing of OPNsense: only the platform ever reached its GUI and ssh (2026-10-12).
  - The learner map keeps its 13 nodes; addresses come from the per-session address table as now.
  - The F6 reload command text becomes `nginx -t && nginx -s reload` (no systemd in a container). `wargames.lesson` fills it from the declaration.
  - Both sensors run the same pinned Suricata build.
- **Numbers (estimates until the prototype measures them).**
  - Reset of one slot: about 35-50 s, against 70-82 s measured. The Kali and WAF Nova rebuild plus boot (about 48 s boot, 78 s path) goes away. The critical path becomes the wargame chain: about 8 s `down -v`, 5 s restore, MySQL start, 13 s board, 6 s rules and logs. MySQL's InnoDB start was 18.5 s with VM rebuilds writing to the same disk, and 3.2-9.3 s with one writer on scratch datadirs.
  - RAM per session: about 1.5-1.8 GB. The docker session stack measured roughly 1.5 GB with 9 containers (2026-10-10); this stack has 9 to 10 containers and one more Suricata. Today a slot reserves 11 GB.
  - Sessions per host: about 8 on a 16 GB / 8 vCPU range host, against 2 slots now.
  - Open to ready: already near-instant when a READY slot exists. Cheap slots let the platform keep one spare slot so the reset is off the learner's path.

## 1. Current state, as read

- A slot is 4 VMs: `cr-edge`, `cr-kali`, `cr-waf`, `cr-wargame-host`, plus `-N` copies.
  - Slots N>1 get their own `cr-internet-N` (the same 30 origin /24s) and `cr-estate-N` (the same estate CIDR). `mgmt` is shared.
  - Kali holds 30 subnets' worth of pinned Neutron fixed IPs and uses `set-origin` SNAT.
  - The edge holds `.1` on every origin subnet and runs Suricata on the WAN in pcap mode.
  - The estate sensor is a host-network `jasonish/suricata` container on the wargame host, using af-packet on the estate NIC.
- Logs reach the collector over syslog UDP 5140. The slot is taken from the sender hostname by the regex `-(\d+)` in `deploy/filebeat/filebeat.yml`.
- Close (2026-10-12): the edge and the wargame host are reset in place. Kali and the WAF are rebuilt by Nova because both hand out a root shell.
- Terminals: `entrypoint.sh` runs ttyd, which runs `vm-terminal.sh cr-kali|cr-waf`. That script looks up the `mgmt` address and ssh's to the VM.

## 2. The options

### (a2) Range-host VM with per-slot compose projects (recommended)

- **What a session is.** It still takes a slot. Slot N is compose project `s<N>` on `cr-range`, with these containers: `kali` (the stamping proxy runs inside), `edge`, `edge-sensor`, `waf`, `estate-sensor`, `board`, `board-db`, `corp-wp`, `corp-db`.
- **Networks.** `s<N>_internet` and `s<N>_estate` are `internal: true` bridges, plus the wargames' own default networks.
- **Isolation.**
  - Each slot has its own L2 bridges. Docker's isolation chains drop forwarding between bridges, and internal networks have no egress and no masquerade.
  - Docker refuses overlapping subnets, so docker gets a small throwaway subnet for each internet bridge. The real addresses go in with `nsenter -t <pid> -n ip addr add` from the host: the 30 `.1` gateways on the edge, about 151 origin addresses on Kali, and Kali's default route. The pattern is already in `interfaces.CONTAINERS`.
  - The estate can use a docker-managed per-slot subnet, 10.30.N.0/24, inside `HOME_NET` 10.0.0.0/8. Alternative: the same declared CIDR assigned with nsenter.
  - The bridge's host-side IP has to be closed off with Docker's isolated gateway mode or host INPUT drop rules. Verify which in the prototype.
  - Kali is not on `mgmt`.
- **Suricata.**
  - Edge leg: `edge-sensor` uses `network_mode: host` and `--af-packet=<s<N>_internet bridge>`. It sees what OPNsense's WAN sees: Kali and customers to the edge.
  - Estate leg: `estate-sensor` uses af-packet on `s<N>_estate` with a BPF filter on the board and corp addresses. That reproduces the wargame host NIC's view (WAF to targets with XFF, and direct hits), which F3's `site_source`/`client_source`/`xff` depend on.
  - The edge itself is a pinned busybox container with `sysctls: net.ipv4.ip_forward=1` (the digest is already in `interfaces.BUSYBOX`). It only forwards and nothing listens on it.
  - Rule files are bind-mounted under `/opt/cr/s<N>/<sensor>/rules`. Reload is `suricatasc -c reload-rules`, run through `docker exec`.
- **Terminals.** ttyd on the platform runs `vm-terminal.sh kali|waf`. That ssh's to `cr-range` and runs `sudo docker exec -it -u kali s<N>-kali bash -l` (or the `waf` container). The prompt hostnames stay `kali` and `waf`.
- **Ground truth, seams.**
  - `runner(role)` becomes ssh to `cr-range` plus `docker exec s<N>-<service>`; today it does this only for the wargame roles.
  - `api/loot.py`, `api/effect.py`, `attacker.py`, `operator_log.py`, `rules/*`, `ingest/elastic.py` and `kibana.py` are unchanged.
  - The `range/opnsense.py` seam exception is deleted. The `wargame_host.py` exception becomes the range host's.
  - `site.egress_of` / `opened()` keep working through `docker exec -i kali python3 …`.
- **Logs.** Range-host rsyslog runs imfile per slot per log. `omfwd` gets a template with a fixed per-slot hostname (`edge-N`, `waf-N`, nothing for slot 1), so the filebeat slot regex is unchanged. `range/waf.forwarding()` gains a hostname argument.
- **Reset.** `down -v --timeout 1` of the project, `up --no-start`, `pristine.sh restore`, `up -d --wait`, addressing, sensors, rule seed, log restart. Recreating Kali and the WAF from their images wipes them as a Nova rebuild does. Estimate 35-50 s for one slot. Disk contention when several slots reset at once must be measured: two slots at once measured 98 s today.
- **RAM.** About 1.5-1.8 GB per session (based on the 1.5 GB stack of 2026-10-10).
- **Capacity.** Removing 8 slot VMs frees 22 GB / 10 vCPU, on top of the 20 GB / 7 vCPU free now. The project quota allows 20 cores and 48 GB beyond the platform VM. Caveat: com01's RAM allocation ratio is 1.5, so a dense host that really uses its RAM can push com01 into swap. The cloud admin must check physical free memory.
- **Code that goes.**
  - `range/opnsense.py` (283 lines) and `deploy/opnsense/*` (about 470 lines), including the QEMU builder and importer.
  - In `openstack.py`: edge configure/reset/reboot/settle, the 4-role image bundles, the Kali/WAF rebuild, per-slot `HostKeyAlias` generations.
  - Most of `slot.py`'s fixed-IP port planning.
  - The per-slot internet/estate networks in `fabric.py`.
  - The flavor wiring for 4 roles.
  - The OPNsense publishing question (backlog 0) and Next 7 (edge WAN aliases, stale WAF host key) disappear as a class.
- **Code that comes.**
  - `deploy/kali/Dockerfile` (restore from git history before the removal commit, adapted) and `deploy/waf/Dockerfile` (from `setup.sh`, nginx in the foreground).
  - `deploy/range-host/` (from `deploy/wargame-host/`): `setup.sh` pulls every image, `slot.yaml`, `address.sh`, rsyslog template.
  - `images.yml` and `bin/platform-rebuild` `IMAGES` gain `kali` and `waf`.
  - A slot-as-project adapter.

### (b) k3s pods: rejected

- **What a session is:** a namespace.
- **Isolation:** NetworkPolicy plus Multus bridge networks, needed for multi-homed pods on identical origin CIDRs.
- **Suricata:** still host-network pods sniffing per-namespace bridges, as in (a).
- **Reset:** delete and recreate the namespace. Pod sandbox and CNI add about 1-3 s per pod (estimate); this is not faster than compose.
- **Cost:** about 0.5-0.7 GB for the k3s server. containerd replaces Docker, which conflicts with the fixed tech. Wargames would need manifests besides `compose.yaml`. Multus is one more component. Terminals become `kubectl exec`. No code goes that (a2) does not already remove.

### (c) Bigger platform VM running the sessions: rejected

**Which removal reasons still apply.**

- **The 2026-10-20 ruling (OpenStack-only, one substrate).** This does not block (c) by itself, since the platform VM is on OpenStack. But it is the removed substrate brought back on the control plane's daemon.
- **The 2026-10-10 OOM.** About 1.5 GB per stack. Elasticsearch was OOM-killed on a 4 GB VM, and 2 sessions were the cap on an 8 GB VM. This still applies: Elasticsearch (512 MB heap, about 1.2 GB RSS), Kibana (about 1 GB), GNS3, the platform and ttyd already sit on `m1.large`. 4 sessions would need about 16 GB plus a reserve.
  - Fix: a bigger flavor plus cgroup memory limits per slot and a reservation for Elasticsearch. It is fixable.
- **2026-09-30 placement spec, "Shares a kernel and the root Docker daemon with the red team".** This still applies, and harder:
  - The platform and GNS3 containers mount `/var/run/docker.sock`. A breakout from Kali or the WAF lands on the host, which holds that socket, `openstack.env` (cloud credentials), the range ssh key, `db.sqlite3` and the Elasticsearch data.
  - Fix: a second dockerd with its own socket and data-root, or rootless docker, or gVisor for Kali and the WAF. The kernel is still shared, so the only full fix is a separate VM, which is (a).
- **"Undoes the platform's range-address refusal".** Still applies: Kali's bridge reaches the platform's 8000/8002/3080 through the host. Fix: INPUT drop rules in `platform.yaml`'s cloud-init.
- **"Rebuilt, never patched".** Every `bin/platform-rebuild` (15-42 min) would kill every running session and redo the pristine data at bring-up.

**Blast radius:** the whole product.

## 3. Prototype (measure before any replacement)

Run it on a throwaway VM `cr-range-proto`, 4 vCPU / 8 GB. It fits the quota: 18 of 24 cores and 38 of 56 GB. It needs a port with egress to pull images.

Work on branch `range-host-proto`, under `deploy/range-host/proto/`:

1. `slot.yaml` (the 5 range containers) and the rendered board/corp files at the current tag.
2. `address.sh` (nsenter addresses and routes).
3. Kali and WAF images built on the VM.
4. A `measure.sh` that logs timings and `docker stats`, `free -m`, and the cgroup `memory.current` for each project.

What it measures:

- **(i)** Cold `up` to all healthy for one slot.
- **(ii)** Reset of one slot, then of 2, 3 and 4 slots at once.
- **(iii)** RAM per session, idle and during the `board-sqli-orderby-sqlmap` sqlmap run from `s1-kali`.
- **(iv)** The largest N for which free memory stays above 1 GB, one reset stays at or under 60 s, and sqlmap's time grows by less than 1.5x.
- **(v)** Isolation. From `s1-kali`, all of these must fail: reaching s2's estate, the bridge's host IP, the platform's `mgmt` address, and the Internet. `curl board.com` must succeed, with the origin source in the WAF audit log, the edge sensor's EVE showing the origin source, and the estate sensor showing WAF to board with XFF.
- **(vi)** Rule reload time through `docker exec suricatasc`.

Proposed pass bar for the user to confirm: one reset at or under 45 s, three at once at or under 60 s, at most 2 GB per session, at least 4 sessions on 8 GB (so at least 8 on 16 GB), and every isolation check holds.

## 4. Replacement stages (only after the numbers pass)

1. **Images.** `deploy/kali/Dockerfile`, `deploy/waf/Dockerfile`, `.github/workflows/images.yml`, `bin/platform-rebuild` `IMAGES`, and their tests.
2. **Range-host image.** `deploy/wargame-host/` becomes `deploy/range-host/`: `setup.sh`, `pristine.sh`, `slot.yaml`, `address.sh`, `daemon.json`. `range/wargame_host.py` renders one project per slot with `s<N>-` container names.
3. **Declaration.**
   - `platform/range/declaration.yaml`: every role goes to `cr-range`.
   - The `compose:` map gains attacker/proxy=kali, gateway=waf, sensor=edge-sensor, edge=edge.
   - Per-sensor rule paths and reload commands as seen inside the containers; WAF reload `nginx -t && nginx -s reload`.
   - `declared.py` gains the bridge and estate CIDR fields.
   - `cr/settings.py` derivations keep their shape.
4. **Adapter.** `platform/range/openstack.py` (or a new `range/rangehost.py`):
   - `in_slot` selects a project; `runner` uses `docker exec`.
   - `describe()` is built from the declared origins plus `docker inspect`, through `interfaces.containers`.
   - `reset_slot` / `rebuild_slot` / `configure_slot` / `plan_slot` / `teardown_slot` work on projects.
   - Nova manages only the platform VM and `cr-range`.
   - Delete `opnsense.py`, `deploy/opnsense/`, the edge methods, `slot.py` port planning, and the per-slot networks in `fabric.py`.
5. **Logs.** Per-slot rsyslog with a fixed-hostname template (`range/waf.py`). `deploy/filebeat/filebeat.yml` is unchanged.
6. **Terminals.** `platform/vm-terminal.sh` (`kali|waf` plus the slot, `docker exec -it`), `platform/entrypoint.sh` arguments. `nginx.conf` is unchanged.
7. **Maps.** Redraw the system map `deploy/topology/system/range-openstack.gns3`. Check the learner map's addresses. Update `api/maps.py` if the interface source moves.
8. **Tests.**
   - Retarget or delete the VM-shaped unit tests (the opnsense, flavor, slot-port, image-bundle and configure tests), with each deletion justified in the commit.
   - `bin/verify --fast`, then the full `bin/verify` on the cloud.
   - Raise `compute.slots` to 4 and measure the acceptance time.
9. **Cut-over.**
   - `bin/cloud up --replace`: builds `cr-range`; deletes the 8 slot VMs, the per-slot networks and the OPNsense image.
   - Docs: the CLAUDE.md seam exceptions, the `ARCHITECTURE.md` and `.ko.md` pair, `OPENSTACK.md`, `THREAT-MODEL.md`, a `DECISIONS.md` entry, `STATE.md`, `now.md`.

### Critical Files for Implementation
- /Users/nekonic/Documents/GitHub/fsl-project-mvp/.claude/worktrees/cloud-vm-status-report-45aefd/platform/range/openstack.py
- /Users/nekonic/Documents/GitHub/fsl-project-mvp/.claude/worktrees/cloud-vm-status-report-45aefd/platform/range/declaration.yaml
- /Users/nekonic/Documents/GitHub/fsl-project-mvp/.claude/worktrees/cloud-vm-status-report-45aefd/platform/range/wargame_host.py
- /Users/nekonic/Documents/GitHub/fsl-project-mvp/.claude/worktrees/cloud-vm-status-report-45aefd/platform/vm-terminal.sh
- /Users/nekonic/Documents/GitHub/fsl-project-mvp/.claude/worktrees/cloud-vm-status-report-45aefd/deploy/wargame-host/setup.sh