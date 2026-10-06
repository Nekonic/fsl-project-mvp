# Now

The live state of the work in flight. Small on purpose: the orchestrator keeps
its own context, so this is the handover across compaction, not a full history.
The product backlog and the finished record stay in `docs/STATE.md`; rulings
are in `docs/DECISIONS.md`; detail is in `git log`.

Updated: 2026-10-06

## In flight

Branch `claude/agent-orchestration-harness-e4de7c`. Done this session, unit-green
and awaiting the gate-2 push to `dev`:

- **Wargame target rename** (`cc8d73d`): target containers/VMs carry `fsl-wg-`
  so a listing tells a target from a platform/range service.
- **Blue console rebuilt as the sidebar** (the custom dashboard/map/alerts/rules/
  score are gone): three panes framing the real tools — **ELK** Kibana at
  `/kibana/`, **WAF**/**Kali** as GCP-style web-SSH terminals (`/vm-terminal/<host>/`),
  **pfSense** the real web GUI — and the zero-sum scoreboard on the session page
  at close.
- **pfSense pane: live-verified end to end on 192.168.0.210.** Reverse-proxied on
  the platform's own `:8080` (a distinct origin so pfSense's root-absolute URLs
  resolve; the kiosk VM is retired), **auto-logged-in** by a server-primed admin
  session nginx injects on every request. The proxy also handles every
  pfSense-in-an-iframe gotcha, all on the proxy side (pfSense config untouched):
  strips `X-Frame-Options`/CSP/`Set-Cookie`, `sub_filter`s out the inline
  frame-buster, blanks `Referer` past the HTTP_REFERER check, spoofs `Host` past
  anti-DNS-rebind, and re-validates/re-primes the session every 15 min (reusing a
  still-valid one so an open form's CSRF token is not rotated). See
  `docs/DECISIONS.md` (2026-10-06).

## Deploy state (192.168.0.210)

- The platform container was recreated from the synced `platform/` + `compose.yaml`
  and publishes `:8000` (console) and `:8080` (pfSense). The `fsl-platform`
  security group gained a `tcp/8080` ingress rule (IPv4 any, matching `:8000`),
  **added live** — a rebuilt platform VM needs the same rule, so bake it into
  `deploy/openstack/platform.yaml`.
- `/opt/fsl` on the VM is a **partial/stale tree** (no `corp`, old `juice-shop`),
  and Kibana was started ad-hoc, not from the VM's compose. A proper deploy syncs
  the whole tree and runs `docker compose up -d`.

## Next (details and priority in `docs/STATE.md`)

- **Turn blocking on** (backlog 1): the blue team now has the real pfSense GUI to
  switch Suricata drop rules and the WAF mode; record which cases were blocked,
  read from the target side, to light up the scoring response pillar.
- **OpenStack cutover / retire dev Docker**: Phase-4 cloud cleanup (leftover
  `fsl-juice-shop`/`fsl-wiki`, re-check the live slot), `test/range.py`'s OpenStack
  adapter, and the Docker-socket mount goes away with it.
- **Cleanups left by this session**: the noVNC console API
  (`/api/range/console/`, `OpenStack.console()`) and `bin/worldmap` / `world.svg`
  / `/api/sessions/<id>/map/` are now unused by any screen.

## On merge to dev

- Fast-forward the main checkout's `dev` after each push (Desktop reads project
  config from it; a stale checkout means the harness does not load in sessions).
- Retire/rewrite the user auto-memory `recursive-improvement-loop.md` once the new
  `CLAUDE.md` is on `dev`, so memory and the repo agree.
- The `now.md` SessionStart hook reads the main checkout's `now.md`, not the
  session worktree's — fix it to take the cwd from the hook's stdin.
- Doc pass P2 left: corp's architecture paragraph (WordPress CVEs, corp-db binlog,
  `effect_observed`) and the README corp sections.

## Decisions pending a person

- **Gate 2: push this session's work to `dev`** (console rebuild + pfSense pane),
  unit-green and live-verified.
