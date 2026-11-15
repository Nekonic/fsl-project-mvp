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
| **What the defence has** | Suricata on two legs, the slot's Internet side in front of the edge router and the estate side between the WAF and the targets, and ModSecurity with the Core Rule Set (CRS) in front of the application. ModSecurity blocks (`SecRuleEngine On`, `deploy/waf/modsecurity.conf:1`). Both send their alerts to one Elasticsearch index. The defender can write and disable Suricata rules. The defender can tune the WAF through `PUT /api/sessions/<id>/waf/`: CRS paranoia level, anomaly thresholds and rule exclusions. The defender also has a root shell in the WAF container and, outside a wargame, a root shell in the Kali container for attacking the range as practice. The defender has nothing else. |

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
knows the default. The platform stands on the management network only,
and no slot container has a route to it: every slot network is internal and its
bridge carries no address of the range host. If a container did reach it, the
attacker's shell could call `POST /api/rules/apply/` and rewrite the detector
that scores the attacker. The API therefore also refuses any request from the
address of a host in the range: the range host's management address and every
address the slots' containers report. The operator's console reaches the API
through the platform's floating address, from an address that is not a host in
the range. The check has three limits:

- The platform caches the list of range hosts for 30 seconds. A host that is
  recreated within that time keeps its old answer.
- If the platform cannot read the list of hosts, the list is empty for those
  30 seconds and the check lets every request through.
- Nothing stops a host in the range from sending with another host's address.

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
  `docker inspect`, `nsenter -n ip -o -4 addr` and a `sed` of the slot's
  rsyslog file. The platform container holds no Docker socket and its image
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
  range host.

**The learner-facing containers run on gVisor; the edge and the sensors share
the range host's kernel.** The range is one VM, `cr-range`, and each slot is a Docker
Compose project on it. The earlier range
gave each slot its own VMs, so reaching another slot meant breaking out of the
hypervisor. Now a learner holds a root shell in the Kali container and in the
WAF container (no-new-privileges leaves `sudo` nothing to gain, so the shell
starts as root), and one kernel separates that shell from every other slot.

What stands between them (`deploy/range-host/slot.yaml`,
`platform/range/rangehost.py`):

- Kali, the WAF, `board`, `board-db`, `corp-wp` and `corp-db` run on gVisor
  (`runsc`, release 20261026.0, pinned by SHA-512 in
  `deploy/range-host/setup.sh`). gVisor answers their system calls in its own
  user-space kernel, so the learner's root shells and the targets reach the
  range host's kernel only through gVisor. `runsc` runs with `--net-raw`,
  since Kali's SYN scan needs raw sockets, and `--platform=kvm`.
- gVisor's netstack never reaches Docker's embedded DNS at 127.0.0.11, which
  Docker serves through iptables rules in the container's network namespace:
  on `runsc` board first exited with `Unknown server host 'board-db' (-3)`
  and WordPress never became healthy (measured 2026-11-15; gVisor's FAQ names
  the same failure for user-defined bridges). Each target's backend network
  therefore has a fixed /28 (`rangehost.backend`, 10.40.N+1.0/28 and
  10.40.N+1.16/28 for slot N), every service on it a fixed address, and each
  service names the others in `/etc/hosts` (`extra_hosts`). Nothing in a slot
  resolves a name through DNS.
- Two stay on runc and share the range host's kernel. No learner has a shell
  in either:
  - The two Suricata sensors, which read the slot's host bridges with
    af-packet on the host network; gVisor's netstack offers no view of the
    host's bridges.
  - The edge, which forwards between the slot's networks and filters with the
    kernel's nftables and sysctls (`ip_forward`, `rp_filter`).
- `slot.sh` reaches into a sandbox's network with `docker exec --privileged`
  (the one process gets every capability inside gVisor, the container keeps
  its list), because gVisor copies the interfaces and routes into its own
  netstack when the sandbox starts and removes the addresses from the host
  namespace (gVisor `runsc/sandbox/network.go`), so `nsenter` from the host
  would change nothing the sandbox sees. gVisor refuses `ip addr flush`
  (`Operation not supported`), so the script deletes Kali's addresses one by
  one.

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
  host path, except the WAF's audit log, which is one file.
