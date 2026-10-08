# Now

The state of the work in flight, kept short: it is the handover across
compaction, not a history. The product backlog and the finished record are in
`docs/STATE.md`; rulings in `docs/DECISIONS.md`; detail in `git log`.

Updated: 2026-10-08

## In flight: building the composable, session-isolated learning MVP

Read first, before planning or building: the canonical spec
`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`
and the living-doc artifact 37HeLkkLEFQgVWbwLuXH7S, whose items marked as
confirmed are final. Read them directly, not this file's summary or memory. Do not overturn a
confirmed item without quoting it and showing where it fails. Example: the edge
origin subnets stay fixed and shared and only `estate`/`mgmt` float per session,
so there is no per-session edge and no subnet collision.

The direction is approved to build. Rationale: `docs/DECISIONS.md` (2026-10-08
entries).

What the MVP is: a learning-first platform, one session with two settings
(guidance on/off; baseline rules minimal or full CRS). The differentiator: the
learner tunes CRS or writes a Suricata rule that blocks a real attack, checked
against the target's own records rather than a flag or quiz, and passes only
when every malicious variant is blocked and every benign case passes. Scope: WAF
(ModSecurity/CRS, tuning) and IDS/IPS (Suricata, detection); firewall out.
Sessions are isolated instances composed from reusable elements; one built image
backs many scenarios.

## Build order (compose first; OpenStack deferred)

The steps below are numbered 1-8. Spec MVP item 1 is steps 1+2 here; spec items
2-7 are steps 3-8.

Landed 2026-10-08 (fast gate only, unit and console; the live two-project
acceptance has not run): step 3, commit 81fb283. WARGAMES is discovered from
`wargames/<id>/scenario.yaml` (name, description, image, public_url,
objective_model, case_file) and validated at import (platform/wargames.py:41-50).
WARGAMES stays a dict, so no call site changed (views.py:166,368 membership;
three tests patch.dict it; two do dict(WARGAMES["board"], ...); test_compose
set(WARGAMES)). board public_url is the literal http://board.com. The `image`
field (fsl/board:mvp, fsl/corp:mvp) is declared and read by nothing yet; steps 1
and 2 consume it. Metrics: `bin/measure`, `metrics.json`. board-easy/board-hard
was not added: platform/tests/test_compose.py:251 ties set(WARGAMES) to the set
of wargames/<id>/compose.yaml folders, so a new scenario id needs its own compose
folder, which the step-1 compose split reworks; do them together, live.

Steps 1, 2 and 4-8 need the live stack (`docker compose up` plus the acceptance
suite), which a worktree cannot drive. Do not land them against the fast gate
alone. Agreed with the user 2026-10-08: the live build runs on the OpenStack
deployment (192.168.0.100), driven together. Each step starts at gate 1 (present
the plan, wait), runs live, and runs the acceptance there; push waits until that
acceptance passes on this branch. Constraints found 2026-10-08:

- Step 5: loot.ground_truth (loot.py:20-21) builds the URL from
  settings.BOARD_API_URL; it is called for the session baseline at views.py:183
  and for the readiness probe at views.py:1215 (`loot.ground_truth("board")`).
  The effect reader uses a role runner with a fixed role: `runner("corp-db")` at
  views.py:188 (baseline) and views.py:408 (observe). The address resolver can
  reuse docker.py:127-145 `_segment` (Containers[].IPv4Address -> Node.address).
- Step 4: docker.py `runner` (docker.py:56-74) execs `declared.host(role)`, a
  fixed container name from declaration.yaml roles (declaration.yaml:48-57). The
  per-project lookup pattern exists at docker.py:169-185 (`_modes` filters by
  label com.docker.compose.project). Literal container names in tests: about 194
  occurrences in 36 test files, some of them OpenStack VM names that do not
  change. Examples: test_declaration.py:239; test_openstack_sketch.py:295
  (`:293` is a role name); platform/tests/test_range_seam.py:116,203 (container
  names) and :223-224 (compose service names, run without `-p`). The ttyd proxy
  is hardwired to fsl-kali/fsl-waf (nginx.conf:63,73; entrypoint.sh:43-44).
- Step 6: elastic.fetch (elastic.py:17-23) already takes `index`; views.py:702
  and :1317 pass settings.ELASTIC_INDEX. Pass a per-session
  fsl-logs-<session>-* instead.
- Step 2: both wargame app services are `build: ./app` with no tag
  (wargames/board/compose.yaml:4, wargames/corp/compose.yaml:4). Add
  `image: fsl/board:mvp` / `fsl/corp:mvp` beside `build` (build and tag), so the
  shared `up` still builds and session.yaml can reference the image only.
  `services` is gated down-only; moving waf/suricata/filebeat into session.yaml
  lowers it because session.yaml is not on the include chain. Record the reason
  or make bin/measure count it.

