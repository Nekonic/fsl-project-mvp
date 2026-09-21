# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-22 (the substrate starts the tools; core no longer shells out)

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md` and runs in four
phases; all four are done.

`bin/verify` is green. It prints the scores; they are not written down here,
because they move whenever the rules or the cases do.

`metrics.json` holds the baseline. Read it there rather than here: a copy in
prose is a copy that goes stale, and this one already did twice.

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

Nothing half-finished. The last session left the tree green and committed.

## The substrate seam

Docker was the MVP shortcut; OpenStack was always the target. That move is now
most of the way done, and the remaining work is named below rather than
guessed at.

`platform/range/` holds the port: `describe() -> Shape` and
`runner(role, segment) -> Runner`. `platform/range/docker.py` implements both,
and `platform/range/declaration.yaml` tells it what the range means.
Nothing under `platform/scoring/`, `platform/ingest/`, `platform/rules/` or
`redteam/harness.py` contains the word docker, and neither does
`platform/topology.py`, `platform/attacker.py` or `platform/objectives.py`.
`test/range.py` is the same idea for the acceptance suite, which used to shell
out to `docker exec` in five files.

Two mechanics were measured against the running stack rather than assumed, and
both are load-bearing:

- Suricata is PID 1 in its container, so `kill -USR2 1` through the runner is
  exactly `docker kill -s USR2`. With stdin round-tripping through
  `docker exec -i`, write, validate and reload collapse into one operation.
  That is why the port has two verbs and not five, and why five settings and
  four compose environment lines went away.
- The marker lives only on Suricata `http` documents, never on `alert` ones -
  0 of 3,969 alerts carry `http.request_headers`. Any change that filters the
  ingest to `event_type: alert` destroys correlation entirely.

The range is now **declared**. `platform/range/declaration.yaml` holds the one
substrate-neutral statement of it - per segment an id, the name a person reads
and the origin it attacks from, plus the role table naming the host that fills
each job - and three readers share it: `range/docker.py` merges the declared
identity into what the daemon allocated, `fsl/settings.py` takes the attacker
and proxy identity from it instead of restating them, and `test/range.py` builds
the acceptance suite's host table from it. The adapter no longer reads
`fsl.segment` or `fsl.origin`; it asks Docker only for addresses and membership,
which is exactly the set of questions Neutron can answer.

The subnet stays substrate-assigned, deliberately. Identity is declared,
allocation is reported: a subnet written into the declaration would be an
address fact the platform does not own, and when it disagreed with the one the
range handed out the console would bin alerts by a subnet nothing lives on.
Gateway settles it - nobody can declare that at all.

`compose.yaml` is the Docker realisation of the declaration and nothing
generates one from the other, so `platform/tests/test_declaration.py` holds them
together: a network built and not declared, a segment declared and not built, a
name or an origin changed on one side, or a role pointing at a container compose
does not define, each fails the suite naming the segment or the role.

`platform/range/openstack.py` is a **sketch**, not an adapter: it answers the
same two verbs against Neutron and Nova with the cloud call itself left
unimplemented, and it exists to be read. `test_openstack_sketch.py` holds it to
the port and asserts nothing at runtime imports it. What it found is below;
`topology.shape()` consumed its `Shape` unchanged, which is the part that works.

Closed since the sketch was written: which origin is the default, how the
sensor is reloaded, whether a sensor is one of its segment's participants, how
many subnets a segment may carry, how a substrate object is bound to a declared
segment, and who starts a tool.

**The substrate starts the tools.** `redteam/harness.py` is gated core and ran
`docker run --rm --network ...` itself, with the network recovered by cutting
`waf-` off the target's hostname and pasting the project name back on - the
origin id it was built from had been thrown away two calls earlier. Core now
takes a launcher, the same way it takes a sensor: no `subprocess` import
remains in it. `Substrate.launcher(segment_id)` is the port's third verb, and
`test/test_tool_cases.py` fires one end to end, which nothing did before -
breaking the binding turns all three of its assertions red.

**A segment is bound by a mark it carries.** The Docker adapter used to cut the
compose project off the front of a network name, and the sketch matched a
Neutron network whose name happened to equal the declared id. Both were rules,
and both were wrong: compose lets a network override its own name, Heat appends
a stack suffix to every one it builds, Neutron does not keep names unique, and a
project called `fsl_lab` swallowed part of itself. Now whoever builds the range
marks each network with the segment it realises - a Docker label, a Neutron tag,
`fsl.segment.id` in both - and the adapter reads it. Nothing else is part of the
range, which is also the answer to a shared Neutron project handing back other
tenants' networks: the listing is filtered by `tags-any`, a documented Neutron
filter, so the cloud is never asked for them.

What is left for OpenStack, in order:

1. **Name resolution.** Nine places still name a host - `shop.com`,
   `wiki.internal`, `juice-shop:3000`, `proxy:8081`. Compose gives those away;
   Neutron does not. cloud-init writing `/etc/hosts` is the cheapest answer
   that keeps `shop.com` a name, which is the product - and `shop.com` is the
   one name worth keeping, because a range where the target has no name is not
   the product. The other two classes are gone: `FSL_TOOL_NETWORK`, and the
   five `waf-<origin>` aliases.

2. **The sensor's placement.** `network_mode: "service:waf"` puts Suricata in
   the WAF's namespace so it sees both legs of every proxied request. Neutron
   has no namespace sharing: either Suricata rides the WAF instance, or
   Tap-as-a-Service mirrors the ports. `Sensor(name, watches)` already carries
   the relationship either way, but nothing *supplies* it: Docker reads it off
   `NetworkMode: container:<id>` and Neutron has no such fact, so the sketch
   assumes the sensor watches the gateway. That assumption belongs in the
   declaration, beside the roles.

3. **Nothing says how to get a shell.** `runner()` on Docker is `docker exec`,
   which needs no credential. The sketch needs an ssh user, a key and an address
   the platform can reach, and none of the three has anywhere to live. They are
   credentials, so the answer is probably settings rather than the declaration -
   but the declaration's `roles` values are host names in substrate vocabulary
   (`fsl-kali` is a compose `container_name`, a Nova server name and, after
   `removeprefix("fsl-")`, a compose unit), and a Nova server name is not unique
   and is not addressable.

4. **Floating IPs and router SNAT.** A Nova instance reports both a fixed and a
   floating address, and the adapter keeps the fixed one. An attack leaving the
   range through a Neutron router is source-NATed, so the address Suricata sees
   is the router's, not the attacker's - the stamping proxy solves this on
   Docker and has no Neutron equivalent yet.

`docs/ARCHITECTURE.md` has the mechanism and the measured numbers.

## Done since v1.0

One line each.

**The range**
- The platform is told what the range means rather than asking the daemon:
  one declaration, a Docker adapter that fills in what it allocated, and a test
  that fails when compose and the declaration disagree.
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

**What the operator actually typed**
- Every command typed at the terminal is recorded with the case that was open
  when it was typed: the box appends to a log on each prompt, stamping it with
  the marker the proxy is already labelling traffic with, and the platform
  reads it through `runner("attacker")`.
  `GET /api/sessions/<id>/commands/` returns what was typed inside the
  session's window. `nmap` leaves a record now, not just an alert with no case
  behind it.

**Where an attack sits in an intrusion**
- Every attack case carries the Mandiant life cycle stage it belongs to, an
  ATT&CK technique id and a CAPEC pattern id, and the console links both ids to
  the catalogue that defines them. `technique: SQLi` was an abbreviation from
  nowhere; T1190 and CAPEC-66 can be checked.
- The catalogue reports which stages the cases reach and which five of the
  eight they never do, computed from the cases rather than written down, and
  the red console says both. `docs/THREAT-MODEL.md` says which threat is being
  emulated, that there is no C2 at all, and what the range cannot show.

**Smaller**
- Dropped djangorestframework and Kibana; collapsed the Django boilerplate;
  shrank `redteam/harness.py`; deleted the dead marker-probing.
- Tried to replace Django entirely and did not: it cost more lines than it
  saved.

## Backlog

The user's direction, from the Korean red team playbook at www.xn--hy1b43d247a.com:
the range should cover more of the attack lifecycle than initial access. Its
nine stages are attacker infrastructure, initial reconnaissance, initial
access, foothold, privilege escalation, internal reconnaissance, lateral
movement, persistence, mission. The inside now exists; what is missing is
below.

### 1. A foothold to escalate from

Absent: foothold, privilege escalation, persistence. There is no code
execution on the target, so the estate is reached through the application
rather than from a shell on it, and there is nothing to escalate. Whether that
matters is a scope decision: a C2 and a foothold is a large step, and the
range may be more useful as a web-entry range that is honest about where it
stops.

### 2. Show the operator log in the console

The API records and returns what was typed; nothing draws it. A window case in
the blue console still says only that an attack happened. The commands are
there to be shown beside it.

## Known gaps

- `test_declaration.py` compares two files and never the running range. Six
  deliberate breakages - an undeclared network, an unmarked one, a renamed
  segment, a changed origin, a removed origin, a role pointing at no container -
  are each caught by name, and a `name:` override no longer breaks anything
  because the binding is a label rather than the name. It still cannot see a
  range that does not match either file.
- The `platform` container still mounts the Docker socket, now reached as a
  non-root user through a group whose id compose passes as `DOCKER_GID`
  (`bin/docker-gid` prints it; read off the host instead of inside the VM it
  comes back `1` and the platform answers 200 with `permission denied` in the
  body). It is still a container escape path and it disappears with the substrate: an
  OpenStack adapter authenticates rather than mounting anything.
- The Kali terminal on 7681 is an unauthenticated root shell. Local lab only.
- `elastic.fetch` reads at most 5000 documents per ingest and has no
  `event_type` filter, so `http` records burn the same budget. It now reports
  what it could not read and the console says so, but a long session still
  scores on part of its evidence. Paginating with `search_after` needs a
  monotonic write-time field, which the index does not have; one
  `set: _ingest.timestamp` processor in the pipeline would give it one.
- `Detection.raw` for ModSecurity holds only the `message` sub-object. The
  drawer now names the CRS rule and says the ruleset lives in the WAF, so the
  operator is not stuck, but the record is still a fragment.
- The operator log lives inside the attacker box and is lost when it is
  recreated, and its stamps are whole seconds - a session's window is widened
  to whole seconds to match, so two sessions less than a second apart would
  each claim the other's commands.
- Two labelled terminal windows less than four seconds apart overlap, because
  `WINDOW_SLACK` is two seconds at each end. The console does not say so.
- Nothing stops two people opening the same session in four windows. One user,
  one session was a deliberate scope decision.
- The console loads Tailwind from `cdn.tailwindcss.com` on every page, so an
  isolated range renders unstyled.

## Tried and thrown away

**Elasticsearch as the only store, 2026-09-22.** The idea was to delete the
Django `Detection` table and query the index directly: one copy of the truth,
no 5000-document cap, aggregations instead of Python loops. Killed at the
scoping stage, before any production code, by three measurements:

- Window correlation has no Elasticsearch form. Both event clocks are mapped
  `keyword`; the only `date` field is filebeat's read clock, which runs ahead
  of ModSecurity's by a median of 2.5s and p90 of 7.9s against a two-second
  `WINDOW_SLACK`. 64% of ModSecurity alerts would land in the wrong window.
- It does not re-derive the same score, it changes it. One session's frozen 66
  detections come back as 98 when its window is re-queried, and no closed
  session could be told from a regression.
- 85 of the tests are written against the `patch(elastic.fetch)` seam and the
  floor may only rise, so most of the work is rewriting tests to stand still.

The motivating measurement was also wrong, which is the more useful lesson:
`/top/` at 44-82ms against an aggregation at 3-9ms is not Django versus
Elasticsearch. `/map/` walks the same rows in Python in 3.5ms; the 40ms was the
Docker call in `_segments()`, since removed.

Worth keeping from it: a `set: _ingest.timestamp` processor is the one line
every future version of that idea depends on.
