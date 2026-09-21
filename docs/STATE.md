# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-21 (the estate has an inside, and it can be lost)

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md` and runs in four
phases; all four are done.

`bin/verify` is green. It prints the scores; they are not written down here,
because they move whenever the rules or the cases do.

`metrics.json` holds the baseline - 611 core, 3996 product,
6 dependencies, 9 services, 315 tests. Read it there rather
than here: a copy in prose is a copy that goes stale, and this one did.

**You can now run the whole loop in a browser.** Open `/`, start a session,
then open the two windows side by side: fire cases from one, watch the
score move in the other, edit a Suricata rule and fire again. The red window
also has a Kali terminal - name an attack, press start, type it, press stop,
and it is scored two ways at once - by time and source, and by a marker the
proxy stamps - with both answers side by side in the blue window.

The blue window is a live console now: it ingests and redraws on a timer, so
alerts arrive while you watch rather than when you press something, and any
alert opens the whole Elasticsearch record behind it.

## In progress

Nothing. The product design is finished; the next item is not written yet.

## Done since v1.0

One line each.

**The range**
- Three segments plus four origin networks; the WAF is the only intended way
  across, and the published port arrives on the outside one.
- The attacks come from four countries, chosen in the console; the stamping
  proxy rewrites the upstream so nobody types a routing name.
- The target is `http://shop.com` on port 80 - no appliance name, no port.
- The estate has an inside: an internal wiki reachable from the application
  and nowhere else, taken by SSRF, judged by its own access log.
- Filebeat's registry is a named volume, so a recreate does not re-ship every
  log it has ever read.

**The red team**
- One attacker image. Kali with nmap, whatweb, ffuf, gobuster, nikto, sqlmap,
  hydra and a wordlist; the same image a `tool:` case runs in.
- The shell is the red team; the case file is a scripted baseline. A labelled
  window is scored by time and source and by a marker the proxy stamps.
- Two routes out of the box - through the proxy for HTTP, direct for raw TCP -
  and the window records whichever the work used.
- Cases declare what they take, and seven objectives fall instead of two.

**The score**
- Objectives lead it: the target flips its own `solved`, so the platform
  labels nothing about what an attack achieved.
- A breach is credited to the attack that took it, using the target's own
  timestamp, with a tolerance for the two clocks involved.
- A true positive has to name the right rule: a case declares `expect`, and an
  alert that does not mention the attack's mechanism is reported uncorroborated.
- Silencing a rule is the verdict, and it expires by itself.

**The console**
- One blue console: Dashboard, Live, Scoreboard, Rules. It ingests on a timer,
  and any alert opens the whole Elasticsearch record behind it.
- The dashboard is top-N tables - source addresses with their zone and
  country, destinations, signatures, request paths - plus a map and a trend.
- Every value is escaped before it reaches the page, and there is a test that
  says so. The console used to run the attacks it collected.
- Every UI action is a REST call first.

**Smaller**
- Dropped djangorestframework and Kibana; collapsed the Django boilerplate;
  shrank `redteam/harness.py`; deleted the dead marker-probing.
- Tried to replace Django entirely and did not: it cost more lines than it
  saved.

## Backlog

The user's direction, from the red team playbook at 레드팀.com: the range
should cover more of the attack lifecycle than initial access. The inside now
exists; what is still missing is named below.

### 1. A foothold to escalate from

Still absent: 거점 확보, 권한 상승, 지속성 유지. There is no code execution on
the target, so the estate is reached *through* the application rather than
from a shell on it, and there is nothing to escalate. Whether that matters is
a scope decision: a C2 and a foothold is a large step, and the range may be
more useful as a web-entry range that is honest about where it stops.

### 2. The vocabulary and the threat model

Take the industry's words rather than invented ones - 공격 인프라 구축, 초기
정찰, 초기 침투, 내부 정찰, 횡적 이동, 미션 수행 - and label the cases and the
console with the stage each belongs to, plus the ATT&CK technique id. Add the
위협 모델링 table and a 한계점 section to the docs: state the threat being
emulated, the attacker's position, the TTP outline, and then what this range
cannot show.

### 3. What the operator actually typed

The standard red team operator log records Tool/App and Command. The shell
records neither: the proxy sees HTTP requests, and nothing sees nmap. Without
it a window case says an attack happened and not what it was.

## Known gaps

- The `platform` container mounts the Docker socket to validate rules, and the
  Kali terminal is an unauthenticated root shell on 7681. Both are container
  escape paths, acceptable in a local lab and nowhere else.
- Two labelled terminal windows less than four seconds apart overlap, because
  `WINDOW_SLACK` is two seconds at each end. The console does not say so on
  screen yet.
- Nothing stops two people opening the same session in four windows. One user,
  one session was a deliberate scope decision; revisit it only if the answer to
  "who is in front of this" changes.
