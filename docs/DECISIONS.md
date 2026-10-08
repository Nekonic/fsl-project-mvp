# Decisions

Append-only. Every ruling and every rejected approach, with the reason, so the
same ground is not re-argued. Read before proposing; add when something is
settled. Newest last.

## 2026-10-05 — Harness rebuilt for single-session orchestration

The session is now a standing orchestrator: the user states a goal in plain
language and this one session scopes it, runs fan-out work as workflows,
reports, and stops only at defined gates. Replaces the old protocol of many
short sessions each doing one backlog item and handing off through a large
`STATE.md`. Grounded in current primary and practitioner sources (Anthropic
engineering + Claude Code docs, HumanLayer, Böckeler, Cognition), each cited
claim re-fetched and quote-verified before use.

- **Two review gates, upstream and before anything outward.** Gate 1 is plan
  approval (a wrong plan line multiplies into wrong code — HumanLayer ACE-FCA);
  gate 2 is before push/merge. Autonomous between them. Rejected: a gate at
  every phase (review fatigue — approving each step is not review, Anthropic
  auto-mode study: 93% approval), and plan-only with no final gate (misses the
  ~half of test-passing agent PRs that fail human review — METR).

- **superpowers: keep the patterns, drop the auto hook.** Its `executing-plans`
  (native execution, ~2x faster and half the cost of subagent-driven on a
  frontier model — Jesse Vincent) and `dispatching-parallel-agents` are the
  engine we want, but its `using-superpowers` SessionStart hook forces
  skill-invocation before any reply and brainstorming hard-gates a design
  approval, both of which fight the user's "do not over-ask" rule, and the
  "1% chance, ABSOLUTELY MUST" trigger is measured to misfire (obra/superpowers
  issue #2386). Platform constraint: an individual hook cannot be disabled, and
  `skillOverrides` does not apply to plugin skills, so the two cannot be
  separated while the plugin is enabled. Resolution: disable the plugin for
  this project and re-encode the two patterns in the `orchestrate` skill. The
  project-scoped disable is confirmed to stop the user-level hook — the plugin
  loading docs rank project settings above user settings, so the project
  `false` overrides the user `true` and neither the plugin nor its SessionStart
  hook loads. Consequence to accept: this also drops superpowers' other skills
  for the project (test-driven-development, systematic-debugging). They are
  patterns a frontier model largely follows anyway and the `orchestrate` skill
  carries the load-bearing parts; re-enabling the plugin is one settings flip
  if they are missed.

- **CLAUDE.md rewritten from scratch, 205 → ~110 lines.** Gotchas and
  invariants only; the session protocol moved to the `orchestrate` skill, the
  metrics table and seams to `reference.md`, the layout table dropped (it is in
  `ARCHITECTURE.md`). Emphatic wording (bold, caps, MUST) removed because
  Opus 4.5+ over-triggers on it (Anthropic prompting guide); reasons given
  instead. Target under 200 lines (Claude Code memory docs).

- **STATE.md demoted, not rewritten.** Live state moves to `docs/state/now.md`
  (re-injected after compaction by a SessionStart hook); rulings to this file.
  `STATE.md` stays as the product backlog and finished record — it is product
  state, not harness, so it was not rewritten here.

- **Anti-slop is mechanism, not prose.** A `fsl-orchestrator` output style
  (built on the Concise idea) leads with the result, names concrete tells to
  avoid rather than "avoid an AI look" (Fable 5.1 guidance), and makes reviews
  visual. The behavioural rules that must also reach subagents stay in
  `CLAUDE.md`, because an output style does not reach subagents.

- **Docs are kept matched to code inside the loop.** Before gate 2 a
  fresh-context reviewer lists doc-versus-code drift in the touched area and it
  is fixed. Prose copies of numbers were banned in favour of pointing at
  `metrics.json` / `bin/measure`, because prose copies went stale twice before.

- **researcher carries `omitClaudeMd`; reviewer does not.** researcher does
  external and bounded lookups and takes everything from its delegation prompt,
  so it skips CLAUDE.md (every non-fork subagent otherwise reloads it, ×16
  concurrent). reviewer deliberately keeps CLAUDE.md, because judging a change
  against the invariants — the target decides objectives, the isolation seams —
  requires knowing them.

- **Pruned:** clangd, rust-analyzer and gitkraken-hooks plugins disabled for
  the project. The LSPs do not fit a Python/HTML/compose repo; gitkraken-hooks
  runs an external binary on every lifecycle event, including every tool call,
  which is per-call latency on a dispatch-heavy session (user: disable,
  2026-10-05).

- **Working language tightened** (user, 2026-10-05). English in every repo file
  — code, commit messages, PR descriptions, documents, the state and decision
  files. Korean lives in exactly three places: `*.ko.md` documents for Korean
  readers (the English file is canonical; a `.ko.md` is added only on request),
  `strings.html`, and `docs/vocabulary.md`. When a change touches a document
  that has a `.ko.md` pair, both are updated together in the doc-code sync step.
  Reverts dev's looser "write Korean when the content genuinely calls for it",
  which was ambiguous.

## 2026-10-05 — Blue console: a sidebar that frames the real tools

The platform stops shipping its own alert views, rule editor and dashboard.
The blue console becomes a left sidebar whose work screen holds the real tools,
framed or consoled in; session start/stop and the end-of-session scoreboard
stay on the landing page `/`, outside the sidebar. This is the design already
in `docs/STATE.md` and `docs/ARCHITECTURE.md` (2026-09-30); the two panes it
held "out of scope in this backlog" are now the work.

- **Panes.** pfSense (edge firewall + the Suricata IPS package, its own GUI);
  ELK/Kibana (detections and logs); the WAF. pfSense refuses framing
  (`X-Frame-Options`/`frame-ancestors`), so its pane is the Nova noVNC console
  of a kiosk-browser VM; Kibana frames directly. The current custom
  dashboard/map, alerts table, rule editor and score tabs are removed.

- **ELK is the real stack, not a read-only role** (user, 2026-10-05). Earlier
  docs locked Kibana to a read-only Elasticsearch role so the blue team could
  not alter evidence. That restriction is dropped: the "blue team might tamper
  with evidence" assumption was already abandoned when Tap-as-a-Service and the
  organiser sensor were dropped (placement spec), so the read-only role has no
  remaining justification. The blue team gets the real ELK.

- **The WAF pane follows its interface** (user, 2026-10-05). The blue console's
  terminal pane is for the WAF, not the attacker — the Kali terminal is the red
  console's. nginx + ModSecurity has no GUI, so the WAF is managed through a
  shell pane; if a GUI'd WAF is adopted later, its GUI is framed as a pane the
  same way, "as-is".

- **Kibana returns to compose as a gated `services` +1** (7 -> 8), the step
  `docs/STATE.md` anticipated. It reads the same Elasticsearch the platform
  ingests from, is reached through the platform's one published port at
  `/kibana/`, and is published on no port of its own.

- **Live runtime.** This is cloud-native work: Kibana in compose, pfSense
  reachable (up on the cloud), and a kiosk-browser VM for the pfSense noVNC
  pane. docker-compose is how the platform is brought up (the platform VM boots
  by running it), not a local-only convenience; the gate for a change is the
  unit/console tests, not a locally-run Docker acceptance pass.

## 2026-10-05 — Blue console becomes the sidebar; the tests floor is lowered

Stage ③ of the console rebuild replaced the custom blue console (the dashboard
with its world map and KPI tiles, the alerts table, the score tab, the rule
editor, the suppression list) with a left sidebar whose panes frame the real
tools over a noVNC console URL (`GET /api/range/console/<host>/`). The custom
UI is gone from `blue.html`.

- **The `tests` floor is lowered 1270 → 1192** (the user, 2026-10-05). The
  deleted tests covered the removed UI — `test_world_map.py`, most of
  `test_console_behaviour.py`, and three `test_console_views.py` cases for the
  two-view/tabs/overview layout. Deleting a test is normally refused (the floor
  is the defence against faking a pass), so this was taken as an explicit
  decision, not a silent step: the tests exercised behaviour that no longer
  exists, and new sidebar tests were added in their place. `core_loc` is
  unchanged; `product_loc` fell ~900 lines with the removed UI.

- **Left behind, not folded in:** `bin/worldmap`, `world.svg` and the
  `/api/sessions/<id>/map/` endpoint are now unused by any screen. Removing
  them is a separate cleanup (the acceptance `test/test_map.py` still exercises
  the endpoint). Reported here so it is not forgotten.

## 2026-10-06 — Tested: can pfSense be framed like Kibana? Only via its own origin

Tested whether pfSense can drop the kiosk VM and be framed directly like ELK.
The platform reaches pfSense's web GUI at `http://10.31.0.158:80` (its mgmt
interface; `:443` is filtered, the LAN GUI at `10.30.0.1` is refused — the
platform is not on estate). An nginx reverse-proxy to it returned the login
page (HTTP 200, `<title>pfSense - Login</title>`) with `X-Frame-Options` and
`Content-Security-Policy` stripped so it frames same-origin, and with `Host`
set to `10.31.0.158` so pfSense's anti-DNS-rebind check passes.

