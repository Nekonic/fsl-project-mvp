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

**The platform API checks where a request comes from, but it does not
authenticate the caller.** The platform stands on the management network only,
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
target run script in any browser that loads its pages. For that reason the API
also refuses cross-origin writes and any write whose body is not
`application/json`.

**Anyone who can reach port 3080 can read the GNS3 server.**

- Its sign-in page (`/static/web-ui/map.html`) holds the learner's password.
  Bring-up generates that password. It is not a shipped default.
- The learner has only GNS3's built-in Auditor role, which is read-only. The
  Auditor was refused every write we tried: start, open, close, delete, node and
  drawing create, image pull and user create all returned 403 (measured
  2026-10-13).
- The Auditor can read the host's Docker image list
  (`GET /v3/computes/local/docker/images`).
- The admin password is `CR_GNS3_ADMIN_PASSWORD`, or it is generated into
  `/var/lib/cr-gns3/admin-password`. It is never given to learners. API keys
  for MCP are made only with `docker exec` on the platform host.
- **GNS3's admin controls the platform host's Docker daemon, and so does the
  platform container.** To open the projects, the container holds the Docker
  socket, `CAP_NET_ADMIN` and `/dev/net/tun`. A `docker` node in GNS3 is a
  privileged container on the host's daemon.
- At bring-up the platform starts every node of the learner map
  (`deploy/gns3/provision.py` `started`). Each node is an idle container of one
  pinned busybox image.
- An admin who adds a node with another image, or starts one, runs code as root
  on the host.
- The sign-in page turns off the web UI's usage statistics
  (`statistics_command` false), so the console's Map pane sends nothing to
  Google Analytics.

**On OpenStack the platform answers NTP (time) requests from the range host.**

- The security group `cr-mgmt` shields the range host's `mgmt` port so that
  only the platform can reach it.
- The ways back to the platform's `mgmt` port are udp 123 from members of
  `cr-mgmt`, which chrony answers, and udp 5140 from the range host's own
  address, the syslog collector. chrony accepts that subnet (`allow`) and has
  no `cmdallow`, so its command port stays on loopback.
- The slots' containers reach neither: their networks have no route off the
  range host.

**Every slot shares the range host's kernel.** The range is one VM,
`cr-range`, and each slot is a Docker Compose project on it. The earlier range
gave each slot its own VMs, so reaching another slot meant breaking out of the
hypervisor. Now a learner holds a root shell in the Kali container and in the
WAF container (no-new-privileges leaves `sudo` nothing to gain, so the shell
starts as root), and one kernel separates that shell from every other slot.

What stands between them (`deploy/range-host/slot.yaml`,
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
  host path, except the WAF's audit log directory.
- Every slot network is internal and its bridge has no host address
  (`gateway_mode_ipv4` isolated). Nothing is published and nothing is NATed, so
  a container has no route out and no address of the range host to reach.
- The range host's `mgmt` port is in `cr-mgmt`, which only the platform
  reaches. Its second port, on the platform's network, is in `cr-egress`, which
  admits nothing inbound; the range host uses it to pull images.
- The two Suricata sensors of each slot run on the host network with
  `NET_ADMIN`, `NET_RAW` and `SYS_NICE` and no user namespace remap. No learner
  is given a shell in them.

What a container escape reaches: a kernel bug reachable through the default
seccomp profile puts the learner on the range host as the remapped user, and a
second bug as root. From there every other slot on the host is open, including
its board's `auth_user` secret, its sensors and its logs, and so are the range
host's own way to the Internet and its syslog stream to the platform. The
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
  path beyond its own log; a slot network not internal or with a host address;
  two slots sharing a subnet or a name; dockerd without `userns-remap`.
- `test/test_range_isolation.py` checks a live slot from Kali, the WAF and the
  board: none reaches the range host's sshd, the platform, the Internet, the
  metadata service or another slot's WAF; Kali reaches `board.com` (the WAF)
  and the board through the edge; `board-db` does not resolve from Kali; a SYN
  scan runs.
- No test runs an escape. The kernel is the boundary, and its bugs are not
  something the range can show.

**One operator, one session.** There are no accounts and no roles. Nothing
stops two browser windows from driving the same session. We decided this to
limit scope.

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