1. Split compose into a shared control plane (platform, ES, Kibana, single) and
   a per-session data-plane stack (session.yaml: target, db, waf, suricata,
   filebeat) started with `docker compose -p fsl-<session>`. Do not replicate the
   control plane: running the whole current compose.yaml per session would start
   a second orchestrator, ES and Kibana (the review's high-severity finding).
2. Build each target image once and tag it (fsl/board:mvp); reference it by
   `image:`, never a per-session `build:`. Today wargames/board/compose.yaml:4
   builds it, which blocks one image serving many scenarios.
3. Done (81fb283): WARGAMES is discovered from `wargames/<id>/scenario.yaml`.
   Still open: prove one image, many scenarios with board-easy/board-hard (needs
   their own compose folders per test_compose.py:251, so it goes with step 1),
   and add the planned `defense` field (Suricata ruleset, WAF vhost) once step 7
   gives it a consumer.
4. declaration.yaml roles -> compose service names; the runner resolves
   service to container per project (pattern: platform/range/docker.py:169-173
   label lookup). Delete the container_name pins and `name: fsl`; float only the
   internal `estate`/`mgmt` subnets (keep the edge origin subnets fixed; they
   carry attacker origin for GeoIP attribution); ephemeral host ports.
5. loot.ground_truth and the effect runner read the session's own target
   address (docker.py Node.address inspection; cross-project DNS does not
   resolve), with the baseline on Session.baseline, captured after the target is
   healthy.
6. Per-session ES index fsl-logs-<session>-* into elastic.fetch
   (platform/ingest/elastic.py:17-23 unchanged; `index` is already a parameter).
7. The lesson: board ?sort= SQLi (CVE-2021-35042). The WAF runs
   `SecRuleEngine DetectionOnly` today (deploy/waf/modsecurity.conf:1); switch it
   to `On` with CRS and tune CRS to block the attack while the benign O'Brien
   search passes. Suricata already shares the WAF network namespace
   (compose.yaml:114, `network_mode: "service:waf"`); per session, one sensor.
8. Acceptance (live gate, bin/verify): two concurrent sessions, each scoring only
   its own target's data/effect and its own alerts. The fast unit and console
   gate covers the scenario loader and address wiring, not isolation.

## Build-time spikes
- Log highlight on the real Kibana (stable data-test-subj selectors); fall back
  to a task panel beside the Kibana iframe if it does not hold.
- CRS starting configuration: does CRS at the default paranoia level block this
  SQLi, or raise a false positive on O'Brien? The answer sets the lesson's
  starting state (tune down an over-blocking CRS, or tune up a permissive one).

## What must not break
- Each isolation seam keeps a single owner (loot/effect, elastic, suricata,
  attacker); add a session address, not new knowledge. The target decides
  whether it was beaten.
- Ratchet: the resolvers are new core Python that can raise core_loc; keep them
  minimal, reuse the existing validators (wargames.py:22-39, :65-81, :128-147),
  and run bin/measure before committing; the tests floor only rises.
- Work this touches that is more than a deletion: the container-name pins in
  tests (step 4 above); the ttyd vm-terminal proxy hardwired to fsl-kali/fsl-waf;
  the benign true-negative cases re-baselined with the WAF in blocking mode; a
  per-session Suricata ruleset / WAF vhost is a parameterised mount, not only a
  YAML key.

## Deferred (OpenStack work, not MVP)
Per-session CIDR allocation (fabric.py:11); removal of the single-session lock
(views.py:171-173, OpenStack only, a no-op on docker) and of the bin/verify
open-session guard (bin/verify:56-73); splitting pfSense's edge and sensor roles
(declaration.yaml:75-76); per-session ES containers (instead of shared ES with a
per-session index). The pfSense console pane and the :8080 proxy were removed
on 2026-10-08 (firewall dropped from scope); pfSense stays as the OpenStack edge
and Suricata host.

## Also still open from before
- dev is at a6fb72b (fast-forward, 2026-10-08): the earlier tidy-up, the
  direction docs, step 3 (scenario.yaml) and the prevention-measures commit. Only
  the fast gate (unit and console) has run; the live acceptance (test/,
  concurrent-session non-interference) has not. A worktree cannot drive it; run
  it in the OpenStack build session. 562486d (platform code, prior session) is
  the one change in that range not yet verified live.
- The main checkout's local dev may need a fast-forward so the desktop app and
  harness load the current project config (do it in the main checkout).

## To do
The open items found by the 2026-10-08 doc review (seam exceptions, `/vm-terminal/` on compose, the `?sort=`
extraction) are a checklist under backlog 0 in `docs/STATE.md`.
