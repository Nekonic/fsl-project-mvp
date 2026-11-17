# The range as one Heat stack per slot (KYPO-style): design and gate-1 plan

Gate 1, waiting for approval; the user's rulings of 2026-11-18. Replaces the container range of
`2026-11-13-container-range-design.md` (one range-host VM, slot = compose project `sN`).
**[unverified]** marks what is not measured on this cloud; P0 checks what the design rests on.

## 1. Direction (user rulings, 2026-11-18)

- The range moves back onto OpenStack, built the way KYPO builds it. Vykopal et al., "KYPO Cyber
  Range: Design and Use Cases", ICSOFT 2017: a sandbox is an isolated virtual network built by a
  sandbox management component through one infrastructure driver; a LAN Management Node (Debian,
  Open vSwitch learning switch, Linux routing) carries each sandbox's LANs; monitoring is built in
  (flow and full packet capture). In today's KYPO CRP the OpenStack driver turns the sandbox's
  topology definition into a Heat Orchestration Template, and pools of sandboxes are allocated
  ahead of trainees (https://docs.crp.kypo.muni.cz/user-guide-advanced/sandboxes/topology-instance/,
  read through a search summary; the site did not resolve at writing time).
- **One slot = one Heat stack** `cr-slot-<n>`. Slots are pre-allocated in a pool, so a reset
  (delete the used stack, create a fresh one) is off the learner's path. How many slots run at once
  is the cloud's capacity, never a limit in the design.
- **Neutron/Heat do everything a project member can do**, to cut code.
- **Only what a member cannot do stays in a guest**, on one `infra` VM per slot that no learner
  gets a shell on (the KYPO LMN role).

## 2. A slot

LANs, one Neutron network each, per slot, no Neutron router on any of them:

| LAN | Members | Note |
|---|---|---|
| `internet` | Kali, infra `wan` 121.134.88.42/29 | the fake internet; the 30 origin /24s of `platform/range/declaration.yaml` |
| `dmz` | infra `lan` .1, WAF front .247 | |
| `web-outer` | WAF back, infra IDS leg A | IDS leg: port security off |
| `web-inner` | board .59, corp .60 (target VM), infra IDS leg B | IDS leg: port security off |
| `mgmt` (slot) | infra log server, WAF mgmt | the monitoring LAN the learner map draws |

Every slot uses the same addresses, as the origins already do; slots differ by network, not CIDR,
so `rangehost.py`'s per-slot `10.30.N.0/24` and `10.30.N+128.0/24` arithmetic goes. Each slot VM also has one control port on the shared `cr-mgmt`
(10.31.0.0/24, `platform/range/fabric.py`), whose security group admits tcp/22 from the platform's
group only and lets out only syslog and NTP to the platform; this is how the platform's runner and
the web terminals reach a slot. The map draws that port as the management link.

