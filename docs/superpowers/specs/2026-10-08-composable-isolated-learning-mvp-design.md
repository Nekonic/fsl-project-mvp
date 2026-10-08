# Composable, session-isolated learning MVP: design

Status: approved to build (2026-10-08). MVP item 2 (scenario discovery from
`wargames/<id>/scenario.yaml`) landed in 81fb283; the other items are not built.
The user-facing version is the Korean living doc (Claude Docs artifact
37HeLkkLEFQgVWbwLuXH7S); this file is the canonical English spec. Four
interview rounds and three research workflows produced it; the rationale for
each decision is in docs/DECISIONS.md (2026-10-08 entries).

## What this builds and why

fsl is learning-first: guided study, then hands-on practice. The scored
attack/defence wargame is the same session run without the guidance. Learning
and wargame share one session, engine, target and score, and differ in two
settings:

- guidance (lesson steps) on or off;
- pre-applied baseline rules: minimal (the learner's own rule is the defence) or
  full CRS plus custom rules (wargame).

Goal (user's words): learn security monitoring and log analysis; see how attacks
are detected and logged (attacker view) and how to write and tune rules that stop
them (defender view). Open-source tools (Suricata, ModSecurity/CRS, ELK,
OpenStack) over commercial clouds; red and blue team equally. A university club
uses it now; it may be public later. The team is small with little funding, so
this repo is the cheap, disposable MVP that finds the right shape.

## Differentiator

The learner writes or tunes a rule that blocks a real attack, and success is
checked against the target's own records (ground truth), not a flag or quiz.
Most platforms (TryHackMe, HTB, LetsDefend, CyberDefenders, Splunk BOTS) check a
submitted flag or answer; enterprise ranges (RangeForce, Immersive) check an
outcome, but none require that every malicious variant is blocked and every
benign case passes, as read from the target's ground truth.

## Scope

Network and web perimeter defence first:

- Suricata (IDS) detects. Learners write signatures from scratch, the usual way
  IDS is taught (SANS SEC503, HTB Academy, TryHackMe).
- ModSecurity with OWASP CRS (WAF) blocks. Learners tune CRS (paranoia levels
  and rule exclusions) and do not write SecRules from scratch; the CRS docs
  advise against it for production ("directly modifying CRS rules essentially
  creates a fork"), and netnea's 12-tutorial series has no "write your own rule"
  tutorial.

Firewall is out of scope as a lesson. A firewall filters at L3/L4 (IP and
port); SQLi uses the same tcp/80 as legitimate traffic, so a firewall lesson on
SQLi would teach a misconception. pfSense stays as OpenStack infrastructure
(edge router and the host that runs the Suricata IPS). The firewall lesson, the
pfSense console pane and the :8080 proxy are out of scope.

Roadmap (later, user-requested, recommended order): host/endpoint and SIEM
(Wazuh/Elastic Agent) with Sigma; UTM/NGFW; Windows Server AD DS attack and
defence; YARA, DNS/proxy and cloud audit logs.

## The lesson

Loop: read (theory, the attack's logs and alerts in Kibana, rule anatomy) ->
write or tune (a Suricata signature, or CRS tuning) -> replay (run the real
attack case) -> verify (completed automatically from target ground truth).

Difficulty rises along one axis at a time: first the hints fade (finished
rule, then partial with blanks, then none), then attack complexity, then rule
difficulty. Changing all three at once raises cognitive load and makes a failure
hard to diagnose. The MVP uses a fixed sequence;
adaptive fading comes later.

Completion is verified automatically and requires both: every malicious variant
is blocked (the exfiltrated-data and effect ground truth is unchanged) and every
benign case still passes (no false positive), using the existing TP/FP/FN/TN
scoreboard. Blocking only the one payload shown is not enough, and a rule that
blocks everything fails the benign check.

Evidence of a block (decision P1): target state is primary. The attack did not
reach or affect the target (data unchanged, or the app never logged the
request). The ModSecurity 403 or Suricata drop line is secondary corroboration.
There is no industry norm for this; it is fsl's choice.

Learner feedback: a PASS/FAIL result matching the real check, plus per-attempt
diagnostics in plain language derived from TP/FP/FN/TN ("variant union-select
still got through, 2 of 3 blocked"; "your rule also blocked the benign O'Brien
search"). The learner does not see raw TP/FP/FN/TN labels or precision/recall,
and there is no gamification (points, badges, leaderboards). The track is
positioned as detection engineering / rule authoring, which is not the usual SOC
training order (fundamentals, then SIEM/endpoint, then network IDS); the closest
comparable course is HTB Academy's "Working with IDS/IPS".

## Composability and session isolation (both MVP requirements)

A scenario is a composition of reusable elements, and each session is an
isolated instance. An audit found the parts reusable (cases in
redteam/cases/*.yaml, objectives in wargames/*/objectives.yaml, topology in
platform/range/declaration.yaml) and the assembly hardcoded. At approval time
the scenario registry was a two-entry Python dict; 81fb283 replaced it with
discovery from `wargames/<id>/scenario.yaml`. Still true at HEAD: each scenario
builds its own image (`build: ./app`, untagged), so one image cannot back
several scenarios; `api/loot.py` reads the board through the process-wide
`settings.BOARD_API_URL`, and the effect reader runs against the fixed role
`corp-db` (views.py:188, :408); the range runs one session against one shared
target and Elasticsearch.

Target architecture:

- Shared control plane (platform, Elasticsearch, Kibana): one long-lived
  instance, never replicated per session.
- Per-session data plane (target, db, WAF, Suricata, Filebeat): one instance per
  session.
- docker compose (dev, and production on a VM): one compose project per session
  (`docker compose -p fsl-<session>`). The Docker adapter already takes a
  project (docker.py:28-30 `project=`). Compose prefixes containers, networks
  and volumes with the project name, so concurrent stacks do not collide.
- OpenStack (real range, later): the equivalent is a per-session network and VMs
  booted from the existing Glance snapshot, tagged by session. Deferred from the
  MVP.

One image, many scenarios: build each target image once and tag it (e.g.
fsl/board:mvp); scenarios reference it with `image:`, never a per-session
`build:`. The descriptor `wargames/<id>/scenario.yaml` (discovered per
directory, validated like objectives and cases) composes an image reference,
cases and objectives. The `image` field is declared but nothing reads it yet. A
`defense` field (CRS tuning config, Suricata ruleset, WAF vhost) is planned and
not built; it is added once the lesson step gives it a consumer. Prove the
design with `board-easy`/`board-hard` on the one board image, differing only in
objectives and ruleset.

The isolation seams stay; each receives a session-scoped address and no new
knowledge:

- loot.py and effect.py remain the only readers of target ground truth. They
  will read the session's own target address (from the adapter's network
  inspection; cross-project Docker DNS does not resolve) instead of the
  process-wide BOARD_API_URL. Session.baseline already stores the per-session
  snapshot.
- ingest/elastic.py stays the only Elasticsearch-aware file. elastic.fetch
  already takes `index` (elastic.py:17-23); pass a per-session index
  `fsl-logs-<session>-*`. Each session's Filebeat ships to its own index; ES is
  shared and the index is the isolation boundary.
- rules/suricata.py and attacker.py: one instance per session project.

## The MVP (cheapest viable, per the adversarial review)

1. Split compose: a shared control-plane project (platform, ES, Kibana,
   unchanged, single) and a per-session data-plane stack (session.yaml: target,
   db, waf, suricata, filebeat) started with `-p fsl-<session>` from a target
   image built once and tagged, referenced by `image:` (never rebuilt per
   session).
2. Data-driven scenarios: the WARGAMES dict moves into discovered
   `wargames/<id>/scenario.yaml` with an `image:` reference (done in 81fb283,
   platform/wargames.py:41-50); prove one image, many scenarios with
   board-easy/board-hard on the one tagged image (not done).
3. declaration.yaml roles name compose services instead of fixed container
   names; the runner resolves service to running container per project (the
   pattern exists: docker.py:169-173 filters by label com.docker.compose.project).
   Delete the hardcoded container_name entries and the `name: fsl` project pin;
   float only the internal `estate`/`mgmt` subnets (keep the edge origin subnets
   fixed; they encode attacker origin for GeoIP attribution); make host ports
   ephemeral.
4. Per-session ground truth: loot.ground_truth and the effect runner read the
   session's own target address (docker.py Node.address inspection), with the
   baseline on Session.baseline, captured after the target is healthy and before
   the attacker acts.
5. Per-session ES index `fsl-logs-<session>-*` passed into elastic.fetch;
   elastic.py unchanged.
6. The WAF and IPS lesson: board SQLi via ?sort= order_by (CVE-2021-35042, the
   one attack that changes ground truth; the ' OR 1=1-- attack on /search/ is
   parameterised by the ORM and cannot exfiltrate data, so it was rejected).
   Today the WAF runs `SecRuleEngine DetectionOnly` with CRS
   (deploy/waf/modsecurity.conf:1); the lesson switches it to `On` and tunes CRS
   so the attack is blocked (data unchanged) and the benign O'Brien search
   passes (no FP). Suricata already shares the WAF's network namespace
   (compose.yaml:114, `network_mode: "service:waf"`); in the per-session stack
   each session gets its own WAF and sensor pair, never shared.
7. Acceptance is non-interference: two sessions started concurrently, each
   scoring only its own target's data/effect and its own alerts. This is a live
   gate (bin/verify) property; the fast unit and console gate covers only the
   scenario loader and the address wiring.

## Build-time spikes

- Log-analysis guidance: the user wants a game-tutorial-style clickable
  highlight on the real Kibana. No comparable platform overlays the real tool's
  DOM, and a same-origin overlay couples to Kibana's version and DOM. Test
  whether a highlight anchored on stable data-test-subj selectors works; if it
  does, use it (pin the Kibana version, degrade gracefully); if not, fall back to
  a task panel beside the Kibana iframe (standard, robust across versions, also
  acceptable to the user). The same-origin XSS concern is an unverified
  hypothesis, accepted for the internal club phase and reviewed before a public
  launch.
- CRS starting configuration: check whether CRS at the default paranoia level
  already blocks this SQLi and whether it raises a false positive on the benign
  O'Brien search. The answer sets the lesson's starting state (tune down an
  over-blocking CRS, or tune up a permissive one).

## Deferred (OpenStack work, not MVP)

Per-session CIDR allocation (replacing the fixed blocks at fabric.py:11);
removal of the single-session lock (views.py:171-173) and the bin/verify
open-session guard (bin/verify:56-73); splitting pfSense's edge and sensor roles
(declaration.yaml:75-76) so the sensor is independent; per-session ES containers
(instead of shared ES with a per-session index).

## What must not break

- The isolation seams (loot.py/effect.py for ground truth, ingest/elastic.py for
  ES, rules/suricata.py for Suricata, attacker.py for the attacker) each stay the
  single owner of their concern; they gain a session-scoped address, never new
  knowledge.
- The target decides whether an attack succeeded; lesson completion reads the
  exfiltrated-data or effect ground truth, never the platform's belief.
- The ratchet: core_loc, services and dependencies may only fall; tests may only
  rise. The service-to-container and address resolvers are new core Python that
  can raise core_loc; keep them minimal, reuse the existing generic validators
  (wargames.py:22-39 checked_scenario, :65-81 checked_objectives, :128-147
  checked), and run bin/measure before committing.
- Work this touches that is more than a deletion: about 194 occurrences of
  literal container names across 36 test files (some are OpenStack VM names that
  do not change; e.g. test_declaration.py:239-240), the ttyd vm-terminal proxy
  hardwired to fsl-kali/fsl-waf (nginx.conf:63,73; entrypoint.sh:43-44), and the
  benign true-negative cases re-baselined with the WAF in blocking mode.
