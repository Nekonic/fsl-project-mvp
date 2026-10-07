# Composable, session-isolated learning MVP — design

Status: approved to build (2026-10-08). The user-facing version is the Korean
living doc (Claude Docs artifact 37HeLkkLEFQgVWbwLuXH7S); this file is the
canonical English spec. Four interview rounds plus three validation/research
workflows (direction critique, "how others teach detection rules", "resolve open
items by majority") produced it; the per-decision rationale is in
docs/DECISIONS.md (2026-10-08 entries).

## What this builds and why

fsl is LEARNING-FIRST: guided study -> hands-on practice, with the scored
attack/defence wargame being the same session run without the guidance. Learning
and wargame are NOT separate products — one session, one engine, one target, one
score, with two dials:

- guidance (lesson steps) on/off
- pre-applied baseline rules: minimal (the learner's own rule is the defence) vs
  full CRS + custom (wargame)

Goal (user's words): learn security monitoring / log analysis; see how attacks
are detected and logged (attacker view) and how to detect/tune rules to stop them
(defender view). Open-source fundamentals (Suricata, ModSecurity/CRS, ELK,
OpenStack) over commercial clouds. Red and blue equally. Used by a university
club now; possibly public later. Few developers, little capital -> this repo is
the cheap-to-throw-away MVP that finds the right shape.

## The wedge (what no comparable platform does)

The learner writes/tunes a rule that ACTUALLY BLOCKS a real attack, and success
is verified from the TARGET'S OWN state — not a flag or quiz. Most platforms
(TryHackMe, HTB, LetsDefend, CyberDefenders, Splunk BOTS) verify by flag/answer
submission; only enterprise ranges (RangeForce, Immersive) check an outcome, and
none as strictly as fsl's "all malicious variants blocked AND all benign traffic
passes, read from target ground truth." That strictness is the differentiation.

## Scope

Teach NETWORK + WEB PERIMETER defence first:

- Suricata (IDS): DETECT. Learners write signatures FROM SCRATCH — the field-
  standard pedagogy for IDS (SANS SEC503, HTB Academy, TryHackMe).
- ModSecurity / OWASP CRS (WAF): BLOCK. Learners learn by TUNING CRS (paranoia
  levels + exclusions), NOT by writing SecRules from scratch — the field
  deprecates from-scratch SecRules for production (OWASP CRS docs: "directly
  modifying CRS rules essentially creates a fork"; netnea's 12-tutorial series
  has no "write your own rule" tutorial).

Firewall is OUT of scope as a lesson: a firewall filters L3/L4 (IP/port), so it
cannot defend a web attack (SQLi rides the same tcp/80 as legitimate traffic);
teaching "block SQLi with a firewall" would teach a misconception. pfSense STAYS
as load-bearing OpenStack infrastructure (edge router + the host that runs the
Suricata IPS); only the firewall LESSON and the pfSense console pane / :8080
proxy are not built.

Roadmap (later, user-requested, recommended order): host/endpoint + SIEM
(Wazuh/Elastic Agent) + Sigma; UTM/NGFW; Windows Server AD DS attack/defence;
YARA, DNS/proxy, cloud audit logs.

## The lesson

Loop: READ (theory + read the attack's logs/alerts in Kibana + rule anatomy) ->
WRITE/TUNE (author a Suricata signature, or tune CRS) -> REPLAY (fire the real
attack case) -> VERIFY (auto-complete from target ground truth).

Difficulty rises ONE AXIS AT A TIME across the ordered path: fade the hint axis
first (finished rule -> partial/blanks -> none), THEN attack/topic complexity,
THEN rule difficulty. Never all three at once (cognitive-load anti-pattern;
confounds failure diagnosis). MVP uses a fixed sequence; adaptive fading later.

Completion is AUTO-VERIFIED and gated on BOTH: every malicious variant blocked
(loot/effect ground truth holds) AND every benign case still passes (no false
positive) — the TP/FP/FN/TN scoreboard that already exists. "Blocked the one
payload shown" is NOT enough (a block-everything rule must fail the benign gate).

"Blocked" witness (the P1 decision): TARGET STATE is primary — the attack never
reached/affected the target (loot unchanged / the app never logged the request);
the ModSec 403 / Suricata drop line is SECONDARY corroboration only. No industry
norm exists for this low-level witness; it is fsl's call.

Learner-facing feedback: a PASS/FAIL gate (mirroring the real gate) plus plain-
language per-attempt diagnostics derived from TP/FP/FN/TN ("variant union-select
still got through — 2 of 3 blocked"; "your rule also blocked the benign O'Brien
search"). Do NOT show raw TP/FP/FN/TN labels or precision/recall to the learner,
and NO gamification (points/badges/leaderboards). Branding: perimeter-first is a
deliberate "detection-engineering / rule-authoring" track, not the majority SOC
order (fundamentals -> SIEM/endpoint -> network IDS); the closest peer analog is
HTB Academy's "Working with IDS/IPS".

## Composability + session isolation (both MVP requirements)

A scenario is a COMPOSITION of reusable elements, and sessions are ISOLATED
instances — both mandatory in the MVP. Audit found the leaves reusable (cases
redteam/cases/*.yaml, objectives wargames/*/objectives.yaml, topology
declaration.yaml) but the assembly hardcoded: the scenario registry is a 2-entry
Python dict (wargames.py:13-39), image<->scenario is 1:1 (each scenario builds
its own image, so "one image many scenarios" is FALSE today), loot.py/effect.py
are welded to one target, and the range is single-session with one shared
target/ES.

Target architecture:

- SHARED control plane (platform + Elasticsearch + Kibana): one, long-lived.
- PER-SESSION data plane (target + db + WAF + Suricata + Filebeat): its own
  instance. Do NOT replicate the control plane per session.
- docker compose (dev + production-on-a-VM): one compose PROJECT per session
  (`docker compose -p fsl-<session>`), which the Docker adapter already accepts
  (docker.py:28-30 `project=`). Compose prefixes containers/networks/volumes by
  project -> collision-free concurrent stacks.
- OpenStack (real range, LATER): the mirror — per-session network + VMs booted
  from the already-snapshotted Glance image (image reuse already exists), tagged
  by session. Deferred from the MVP.

One image, many scenarios: build each target image ONCE and TAG it (e.g.
fsl/board:mvp); scenarios reference it by `image:` (never `build:` per session).
A descriptor `wargames/<id>/scenario.yaml` (discovered per directory, loaded by
the same generic validator pattern as objectives/cases) composes: image ref +
cases + objectives + defense (CRS tuning config / Suricata ruleset + WAF vhost).
Prove it with `board-easy`/`board-hard` on the ONE board image, differing only in
objectives + ruleset.

Seams stay intact — each takes a session-scoped ADDRESS, not new knowledge:

- loot.py + effect.py remain the only ground-truth readers; they read the
  SESSION's own target address (resolved from the adapter's network inspection,
  NOT a cross-project DNS name — cross-project Docker DNS does not resolve), not
  process-wide BOARD_API_URL. Session.baseline already stores the per-session
  snapshot.
- ingest/elastic.py stays the only ES-aware file; elastic.fetch already takes
  `index` (elastic.py:17-23) — pass a per-session index `fsl-logs-<session>-*`
  (each session's Filebeat ships to its own index; ES stays shared, the index is
  the isolation boundary).
- rules/suricata.py and attacker.py: one instance per session project.

## The MVP (cheapest viable, per the adversarial review)

1. Split compose: a shared control-plane project (platform + ES + Kibana,
   unchanged, single) and a per-session data-plane stack (session.yaml: target +
   db + waf + suricata + filebeat) launched `-p fsl-<session>` from a target
   image BUILT ONCE and TAGGED, referenced by `image:` (never rebuilt per
   session).
2. Data-driven scenarios: move the WARGAMES dict (wargames.py:13-39) into
   discovered `wargames/<id>/scenario.yaml` with an `image:` ref; prove
   one-image-many-scenarios with board-easy/board-hard on the one tagged image.
3. declaration.yaml roles name compose SERVICES (not fixed container names); the
   runner resolves service->running container per project (the pattern exists:
   docker.py:169-173 filters by label com.docker.compose.project). Delete the
   hardcoded container_name entries and the `name: fsl` project pin; float only
   the internal estate/mgmt subnets (PRESERVE the edge origin subnets — they
   encode attacker origin for geo-attribution); make host ports ephemeral.
4. Per-session ground truth: loot.ground_truth and the effect runner read the
   session's own target address (docker.py Node.address inspection), baseline on
   Session.baseline, captured after the target is healthy and before the attacker
   acts.
5. Per-session ES index `fsl-logs-<session>-*` passed into elastic.fetch;
   elastic.py untouched.
6. The WAF+IPS lesson: board SQLi via ?sort= order_by (CVE-2021-35042 — the one
   attack that moves ground truth; the ' OR 1=1-- vs /search/ attack is
   parameterised by the ORM and cannot exfiltrate, so it was rejected). WAF is
   SecRuleEngine On with CRS; the lesson TUNES CRS so the attack is blocked (loot
   holds) and the benign O'Brien search passes (no FP). Suricata rides the WAF's
   netns (network_mode: service:waf) as the inline tap, paired inside the
   per-session stack (one sensor per session, never shared).
7. Acceptance = NON-INTERFERENCE: two sessions started concurrently, each scoring
   only its own target's loot/effect and its own alerts. This is a LIVE-gate
   (bin/verify) property; the fast unit+console gate only covers the scenario
   loader and address wiring.

## Build-time spikes

- Log-analysis guidance: the user wants a game-tutorial-style clickable HIGHLIGHT
  on real Kibana. No comparable platform overlays the real tool's DOM, and a
  same-origin overlay couples to Kibana's version/DOM. SPIKE whether a highlight
  anchored on stable data-test-subj selectors works here; if it does, use it (pin
  the Kibana version, degrade gracefully); if not, fall back to a side
  task/instruction panel beside the Kibana iframe (standard, version-robust, also
  acceptable to the user). The same-origin XSS concern is an UNVERIFIED
  hypothesis, accepted for the internal/club phase, reviewed before public launch.
- CRS start posture: check whether default-PL CRS already blocks this SQLi and
  whether it false-positives on the benign O'Brien search; that sets the lesson's
  starting state (tune down an over-blocking CRS vs tune up a permissive one).

## Deferred (OpenStack debt, not MVP)

Per-session CIDR allocation (replacing fabric.py:11 fixed blocks); removal of the
single-session lock (views.py:171-173) and the bin/verify open-session guard
(bin/verify:56-70); splitting pfSense's edge+sensor coupling (declaration.yaml:
75-76) so the sensor is independent; per-session ES containers (vs shared ES +
per-session index).

## What must not break

- The isolation seams (loot.py/effect.py ground truth, ingest/elastic.py ES,
  rules/suricata.py Suricata, attacker.py attacker) stay the single owner of
  their concern — add a session-scoped address, never new knowledge.
- The target decides whether an attack succeeded; the lesson's completion reads
  loot/effect ground truth, never the platform's belief.
- The ratchet: core_loc/services/dependencies down-only, tests up-only. The
  scenario loader and the service->container + address resolvers are new core
  Python that can push core_loc UP — keep them minimal, lean on the existing
  generic validators (wargames.py:54-70,117-142), run bin/measure before
  committing; moving the WARGAMES dict to YAML offsets some of it.
- Real work this touches (not free deletions): the ~dozen tests that pin literal
  container names (test_declaration.py:239-240 and others), the ttyd vm-terminal
  proxy that hard-wires fsl-kali/fsl-waf (nginx.conf:63,73; entrypoint.sh:43-44),
  and the benign true-negative cases re-baselined against CRS-On.
