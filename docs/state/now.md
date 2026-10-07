# Now

The live state of the work in flight. Small on purpose: the orchestrator keeps
its own context, so this is the handover across compaction, not a full history.
The product backlog and the finished record stay in `docs/STATE.md`; rulings
are in `docs/DECISIONS.md`; detail is in `git log`.

Updated: 2026-10-08

## In flight: building the composable, session-isolated learning MVP

READ FIRST — the source of truth, before planning or building: the canonical
spec `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`
AND the `[확정]` living-doc artifact 37HeLkkLEFQgVWbwLuXH7S. Read them directly;
do not plan from this file's reconstruction or from memory, and never overturn a
`[확정]` decision without quoting it and showing where it fails (e.g. the edge
origin subnets are PRESERVED/shared and only estate/mgmt float per session — so
there is no per-session edge and no subnet collision; that is already decided).

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

Landed 2026-10-08 (fast gate only — unit+console; the live 2-project acceptance
has NOT run): **step 3 DONE** (commit d436839). The WARGAMES dict is now
discovered from `wargames/<id>/scenario.yaml` (name, description, image,
public_url, objective_model, case_file), validated at import; WARGAMES stays a
real dict so no call site changed (views.py:166,368 membership; three tests
patch.dict it; two do dict(WARGAMES["board"], ...); test_compose set(WARGAMES)).
board public_url is now literal http://board.com. The `image` field
(fsl/board:mvp, fsl/corp:mvp) is declared but not consumed yet — it is the anchor
for steps 2 and 1. core_loc flat 462, tests 1203->1209. board-easy/board-hard was
NOT added: test_compose:238 ties set(WARGAMES) to the set of wargames/<id>/
compose.yaml folders, so a new scenario id needs its own compose folder, which is
exactly what the step-1 compose split reworks — do them together, live.

Steps 1, 2, 4-8 remain and are LIVE-STACK work (they can only be proven by
`docker compose up` + the acceptance suite, which a worktree cannot drive). Do
NOT land them blind against the fast gate. AGREED 2026-10-08 (the user): the live
build runs on the OpenStack deployment (192.168.0.100), driven together — start
each step at gate 1 (present the plan, wait), execute live, run the acceptance
there; push is held until that acceptance passes on this branch. Precise
constraints found 2026-10-08:
- Step 5 seam: loot.ground_truth (loot.py:20-21) builds the URL from
  settings.BOARD_API_URL; views.py:1215 hardcodes loot.ground_truth("board") for
  the readiness probe; effect uses a role runner already (effect.snapshot via
  adapter.runner("corp-db"), views.py:188). The address resolver can reuse
  docker.py:127-145 _segment (Containers[].IPv4Address -> Node.address).
- Step 4: docker.py.runner (docker.py:56-74) execs declared.host(role) = a fixed
  container name from declaration.yaml roles (declaration.yaml:48-57). The per-
  project resolution pattern already exists at docker.py:169-185 (_modes filters
  by label com.docker.compose.project). Tests pinning literal names:
  test_declaration.py:239, test_openstack_sketch.py:293,295, test_range_seam.py:
  223-224. ttyd proxy hard-wires fsl-kali/fsl-waf (nginx.conf:63,73;
  entrypoint.sh:43-44).
- Step 6: elastic.fetch (elastic.py:17-23) already takes `index`; views.py:702,1317
  pass settings.ELASTIC_INDEX. Thread a per-session fsl-logs-<session>-* instead.
- Step 2: today both wargame app services are `build:` with no tag
  (board/compose.yaml:3, corp/compose.yaml:3). Add `image: fsl/board:mvp` /
  `fsl/corp:mvp` alongside build (build-and-tag) so the shared up still builds and
  session.yaml can reference by image: only. `services` is gated down-only (8) —
  moving waf/suricata/filebeat into session.yaml drops it; keep bin/measure honest
  (session.yaml is not on the include chain, so it vanishes from the count — record
  the reason or teach measure to count it).

1. Split compose into a SHARED control plane (platform + ES + Kibana, single) and
   a PER-SESSION data-plane stack (session.yaml: target + db + waf + suricata +
   filebeat) launched `docker compose -p fsl-<session>`. Do NOT replicate the
   control plane (running the whole current compose.yaml per session would spin a
   2nd orchestrator/ES/Kibana — the review's high-severity finding).
2. Build each target image ONCE and TAG it (fsl/board:mvp); reference by
   `image:`, never `build:` per session (wargames/board/compose.yaml:4 rebuilds
   today — the "one image, many scenarios" blocker).
3. DONE (d436839) — WARGAMES is discovered from `wargames/<id>/scenario.yaml`.
   Still open under this step: prove one-image-many-scenarios with
   board-easy/board-hard (needs their own compose folders per test_compose:238,
   so it rides step 1), and fold the Suricata ruleset / WAF vhost ("defense")
   into the descriptor once step 7 gives it a consumer.
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
- This branch is UNPUSHED and ahead of dev by five commits: the earlier tidy
  (three), the direction docs, and step 3 (scenario.yaml discovery + its docs, one
  commit). Push is the human's, fast-forward to dev. Full acceptance (live stack)
  must run on this branch before the push — a worktree cannot drive the live gate,
  so the fast gate is all that has run.
