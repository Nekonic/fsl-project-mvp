# Threat model

Which threat the cases stand for, where the attacker starts, and what the range
cannot show.

## The threat

| | |
|---|---|
| **Threat emulated** | An unauthenticated attacker on the public internet, against a shop exposed to it. Opportunistic rather than targeted: no phishing, no insider, no stolen credentials. |
| **Attacker's position** | Outside, on one of four Internet segments, each with its own address range and a declared geographic origin. No account on the target, no code on it, no presence inside the estate. |
| **Command and control** | None. Attacks are requests sent from Kali or from the platform; nothing left on the target calls home. |
| **What the attacker is after** | Juice Shop's challenges, which it marks `solved` itself, plus reading the internal wiki, judged from the wiki's access log. |
| **What the defence has** | Suricata on the WAF's traffic and ModSecurity in front of the application, both reporting into one index. The defender writes and silences rules, nothing else. |

## The stages it reaches

The stages are those of Mandiant's targeted attack life cycle. Three of its
eight happen here.

| Stage | Cases | ATT&CK | Mechanism (CAPEC) |
|---|---|---|---|
| Initial reconnaissance | `sqlmap-boolean-blind`, `metrics-endpoint-scrape` | [T1595.002 Vulnerability Scanning](https://attack.mitre.org/techniques/T1595/002/) | [66 SQL Injection](https://capec.mitre.org/data/definitions/66.html), [116 Excavation](https://capec.mitre.org/data/definitions/116.html) |
| Initial compromise | the three `sqli-*` cases, both `xss-*` cases | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [66 SQL Injection](https://capec.mitre.org/data/definitions/66.html), [63 Cross-Site Scripting (XSS)](https://capec.mitre.org/data/definitions/63.html) |
| Complete mission | `path-traversal-ftp`, `confidential-document-access`, `backup-file-null-byte` | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [126 Path Traversal](https://capec.mitre.org/data/definitions/126.html), [1 Accessing Functionality Not Properly Constrained by ACLs](https://capec.mitre.org/data/definitions/1.html), [52 Embedding NULL Bytes](https://capec.mitre.org/data/definitions/52.html) |

Benign cases carry no stage. A stage on them would make every false positive
read as part of an attack.

## What it cannot show

**Five of the eight stages never happen.** Establish foothold, escalate
privileges, internal reconnaissance, move laterally and maintain presence are
all absent because nothing executes code on the target. The estate is reached
through the application, so there is no foothold to escalate from. Whether the
range should grow one is an open scope decision (`docs/STATE.md`, backlog). The
console computes which stages the cases reach from the case file, so that list
cannot drift.

**The ATT&CK mapping is coarse.** Every exploitation case is T1190, the only
Enterprise technique for exploiting a public-facing application; ATT&CK does
not distinguish SQL injection from path traversal. The CAPEC id in each case's
`pattern` field does.

**The target only judges its own challenges.** An attack that achieves
something Juice Shop has no challenge for scores as achieving nothing.

**Benign traffic is a handful of cases, not a population.** Two of them look
like attacks (an apostrophe in a search, the word `select`). They catch a rule
that fires on everything; they do not estimate a false positive rate.

**The scorer is guarded, not authenticated.** The platform stands on every
segment, and without a guard the attacker's shell could call
`POST /api/rules/apply/` and rewrite the detector it is scored by. The API
refuses any address that belongs to a host in the range; the operator's
console arrives through the published port from a segment's gateway, which is
not a host. Limits:

- the set of range hosts is cached for 30 seconds, so a host recreated inside
  that time keeps its old answer;
- if the substrate cannot be read, the set is empty for those 30 seconds and
  the guard lets everything through;
- nothing stops a host in the range from sending with another host's address.

The target (`:8080`) and the console (`:8000`) are the same site, and the XSS
cases make the target run script, so the API also refuses cross-origin writes
and any write whose body is not `application/json`.

**One operator, one session.** No accounts, no roles, and nothing stops two
browser windows driving the same session. That was a scope decision.

**The attacker's actions are partly recorded.** The proxy labels HTTP requests,
and commands typed in the Kali shell are logged with the active label
(`GET /api/sessions/<id>/commands/`). Non-HTTP traffic such as `nmap` still
draws alerts that no marker ties to a case.
