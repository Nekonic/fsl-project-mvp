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
| **What the defence has** | Suricata on one leg, the web servers' segment behind the WAF, and ModSecurity with the Core Rule Set (CRS) in front of the application. A request the WAF blocks never reaches Suricata; the WAF's own logs record it: ModSecurity's audit log, and nginx's log of the requests it refuses with 400 before ModSecurity runs. Suricata sees every request coming from the WAF and credits each alert to the client address its `X-Forwarded-For` names. ModSecurity blocks (`SecRuleEngine On`, `deploy/waf/modsecurity.conf:1`). Both send their alerts to one Elasticsearch index. The defender can write and disable Suricata rules. The defender can tune the WAF through `PUT /api/sessions/<id>/waf/`: CRS paranoia level, anomaly thresholds and rule exclusions. The defender also has a root shell in the WAF container and, outside a wargame, a root shell in the Kali container for attacking the range as practice. The defender has nothing else. |

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
  stand on networks the attacker's container is not on, so they can be reached
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

**Kibana shows a learner their open session's slot only.** Elasticsearch
and Kibana run without security, and Kibana's own documentation says spaces
are no boundary without it: "Controlling feature visibility is not a
security feature" (Kibana 8.15, Spaces). Each slot has a space
(`soc-logs-N`) whose data view is `logs-N-*`; the boundary is the platform's
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
- every index the call names is exactly the slot's pattern (`params.index`
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
  staff Discover reads every slot.
- A slot is reused: a learner who opens a session on a slot sees what an
  earlier session on that slot left in `logs-N-*`, back to the index's
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
  that picks the slot (`SLOT_CHOICE`), so parallel opens by one learner get
  one session. The lock holds because one waitress process serves the API; a
  second process would need a database lock.

The platform stands on the management network only,
and no slot container has a route to it: every slot network but the 관제망 is
internal and its bridge carries no address of the range host. The 관제망 lets
out one path, the log server's 5140/udp to the collector; the one
learner-facing container on it is the WAF, whose filter drops everything but
that path from other addresses. If a container did reach it, the
attacker's shell could call `POST /api/rules/apply/` and rewrite the detector
that scores the attacker. The API therefore also refuses any request from the
address of a host in the range: the range host's management address and every
address the slots' containers report. The operator's console reaches the API
through the platform's floating address, from an address that is not a host in
the range. The check has four limits:

- The platform caches the list of range hosts for 30 seconds. A host that is
  recreated within that time keeps its old answer.
- If the platform cannot read the list of hosts, the list is empty for those
  30 seconds and the check lets every request through.
- Nothing stops a host in the range from sending with another host's address.
- nginx keeps the session check's answer for the terminals, `/kibana/` and
  port 8002 five seconds, keyed on the session cookie, the client's address
  and the session the URL names, so a cached yes is never reused for a range
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
- To draw it, the platform runs one read-only script on the range host over
  the ssh key it already holds for `sudo docker`: `docker network inspect`,
  `docker inspect` and `nsenter -n ip -o -4 addr`. It reads no rsyslog file,
  and the map shows nothing outside the slot: no range host, platform VM,
  collector or customers. The platform container holds no Docker socket and its image
  no Docker client (until 2026-11-15 it held the platform host's socket, and
  the GNS3 server held it too, with `pid: host`, `CAP_NET_ADMIN` and
  `/dev/net/tun`).

**On OpenStack the platform answers NTP (time) requests from the range host.**

- The security group `cr-mgmt` shields the range host's `mgmt` port so that
  only the platform can reach it.
- The ways back to the platform's `mgmt` port are udp 123 from members of
  `cr-mgmt`, which chrony answers, and udp 5140 from the range host's own
  address, the syslog collector. chrony accepts that subnet (`allow`) and has
  no `cmdallow`, so its command port stays on loopback.
- The slots' containers reach neither: their networks have no route off the
  range host, except the log server's filtered 5140/udp to the collector over
  the 관제망.

**Each slot is a Docker Compose project on the range host.** The range is one
VM, `cr-range`, and its containers run on Docker's default runtime. A learner
holds a root shell in the Kali container and in the WAF container
(no-new-privileges leaves `sudo` nothing to gain, so the shell starts as root).

How the containers are set up (`deploy/range-host/slot.yaml`,
`platform/range/rangehost.py`):

- dockerd runs with `userns-remap`, so root in a container is an unprivileged
  user on the range host.
- Every learner-facing container (Kali, the WAF, the edge router and the four
  targets) drops all capabilities and adds back only a listed few: Kali
  `NET_RAW`, `NET_ADMIN`, `SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE`, `FOWNER`,
  `KILL`, `AUDIT_WRITE`; the WAF `NET_BIND_SERVICE`, `SETUID`, `SETGID`,
  `CHOWN`, `DAC_OVERRIDE`; the edge `NET_ADMIN`; the targets `CHOWN`,
  `DAC_OVERRIDE`, `FOWNER`, `SETUID`, `SETGID`, and corp's WordPress also
  `NET_BIND_SERVICE`.
