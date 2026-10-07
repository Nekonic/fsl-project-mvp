# Now

The live state of the work in flight. Small on purpose: the orchestrator keeps
its own context, so this is the handover across compaction, not a full history.
The product backlog and the finished record stay in `docs/STATE.md`; rulings
are in `docs/DECISIONS.md`; detail is in `git log`.

Updated: 2026-10-07

## In flight this session (branch `claude/agent-orchestration-harness-e4de7c`)

An overnight hygiene + doc-reconciliation sweep. **Committed locally, not yet
pushed** (`git log dev..HEAD`); the push is the human's, to `dev` as a
fast-forward. The fast gate is green (`bin/verify --fast`: 1208 unit/API/console
tests, `core_loc` 462 unchanged, `tests` floor raised 1198 -> 1214). Full
acceptance was not run here: the only local stack is the main checkout's, which
`bin/verify` refuses to drive from a worktree — run it from a stack on this
branch before the push.

What landed:

- **Doc reconciliation** (two review workflows, each finding adversarially
  re-verified). README/ARCHITECTURE (en+ko), CLAUDE.md and THREAT-MODEL.md were
  wrong wherever the pfSense `:8080` pane, the Kibana service, the removed
  `FSL_OPENSTACK_SSH_CONFIG` knob, and corp's `escalate-privileges` stage had
  moved past them. Eleven confirmed drifts fixed.
- **A real defect:** `_observe_objectives` reported the full count of
  previously-credited objectives as `achieved` when the corp-db binlog read
  failed, so the red console re-announced every prior objective as freshly
  taken. Now returns 0 newly-credited (fix + test).
- **Coverage:** sixteen tests added for untested branches — the game pillars
  (weight renormalisation, accuracy clamp, coverage dedup), ingest fetch
  failures, the loot ground-truth guard, the suricata write failure, harness
  `fire`/`run`, the images Nova-ERROR branch, and pf_prime login/session parsing.
- **Small cleanups:** a dead `datetime` import and a redundant `if missing:`
  guard in `range/openstack.py`, a re-read role in `range/slot.py`, an unused
  `adapter` parameter on `_ground_truth_readable`, a vestigial single-element
  loop in `test_channels.py`.
- **Backlog items done** (from STATE's "Left to engineering"): the red console
  clears the attacker label on load and at stop (stale-attribution guard, with a
  console test); `bin/verify` refuses to run while a session is open; the
  `now.md` SessionStart hook now reads the session cwd, not the main checkout.
- The `test_platform_vm` ingress-set test was fixed to expect the `tcp/8080`
  that `ae1809e` opened (it had been left red on the branch).

## Live range note (192.168.0.210)

The OpenStack range was made session-ready earlier today by a **live patch**, not
a deploy: the platform VM runs a stale local Docker stack (container `fsl-board`,
no corp, old names), and the readiness `ground_truth` check reads that container,
not the OpenStack board VM. The board container's image lacked
`/internal/auth-users`, so the route was `docker cp`'d in and gunicorn
SIGHUP-reloaded; the suricata baseline was written to the pfSense VM. **Both
revert on a container/VM restart.** The OpenStack `fsl-waf` VM is a bare
host-nginx+ModSecurity box (config under `/etc/nginx/modsecurity/`), not the
Docker CRS image. This hybrid — attacks hit the OpenStack VMs, ground truth reads
the local Docker board — is the unfinished OpenStack cutover (P2).

## Backlog remaining (priority in `docs/STATE.md`)

- **P1 — turn blocking on (response pillar).** Still needs the person's decision
  on what counts as "blocked" read from the target side. Awaiting the person.
- **P2 — OpenStack cutover / retire the dev Docker stack.** Large and
  destructive (delete leftover `fsl-juice-shop`/`fsl-wiki`/`fsl-kiosk` cloud VMs;
  the live-range hybrid above is the symptom). Confirm before deleting.
- **Deferred engineering** (see the artifact): `no_marker` per engine and
  `fsl-logs-*` 30-day expiry (need live-stack verification), a tool killed on
  the attacker at timeout (touches the attacker seam), and the ratchet
  "statements" change + `scoreboard.py` into core (would raise gated core_loc).
  The "rule editor refuses an over-indented rule" item is **obsolete** — the
  console rebuild removed the rule editor; rules are edited in pfSense.

## Decisions pending a person (collected in tonight's artifact)

- **P1's "blocked" signal** and **P2's cloud-VM deletion** (as before).
- **The blue console no longer fetches `/api/`** — it frames pfSense/Kibana/ttyd
  directly. The only thing keeping `test_page_fetches_its_data_from_the_api[/blue/]`
  green and the dead `/api/range/console/` noVNC endpoint alive is an unreachable
  fallback branch in `blue.html`. Removing the dead branch and the dead endpoint
  (which lowers the tests floor) needs a ruling on whether `/blue/` is an
  accepted exception to the "console templates fetch /api/" invariant.
- Two near-duplicate/weak tests flagged (`test_pf_prime` mgmt-interface,
  a strategy-honesty acceptance test that greps the rebuilt `blue.html`) —
  changing them touches the tests floor, so they are the person's call.

## On merge to dev

- Fast-forward the main checkout's `dev` after the push (the Desktop reads
  project config from it; a stale checkout means the harness does not load).