- **A `/kibana/`-style same-origin subpath does not work.** pfSense emits
  root-absolute URLs (`/css/login.css`, `/js/pfSense.js`, `/vendor/…`,
  `/csrf/csrf-magic.js`) and its login success redirects to `Location: /`, and
  it has no base-path setting (Kibana's `SERVER_BASEPATH=/kibana` has no pfSense
  equivalent). Under `/pfsense/` the login page loads but every asset and the
  post-login redirect resolve to the platform root, not pfSense — navigation
  breaks. sub_filter rewriting would still miss JS- and XHR-built paths.
- **A dedicated origin works** (pfSense at the root of its own port or
  subdomain, framed cross-origin with `X-Frame-Options`/CSP stripped): the
  root-absolute URLs then resolve correctly. Cost: a second port exposed on the
  platform VM (an OpenStack security-group rule), and auto-login re-solved — the
  kiosk's Chrome content-script extension cannot run inside an iframe.
- **Kept the kiosk VM for now.** It is built, committed and deployed, and the
  reverse-proxy's win (retiring one VM's quota + the extension) trades against
  the port + auto-login work. The test location was reverted; nothing shipped.

## 2026-10-06 — pfSense pane switched to a dedicated-port reverse-proxy; kiosk retired

Chosen after the test above (the user's call): drop the kiosk VM and frame the
real pfSense GUI through a reverse-proxy on the platform's own port, auto-logged
in. The same-origin subpath was ruled out (pfSense's root-absolute URLs); a
distinct origin was needed.

- **Origin: a dedicated port `:8080`, not a `pf.<ip>.nip.io` virtual host.** The
  nip.io host worked at the proxy but `*.nip.io` is on common ad-block lists
  (uBlock), and the in-app browser blocked its subresources (`ERR_BLOCKED_BY_CLIENT`)
  while leaving the console's own origin alone — a real risk of an unstyled pane
  for any blue-teamer running a blocker. A plain `IP:8080` origin has no domain
  reputation. `blue.html` builds the pane src as `//<console-host>:8080/`.
- **Auto-login by server-side session injection.** pfSense auth is a per-browser
  `PHPSESSID` cookie (`SameSite=Strict`, so it would not ride in a cross-origin
  iframe), not image state — "a pre-logged-in image" is not a thing. Instead
  `entrypoint.sh` logs in once (`pf_prime.py`), writes the session into an nginx
  include, and the `:8080` vhost injects it on every upstream request, so any
  browser sees the dashboard with no login page. A 15-min re-prime reuses a
  still-valid session (only re-logs-in when it has actually expired, so an open
  form's session-bound `__csrf_magic` is not rotated out from under it). nginx
  also strips `X-Frame-Options`/CSP and `Set-Cookie` so it frames, blanks the
  `Referer` past pfSense's HTTP_REFERER enforcement (the proxy origin would
  otherwise mismatch), spoofs `Host` to pfSense's own IP past its anti-DNS-rebind
  check, and `sub_filter`s out pfSense's inline frame-buster
  (`if (top != self) top.location = self.location`, which header-stripping alone
  cannot stop) so the GUI stays in the pane. Verified live: dashboard and deep
  pages 200-authenticated, assets served, forms reachable across a re-prime, no
  frame-bust.
- **The platform VM's `fsl-platform` security group gained a `tcp/8080` ingress
  rule** (IPv4 any, matching its `:8000` rule), added via the fsl-range Neutron
  creds. pfSense on `:8080` is auto-logged-in and unauthenticated to the LAN —
  the same trust posture as the no-auth console already on `:8000`, not a new
  regression. A rebuilt platform VM needs the same rule.
- **The noVNC console path is kept but unused.** `GET /api/range/console/<host>/`
  and `OpenStack.console()` (with their unit tests) stay as a generic "open a
  host's console" capability; no pane calls them now. The `tests` floor rose
  1196→1198: three tests for removed behaviour (the kiosk declaration, the two
  console-unavailable UI states) dropped, five added (`pf_prime`, the proxy pane).
- **Nine vacuous/duplicate tests removed (2026-10-07, the user's authorisation).**
  A whole-suite fake-test audit (a workflow, each flag adversarially re-verified
  against the production code it claims to pin) found nine tests that assert
  nothing the code must satisfy — each would still pass with the targeted code
  broken, or is a strict subset of a stronger sibling. Removed, and the `tests`
  floor lowered 1214 -> 1205 by hand (the sanctioned path for an authorised
  reduction). The itemised list and the proof for each is in the commit message.
  Gone: `test_api_compare` forced-strategy + label-stamp, `test_api_map`
  target==SEOUL, `test_api_sessions` bounded-list, `test_declaration`
  renamed-network, `test_tools` placeholder + marker-injected, `test_pf_prime`
  mgmt-not-estate, `test_compose` database-pinned-by-digest. The audit also
  flagged seven weak-but-real tests to *strengthen* (not delete); those keep the
  floor and are tracked separately.
- **What a test is for, and when to remove one (2026-10-07, the user).** A test
  exists to fail when the thing it guards breaks — it is the alarm that a green
  `bin/verify` means the point still holds (attacks detected, benign passes, the
  target decides, the seams stay isolated). The ruling: **a test that cannot
  fail when its target breaks does not serve that purpose and is removed** —
  unless it is the only guard of a must-not-break, in which case it is
  strengthened until it can fail. Deleting a test to pass remains forbidden; this
  is the opposite — removing tests that were never really testing. Applied once
  as the nine-test removal above, then to five more flagged tests (three
  strengthened, two removed, floor 1205 -> 1203); the per-test proof is in the
  commits. The floor is lowered by hand only for removals made under this ruling.
- **Reframe: learning-first, one session + two dials (2026-10-08, the user).**
  Learning and the scored wargame are not separate products — the same session
  with guidance on/off and baseline rules minimal vs full CRS+custom. The wedge:
  the learner tunes CRS / writes a Suricata rule that really BLOCKS a real attack,
  verified from the TARGET's own state (not a flag/quiz), gated on
  all-variants-blocked AND benign-passes. Spec:
  docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md.
- **Scope: WAF + IPS, firewall out (2026-10-08, the user).** Teach the
  network/web perimeter first — Suricata IDS (detect, from-scratch signatures) +
  ModSecurity CRS (block, learned by TUNING not from-scratch SecRules). The
  firewall is dropped as a lesson (an L3/L4 filter cannot defend a web attack;
  teaching otherwise is a misconception); pfSense stays as OpenStack edge+sensor
  infrastructure. Only the firewall lesson and the pfSense console pane / :8080
  proxy are not built. Roadmap: host/SIEM+Sigma, UTM, AD DS, then others.
- **The MVP lesson teaches CRS TUNING, not from-scratch SecRules (2026-10-08).**
  A "how others teach rule-writing" survey (workflow, five categories +
  synthesis) found from-scratch authoring is standard ONLY for IDS
  (Suricata/Sigma); for the WAF the field teaches enabling and tuning CRS and
  deprecates from-scratch SecRules for production. MVP = tune CRS so the ?sort=
  SQLi (CVE-2021-35042, the only board attack that moves ground truth) is blocked
  while the benign O'Brien search passes. The ' OR 1=1-- vs /search/ candidate
  was rejected: the ORM parameterises it, so it cannot exfiltrate and the
  ground-truth signal is flat.
- **Completion gate and the "blocked" witness (2026-10-08, the user).** A lesson
  completes only when ALL malicious variants are blocked AND ALL benign cases
  pass (the existing TP/FP/FN/TN scoreboard), not when the one shown payload is
  blocked. The "blocked" witness: TARGET STATE is primary (the attack never
  reached/affected the target), the WAF 403 line is corroboration only. No
  industry norm exists for this low-level witness; it is the user's call.
- **Session isolation and composability are MVP requirements (2026-10-08, the
  user).** Two+ sessions must run isolated, scenarios composed from reusable
  elements, one built image backing many scenarios — in the MVP, not later. A
  code audit found the leaves reusable (cases/objectives/topology YAML) but the
  assembly hardcoded (scenario dict, 1:1 image<->scenario, welded ground-truth
  readers). Design (adversarial review): a shared control plane + a per-session
  data-plane stack (compose project per session; OpenStack per-session
  network+VMs later), target image built-once-and-tagged, scenarios as discovered
  scenario.yaml descriptors. Non-interference is a live-gate acceptance property,
  not a fast-gate one.
- **Learner-facing decisions, checked against majority practice (2026-10-08, the
  user).** A "resolve open items by majority" workflow surveyed comparable
  platforms; the user chose per item: curriculum = one linear path, ~6-10 modules
  for the MVP, hands-on auto-verified completion (follows the majority, machine-
  checked and stricter); difficulty rises one axis at a time (never three at
  once); scoring shown as PASS/FAIL + plain-language diagnostics, no raw
  TP/FP/FN/TN and no gamification; log-analysis guidance = pursue a game-style
  clickable highlight on real Kibana (build-time feasibility spike), fall back to
  a side panel; perimeter-first branded as a detection-engineering track (a
  deliberate divergence from the SIEM-first majority, which presupposes a pipeline
  fsl lacks at MVP).
- **scenario.yaml is the discovered wargame registry (2026-10-08, build).** Build
  step 3 landed: the in-code `WARGAMES` dict became `wargames/<id>/scenario.yaml`,
  discovered at import. `WARGAMES` stays a real dict — three tests `patch.dict` it,
  two build a variant with `dict(WARGAMES["board"], ...)`, one does `set(WARGAMES)`
  — so no call site changed; the registry is data, not code. The descriptor carries
  `name`, `description`, `image`, `public_url`, `objective_model`, `case_file`,
  validated at discovery. board's `public_url` is now the literal `http://board.com`
  (was `settings.PUBLIC_TARGET_URL`, whose default is the same string): a scenario
  owns its public identity in the composable model, and the env var still feeds
  settings and attacker_box. The `image` field (`fsl/board:mvp`, `fsl/corp:mvp`) is
  declared but not yet consumed — it is the anchor for step 2 (build-once-and-tag)
  and step 1 (the per-session stack references it by `image:`), both of which need
  the live stack and were not done tonight. Verified by the fast gate only; core_loc
  flat (wargames.py is product_loc), tests floor 1203 -> 1209.

## 2026-10-08 — Docs reconciled with the code

The 2026-10-07 and 2026-10-08 entries above sit under the 2026-10-06 heading;
this log is append-only, so they stay where they are and are found by their
dates.

- **Docs follow the code at a6fb72b (2026-10-08, the user).** Three read-only
  reviewers compared every doc with the code; four writers corrected README,
  ARCHITECTURE (both with their `.ko.md`), STATE, THREAT-MODEL, the spec and
  now.md, and removed coined terms and AI-style prose in favour of the field's
  words (IDS/WAF, true/false positive, rule exclusion, exfiltrated data). The
  approved design did not change; only its status and its claims about current
  code did.
- **The step-3 commit is 81fb283.** now.md cited d436839, a pre-rebase copy that
  no branch contains.
- **Isolation seams have three known exceptions in code.** `register_pipeline.py`
  PUTs the ingest pipeline to Elasticsearch at bring-up; `range/pfsense.py` with
  `deploy/pfsense/configure.php` stops and starts Suricata on pfSense;
  `operator_log.py` reads the attacker's command log and the terminal wiring
  names `fsl-kali`. Recorded in CLAUDE.md and the ARCHITECTURE seams table as
  exceptions to remove, not patterns to copy. Whether to move the code is open.
- **The change gate is `bin/verify --fast`.** The orchestrate skill said full
  `bin/verify`; the 2026-10-05 ruling says unit/console tests. The skill now
  matches the ruling, and live-stack changes also run the acceptance suite on
  the OpenStack deployment before push (the 2026-10-08 agreement in now.md).
- **Product defects found, not fixed here.** No console page calls
  `/ingest/`, so a round played only in the browser scores with no detections;
  the CLI harness always opens a board session, so a corp case file is scored as
  board. Both are carried in now.md for the live build.
- **The sqlmap case sends about 94 requests.** CLAUDE.md said it "draws 94"
  alerts; STATE's measurement is 94 requests and many alerts.
- **The lesson's attack needs a working extraction (open, found 2026-10-08).**
  The spec and the living doc say sqlmap dumps auth_user through `?sort=`; STATE
  records that sqlmap's stock payloads do not finish the dump there (error-based
  extraction by hand does). Step 7 has to settle how the lesson's attack moves
  the target's records before completion can be read from them.
