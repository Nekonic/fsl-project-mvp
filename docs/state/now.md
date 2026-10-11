# Now

The state of the work in flight, kept short: it is the handover across
compaction, not a history. The product backlog and the finished record are in
`docs/STATE.md`; rulings in `docs/DECISIONS.md`; detail in `git log`. Numbers
are in `metrics.json` (`bin/measure`), not here.

Updated: 2026-10-11

## In flight: building the composable, session-isolated learning MVP

Read first, before planning or building: the canonical spec
`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`
and the living-doc artifact 37HeLkkLEFQgVWbwLuXH7S, whose items marked as
confirmed are final. Read them directly, not this file's summary or memory. Do
not overturn a confirmed item without quoting it and showing where it fails.
One deviation is recorded: `mgmt` stays shared rather than floating per
session (`docs/DECISIONS.md`, 2026-10-10).

What the MVP is: a learning-first platform, one session with two settings
(guidance on/off; baseline rules minimal or full CRS). The learner tunes CRS or
writes a Suricata rule that blocks a real attack, checked against the target's
own records, and passes only when every malicious variant is blocked and every
benign case passes. Scope: WAF (ModSecurity/CRS) and IDS/IPS (Suricata);
firewall out. Sessions are isolated instances composed from reusable elements.

## Build order (compose first; OpenStack deferred)

Spec MVP item 1 is steps 1+2 here; spec items 2-7 are steps 3-8.

1. Done (9e8e963): control plane `compose.yaml`, per-session `session.yaml` as
   `fsl-<id>`.
2. Done: target images built once and tagged, sessions start `--no-build`.
3. Done (81fb283): scenarios from `wargames/<id>/scenario.yaml`; the `defense`
   and `lesson` fields came with step 7. Still open: board-easy/board-hard (one
   image, many scenarios).
4. Built (bbde53d, 82d081d): roles resolve to compose services by label;
   container_name pins gone; `estate` session-owned, edges and `mgmt` shared.
5. Built (bbde53d): `Docker.address(role)` is the role's estate IP; loot and
   effect read the session's own target.
6. Built (83f92e0): Filebeat writes `fsl-logs-<session>-<day>`; ingest reads
   `fsl-logs-<session>-*`.
7. Built (4c4c7e8..a2b5eeb): the WAF lesson. Session settings
   `guidance`/`defense`; `rules/crs.py` writes the session's paranoia level and
   exclusions; the sensor's rule file is per session, seeded at open; `/waf/`
   and `/verify/` APIs; lesson note in the blue console (tuning is done in the
   session's WAF terminal since 2026-10-10; `PUT /waf/` stays for agents and
   `GET /waf/` reads the WAF's file); seeded logs for a
   guided session. Live-verified (`test/test_lesson.py`).
8. Live-verified (e307cc9, `test/test_concurrent_sessions.py`). Docker opens at
   most `FSL_MAX_SESSIONS` sessions (default 2); one more answers 409.

Live acceptance (the push gate), 2026-10-10, on the dedicated 8 GB/2 vCPU VM
`fsl-acceptance` (192.168.0.220, substrate docker): `bin/verify` all green
after the pre-push review fixes (af738b2): acceptance 146 passed and 0 failed
in 48 min 55 s, ratchet no regression; the later test-only commit was checked
by running its changed test live. Detail in `docs/DECISIONS.md` (2026-10-10,
the live acceptance and the pre-push review). The platform VM 192.168.0.210 is back on origin/dev
(870b15f), substrate openstack.

Commits 870b15f..HEAD are local on this branch, not pushed; push waits for the
user's approval.

Console redesign (2026-10-11): the five screens rebuilt to the approved
mockup with the user's rulings R1 (no TP/FP/FN/TN or zero-sum wording a
person reads) and R2 (the step popover gives the exact command);
`docs/DECISIONS.md` 2026-10-11. Live-checked on the acceptance VM in session
202 (lesson walked to VERIFY PASS, closed). Not pushed.

Site browser and beginner lesson (2026-10-11): the blue console's Website
pane browses the session's target through its WAF on port 8002; the WAF lesson
is seven platform-checked steps with a hint ladder and "Do it for me"
(`docs/DECISIONS.md`, 2026-10-11). Walked live to VERIFY PASS in session 204
with headless Chromium. Not pushed. The Claude desktop browser does not load
the 8002 frame; the red console has no site pane. Then (PM feedback): a
Network panel recorded by the platform's site proxy, the full URL with "Not
secure", and the guide's words in one place with a red box on every step
(walked live in session 205).

Prebuilt images (2026-10-11, local, not pushed): CI publishes our six images
to ghcr.io; compose and the platform VM pull them; `bin/platform-rebuild`
replaces the platform stack keeping the store and the range key, not yet run
(`docs/DECISIONS.md`). Before its first run: push to `dev`, wait for the
`images` workflow, make the six ghcr.io packages public, create `m1.large` if
absent. Then, with the user, rebuild 192.168.0.210. Proposed, not built: `bin/cloud
up|down` for the whole range and golden images from CI; pfSense pending its
licence research.

Awaiting the user: a test audit (2026-10-10) found 223 of 1,379 tests that
duplicate another test, pin implementation detail, assert framework or YAML
constants, or guard removed features: 163 unit tests (about 1,650 lines) and
60 acceptance tests (the live run would drop from about 49 to 25-30 minutes).
Removing them lowers the tests floor on purpose and needs the user's ruling
(`docs/STATE.md` backlog 0).

## Known open on docker
- The VERIFY diagnosis for a blocked benign case names the status, not the CRS
  rule id; reading the rule id needs the audit record.
- The reachability middleware covers only the newest session's `estate`.
- `/vm-terminal/` does not connect on compose (Kali and the WAF have no `mgmt`
  address); the red terminal uses `/terminal/<id>/` and the blue WAF pane
  `/waf-terminal/<id>/` (live-verified in session 199) instead.
- Two `POST /api/sessions/` within milliseconds can race (pre-existing).
- Naming: `/api/rules/suppressions/` disables a rule (comments it out), which
  Suricata calls disabling, not suppressing; rename candidate awaiting the
  user (`docs/STATE.md` backlog 0).
- Environment: the console tests that drive the page under node
  (`test_console_behaviour.py`, `test_lesson_console.py`,
  `test_site_browser.py`) and `test_the_report_survives_a_real_interpreter`
  fail on a host without node, such as the platform VM; they pass locally.

## Build-time spikes
- Kibana log highlight: done 2026-10-10 (`docs/DECISIONS.md`). The lesson
  panel draws a box over Kibana elements by `data-test-subj` and over its own
  controls, with the panel text as fallback.
- CRS starting configuration: done 2026-10-10 (`docs/DECISIONS.md`).

## What must not break
- Each isolation seam keeps a single owner (loot/effect, elastic, suricata,
  attacker); add a session address, not new knowledge. The target decides
  whether it was beaten.
- Ratchet: run `bin/measure` before committing; the tests floor only rises.
- Step 7 turned the WAF to blocking; benign cases are kept and one added
  (`board-normal-sort`).

## Deferred (OpenStack work, not MVP)
Per-session CIDR allocation (fabric.py:11); the single-session 409 (OpenStack
keeps one; docker allows `FSL_MAX_SESSIONS`) and the bin/verify open-session guard; splitting pfSense's
edge and sensor roles; acceptance on substrate openstack (`docs/STATE.md`
backlog 0).

## To do
The open items from the doc reviews are a checklist under backlog 0 in
`docs/STATE.md`.
