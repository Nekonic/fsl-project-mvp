# Where the range's parts sit on OpenStack

2026-09-30. Research, not a decision: three questions the user asked to have
compared before choosing. Every claim below was fetched and checked against
its source by a second agent; claims it could not confirm are marked or left
out.

## The architecture this assumes (the user's, 2026-09-30)

One Ubuntu 24.04 VM runs the platform with `docker compose up`: the website,
Elasticsearch, scoring. From that VM the platform calls the OpenStack API to
create the VMs a training session needs. The cloud is kolla-ansible, one KVM
compute node (8 vCPU, 64 GB), ML2/Open vSwitch, and the range runs as the
member-role user `fsl-range` (see `docs/STATE.md`, the substrate seam).

## 1. Where IPS/IDS (WAF + Suricata) runs

| Option | Verdict | Why |
|---|---|---|
| (a) Gateway VM created per slot, nginx+ModSecurity+Suricata inline, the only path from the origins to the estate | **Recommended** | Today's compose invariant on Nova. The only option that can block (the response pillar). KYPO does exactly this on OpenStack. |
| (b) WAF+Suricata in Docker on the platform VM, which routes between attacker and target networks | Reject | Puts the scorer on every attacker network and in the blue team's kernel; Docker publishes on all addresses and drops FORWARD by default. |
| (c) Host-based on each target VM | Weak | Evidence that feeds scoring would sit on the host the red team is trying to own; one sensor per host. At most a later host-log layer. |
| (d) Separate sensor VM fed by Tap-as-a-Service mirroring | Phase 2 on top of (a) | Cannot block. Its value is an organiser-owned sensor the blue team cannot stop. networking-sfc: skip (cannot chain a TCP-terminating WAF; Heat has no resources for it). |

Mechanics that make (a) work without admin rights:

- **No Neutron router on the range networks.** Neutron SNATs only traffic
  leaving through a router's external gateway, and turning `enable_snat` off
  is admin-only by default. With no router, the Moscow/Sao Paulo/Hong Kong/
  North Korea source addresses survive. Each origin subnet's and the estate's
  `gateway_ip` is set to the gateway VM's port. KYPO's generated Terraform
  creates no Neutron router and does exactly this.
