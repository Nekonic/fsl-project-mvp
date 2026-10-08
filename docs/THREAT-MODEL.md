# Threat model

Which threat the cases stand for, where the attacker starts, and what the range
cannot show.

## The threat

| | |
|---|---|
| **Threat emulated** | An unauthenticated attacker on the public internet, against two web applications exposed to it: a community board (`board`) and a WordPress site (`corp`). Opportunistic: no phishing, no insider, no stolen credentials. |
| **Attacker's position** | Outside, from one of the Internet origins the range builds (four on Docker, thirty declared), each with its own address range and a declared country that GeoIP agrees with. No account on the target at the start, no code on it, no presence on the internal network. |
| **Command and control** | None. Attacks are requests sent from Kali or from the platform; nothing left on the target calls back. |
| **What the attacker is after** | On `board`, the `auth_user` password hashes: the attacker exfiltrates them and submits them, and the platform credits only data that matches the target's own start-of-session snapshot (`loot_verified`). On `corp`, three changes to the WordPress database listed in `wargames/corp/objectives.yaml`: a rogue administrator, the `users_can_register` option turned on, and content written without permission. The platform reads them from `corp-db`'s own records of changes since the session started (`effect_observed`). |
| **What the defence has** | Suricata on the WAF's traffic and ModSecurity with CRS in front of the application, currently in detection-only mode (`deploy/waf/modsecurity.conf:1`), both reporting into one index. The defender writes and suppresses rules and does nothing else. |

## The stages it reaches

The stages are those of Mandiant's targeted attack life cycle. Three of its
eight happen here.

| Stage | Cases | ATT&CK | Mechanism (CAPEC) |
|---|---|---|---|
| Initial compromise | the four `board-sqli-*` cases, both `board-xss-*` cases | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [66 SQL Injection](https://capec.mitre.org/data/definitions/66.html), [63 Cross-Site Scripting (XSS)](https://capec.mitre.org/data/definitions/63.html) |
| Escalate privileges | `corp-rogue-admin` | [T1068 Exploitation for Privilege Escalation](https://attack.mitre.org/techniques/T1068/) | [233 Privilege Escalation](https://capec.mitre.org/data/definitions/233.html) |
| Escalate privileges | `corp-option-flip` | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [1 Accessing Functionality Not Properly Constrained by ACLs](https://capec.mitre.org/data/definitions/1.html) |
| Complete mission | `board-path-traversal-static` | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [126 Path Traversal](https://capec.mitre.org/data/definitions/126.html) |
| Complete mission | `corp-content-write` | [T1565 Data Manipulation](https://attack.mitre.org/techniques/T1565/) | [242 Code Injection](https://capec.mitre.org/data/definitions/242.html) |

Benign cases carry no stage, so that a false positive is not read as part of an
attack.

## What it cannot show

**Five of the eight stages never happen.** No case scans, so initial
reconnaissance is absent. Establish foothold, internal reconnaissance, move
laterally and maintain presence are absent because nothing executes code on the
target: the internal network is reached only through the application, so there
is no OS foothold. Privilege escalation happens inside the application only:
corp's Ultimate Member CVE turns an unprivileged registration into a WordPress
administrator (`corp-rogue-admin`). An OS foothold, OS-level privilege
escalation and persistence were set as a later goal on 2026-09-28
(`docs/STATE.md`, Backlog); moving laterally waits until a target gives it
somewhere to go. The console computes which stages the cases reach from the case
files, so that list cannot drift.

**The ATT&CK mapping is coarse.** Most exploitation cases are T1190, the
Enterprise technique for exploiting a public-facing application; ATT&CK does not
distinguish SQL injection from path traversal. The CAPEC id in each case's
`pattern` field does.

**Only the declared objectives count.** On `board` that is the exfiltrated
`auth_user` hashes; on `corp`, the three database changes in
`wargames/corp/objectives.yaml`. An attack that achieves anything else scores as
achieving nothing.

**Benign traffic is a handful of cases, not a population.** One of them looks
like an attack: a search for `O'Brien` (`board-normal-search-with-apostrophe`).
The cases catch a rule that fires on everything; they do not estimate a false
positive rate.

**The scorer is guarded, not authenticated.** The platform is attached to every
segment, and without a guard the attacker's shell could call
`POST /api/rules/apply/` and rewrite the detector it is scored by. The API
refuses any address that belongs to a host in the range; the operator's console
arrives through the published port from a segment's gateway, which is not a
host. Limits:

- the set of range hosts is cached for 30 seconds, so a host recreated inside
  that time keeps its old answer;
- if the substrate cannot be read, the set is empty for those 30 seconds and
  the guard lets everything through;
- nothing stops a host in the range from sending with another host's address.

The target is not published; port 8080 is the reverse proxy for the pfSense
pane and port 8000 is the console. The XSS cases make the target run script in
any browser that loads its pages, so the API also refuses cross-origin writes
and any write whose body is not `application/json`.

**One operator, one session.** No accounts, no roles, and nothing stops two
browser windows driving the same session. That was a scope decision.

**The attacker's actions are partly recorded.** The proxy labels HTTP requests,
and commands typed in the Kali shell are logged with the active label
(`GET /api/sessions/<id>/commands/`). Non-HTTP traffic such as `nmap` still
draws alerts that no marker ties to a case.
