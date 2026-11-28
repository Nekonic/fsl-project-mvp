# Threat model

This file says which attacker the test cases imitate, where that attacker
starts, and what the range cannot show.

## The threat

| | |
|---|---|
| **Threat emulated** | An attacker on the public internet with no account, going after two web applications: a community board (`board`) and a WordPress site (`corp`). The attacker takes whatever is exposed. There is no phishing, no insider and no stolen credentials. |
| **Attacker's position** | Outside the network. The attacker sends from one of the Internet origins the range builds (thirty, one /24 each). Each origin has its own address range and a declared country, and GeoIP gives the same country. At the start the attacker has no account on the target, no code running on it and no access to the internal network. |
| **Command and control** | None. The attacks are requests sent from Kali or from the platform. Nothing left on the target calls back. |
| **What the attacker is after** | On `board`, the password hashes in `auth_user`. The attacker steals them and submits them. The platform counts them only if they match the copy of `auth_user` the platform took from the target when the session opened (`loot_verified`). On `corp`, three changes to the WordPress database, listed in `wargames/corp/objectives.yaml`: a new administrator account, the `users_can_register` option turned on, and content written without permission. The platform finds these in `corp-db`'s own record of changes since the session started (`effect_observed`). |
| **What the defence has** | Suricata inline between the WAF and the web servers, on a bridge of the session's infra VM, and ModSecurity with the Core Rule Set (CRS) in front of the application. A request the WAF blocks never reaches Suricata; the WAF's own logs record it: ModSecurity's audit log, and nginx's log of the requests it refuses with 400 before ModSecurity runs. Suricata sees every request coming from the WAF and credits each alert to the client address its `X-Forwarded-For` names. ModSecurity blocks (`SecRuleEngine On`, `deploy/roles/waf/modsecurity.conf:1`). Both send their alerts to one Elasticsearch index. The defender can write and disable Suricata rules. The defender can tune the WAF through `PUT /api/sessions/<id>/waf/`: CRS paranoia level, anomaly thresholds and rule exclusions. The defender also has a root shell on the WAF VM and, outside a wargame, a root shell on the Kali VM for attacking the range as practice. The defender has nothing else. |

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

- No case scans, so initial reconnaissance is missing.
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
- The console works out which stages the cases reach from the case files, so
  this list cannot drift from the cases.

**The ATT&CK mapping is coarse.** Most exploitation cases map to T1190, the
Enterprise technique for exploiting a public-facing application. ATT&CK does not
tell SQL injection from path traversal. The CAPEC id in each case's `pattern`
field does.

**Only the declared objectives count.** On `board` that is the stolen
`auth_user` hashes. On `corp` it is the three database changes in
`wargames/corp/objectives.yaml`. An attack that achieves anything else scores as
if it achieved nothing.

**Benign traffic is a handful of cases, not a population.** One of them looks
like an attack: a search for `O'Brien` (`board-normal-search-with-apostrophe`).
These cases catch a rule that fires on everything. They do not estimate a false
positive rate.

**The platform API authenticates the caller and checks where the request
comes from.** Every console page and every `/api/` endpoint needs a signed-in
Django session; the terminals, `/kibana/` and port 8002 ask the same session
through nginx's `auth_request`. The first start makes `admin` with the password
`123456`, and nothing makes anyone change it, so the password stops nobody who
knows the default. Anyone who reaches port 8000 can sign up, but a sign-up
makes an inactive account that cannot sign in, open a session or pass
`auth_request` until an admin approves it on the console's account screen (`/users/`); a rejected one is
deleted. An approved learner sees and drives only the sessions they opened:
every API and page that names a session or a detection answers 404 for
another learner's, a request that names none acts on the learner's own, and
the front's session check refuses a terminal or `/site/` URL that names
another's session (403). Only staff change the range (`/api/range/` writes) or
manage accounts; staff see every session.

**Kibana shows a learner their open session's logs only.** Elasticsearch
and Kibana run without security, and Kibana's own documentation says spaces
are no boundary without it: "Controlling feature visibility is not a
security feature" (Kibana 8.15, Spaces). Each range stack has a space
(`soc-logs-N`) whose data view is `logs-N-*`; N is the stack number (see the
glossary in `docs/ARCHITECTURE.md`). The boundary is the platform's
gate in front of every Kibana API call in a space
(`/kibana/s/<space>/api/` and `/internal/`, which nginx hands to Django's
`/kibana-gate/` with the raw URI). The gate (`kibana.refusal`) forwards a
call only when:

- the space is that of a session the learner has open (staff: any space);
- the call is on a short list of what Discover asks (capabilities, settings
  read, the space's data view and saved search read, field list, value
  suggestions, `ese` search and its polls and cancels); everything else is
  403, among it `/internal/bsearch`, the `es`, `esql`, `sql` and `eql`
  strategies, Dev Tools' console proxy, saved object and data view writes,
  advanced settings writes and `resolve_index`;
- every index the call names is exactly the session's pattern (`params.index`
  of a search, `pattern` of the field list, the index in the value
  suggestions path), so a hand-typed `logs-2-*`, `logs-*`, a list, or a
  backing index `.ds-logs-2-...` is refused;
