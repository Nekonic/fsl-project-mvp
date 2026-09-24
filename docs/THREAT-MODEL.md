# What this range emulates, and what it does not

The range is worth what its threat model is worth. This says which threat the
cases stand for, where the attacker starts, and which parts of an intrusion
never happen here. A range that does not say what it leaves out reads as one
that covers everything.

## The threat

| | |
|---|---|
| **Threat emulated** | An unauthenticated attacker on the public internet, against a shop that is exposed to it. Opportunistic rather than targeted: no phishing, no insider, no stolen credentials. |
| **Attacker's position** | Outside, on one of four Internet segments, each with its own address range and a geographic origin the declaration names. No account on the target, no code on it, no presence inside the estate. |
| **Command and control** | **None.** Attacks are requests sent from Kali or from the platform; nothing is left on the target to call home. |
| **What the attacker is after** | The shop's own challenges, which Juice Shop marks `solved` itself, plus one objective the platform adds: reading the internal wiki, judged from the wiki's access log. |
| **What the defence has** | Suricata on the gateway's traffic and ModSecurity in front of the application, both reporting into one index. The defender writes and silences rules; nothing else. |

## The stages it reaches

The life cycle is Mandiant's targeted attack life cycle, in its order. Three of
its eight stages happen here.

| Stage | Cases | ATT&CK | Mechanism (CAPEC) |
|---|---|---|---|
| Initial reconnaissance | `sqlmap-boolean-blind`, `metrics-endpoint-scrape` | [T1595.002 Vulnerability Scanning](https://attack.mitre.org/techniques/T1595/002/) | [66 SQL Injection](https://capec.mitre.org/data/definitions/66.html), [116 Excavation](https://capec.mitre.org/data/definitions/116.html) |
| Initial compromise | the three `sqli-*` cases, both `xss-*` cases | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [66 SQL Injection](https://capec.mitre.org/data/definitions/66.html), [63 Cross-Site Scripting (XSS)](https://capec.mitre.org/data/definitions/63.html) |
| Complete mission | `path-traversal-ftp`, `confidential-document-access`, `backup-file-null-byte` | [T1190 Exploit Public-Facing Application](https://attack.mitre.org/techniques/T1190/) | [126 Path Traversal](https://capec.mitre.org/data/definitions/126.html), [1 Accessing Functionality Not Properly Constrained by ACLs](https://capec.mitre.org/data/definitions/1.html), [52 Embedding NULL Bytes](https://capec.mitre.org/data/definitions/52.html) |

Six benign cases carry no stage at all. They are traffic that is meant to pass,
and a stage on them would make every false positive read as part of an attack.

## What it cannot show

**Five of the eight stages never happen.** Establish foothold, escalate
privileges, internal reconnaissance, move laterally and maintain presence are
all absent, and for one reason: nothing here executes code on the target. The
estate is reached through the application, not from a shell on it, so there is
no foothold to escalate from and nothing to move laterally to. Whether that
matters is a scope decision nobody has taken; the range may be more useful as a
web-entry range that is honest about where it stops than as a thin imitation of
a full intrusion. The console says which stages it reaches and which it does
not, computed from the cases rather than written down, so it cannot drift.

**The ATT&CK mapping is coarse, and has to be.** Every exploitation case is
T1190, because that is the only Enterprise technique for exploiting a
public-facing application: ATT&CK does not distinguish SQL injection from path
traversal, and was never meant to. The `pattern` field carries the mechanism as
a CAPEC id, which does distinguish them, and the console links both ids to their
definitions.

**The target judges whether it was beaten, and only about its own challenges.**
An attack that achieves something Juice Shop has no challenge for is scored as
achieving nothing. The objective score is as complete as Juice Shop's challenge
list and no more.

**Benign traffic is six cases, not a population.** Two of them look like
attacks (an apostrophe in a search, the word `select`); none is a day of real
shopping. They catch a rule that blocks everything; they do not estimate a false
positive rate.

**The scoreboard does not answer the range.** The platform stands on every
segment, so until this was closed the attacker's own terminal could call the
scoring API - no accounts, no authentication, `GET /api/rules/` answered it
with 200. From there `POST /api/rules/apply/` rewrites the detector: blank the
file and every attack is a miss, match the marker header and every attack is a
hit. Every cell of the confusion matrix was writable by the party being
measured. The API now refuses any address standing inside the range, which is
not a login - the operator's console arrives through the published port, so its
source is a segment's gateway rather than a participant. Two limits remain: the
set of participants is cached for thirty seconds, and nothing stops a host
inside the range from sending with another host's address.

**One operator, one session.** No accounts, no roles, and nothing stops two
browser windows driving the same session. That was a scope decision.

**The attacker's own actions are only partly recorded.** The proxy labels HTTP
requests. Commands typed in the Kali shell are logged with the active label
(`GET /api/sessions/<id>/commands/`), but non-HTTP traffic such as `nmap` still
draws alerts that no marker ties to a case.
