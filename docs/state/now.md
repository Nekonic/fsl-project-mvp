# Now

The live state of the work in flight. Small on purpose: the orchestrator keeps
its own context, so this is the handover across compaction, not a full history.
The product backlog and the finished record stay in `docs/STATE.md`; rulings
are in `docs/DECISIONS.md`; detail is in `git log`.

Updated: 2026-10-08

## In flight: building the composable, session-isolated learning MVP

Direction is firm and approved to build. Canonical spec:
`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`.
Rationale: `docs/DECISIONS.md` (2026-10-08 entries). User-facing Korean version:
Claude Docs artifact 37HeLkkLEFQgVWbwLuXH7S. Produced by four interview rounds +
three workflows (direction critique, how-others-teach-rules,
resolve-open-items-by-majority).

What the MVP is: a LEARNING-FIRST platform — one session with dials (guidance
on/off; baseline rules minimal vs full CRS). The wedge: the learner tunes CRS /
writes a Suricata rule that really BLOCKS a real attack, verified from the
TARGET's own state (not a flag/quiz), gated on all-variants-blocked AND
benign-passes. Scope: WAF (ModSec/CRS, tuning) + IPS (Suricata, detect);
firewall out. Sessions are isolated instances composed from reusable elements;
one built image backs many scenarios.

## Build order (compose substrate first; OpenStack deferred)

1. Split compose into a SHARED control plane (platform + ES + Kibana, single) and
   a PER-SESSION data-plane stack (session.yaml: target + db + waf + suricata +
   filebeat) launched `docker compose -p fsl-<session>`. Do NOT replicate the
   control plane (running the whole current compose.yaml per session would spin a
   2nd orchestrator/ES/Kibana — the review's high-severity finding).
2. Build each target image ONCE and TAG it (fsl/board:mvp); reference by
   `image:`, never `build:` per session (wargames/board/compose.yaml:4 rebuilds
   today — the "one image, many scenarios" blocker).
3. Move the WARGAMES dict (platform/wargames.py:13-39) to discovered
   `wargames/<id>/scenario.yaml` (image + cases + objectives + defense), loaded
   by the existing generic validator pattern; prove one-image-many-scenarios with
   board-easy/board-hard on the one tagged board image (differ only in
   objectives + Suricata ruleset).
4. declaration.yaml roles -> compose SERVICE names; runner resolves
   service->container per project (pattern exists: platform/range/docker.py:169-173
   label lookup). Delete container_name pins and `name: fsl`; float only internal
   estate/mgmt subnets (PRESERVE edge origin subnets — attacker geo-attribution);
   ephemeral host ports.
5. loot.ground_truth + the effect runner read the session's own target ADDRESS
   (docker.py Node.address inspection — NOT cross-project DNS, which does not
   resolve), baseline on Session.baseline, captured after the target is healthy.
6. Per-session ES index fsl-logs-<session>-* into elastic.fetch
   (platform/ingest/elastic.py:17-23 untouched; `index` is already a param).
7. The lesson: board ?sort= SQLi (CVE-2021-35042), WAF SecRuleEngine On with CRS;
   tune CRS to block it while the benign O'Brien search passes; Suricata inline on
   the WAF netns (network_mode: service:waf), one sensor per session.
8. Acceptance (LIVE gate, bin/verify): two concurrent sessions, each scores only
   its own loot/effect and its own alerts. The fast unit+console gate only covers
   the scenario loader and address wiring, not actual isolation.

## Build-time spikes
- Log-highlight feasibility on real Kibana (stable data-test-subj selectors);
  fall back to a side task panel beside the Kibana iframe if it does not hold.
- CRS start posture: does default-PL CRS block this SQLi / FP on O'Brien? sets
  the lesson's starting state (tune down an over-blocker vs up a permissive one).

## What must not break
- Seams stay single-owner (loot/effect, elastic, suricata, attacker) — add a
  session address, not new knowledge. The target decides whether it was beaten.
- Ratchet: the scenario loader + resolvers are new core Python that can push
  core_loc UP — keep minimal, lean on the existing generic validators
  (wargames.py:54-70,117-142), run bin/measure before committing; tests floor
  up-only.
- Real work this touches (not free deletions): the ~dozen tests pinning literal
  container names (test_declaration.py:239-240 and others); the ttyd vm-terminal
  proxy hard-wiring fsl-kali/fsl-waf (nginx.conf:63,73, entrypoint.sh:43-44); the
  benign TN cases re-baselined against CRS-On; per-session Suricata ruleset / WAF
  vhost is a parameterised mount, not just a YAML key.

## Deferred (OpenStack debt, not MVP)
Per-session CIDR allocation (fabric.py:11); single-session lock
(views.py:171-173, OpenStack-only — a no-op on docker) + bin/verify open-session
guard removal; pfSense edge+sensor split (declaration.yaml:75-76); per-session ES
containers (vs shared ES + per-session index). The firewall console pane + :8080
pfSense proxy removal is also pending (firewall dropped from scope) — pfSense
itself STAYS as the OpenStack edge + Suricata host.

## Also still open from before
- Three tidied commits (f981e9b/562486d/10aa601) on this branch are UNPUSHED to
  dev; push is the human's, fast-forward. Full acceptance must run on this
  branch's stack before the push (cannot drive the live gate from a worktree).