- Each runs with `no-new-privileges`, Docker's default seccomp and AppArmor
  profiles, and a memory and process limit. None is privileged, holds the
  Docker socket, shares the host's network, PID or IPC namespace, or mounts a
  host path, except the WAF's two log files, its audit log and nginx's log of
  refused requests.
- No root operation on the range host goes through a path a learner can
  alter. The WAF is root in its container, and its root may create links in
  any host directory mounted into it, because the directory belongs to the
  remapped range. A host process that later opens a name in that directory
  follows the link: `slot.sh reset` (root) emptied
  `/var/log/cr/sN/waf/audit.log` with `: >`, and the range host's rsyslog
  (`syslog`, in `adm`) read the same name with `imfile` (since 2026-11-15 the
  slot's WAF shipper reads it, in the WAF's network namespace but from its own
  read-only mount of the file), which reads a symlinked file as if it
  were the file ("For symlink-ed files this does **not** contain name of the
  actual file", rsyslog's imfile documentation, Metadata). A link to
  `/etc/passwd` would have had the next reset truncate it; a link to another
  slot's log or to `/var/log/auth.log` would have shipped those lines as this
  slot's. The WAF therefore mounts only the files
  `/var/log/cr/sN/waf/audit.log` and `/var/log/cr/sN/waf/refused.log`; their
  directory is root's (`0755`), so the WAF can write the files it holds and
  can neither replace them nor add a name beside them. `slot.sh` makes the
  directory root's, removes any other name in it and recreates each log that
  is not a regular file before every `up` and `reset`. Kali, the edge and the targets mount no host path; the targets'
  volumes are refilled from `/opt/cr/pristine` only while freshly created and
  empty, before their container first runs. The platform's reads of the
  learner's boxes (`operator_log` reading Kali's `/var/log/commands.log`, the
  loot and effect paths) run inside the container through `docker exec`, so a
  link there resolves in the container's own filesystem.
- Every slot network but the 관제망 is internal and its bridge has no host
  address (`gateway_mode_ipv4` isolated). Nothing is published. The 관제망
  (`sN_mgmt`) is NATed so the log server can reach the platform's collector;
  `slot.sh` installs its filter before compose creates it: INPUT drops
  everything from `sN-mgmt`, and DOCKER-USER passes only `sN-mgmt` to itself
  and the log server's address to the collector's 5140/udp. The 관제망 holds
  the sensor, the log server and the WAF's management interface. The WAF is
  the one learner-facing container on it: it holds neither `NET_RAW` nor
  `NET_ADMIN`, so it sends from its own address only, and the log server names
  every log by the address it came from and relays a sender's lines only under
  the tags its own logs carry (`modsecurity` and `nginx` for the WAF), so the
  WAF can write only the WAF's logs, which it already writes, and cannot pass
  a line off as Suricata's. From the 관제망 it reaches the log server's
  514/tcp and nothing listening on the sensor.
- The range host's `mgmt` port is in `cr-mgmt`, which only the platform
  reaches. While it sets itself up it has a second port, on the platform's
  network, in `cr-egress`, which admits nothing inbound; the range host uses it
  to pull images. Once the setup reports ready, the platform detaches that
  port, so a set-up range host has no way to the Internet and no DNS
  resolver.
- Each slot's one Suricata sensor is a slot container on the one bridge it
  watches, `sN-web` behind the WAF (an interface with no address, fed by
  `tc mirred`), and on the 관제망, with `NET_ADMIN`, `NET_RAW` and `SYS_NICE` under the same user
  namespace remap as every other container. The log server and the shippers
  hold no capability and mount only read-only files. No learner is given a
  shell in any of them.

What is tested:

- `platform/tests/test_containment.py` fails `bin/verify` when the rendered
  slot compose breaks any rule above: a learner-facing container privileged,
  keeping default capabilities, gaining one not listed, missing
  `no-new-privileges` or a limit, leaving a default profile, sharing a host
  namespace, publishing a port, holding the Docker socket or mounting a host
  path beyond its own log file; a slot network other than the 관제망 not internal or with a host address;
  two slots sharing a subnet or a name; dockerd without `userns-remap`.
- `test/test_range_isolation.py` checks a live slot from Kali, the WAF and the
  board: none reaches the range host's sshd, the platform, the Internet, the
  metadata service or another slot's WAF; Kali reaches `board.com` (the WAF)
  and neither target past it, by the WAF's own upstream addresses; `board`,
  `corp-wp`, `board-db` and `corp-db` do not resolve from Kali; a SYN
  scan runs; Kali finds no open service port on the range host, the platform
  or the range host's `mgmt` network. Its last test opens a session, has the
  WAF plant links to a host canary file, to `/etc/passwd` and to another
  slot's log in its audit directory, waits for a line the WAF wrote to reach
  its own slot's index, closes the session and, after the reset, checks the
  canary unchanged, nothing of it in Elasticsearch, and the WAF's host log
  directory root's and holding only `audit.log`.

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