What Neutron/Heat do (Heat resource types: https://docs.openstack.org/heat/latest/template_guide/openstack.html):

- **Addresses.** Fixed IPs on `OS::Neutron::Port`, subnets with DHCP off, `config_drive: true`;
  Nova writes `network_data.json` ("contains information retrieved from neutron",
  https://docs.openstack.org/nova/latest/user/metadata.html) and cloud-init configures the NICs.
  No netplan, `nsenter` or `ip -batch` rendering for the LANs.
- **Isolation.** Security groups and port security, enforced by OVN outside the guest. A root shell
  in Kali or the WAF cannot change them.
- **Kali's sources.** The origin /24s as `allowed_address_pairs` on Kali's one `internet` port,
  instead of about 100 fixed IPs. Neutron's default policy lets the network owner set both this and
  `port_security_enabled` (`role:member and rule:network_owner`,
  https://docs.openstack.org/neutron/latest/configuration/policy.html). **Limit:**
  `max_allowed_address_pair` defaults to 10
  (https://docs.openstack.org/neutron/latest/configuration/neutron.html); 30 pairs need the admin
  to raise it. Fallback without admin: one pair `0.0.0.0/0`, which changes nothing outside the slot
  because the slot's `internet` has no router. The ~100 addresses and Kali's default route onlink
  to 121.134.88.42 stay a boot step of the Kali role, read from the declaration.
- **Ordering and cleanup.** Heat creates in order and deletes the whole stack; `plan_leftovers`/`clean_leftovers` go.
- **The map.** Networks and ports are tagged `cr.slot=<n>`; the learner map is read from Neutron
  and Nova (the stack's resource list as fallback) **[unverified: `tags` on `OS::Neutron::Port`]**.

What stays in the `infra` guest, and why a member cannot have it from Neutron:

- **Edge NAT.** 121.134.88.42/29 on `wan`, tcp 80 DNAT to the WAF's DMZ address, only replies and
  DNAT'd connections in from `wan` (today's `rangehost.edge_rules`, over `deploy/edge/edge.nft`). Floating-IP port forwarding is open to members
  (`create_floatingip_port_forwarding`: `role:member and rule:ext_parent_owner`), but a floating
  IP lives on an external network, and creating one (`create_network:router:external`) is
  `rule:admin_only`; a fake internet per slot with the same 121.134.88.42 cannot be one.
  The router answers ICMP and decrements TTL, so ping and traceroute from Kali work.
- **IDS.** A Linux bridge between the `web-outer` and `web-inner` legs, port security off on both,
  Suricata on the bridge with af-packet. OVN's mirroring (Neutron TaaS `tap_mirror`) is admin-only
  (user's reading; the TaaS policy is not in the Neutron policy reference). Unlike today's
  `tc mirred` SPAN on `sN-web` (`deploy/range-host/slot.sh` `spanned`), the sensor is inline:
  F3's view (WAF to targets, with X-Forwarded-For) is unchanged.
- **Log server.** rsyslog: the WAF ships its audit and refused logs over the slot `mgmt`; the infra
  forwards those and Suricata's EVE to the platform collector (udp 5140 over `cr-mgmt`). The sender
  hostname keeps the slot number, so `deploy/filebeat/filebeat.yml`'s `-(\d+)` regex is unchanged.

Slot VMs (images in §5):

| VM | Image | Learner |
|---|---|---|
| `kali` | Kali Generic Cloud (amd64, `.tar.xz`), baked with `kali-linux-headless` | root; ssh (§4) and web terminal |
| `waf` | Ubuntu 24.04 + nginx 1.24 + ModSecurity 3.0.16 + CRS 4.25.1 | root, web terminal |
| `infra` | Ubuntu 24.04 + nftables + Suricata + rsyslog | none |
| `target` | Ubuntu 24.04 + Docker, the wargame's `compose.yaml` (board+DB or corp+DB) | none |

Kali's Generic Cloud image is for "most" cloud providers, and Kali says "if you are self-hosting
OpenStack, this is a great way of getting Kali loaded up!"
(https://www.kali.org/blog/kali-linux-2022-4-release/). It ships as
`kali-linux-<ver>-cloud-genericcloud-amd64.tar.xz` (https://www.kali.org/get-kali/#kali-cloud);
**[unverified]** what the archive holds and the conversion to a Glance image. Image size does not
matter (user); Metasploit lessons later need the full headless set. Windows/AD joins a LAN later as
another VM (`os: windows`, cloudbase-init + OpenSSH); not built now.

## 3. Module map

All paths below exist today unless marked new. `platform/` is the working directory.

| Change | Path | What |
|---|---|---|
| new | `wargames/{board,corp}/topology.yaml` | the slot's LANs, VMs, images, fixed IPs, which ports are IDS legs |
| new | `range/sandbox.py` | topology + declaration → a cloud-neutral sandbox plan (networks, ports, groups, servers) |
| new | `range/pool.py` | pool states (BUILDING, READY, HELD, DELETING, FAILED), allocate, release, refill |
| new | `range/wiring.py` | neutral port records → the `Wiring` the learner map draws (replaces `range/interfaces.py`) |
| new | `deploy/roles/{kali,waf,infra,target}/` | per-role bake script and boot files; Kali takes `deploy/kali/{bashrc,operator-log.sh,set-origin}` and `deploy/proxy/stamp.py`; WAF takes `deploy/waf/{board.com.conf,modsecurity.conf}` |
| rewritten | `range/openstack.py` | Keystone, Heat (HOT rendering from the plan, stack create/delete/status), Nova, Neutron, Glance over `requests`; ssh runner to each slot VM. The only OpenStack file |
| rewritten | `range/fabric.py` | the shared part only: `cr-mgmt`, the security groups, the keypair |
| rewritten | `range/declared.py` | roles → slot VMs (`attacker`/`proxy`→kali, `gateway`→waf, `sensor`/`edge`/`log-server`→infra, wargame roles→target); reads `topology.yaml` |
| rewritten | `api/reset.py` | → pool: close releases the slot; open takes a READY one |
| rewritten | `topology.py` | names the wiring from `range/wiring.py`; drops `range.slot.NAMED_ON` |
| rewritten | `vm-terminal.sh` | ssh to the slot VM's control address, no `docker exec` |
| deleted | `range/rangehost.py`, `range/interfaces.py`, `range/slot.py` | slot rendering, `ip`/`docker inspect` parsing, port planning |
| deleted | `deploy/range-host/` (incl. `proto/`), `deploy/edge/`, `deploy/kali/Dockerfile`, `deploy/waf/Dockerfile` | and the `kali`, `waf`, `edge` entries of `.github/workflows/images.yml` |

Unchanged seams: `ingest/elastic.py`, `kibana.py`, `rules/suricata.py` (handed the infra's rule path
and `suricatasc -c reload-rules`), `rules/crs.py` (WAF exclusion file and `nginx -t && nginx -s
reload`, which F6's text keeps), `attacker.py`, `api/loot.py`, `api/effect.py`, `range/ports.py`.
The `rangehost.py`/`slot.sh`/`slot.yaml` exceptions in `CLAUDE.md` go; the seam test in
`tests/test_isolation_seams.py` names `openstack.py` as the only OpenStack file.

## 4. Learner ssh to Kali (proposed; open to the user)

- The platform VM's existing floating IP is the ssh jump (OpenSSH `ProxyJump`). The jump is an
  sshd started by `entrypoint.sh` inside the platform container, beside ttyd, on its own port; no new
  compose service. Its keys come from the platform (`AuthorizedKeysCommand`) as
  `restrict,port-forwarding,permitopen="<that slot's Kali control address>:22"`, no shell.
- The console issues a per-session key (REST: `POST /api/sessions/<id>/ssh/`, shown once) or a
  password; the same public key goes into Kali's `kali` user when the slot is allocated, and both
  are dropped when it is released.
- Kali's security group admits tcp/22 only from the platform's group. No extra floating IPs. The
  web terminal stays.
- Alternative: a floating IP per Kali. Rejected: it needs a Neutron router from the slot to the
  provider network, which gives the fake internet a real way out; the pool (192.168.2.200-250)
  would cap the slot count; each Kali would sit on the provider network.

## 5. Images

`deploy/roles/<role>/setup.sh` runs once per image on a builder VM with egress (today's
`cr-egress` group), then a Nova snapshot becomes `cr-<role>-<digest of the role dir>` in Glance.
Slots boot from those images with no egress; the target image holds the wargame images
(`docker load`), so a fresh stack is the pristine state and `pristine.sh`/`restore` go. Kali's base
is the Generic Cloud image converted and uploaded once **[unverified: format, boot time]**.

## 6. Invariants and the ratchet

- Two scores; target ground truth (loot and effect read the target VM through `docker exec` as
  now); benign cases in `redteam/cases/` stay; TP > 0 and TN > 0; REST API first; Korean-only
  product.
- `core_loc` 604, `dependencies` 6, `services` 4 must not rise: Heat through `requests` (already a
  dependency), no SDK at runtime, no Ansible; the jump sshd runs in the platform container.

## 7. Tests

Unit and API tests with fakes while working; no rebuild, replace, full `bin/verify` or walk per change.

- **New fakes.** `tests/fakecloud.py`: one HTTP server for Keystone, Heat, Nova, Neutron, Glance,
  grown from the handler in `tests/test_openstack_http.py`; a stack create applies the HOT to
  in-memory networks/ports/servers and walks `CREATE_IN_PROGRESS` → `CREATE_COMPLETE` (or
  `CREATE_FAILED` on demand). A recording ssh runner: keeps argv, answers scripted output.
- **Kept.** Scoring, ingest, rules, harness, lesson, console, Kibana, API tests; `test_range_seam.py`, `test_openstack_http.py`, `test_openstack_connect.py` (plus the Heat
  endpoint); `test_api_slots.py` against the fake pool; the board/corp/platform image checks of
  `test_prebuilt_images.py`.
- **Replaced.** `test_range_host.py` → `test_sandbox.py` (plan) and `test_hot.py` (rendered HOT);
  `test_live_map.py` → `test_wiring.py`; `test_range_reset.py` → `test_pool.py`;
  `test_containment.py` → isolation read from the rendered HOT (no router on a slot network; port
  security off only on the two IDS legs; Kali's groups); `test_openstack_fabric.py`,
  `test_openstack_ssh.py`, `test_vm_terminal.py`, `test_attacker_snat.py`, `test_one_sensor.py`
  retargeted to VMs; the kali/waf/edge parts of `test_prebuilt_images.py` → role image tests.
  Each deletion is justified in its commit.

## 8. Phases

| | Phase | Done when |
|---|---|---|
| P0 | Probe: one ~20-minute throwaway Heat stack, deleted after | (1) OVN delivers unknown-destination frames to a port-security-off port, so the IDS bridge passes WAF↔board; (2) a member disables port security and sets `allowed_address_pairs` (and the pair limit); (3) Kali Generic Cloud import works, boot time measured; (4) static `network_data.json` from DHCP-off subnets configures the NICs |
| P1 | `topology.yaml` + `range/sandbox.py` | plans for board and corp pass `test_sandbox.py` |
| P2 | HOT rendering in `openstack.py` | rendered stacks pass `test_hot.py` and the isolation tests |
| P3 | Heat adapter + `range/pool.py`; delete the old range code | sessions open, close and refill against `fakecloud.py` |
| P4 | Learner map from Neutron/Nova (`range/wiring.py`, `topology.py`) | `test_wiring.py`, map API tests |
| P5 | Role images (`deploy/roles/`) | bake scripts tested with the recording runner |
| P6 | Kali ssh access (§4) | jump and key issue tested; console strings Korean |
| P7 | Docs: `CLAUDE.md` seams, `README.md`, `docs/ARCHITECTURE.md`, `docs/OPENSTACK.md`, `deploy/openstack/network.yaml`, `docs/DECISIONS.md`, `docs/STATE.md` | docs review finds nothing out of step |
| P8 | One live run: bake, pool up, full `bin/verify` with acceptance, a walk | then gate 2 |

## 9. Open decisions (user)

1. **Pool size**: the project quota and com01's free memory set how many slots stand ready; the
   flavors come from the existing list in `cloud.yaml` (no new flavor).
2. **Kali ssh mechanism**: §4 as proposed, or another.

## 10. Unverified

- OVN unknown-destination delivery to the IDS legs (P0-1); member port-security and pair limit
  (P0-2); Kali image format, conversion and boot time (P0-3); static `network_data.json` (P0-4).
- That the platform's OpenStack user may create Heat stacks (the platform stack is created by
  `bin/platform-rebuild` with the `cloud.yaml` identity; check the platform's own credentials).
- `tags` on `OS::Neutron::Port`; stack create and delete time, so the pool refill time; RAM per
  slot of four VMs.
