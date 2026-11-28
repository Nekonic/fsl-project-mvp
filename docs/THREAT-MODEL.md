# Threat model

This file says which attacker the test cases imitate, where that attacker
starts, and what the range cannot show. The surfaces and their protections
are listed in the README's security table; this file explains why they hold
and where they stop.

## The threat

| | |
|---|---|
| **Threat emulated** | An attacker on the public internet with no account, going after two web applications: a community board (`board`) and a WordPress site (`corp`). The attacker takes whatever is exposed. There is no phishing, no insider and no stolen credentials. |
| **Attacker's position** | Outside the network. The attacker sends from the round's Internet origins, drawn from those the range declares (`platform/sandbox/declaration.yaml`); each origin is its own /24 with a declared country, and GeoIP gives the same country. At the start the attacker has no account on the target, no code running on it and no access to the internal network. |
| **Command and control** | None. Attack cases are fired from the attacker box (the round's kali VM, `training/attack/cases.py`); a human attacker works from the same box, through the web terminal, the site pane, or their own PC over the account's WireGuard profile or ssh through the platform's jump host, and that traffic leaves kali under its current origin. Nothing left on the target calls back. |
| **What the attacker is after** | On `board`, the password hashes in `auth_user`. The attacker steals them and submits them as loot. The platform counts them only if they exactly match the snapshot of `auth_user` taken from the target when the round started (`loot_verified`, `scoring/loot.py`). On `corp`, three changes to the WordPress database, listed in `wargames/corp/objectives.yaml`: a new administrator account, self-registration turned on, and content written without permission. The platform finds these in `corp-db`'s own binary log of changes since the round started (`effect_observed`, `scoring/effect.py`). |
| **What the defence has** | Suricata inline between the WAF and the web servers, on a bridge of the slot's infra VM, and ModSecurity with the Core Rule Set (CRS) in front of the application. A request the WAF blocks never reaches Suricata; the WAF's own logs record it: ModSecurity's audit log and nginx's JSON access log of every request (`deploy/roles/waf/sites.conf`). Suricata sees every request coming from the WAF and credits each alert to the client address its `X-Forwarded-For` names. ModSecurity blocks (`SecRuleEngine On`, `deploy/roles/waf/modsecurity.conf`). Both send their alerts to the slot's Elasticsearch index. The defender works through the round's defence API (`/api/rounds/<id>/defence/...`, operationIds `defence_waf_test`, `defence_waf_apply`, `defence_ids_test` and the rest in `openapi/schema.yaml`) and two shells: the `analyst` account on the WAF VM, whose sudo allows only `nginx -t`, `-T`, `-s reload` and `systemctl reload nginx`, and the `analyst` account on the infra VM, whose sudo allows only `suricata -T` and `suricatasc -c reload-rules`. The defender edits the CRS setup and exclusion files, the nginx files under `/etc/nginx/defence/` (`deny`, `limit_req`) and the sensor's rule file. No WAF or IDS change goes live, from the console or the terminal, without a rule test of the same files that passed this round. The defender also reads Kibana (the slot's space), the alert list and the learner map. The defender has nothing else. |

## The stages it reaches

The stages come from Mandiant's targeted attack life cycle, which has eight.
Three of them happen in the range.