- nothing in the body or query names `index`, `_index`, `indices`,
  `namespace` or `namespaces`, which shuts terms lookup, `more_like_this`
  and cross-space reads.

Request batching is off in the session spaces (`bfetch:disable`), so each
search arrives as its own request and is checked whole. nginx refuses a
Kibana path with `%`, a backslash or a dot segment before Kibana decodes it,
any case of the default space or of a space inside a space, and the gate's
own path from outside. Limits:

- Staff are held to the same list of calls but may name any index, so a
  staff Discover reads every session's logs.
- The stack number is reused: a learner whose session is given stack N sees
  what earlier sessions on stack N left in `logs-N-*`, back to the index's
  retention.
- Kibana's page shell and bundles carry no data and stay open to any
  signed-in user in any space.

Abuse limits. nginx answers 429 past 5 sign-in POSTs a minute per address
(burst 5), 1 sign-up POST a minute (burst 3), 20 `/api/` requests a second
per session cookie (burst 40) and 100 per address (burst 200), and 10 open
connections per session cookie to the terminals and port 8002. Django blocks
the client, never the account (`api/blocks.py`): 3 wrong passwords against a
staff account within an hour block that address from signing in for an hour;
10 against any other name block it for 15 minutes. A fingerprint of the
headers the browser sends with the sign-in (User-Agent, Accept,
Accept-Language, Accept-Encoding and the `Sec-CH-UA` hints) is counted the
same way and blocked once it has failed from at least two addresses, so a
client that changes address but keeps its browser is held too. A blocked
client is refused even with the right password; staff list and lift blocks
on the account screen. Django also takes 5 sign-ups an hour from one address
and stops taking them while 50 wait for approval, and lets a learner hold one
open session (staff are exempt, so acceptance can open several). Their
limits:

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
- One open session per learner is checked again under the in-process lock
  that picks the session's stack (`SLOT_CHOICE`), so parallel opens by one learner get
  one session. The lock holds because one waitress process serves the API; a
  second process would need a database lock.

The platform reaches the range stacks only over `cr-mgmt`, where every range
VM has one control port. The platform's port there is in `cr-reach`, which
admits udp 123 (NTP) from members of `cr-mgmt` and udp 5140 (syslog) from
members of `cr-senders`, the infra VM's control port, and nothing else; the
stacks' LANs have no Neutron router, so no range VM has another way to the
platform. If a learner's shell did reach the API, it could call
`POST /api/rules/apply/` and rewrite the detector that scores the attacker.
The API holds no per-request refusal of range addresses: the
`api/reachability.py` check that refused any request from a host in the range
was not called by anything and was removed with the restructure of
2026-11-21. What keeps a range VM from the API is the network above: the
stacks' LANs have no Neutron router to the platform, and `cr-reach` admits
only NTP and syslog from `cr-mgmt`. The operator's console reaches the API
through the platform's floating address. nginx keeps the session check's
answer for the terminals, `/kibana/` and port 8002 five seconds, keyed on the session cookie, the client's address
and the session the URL names, so a cached yes is never reused for another
address or for another session.

The target is not published. Port 8000 is the console. The XSS cases make the
target run script in any browser that loads its pages, and the Website pane
serves the target on port 8002 of the same host, so that script runs in the
operator's signed-in browser, one port away from the console. Cookies are kept
per host, not per port, so the session cookie reaches 8002. What keeps the
script from the API:

- The session cookie is HttpOnly, and the CSRF token lives in the session, not
  in a cookie, so the script reads neither.
- The platform sends no CORS header, so the browser hands the script no answer
  from 8000.
- Every write needs the CSRF token, and the API refuses a cross-origin write
  and any write whose body is not `application/json` before that.
- nginx drops the `Cookie` header before it hands a request on 8002 to the
  site proxy and never passes the target's `Set-Cookie` to the browser.

**The learner map is a page of the console (`/map/<session>/`).**

- It reads `GET /api/sessions/<id>/topology/` and nothing else, and draws with
  a vendored cytoscape.js. It sends nothing to a third party.
- It answers only messages from its own origin and is framed only by it
  (`X-Frame-Options: SAMEORIGIN`).
- To draw it, the platform reads the session's stack's networks and ports
  from Neutron (tagged `cr.slot=<n>`) and, once per stack, runs
  `docker network inspect` on the target VM over ssh. The map shows nothing
  outside that stack: no
  platform VM, collector or customers. The platform container holds no Docker
  socket and its image no Docker client (until 2026-11-15 it held the platform
  host's socket, and the GNS3 server held it too, with `pid: host`,
  `CAP_NET_ADMIN` and `/dev/net/tun`).

**On OpenStack the platform answers NTP (time) requests from the range VMs.**

- Each range VM's user data points systemd-timesyncd at the platform's
  `cr-mgmt` address. chrony accepts that subnet (`allow`) and has no
  `cmdallow`, so its command port stays on loopback.
