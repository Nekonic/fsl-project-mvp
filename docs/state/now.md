# Now

The state of the work in flight, kept short: it is the handover across
compaction, not a history. The product backlog and the finished record are in
`docs/STATE.md`; rulings in `docs/DECISIONS.md`; detail in `git log`. Numbers
are in `metrics.json` (`bin/measure`), not here.

Updated: 2026-10-10

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
3. Done (81fb283): scenarios from `wargames/<id>/scenario.yaml`. Still open:
   board-easy/board-hard (one image, many scenarios) and the `defense` field,
   both with step 7.
4. Built (bbde53d, 82d081d): roles resolve to compose services by label;
   container_name pins gone; `estate` session-owned, edges and `mgmt` shared.
5. Built (bbde53d): `Docker.address(role)` is the role's estate IP; loot and
   effect read the session's own target.
6. Built (83f92e0): Filebeat writes `fsl-logs-<session>-<day>`; ingest reads
   `fsl-logs-<session>-*`.
7. Next: the lesson. WAF `SecRuleEngine On`; starting paranoia level from the CRS
   spike below (start at PL4, which over-blocks O'Brien; the learner tunes).
   Includes a per-session Suricata ruleset mount.
8. Test written (e307cc9, `test/test_concurrent_sessions.py`); live run pending.

Live acceptance of steps 4-6 and 8 on 192.168.0.210 (substrate docker):
LIVE-RESULT-PENDING

Commits 870b15f..2b7ded3 are local on this branch, not pushed; push waits for
that acceptance.

## Known open on docker
- `deploy/suricata/rules` is one bind mount shared by every session's sensor:
  applying a rule writes the shared file and reloads only that session's
  sensor. Fix with step 7.
- The reachability middleware covers only the newest session's `estate`.
- `/vm-terminal/` does not connect on compose (Kali and the WAF have no `mgmt`
  address); the red terminal uses `/terminal/<id>/` instead.
- Two `POST /api/sessions/` within milliseconds can race (pre-existing).
- Environment: the platform VM has no node, so the 12 console-behaviour tests
  and `test_the_report_survives_a_real_interpreter` fail there; they pass
  locally.

## Build-time spikes
- Kibana log highlight on stable `data-test-subj` selectors; fall back to a
  task panel beside the Kibana iframe if it does not hold. Open.
- CRS starting configuration: done 2026-10-10 (`docs/DECISIONS.md`).

## What must not break
- Each isolation seam keeps a single owner (loot/effect, elastic, suricata,
  attacker); add a session address, not new knowledge. The target decides
  whether it was beaten.
- Ratchet: run `bin/measure` before committing; the tests floor only rises.
- Step 7 re-baselines the benign true-negative cases with the WAF blocking.

## Deferred (OpenStack work, not MVP)
Per-session CIDR allocation (fabric.py:11); the single-session 409 (kept on
OpenStack only) and the bin/verify open-session guard; splitting pfSense's
edge and sensor roles; acceptance on substrate openstack (`docs/STATE.md`
backlog 0).

## To do
The open items from the doc reviews are a checklist under backlog 0 in
`docs/STATE.md`.