| Stage | Cases | ATT&CK | Mechanism (CAPEC) |
|---|---|---|---|
| Initial compromise | the nine `board-sqli-*` cases, both `board-xss-*` cases | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [66 SQL Injection](https://capec.mitre.org/data/definitions/66.html), [63 Cross-Site Scripting (XSS)](https://capec.mitre.org/data/definitions/63.html) |
| Escalate privileges | `corp-rogue-admin` | [T1068 Exploitation for Privilege Escalation](https://attack.mitre.org/techniques/T1068/) | [233 Privilege Escalation](https://capec.mitre.org/data/definitions/233.html) |
| Escalate privileges | `corp-option-flip` | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [1 Accessing Functionality Not Properly Constrained by ACLs](https://capec.mitre.org/data/definitions/1.html) |
| Complete mission | `board-path-traversal-static` | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [126 Path Traversal](https://capec.mitre.org/data/definitions/126.html) |
| Complete mission | `corp-content-write` | [T1565 Data Manipulation](https://attack.mitre.org/techniques/T1565/) | [242 Code Injection](https://capec.mitre.org/data/definitions/242.html) |

Benign cases have no stage. This keeps a false positive from being counted as
part of an attack.

## What it cannot show

**Five of the eight stages never happen.**

- No case scans, so initial reconnaissance is missing. A scan a human runs
  from kali is a free action: recorded, never scored as a case.
- Establish foothold, internal reconnaissance, move laterally and maintain
  presence are missing because no case runs code on the target. The databases
  stand on an internal Docker network inside the target VM, so they can be reached
  only through the application, and the attacker never gets a foothold on the
  operating system.
- Privilege escalation happens inside the application only. The Ultimate Member
  CVE on corp lets an unprivileged registration become a WordPress
  administrator (`corp-rogue-admin`).
- On 2026-09-28 we set an operating-system foothold, operating-system privilege
  escalation and persistence as a later goal (`docs/STATE.md`, Backlog).
  Moving laterally waits until a target gives it somewhere to go.
- Each case names its stage in `cases/<wargame>.yaml` (`attack_stage`).
  Nothing in the platform reads that field today, so the table above is kept
  by hand against the case files.

**The ATT&CK mapping is coarse.** Most exploitation cases map to T1190, the
Enterprise technique for exploiting a public-facing application. ATT&CK does not
tell SQL injection from path traversal. The CAPEC id in each case's `pattern`
field does.

**Only the declared objectives count.** On `board` that is the stolen
`auth_user` hashes. On `corp` it is the three database changes in
`wargames/corp/objectives.yaml`. An attack that achieves anything else scores as
if it achieved nothing.

**Benign traffic is a handful of cases and a modelled population, not real
users.** The customers' program on the infra VM (`deploy/roles/infra/customers.py`,
`sandbox/customers.py`) sends the traffic `wargames/board/traffic.yaml`
describes, and the platform fires the benign cases. One benign case looks like
an attack: a search for `O'Brien` (`board-normal-search-with-apostrophe`).
These catch a rule that fires on everything; they do not estimate a false
positive rate against real users.

## The platform

**The platform API authenticates the caller and checks the seat.** Every
`/api/` endpoint needs a signed-in Django session or, for a bot, a player
token (`Authorization: Bearer`, shown once when the round is created and
stored only as a hash). The terminals, `/kibana/` and port 8002 ask the
platform through nginx's `auth_request`. The first start makes `admin` with
the password `123456`, and nothing makes anyone change it, so the password
stops nobody who knows the default. Anyone who reaches port 8000 can sign
up, but a sign-up makes an inactive account that cannot sign in until staff
approve it (`staff_user_approve`). A signed-in user reaches an allocation
they opened or a round in which they hold a seat (`training/round/auth.py`):
the attack API answers only the attack seat, the defence API only the defence
seat, and any other caller gets 403. Staff operate every allocation and are
the only ones who change the range (`/api/staff/range/` writes) or manage
accounts. One person cannot hold both seats of a pvp round
(`already_playing`).

**Kibana shows a defender their round's logs only.** Elasticsearch and
Kibana run without security and listen only on the platform VM's loopback,
and Kibana's own documentation says spaces are no boundary without it:
"Controlling feature visibility is not a security feature" (Kibana 8.15,
Spaces). Each slot has a space (`soc-logs-N`) whose data view is
`logs-N-*`; N is the slot number (see the glossary in
`docs/ARCHITECTURE.md`). The boundary is the platform's gate in front of
every Kibana API call in a space (`/kibana/s/<space>/api/` and
`/internal/`, which nginx hands to Django's `/kibana-gate/` with the raw
URI; `training/defence/kibana_gate.py`, `sandbox/kibana.py`). The gate
forwards a call only when:

- the space is that of a round, not ended, in which the user holds the
  defence seat (staff: any space);
- the call is on a short list of what Discover asks (capabilities, settings
  read, the space's data view and saved search read, field list, value
  suggestions, `ese` search and its polls and cancels); everything else is
  403, among it `/internal/bsearch`, the `es`, `esql`, `sql` and `eql`
  strategies, Dev Tools' console proxy, saved object and data view writes,
  advanced settings writes and `resolve_index`;
- every index the call names is exactly the slot's pattern (`params.index`
  of a search, `pattern` of the field list, the index in the value
  suggestions path), so a hand-typed `logs-2-*`, `logs-*`, a list, or a
  backing index `.ds-logs-2-...` is refused;
- nothing in the body or query names `index`, `_index`, `indices`,
  `namespace` or `namespaces`, which shuts terms lookup, `more_like_this`
  and cross-space reads.

Request batching is off in the slot spaces (`bfetch:disable`), so each
search arrives as its own request and is checked whole. nginx refuses a
Kibana path with `%`, a backslash or a dot segment before Kibana decodes it,
any case of the default space or of a space inside a space, and the gate's
own path from outside. Limits:

- Staff are held to the same list of calls but may name any index, so a
  staff Discover reads every slot's logs.
- The slot number is reused: a defender whose round runs on slot N sees
  what earlier rounds on slot N left in `logs-N-*`, back to the index's
  retention.
- Kibana's page shell and bundles carry no data and stay open to any
  signed-in user in any space.

**Abuse limits.** nginx answers 429 past 5 sign-in POSTs a minute per address
(burst 5), 1 sign-up POST a minute (burst 3), 20 `/api/` requests a second
per session cookie or bearer token (burst 40) and 100 per address (burst
200), and 10 open connections per session cookie to the terminals and port
8002. Django blocks the client, never the account (`users/blocks.py`): 3
wrong passwords against a staff account within an hour block that address
from signing in for an hour; 10 against any other name block it for 15
minutes. A fingerprint of the headers the browser sends with the sign-in
(User-Agent, Accept, Accept-Language, Accept-Encoding and the `Sec-CH-UA`
hints) is counted the same way and blocked once it has failed from at least
two addresses, so a client that changes address but keeps its browser is
held too. A blocked client is refused even with the right password; staff
list and lift blocks (`staff_blocks`, `staff_block_delete`). Django also
takes 5 sign-ups an hour from one address and stops taking them while 50
wait for approval. Their limits:

- The fingerprint is made of headers the client chooses. A script that
  changes its User-Agent or Accept-Language with each address is held only
  by the per-address count. Browsers send `Sec-CH-UA` only to secure
  origins, and port 8000 has no TLS, so on this platform the hints are
  usually empty. TLS fingerprints such as JA4 need the TLS handshake ("JA4
  looks at the TLS Client Hello packet", FoxIO's JA4 specification), which
  plain HTTP on 8000 does not have.
- Two people with the same browser, version and language share a
  fingerprint: one of them failing against `admin` from two addresses
  blocks the other's sign-in too, until it expires or staff lift it.
- A blocked address is every client behind that address: a classroom behind
  one NAT is blocked together after three failures against `admin`.
- An admin whose own address is blocked signs in from another address or
  from the platform VM, which is never blocked.
- The failure counters live in Django's local-memory cache and reset when
  the platform restarts; blocks are rows in the database and survive it.
- The per-cookie keys trust a cookie the client chooses; a client that sends a
  new cookie each time is held by the per-address limits only.
- Requests from the platform host itself (loopback, the Docker gateway
  `172.31.0.1`, the IP literals in `DJANGO_ALLOWED_HOSTS`) are not limited by
  nginx, so `bin/verify` on the VM is not throttled. Through the floating IP
  the VM reaches itself with that address as the source; anything else that
  reached the platform from it would be spared too.
- Parallel allocation opens get different slots because the slot is chosen
  under an in-process lock (`training/round/allocation.py`). The lock holds
  because one waitress process serves the API; a second process would need
  a database lock.

**The range does not reach the API.** The platform reaches the slot stacks
only over `cr-mgmt`, where every range VM has one control port. The
platform's port there is in `cr-reach`, which admits udp 123 (NTP) from
members of `cr-mgmt` and udp 5140 (syslog) from members of `cr-senders`, the
infra VM's control port, and nothing else; the stacks' LANs have no Neutron
router, so no range VM has another way to the platform. The API holds no per-request refusal of range
addresses; what keeps a range VM from it is the network above. nginx keeps
the session check's answer for `/kibana/` and port 8002 five seconds, keyed
on the session cookie and the client's address, so a cached yes is never
reused for another address. The terminal check (`terminal-auth`) is not
cached, and an open shell is checked again every 15 seconds.

**The target's script does not reach the console.** The target is not
published. Port 8000 is the console. The XSS cases make the target run
script in any browser that loads its pages, and the site pane serves the
target on port 8002 of the same host, so that script runs in the signed-in
browser, one port away from the console. Cookies are kept per host, not per
port, so the console's cookies reach 8002. What keeps the script from the
API:

- The session cookie `cr_session` is HttpOnly, so the script cannot read it.
  The CSRF cookie `cr_csrf` is not HttpOnly, so the script can read it.
- The platform sends no CORS header, so the browser hands the script no answer
  from 8000.
- The API parses only `application/json`, which a page on another origin
  cannot send without a CORS preflight the platform does not answer, and
  Django's CSRF check refuses a write whose `Origin` is not the console's.
- nginx drops the `Cookie` header before it hands a request on 8002 to the
  site proxy and never passes the target's `Set-Cookie` to the browser, and
  the site is served under a sandboxing `Content-Security-Policy`.

**The learner map is a pane of the defence console (`front/src/panes/Map.tsx`).**

- It reads `GET /api/rounds/<id>/topology/` (`round_topology`) and nothing
  else, and draws with cytoscape.js bundled into `front/`. It sends nothing
  to a third party.
- To draw it, the platform reads the slot stack's networks and ports from
  Neutron (tagged `cr.slot=<n>`) and runs `docker network inspect` on the
  target VM over ssh (`sandbox/openstack.py`), parses the wiring
  (`sandbox/wiring.py`) and names it for the learner, filtered by side
  (`sandbox/topology.py`). The map shows nothing outside that stack: no
  platform VM, collector or customers' program. No platform service holds
  the Docker socket.

**On OpenStack the platform answers NTP (time) requests from the range VMs.**

- Each range VM's user data points systemd-timesyncd at the platform's
  `cr-mgmt` address. chrony accepts that subnet (`allow`) and has no
  `cmdallow`, so its command port stays on loopback.
- `cr-reach` admits udp 123 from members of `cr-mgmt` (every range VM's
  control port) and udp 5140 only from `cr-senders` (the infra VM's).

**Each allocation's range is one Heat stack of four VMs.** `sandbox/openstack.py`
renders it (`sandbox/stack_plan.py`) from `wargames/<wargame>/topology.yaml`:
kali, waf, infra and target, on five Neutron networks of the stack's own
(`internet`, `dmz`, `web-outer`, `web-inner`, `mgmt`). The attack seat holds
a root shell on kali (`kali` with passwordless sudo, through the web
terminal or ssh through the platform's jump host). The defence seat holds
the `analyst` account on the WAF and on the infra VM, not root. No learner
has a shell on the target. Isolation is Neutron's, enforced outside the
guest, so root on kali cannot change it:

- No stack network has a Neutron router or a floating IP; the stack's only
  way between its LANs is the infra VM.
- Every port has port security on, so it sends only from the MAC and the
  fixed IP Neutron gave it, except:
  - Kali's `internet` port carries the allowed address pair `0.0.0.0/0`, so
    it can send from the origin addresses `slot-boot` adds; port security
    still binds its MAC.
  - The infra's `dmz` port carries the same pair, because the edge forwards
    packets from kali's origin addresses to the WAF.
  - The infra's two IDS legs on `web-outer` and `web-inner` have port
    security off, so the Linux bridge between them can forward the WAF's and
    the target's frames. `analyst` on the infra cannot change the bridge or
    the edge.
- Each LAN's ports are in a security group that admits the LAN's own CIDRs,
  or `0.0.0.0/0` where a port on it carries an address pair (`internet`,
  `dmz`). The stack's `mgmt` admits only tcp 514, the WAF's logs to the log
  server. Every stack shares these groups (`cr-lan-<digest>`, one per rule
  set, three in all); their rules name CIDRs, not groups, and each stack's
  LANs are networks of its own, so sharing a group opens nothing between
  stacks.
- Every control port is in `cr-mgmt`, which admits only `cr-reach`, the
  platform. Kali reaches no other stack's VM and no service on `cr-mgmt`.
- `cr-mgmt` and `cr-senders` send only to `cr-reach` and to DHCP (udp 67);
  the fabric deletes the allow-all egress Neutron gives a new group, on
  groups already standing too (`sandbox/fabric.py`, `CONFINED_GROUPS`). DHCP
  on `cr-mgmt` hands out a route to 169.254.169.254 through the OVN metadata
  port, and that egress rule drops it, so no range VM reaches the metadata
  service. The VMs boot from a config drive and do not need it.
- The edge on the infra VM (nftables, `deploy/roles/infra/edge.nft`) forwards
  tcp 80 on 121.134.88.42 to the WAF's `dmz` address and lets in from `wan`
  only replies and that forward, so kali reaches the targets only through the
  WAF. A spent origin is dropped there, in the `spent` set only
  `sandbox/edge.py` writes, which root on kali cannot touch.
- The WAF sends to the log server from its own address only (port security),
  and the log server relays a sender's lines only under the tags the WAF's
  logs carry (`modsecurity` and `nginx`), so the WAF cannot pass a line off as
  Suricata's.
- The target runs the wargame under Docker: every container drops all
  capabilities and runs with `no-new-privileges`
  (`deploy/roles/target/wargames.yaml`); the database is on an internal
  Docker network inside the VM.
- The platform's reads of the boxes run on the VMs over ssh: kali's
  `/var/log/commands.log` (`sandbox/attacker.py`), and the loot and effect
  reads through `docker exec` on the target (`scoring/loot.py`,
  `scoring/effect.py`).
- A closed allocation's slot is refilled: the stack is deleted and created
  again (`sandbox/refill.py`, the `refill` service), so nothing a learner
  wrote on kali or the WAF reaches the next allocation.
- The platform holds the ssh key of the management user on every range VM
  (passwordless sudo): whoever takes the platform container is root on every
  range VM.

What is tested:

- `platform/tests/seams/test_openstack_template.py` fails `bin/verify` when
  the rendered stack breaks a rule above: a router or a floating IP in a
  stack, port security off on any port but the two IDS legs, kali on a
  network other than `internet` and `cr-mgmt`, the WAF or the target with a
  way out but through the router, the web leg reaching the targets other than
  across the IDS bridge, the stack's `mgmt` admitting more than the WAF's
  logs, a control port off `cr-mgmt` or a range VM other than the infra in
  `cr-senders`. `platform/tests/seams/test_openstack_networks.py` checks that
  the fabric confines the egress of `cr-mgmt` and `cr-senders`.
- `test/test_range_isolation.py` checks a live stack from kali, the WAF and the
  board: none reaches the platform, the Internet or the metadata service;
  kali reaches `board.com` (the router's public address) and neither target
  past it, nor the WAF's private address (a SYN scan, which runs as root,
  reads it filtered); ping and traceroute to 121.134.88.42 answer; kali finds
  no open service port on the control network of its own or any other slot;
  a frame from a MAC Neutron did not give kali's port does not reach the
  router. Its last test writes a file on the WAF, closes the allocation and
  checks that the refilled slot's WAF is a new VM (another boot id) without
  the file.

**Accounts are staff or learner.** Staff (`admin` and any account made staff
in Django) manage accounts, change the range and operate every allocation; a
learner reaches only the allocations they opened and the rounds they hold a
seat in. Nothing stops two browser windows of one account from driving the
same seat.

**A closed allocation's rounds last an hour; their records last 90 days.**

- The platform deletes an allocation closed more than
  `CR_RETAIN_CLOSED_MINUTES` ago (default 60), with its rounds and their
  events (`training/round/retention.py`). It does this when an allocation
  opens and in `manage.py prune`.
- Before it deletes them, each round that started is kept as a record
  (`training/round/records.py`) for `CR_RETAIN_RECORDS_DAYS` (default 90):
  with its score and players, readable through `records_list` and
  `record_read`.
- The alerts stay in Elasticsearch.

**The attacker's actions are only partly recorded.**

- Kali's web proxy (`deploy/roles/kali/web-proxy.py`) stamps a marker on each
  site-pane and learner HTTP request.
- Commands typed in the kali shell are logged in `/var/log/commands.log` and
  read into the round's events (`sandbox/attacker.py`).
- A request in the WAF access log from one of the round's attacker origins
  that no marker names is reported as a free action, never scored as a case.
- Traffic that does not pass the WAF, such as an `nmap` scan of it, never
  reaches Suricata behind the WAF.
