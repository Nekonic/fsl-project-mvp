# Now

The live state of the work in flight. Small on purpose: the orchestrator keeps
its own context, so this is the handover across compaction, not a full history.
The product backlog and the finished record stay in `docs/STATE.md`; rulings
are in `docs/DECISIONS.md`; detail is in `git log`.

Updated: 2026-10-06

## Landed on dev this session

Branch `claude/agent-orchestration-harness-e4de7c`, squashed and pushed to `dev`
(the kiosk dead-end collapsed out of the history):

- **`7e71435`** — the blue console rebuilt as a sidebar framing the real tools:
  **pfSense** the real web GUI reverse-proxied on the platform's own `:8080` and
  auto-logged-in (server-primed session injected by nginx, re-validated every
  15 min; nginx strips X-Frame-Options/CSP/Set-Cookie, sub_filters out the inline
  frame-buster, blanks Referer, spoofs Host past anti-DNS-rebind); **ELK** Kibana
  at `/kibana/`; **WAF**/**Kali** GCP-style web-SSH terminals; the zero-sum
  scoreboard on the session page at close; targets renamed `fsl-wg-*`; Kibana in
  compose (services 7->8); the kiosk VM retired. Live-verified on 192.168.0.210.
- **`ae1809e`** (P3) — `platform.yaml` opens `tcp/8080` on the platform VM so a
  rebuilt VM has the pfSense-proxy port (matching the rule added live).
- **corp docs** (P5) — ARCHITECTURE.md/.ko.md got the corp architecture paragraph
  (WordPress 6.6.2, three pinned plugins + CVEs, corp-db MySQL 8.4 binlog ROW) and
  the corp `effect_observed` scoring paragraph; README.md/.ko.md got corp's binlog
  ground-truth read and a corp.com CLI example, and the stale "Blue = dashboard"
  line was corrected to the sidebar.
- `recursive-improvement-loop.md` memory was already current — no change needed.

## Deploy note (192.168.0.210)

`/opt/fsl` on the VM is a partial/stale tree (no `corp`, old `juice-shop`), and
Kibana was started ad-hoc, not from the VM's compose. A proper deploy syncs the
whole tree and runs `docker compose up -d`.

## Backlog remaining (priority in `docs/STATE.md`; roadmap artifact exists)

- **P1 — turn blocking on (response pillar).** The wiring exists
  (`views.py` reads `case.meta["blocked"]` into `game.response`); what is missing
  is a **decision**: what counts as "blocked" read from the target side. Core
  invariant — the target decides, the platform must not guess. Proposed: credit a
  case as blocked from observed enforcement (WAF 403 / Suricata drop), with the
  loot/effect ground truth confirming the objective held. **Awaiting the person.**
- **P2 — OpenStack cutover / retire dev Docker.** Large (`test/range.py` OpenStack
  adapter) and **destructive** (delete leftover `fsl-juice-shop`/`fsl-wiki` cloud
  VMs — confirm first). Multi-session.
- **P4 — cleanups.** The noVNC console API (`/api/range/console/`,
  `OpenStack.console()` + unit tests) is cleanly dead and removable (lowers the
  tests floor — a decision). `bin/worldmap` / `world.svg` / `/api/sessions/<id>/map/`
  are NOT cleanly removable: the acceptance `test/test_origins.py` and
  `test/test_map.py` still exercise `/map/`, so that check needs rehoming first.
- **P5 leftover** — the `now.md` SessionStart hook reads the main checkout's
  `now.md`, not the session worktree's; fix it to take the cwd from the hook's stdin.

## On merge to dev

- Fast-forward the main checkout's `dev` after each push (the Desktop reads project
  config from it; a stale checkout means the harness does not load in sessions).

## Decisions pending a person

- **P1's "blocked" signal** (above) before implementing the response pillar.
- **P2's cloud-VM deletion** before the OpenStack cutover removes leftovers.