- **Forwarding ports.** Either keep port security with a dedicated security
  group and `allowed_address_pairs` `0.0.0.0/0` (KYPO's pattern), or
  `port_security_enabled=false` (no security groups at all). Both are allowed
  to a member who owns the network. Keep the group dedicated: a `0.0.0.0/0`
  pair weakens remote-group rules for every port sharing the group.
- **IDS now, IPS later.** Suricata AF_PACKET IDS on the gateway; for blocking,
  NFQUEUE on FORWARD (plus INPUT for the nginx listener) with drop rules, and
  ModSecurity `SecRuleEngine On` instead of `DetectionOnly`. In IPS mode
  Suricata passes everything by default and blocks only on drop/reject rules,
  so one rule set can detect now and block later.
- **Reset.** Nova rebuild reinstalls from the image and keeps the server id,
  flavour and IP addresses, so a gateway the blue team broke is reset without
  rewiring.
- **TaaS** (phase 2): kolla-ansible has `enable_neutron_taas` since 18.0.0
  (2024.1); a researcher's claim that it arrived later was contradicted. The
  project is maintained but low-activity, and a 2023 report had taps stuck
  DOWN, so it needs a smoke test on this cloud.

Sources: CyberRangeCZ topology definition and Terraform template
(github.com/cyberrangecz/docs, .../backend-openstack-lib), CyRIS `dmz.yml`,
Suricata docs (ips/setting-up-ipsinline-for-linux, ips/ips-concept),
ModSecurity v3 reference manual, Neutron docs (deploy-ovs-selfservice,
configuration/policy, ml2-ovs-portsecurity spec, neutron-lib api-ref), Heat
template guide, Nova server concepts, Vykopal et al. ICSOFT 2017 (KYPO),
CCDCOE Frankenstack 2017, Security Onion docs.

## 2. Where the attacker (Kali) lives

| Option | Verdict | Why |
|---|---|---|
| (a) One Kali VM per origin segment (four) | If two origins must attack at once, or several red-team members each hold a country | Matches the adapter today (a tool runs on "the attacker on that segment"). Four VMs, terminals and role bindings. |
| (b) One Kali VM with a port on every origin network | **Decided** | Same source fidelity as (a) at a quarter of the VMs, one terminal; compose's proxy is already multi-homed this way. Needs an adapter change. |
| (c) Kali container on the platform VM, routed into the range | Reject on OpenStack | Shares a kernel and the root Docker daemon with the red team; undoes the platform's range-address refusal. Keep only on the Docker substrate. |

For (b): one Neutron port per origin with a pinned fixed IP in that
country's subnet (passes anti-spoofing with no address pairs), plus a
management port. Map NICs by MAC or device tag, never by order: the compute
API does not guarantee guest order. Not a VLAN trunk: trunks are
incompatible with `iptables_hybrid`, kolla's default firewall driver. The
destination still picks the source: the WAF holds an address on each origin,
so the connected route selects the matching port. The stamping proxy moves
onto the attacker VM. Access is ttyd (already in the image) reverse-proxied by
the platform, with the Nova console as fallback. Sizing: Kali's GenericCloud
image (no GUI), 512 MB minimum, 2 GB with tools; Nova's RAM ratio is 1.0, so
memory is a hard cap.

How real ranges do it: KYPO/CyberRangeCZ puts a Kali VM inside each sandbox,
reached through a management access node or Guacamole. Locked Shields 2013 ran
the red team's Kali VMs on the exercise's own cluster. Hack The Box Pwnbox and
the TryHackMe AttackBox are per-user cloud VMs on the lab network. NIST's
cyber range guide describes aligning a virtual Internet's addresses with real
geo-IP ranges, which is what the origin subnets do.

## 3. When training VMs are created and deleted

| Option | Verdict | Why |
|---|---|---|
| (a) Per session: create at Start, delete at Stop | Not the default | Cleanest, but Start waits for boot and cloud-init (minutes, unmeasured here); a failed Stop leaks fixed-IP ports; the member cannot raise the 10-instance quota. Keep for concurrent sessions later. |
| (b) Pre-built slot reset between sessions by Nova rebuild | **Session boundary** | Rebuild keeps server ids, ports and fixed IPs, stays on the same host, and wipes every disk change without listing it. Not shown to be faster than create; measure. |
| (b') Reset inside the guests (restart Juice Shop, reload rules) | In-session only | Fastest, but relies on remembering every piece of state (rule files, `SecRuleEngine`, continue-code cookies). |
| (c) Operator-triggered from the console | **Owns the slow parts** | Networks, GeoIP subnets, security group, keypair, images, later TaaS. `bin/openstack-range up` is this layer already. Alone it fails scoring: the next session inherits solved flags. |

Recommended shape, layered:

1. **Fabric**, created and destroyed only by an operator action (REST first,
   then a button): the six tagged networks, security group, keypair, images.
   Start and Stop never touch it: addresses bin the alerts.
2. **Slot**: one Heat stack with the range VMs and their fixed-IP ports,
   built and test-run by an operator "Provision" action. Send
   `disable_rollback=false` and `timeout_mins` explicitly. Find roles through
   the stack's resource list, not Nova names (which are not unique).
3. **Session**: Start takes a READY slot and creates nothing. Stop rebuilds
   every VM either side can change. The slot is READY only after the range
   answers for itself: nothing solved in Juice Shop, rules and
   `SecRuleEngine` at baseline, clocks in sync, a canary alert in
   Elasticsearch.
4. **Failure**: if a rebuild or check fails, delete the stack and recreate it.
   Delete stacks, not servers: a server delete leaves self-created ports.

How real ranges do it: KYPO builds a sandbox pool before class, sized to
students plus spares, hands one out per access token, and destroys used
sandboxes separately; it has no in-place reset. CyTrONE/CyRIS builds per
session (under 10 min for 100 one-VM ranges on a 30-host testbed). Locked
Shields 2012 reverted blue VMs to snapshots before the exercise. NTNU's
teaching cloud reinstalls a lab by deleting and recreating its Heat stack.
OWASP MultiJuicer re-applies challenge progress after restarts. A Rapifuzz
case study on OpenStack uses Heat plus Glance snapshot rollback.

## What Neutron can and cannot keep honest

The question behind "blue team root on the gateway": if the blue team has a
root shell on the gateway VM, can Neutron keep the score trustworthy? Checked
against the stable/2026.1 sources of tap-as-a-service, kolla-ansible and
ModSecurity.

What Tap-as-a-Service gives:

- The copy is made by OpenFlow rules on the compute host's `br-int`, which
  forward the original frame and send a copy to the tap service's port. There
  is no guest component, so root inside the gateway cannot turn it off.
- A tap flow is `IN`, `OUT` or `BOTH`. A project member may create tap
  services and flows, but only on ports the project owns.
- So an organiser-owned sensor VM can run Suricata on the copy. It can run the
  blue team's submitted rules, so what is scored is still the blue team's
  detection, while the evidence is the organiser's. With both sides of the
  gateway tapped, it also sees whether a request was forwarded to the target,
  that is, whether it was blocked.

What it does not give:

- **ModSecurity's verdicts.** libmodsecurity evaluates HTTP transactions
  handed to it by a connector in the request path (the nginx module); its API
  takes a URI, headers and bodies, and it has no packet, pcap or passive
  input. A packet copy cannot be fed to it without building a component that
  reassembles HTTP from TCP, and none exists in the official repositories.
  nginx's `mirror` module copies requests only, ignores responses, and runs on
  the gateway itself. So which WAF rule fired, and its anomaly score, exist
  only in the gateway's audit log, which a blue root can delete or forge.
- **Why something was blocked.** The copy shows the effect (a request that
  came in and was not forwarded, or a 403), not whether Suricata, ModSecurity
  or an iptables rule did it.
- **Blind spots of the OVS driver.** `OUT` copies everything the guest sends.
  `IN` matches only frames addressed to the port's own MAC, and broadcast and
  multicast ingress are not copied. With port security off on the gateway's
  ports, a guest using another MAC receives frames the `IN` mirror misses.
  Mirroring the gateway therefore needs `BOTH` and port security kept on,
  which settles the port setting of section 1 in favour of the
  allowed-address-pairs pattern. TaaS also requires the ML2 `port_security`
  extension.
- **Traffic that crosses no tapped port.** The SSRF from Juice Shop to the
  wiki stays inside the estate and never passes the gateway, so it needs taps
  on those ports as well. Traffic on a VM's loopback never reaches Open
  vSwitch at all.
- **Stopping sabotage.** Neutron observes; it cannot stop a blue root from
  shutting the gateway down or dropping everything. That is recorded, and
  scored as availability (benign traffic blocked), which is the right place
  for it.

On this cloud TaaS is off. kolla-ansible 2026.1 has `enable_neutron_taas`
(default false; the sample `globals.yml` does not list it), deploying the OVS
driver into `neutron-server` and `neutron-openvswitch-agent`; enabling it is a
`globals.yml` edit plus `kolla-ansible reconfigure` on the host.

Sources: opendev.org tap-as-a-service stable/2026.1 (`ovs_taas.py`,
`policies/tap_flow.py`, `policies/tap_service.py`, `taas_plugin.py`,
`INSTALL.rst`), the Mitaka TaaS spec and `API_REFERENCE.rst`; kolla-ansible
stable/2026.1 (`group_vars/all/neutron.yml`, `roles/neutron`,
`operating-kolla.rst`) and the Gazpacho releases deliverable; ModSecurity v3
README and `headers/modsecurity/transaction.h`, ModSecurity-nginx, nginx
`ngx_http_mirror_module`.

## Decided (the user, 2026-09-30)

- **Platform VM**: an Ubuntu 24.04 VM inside this cloud, brought up by
  `docker compose up` from cloud-init.
- **pfSense CE** goes in as the edge firewall (section above).
- **No Korean or commercial WAF.**

- **Attacker**: option (b), one Kali VM with a port on every origin network.
- **Addresses**: 30 origin countries, taken in order of Internet traffic, about
  100 addresses in all, with more to the countries that carry more traffic, so
  a blocked attacker can move to another (see "Thirty origins" below).
- **Golden images**: a setup script kept in the repo builds each VM once, and
  a snapshot of it is the image; a snapshot alone would lose how it was made.
- **Cloud**: kolla-ansible 2026.1. Tap-as-a-Service is now on (see STATE for
  the kolla bug it hit).
- **IPS/IDS**: option (a), the gateway VM.
- **Lifecycle**: the layered shape above, as a first try that may change.
  Stop resets the slot at once rather than keeping it for review.
- **The blue team configures the WAF through its web console**, not a shell;
  the console opens in its own tab first, and an iframe only if nothing else
  serves. The tutorial is designed later.

## Thirty origins

**The ranking.** Cloudflare Radar is the one source that measures traffic
rather than people: its API `GET /radar/http/top/locations` ranks locations
by share of HTTP requests over up to 52 weeks, can keep only
`botClass=LIKELY_HUMAN` (which drops data-centre bot traffic that inflates
the US, NL, SG, IE and HK), and is CC BY-NC 4.0 behind a free API token with
Radar read access. Its public charts sit behind a bot check, so no Radar
number was verified here and none is frozen into the range; the numbers come
from the API with the token, saved with their date range. APNIC's per-AS
population (verified) counts users, not traffic, and would put China first;
it is the right source for picking each country's real prefixes (its largest
networks), so GeoIP places each address where intended. The NC clause needs a
look if the list moves to the production repo.

**The OpenStack shape.** One Neutron network with 30 subnets, one per
country, not 30 networks:

- The attacker has one port whose `fixed_ips` hold every attack address
  across the subnets (a port may hold addresses from several subnets of its
  network; the per-port cap was removed in Pike). Fixed IPs pass
  anti-spoofing without address pairs.
- The gateway VM's port on that network holds each subnet's `gateway_ip`.
  Its port toward the target forwards packets with country sources, so that
  port needs the allowed-address-pairs setting of section 1.
- The guest adds the extra addresses itself: Nova's metadata describes one
  IPv4 address per NIC and dnsmasq cannot hand several in one subnet to one
  host. Use `bootcmd` or a baked netplan file (`runcmd` runs once per
  instance, so the addresses would be gone after a reboot); DHCP only on the
  management subnet.
- A tool picks its country by source address: `curl --interface <ip>`,
  `nmap -S <ip> -e <nic> -Pn`. Tools with no source option (sqlmap, hydra)
  need a network namespace per country or the stamping proxy binding the
  source; not settled.
- 30 NICs per VM is not ruled out by a hard limit (libvirt adds PCI bridges
  at boot); it loses on simplicity.

This changes the declaration: today a segment is one network with one subnet
and one origin, and the OpenStack adapter refuses a second subnet. The
Internet becomes one segment whose subnets each carry a country.

## pfSense (checked 2026-09-30)

The user wants pfSense in the range. It was set aside on 2026-09-20 only
because it is FreeBSD and Docker cannot run it; on OpenStack it is a VM.

- **Licence**: pfSense CE is free and Apache-2.0 (2.9.0 on a FreeBSD
  16-CURRENT base, and 2.8.1, are the supported CE releases); the name and
  logo are trademarks, so keep them out of the console and ask before ever
  shipping it as a product. pfSense Plus is a paid subscription and not
  needed.
- **Getting it**: the only installer is the online Netgate Installer, a $0
  checkout with a Netgate Store account; no CE cloud image exists. Build once:
  boot the ISO on a VM with Internet access, install to a volume of at least
  8 GB, turn it into a Glance image with `hw_vif_model=virtio`,
  `hw_disk_bus=virtio`, `os_distro=freebsd`.
- **On KVM**: VirtIO drivers are built in; checksum offload must be off on
  `vtnet` (pfSense tries automatically; host-side offload may matter too).
  Configuration is `config.xml` (GUI restore or console); CE has no official
  API, only the community `pfrest` package.
- **No WAF on pfSense**: no ModSecurity or WAF package, so it does not replace
  the WAF VM. It is the edge firewall and router: origins -> pfSense -> WAF ->
  estate, as NIST SP 800-44 places a web server behind a firewall.
- **Addresses**: pfSense's WAN port takes over the 30 subnets' gateway
  addresses (as IP aliases) and routes to the WAF VM without NAT, so country
  sources survive. Its forwarding ports keep port security on with
  `allowed_address_pairs` (TaaS needs that). Untested: that WAN-to-LAN passes
  un-NATed, that "block private/bogon networks" do not interfere.
- **Logs**: remote syslog, UDP only, to up to three servers; firewall events
  are `filterlog` CSV. Filebeat on the platform VM should receive them rather
  than a new service.
- **Suricata on pfSense** exists as a maintained GUI package (ET Open and
  other free sources; blocking off by default). Inline mode needs netmap,
  which is unreliable on virtio in field reports (`e1000` or `igb` NIC models
  are the fallback); legacy mode blocks offenders through a pf table after
  some packets pass. Its default `HOME_NET` would swallow the 30 origin
  subnets once they are pfSense aliases, so a custom `HOME_NET` and pass list
  are mandatory. EVE can go out by syslog.
- **The open choice**: (A) Suricata on pfSense, the real GUI, with the
  platform only reading its EVE (the platform's rule editor and reload have
  no supported way in); or (B) pfSense for layers 3 and 4 only, Suricata
  staying on the WAF VM under the platform. Running both doubles alerts;
  either way a case counts once.

## Settled since (the user, 2026-09-30)

- Suricata runs as the pfSense package (option A), managed in its GUI; the
  platform reads its EVE output.
- Tap-as-a-Service and the organiser sensor are dropped: they served a blue
  team that might tamper with evidence, which is no longer assumed. Whether a
  request was blocked is read from the target side.
- The blue team reads alerts in Kibana (read-only). The platform UI is a
  sidebar of three in-page panes: pfSense (through a kiosk browser VM's Nova
  noVNC console, since pfSense refuses framing), Kibana (framed directly), and
  a ttyd terminal. Horizon is never shown to users.

- The blue team works through the WAF's own interface, not a shell, so the
  root question falls away.
- An IPS outage is an infrastructure fault, not part of the exercise.
- Stop resets the slot at once.
- Juice Shop's continue-code restore is not pursued; objectives will not
  centre on Juice Shop, and the board's user database becomes one.
- A tool's source address is set as it leaves the attacker VM, so every tool
  gets the chosen country without a source option of its own.

## To test on this cloud before building

- A VM port can hold each origin subnet's `.1` `gateway_ip`, and DHCP hands
  that route to the attacker.
- Neutron's firewall driver and service plugins, whether root disks are
  local (volume-backed rebuild needs microversion 2.93), and whether
  `fsl-range` may create Heat stacks.
- With TaaS enabled, that a tap service reaches ACTIVE (a 2023 report had
  taps stuck DOWN).
- Stack-create-to-ready versus rebuild-to-ready per image.
- Whether a TaaS tap survives a Nova rebuild.
- How the platform VM reaches Kali and the targets over the management network
  without giving the red team a path back (STATE's item 5).
- Quota: 10 instances, 20 cores and 51,200 MB by default; a slot of gateway,
  Kali and three targets is five.