- No root operation on the range host goes through a path a learner can
  alter. The WAF is root in its container, and its root may create links in
  any host directory mounted into it, because the directory belongs to the
  remapped range. A host process that later opens a name in that directory
  follows the link: `slot.sh reset` (root) emptied
  `/var/log/cr/sN/waf/audit.log` with `: >`, and rsyslog (`syslog`, in `adm`)
  read the same name with `imfile`, which reads a symlinked file as if it
  were the file ("For symlink-ed files this does **not** contain name of the
  actual file", rsyslog's imfile documentation, Metadata). A link to
  `/etc/passwd` would have had the next reset truncate it; a link to another
  slot's log or to `/var/log/auth.log` would have shipped those lines as this
  slot's. The WAF therefore mounts only the file
  `/var/log/cr/sN/waf/audit.log`; its directory is root's (`0755`), so the
  WAF can write the file it holds and can neither replace it nor add a name
  beside it. `slot.sh` makes the directory root's, removes any other name in
  it and recreates the log if it is not a regular file before every `up` and
  `reset`. Kali, the edge and the targets mount no host path; the targets'
  volumes are refilled from `/opt/cr/pristine` only while freshly created and
  empty, before their container first runs. The platform's reads of the
  learner's boxes (`operator_log` reading Kali's `/var/log/commands.log`, the
  loot and effect paths) run inside the container through `docker exec`, so a
  link there resolves in the container's own filesystem.
- Every slot network is internal and its bridge has no host address
  (`gateway_mode_ipv4` isolated). Nothing is published and nothing is NATed, so
  a container has no route out and no address of the range host to reach.
- The range host's `mgmt` port is in `cr-mgmt`, which only the platform
  reaches. While it sets itself up it has a second port, on the platform's
  network, in `cr-egress`, which admits nothing inbound; the range host uses it
  to pull images. Once the setup reports ready, the platform detaches that
  port, so a set-up range host has no way to the Internet and no DNS
  resolver.
- The two Suricata sensors of each slot run on the host network with
  `NET_ADMIN`, `NET_RAW` and `SYS_NICE` and no user namespace remap. No learner
  is given a shell in them.

What a container escape reaches: with no host path a root operation follows
on the learner's say, leaving Kali, the WAF or a target takes a bug in gVisor and
then a host kernel bug reachable from gVisor's own seccomp filter, which puts the learner on the range host
as the remapped user, and a second bug as root. From there every other slot on the host is open, including
its board's `auth_user` secret, its sensors and its logs, and so is the range
host's syslog stream to the platform. It reaches no way out: the range host's
egress port exists only during its setup, before any slot holds a session. The
control plane is not: the platform is another VM, and from `mgmt` it accepts
only NTP and syslog from the range host. A root on the range host can still
send the platform forged log lines for any slot, so no score from that host is
evidence after an escape.

What is tested:

- `platform/tests/test_containment.py` fails `bin/verify` when the rendered
  slot compose breaks any rule above: a learner-facing container privileged,
  keeping default capabilities, gaining one not listed, missing
  `no-new-privileges` or a limit, leaving a default profile, sharing a host
  namespace, publishing a port, holding the Docker socket or mounting a host
  path beyond its own log file; a slot network not internal or with a host address;
  two slots sharing a subnet or a name; dockerd without `userns-remap`.
- `test/test_range_isolation.py` checks a live slot from Kali, the WAF and the
  board: none reaches the range host's sshd, the platform, the Internet, the
  metadata service or another slot's WAF; Kali reaches `board.com` (the WAF)
  and the board through the edge; `board-db` does not resolve from Kali; a SYN
  scan runs; Kali finds no open service port on the range host, the platform
  or the range host's `mgmt` network. Its last test opens a session, has the
  WAF plant links to a host canary file, to `/etc/passwd` and to another
  slot's log in its audit directory, waits for a line the WAF wrote to reach
  its own slot's index, closes the session and, after the reset, checks the
  canary unchanged, nothing of it in Elasticsearch, and the WAF's host log
  directory root's and holding only `audit.log`.
- No test runs an escape. The kernel is the boundary, and its bugs are not
  something the range can show.

**One account, one operator.** There is one account, `admin`, and no roles.
Nothing stops two browser windows from driving the same session. We decided
this to limit scope.

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
- Traffic that is not HTTP, such as `nmap`, still draws alerts. No label ties
  those alerts to a case.