- `cr-reach` admits udp 123 from members of `cr-mgmt` (every range VM's
  control port) and udp 5140 only from `cr-senders` (the infra VM's).

**Each session's range is one Heat stack of four VMs.** `range/openstack.py`
renders it from `wargames/<wargame>/topology.yaml`: kali, waf, infra and
target, on five Neutron networks of the stack's own (`internet`, `dmz`, `web-outer`,
`web-inner`, `mgmt`). A learner holds a root shell on the Kali VM (the web
terminal, and ssh as `kali` with passwordless sudo through the platform's
jump) and on the WAF VM (the web terminal). No learner has a shell on the
infra or the target VM. Isolation is Neutron's, enforced outside the guest,
so root on Kali or the WAF cannot change it:

- No stack network has a Neutron router or a floating IP; the stack's only
  way between its LANs is the infra VM.
- Every port has port security on, so it sends only from the MAC and the
  fixed IP Neutron gave it, except:
  - Kali's `internet` port carries the allowed address pair `0.0.0.0/0`, so
    it can send from the origin addresses `slot-boot` adds; port security
    still binds its MAC.
  - The infra's `dmz` port carries the same pair, because the edge forwards
    packets from Kali's origin addresses to the WAF.
  - The infra's two IDS legs on `web-outer` and `web-inner` have port
    security off, so the Linux bridge between them can forward the WAF's and
    the target's frames. No learner has a shell on the infra.
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
  groups already standing too (`fabric.CONFINED_GROUPS`). DHCP on `cr-mgmt`
  hands out a route to 169.254.169.254 through the OVN metadata port, and
  that egress rule drops it, so no range VM reaches the metadata service.
  The VMs boot from a config drive and do not need it.
- The edge on the infra VM (nftables) forwards tcp 80 on 121.134.88.42 to the
  WAF's `dmz` address and lets in from `wan` only replies and that forward, so
  Kali reaches the targets only through the WAF.
- The WAF sends to the log server from its own address only (port security),
  and the log server relays a sender's lines only under the tags the WAF's
  logs carry (`modsecurity` and `nginx`), so the WAF cannot pass a line off as
  Suricata's.
- The target runs the wargame under Docker: every container drops all
  capabilities and runs with `no-new-privileges`; the database is on an
  internal Docker network inside the VM.
- The platform's reads of the learner's boxes (`operator_log` reading Kali's
  `/var/log/commands.log`, the loot and effect paths through `docker exec` on
  the target) run on the VM over ssh.
- A close deletes the session's stack and creates a new one, so nothing a
  learner wrote on Kali or the WAF reaches the next session.
- The platform holds the ssh key of the management user on every range VM
  (passwordless sudo): whoever takes the platform container is root on every
  range VM.

What is tested:

- `platform/tests/test_hot.py` fails `bin/verify` when the rendered stack
  breaks a rule above: a router or a floating IP in a stack, port security off
  on any port but the two IDS legs, Kali on a network other than `internet`
  and `cr-mgmt`, the WAF or the target with a way out but through the router,
  the web leg reaching the targets other than across the IDS bridge, the
  stack's `mgmt` admitting more than the WAF's logs, a control port off
  `cr-mgmt` or a range VM other than the infra in `cr-senders`.
  `platform/tests/test_openstack_fabric.py` checks that the fabric confines
  the egress of `cr-mgmt` and `cr-senders`.
- `test/test_range_isolation.py` checks a live stack from Kali, the WAF and the
  board: none reaches the platform, the Internet or the metadata service;
  Kali reaches `board.com` (the router's public address) and neither target
  past it, nor the WAF's private address (a SYN scan, which runs as root,
  reads it filtered); `board`, `corp-wp`, `board-db` and `corp-db` do not
  resolve from Kali; ping and traceroute to 121.134.88.42 answer; Kali finds
  no open service port on `cr-mgmt`; a frame from a MAC Neutron did not give
  Kali's port does not reach the router. Its last test writes a file on the
  WAF, closes the session and checks that the stack's WAF is a new VM (another
  boot id) without the file.

**Accounts are staff or learner.** Staff (`admin` and any account made staff
in Django) manage accounts, change the range and see every session; a
learner holds one open session and reaches only their own. Nothing stops two
browser windows of one account from driving the same session.

**A closed session's records last an hour.**

- The platform deletes a session that was closed more than
  `CR_RETAIN_CLOSED_MINUTES` ago (default 60). It deletes the session's cases,
  detections, customer requests and objectives. It does this at start and after
  every close (`platform/api/retention.py`).
- A disabled rule stays, with its session cleared.
- You cannot review or compare an older session from the platform's store. The
  alerts stay in Elasticsearch.

**The attacker's actions are only partly recorded.**

- The proxy labels HTTP requests.
- Commands typed in the Kali shell are logged with the active label
  (`GET /api/sessions/<id>/commands/`).
- Traffic that does not pass the WAF, such as an `nmap` scan of it, never
  reaches Suricata behind the WAF. A request nginx refuses with 400 is logged
  by address and time with no label, so only a `window` case can claim it.
