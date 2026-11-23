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

## 2026-10-08 — Console ingest, CLI scenario, pfSense pane removed

- **A browser round ingests at close (2026-10-08, the user approved the plan).**
  The session page POSTs `/ingest/` before `/close/`; ingest is incremental, so
  one call at close is enough and no timer is needed. Alerts that land after the
  click are not ingested. A failed ingest does not block the close.
- **The CLI opens the case file's scenario.** `redteam/run.py` finds the
  scenario whose `case_file` matches `--cases` and defaults `--target` to its
  `public_url`; `harness.run` takes `scenario`. `core_loc` +1 (462 -> 463) for
  the parameter, accepted as a small, obviously-correct gated +1 rather than
  joining lines to hide it.
- **The pfSense GUI pane and the :8080 proxy are removed** (ruled out of scope
  earlier today). Gone: `pf_prime.py`, the pfSense code in `entrypoint.sh`, the
  nginx 8080 server, the pane and the now-unreachable noVNC branch in
  `blue.html`, its strings, the 8080 publish and the security-group rule.
  pfSense stays as the OpenStack edge and Suricata host; the
  `/api/range/console/<host>/` endpoint stays, unused.
- **The tests floor is lowered 1209 -> 1203 (the user, option A).** Eight tests
  whose subject was deleted went with it (`test_pf_prime.py` x7 and the pfSense
  pane console test); two console tests were added. No replacement tests were
  written to hold the number, since tests that only assert an absence would be
  padding. `test_page_fetches_its_data_from_the_api` now skips `/blue/1/`, which
  has no data to fetch; the page is still covered by the render tests.
- **Not verified live.** The compose, nginx and security-group changes and the
  corp CLI run need the OpenStack deployment; push waits for that check.

## 2026-10-09 — Acceptance against a remote platform; images tagged

- **The acceptance suite takes `FSL_PLATFORM_URL`** and skips modules that
  docker-exec into compose containers when the platform reports another
  substrate. First runs on the platform VM: substrate openstack 23 passed,
  78 skipped, 17 failed, 21 errors (causes in STATE backlog 0); substrate
  docker (switched for the run, then restored) 129 passed, 10 failed, nine of
  them the missing GeoLite2 database on the VM.
- **Step 2 landed:** every locally built image except the platform carries
  `fsl/<name>:mvp`.
- **The tests floor drops 1205 -> 1204.**
  `test_the_console_is_given_the_reason_and_not_only_the_number` read the
  strategy-comparison panel in `blue.html`, removed with the old blue console
  (7e71435); its subject is gone. The two API-level tests in the same file stay.
- **Step 1 landed: compose is split (2026-10-09).** `compose.yaml` is the shared
  control plane (platform, Elasticsearch, Kibana, collector); `session.yaml` is
  one session's data plane (WAF, Suricata, Filebeat, Kali, proxy and the
  wargames), started as `docker compose -p fsl-<id>` when a session opens. Until
  step 4 removes the container-name pins, opening a session takes down the
  previous `fsl-<n>` stack; closing a session leaves its stack up, because the
  acceptance suite and the console use the range between sessions and Filebeat
  may still be shipping. `services` 8 -> 9 for `collector`, which receives
  pfSense syslog on the OpenStack VM, where only the control plane runs.
  Live on the VM, docker substrate: 138 passed, 0 failed (before: 129/10, the
  10 being the missing GeoLite2 database and a stale test). A session open takes
  about 40 s, so a full `bin/verify` now takes about 38 min.
- **OpenStack readiness reads the compose board (found 2026-10-09).**
  `BOARD_API_URL` (`http://board:8000`) resolves to a compose board on `estate`,
  not the OpenStack board VM; it only passed because a compose board ran on the
  VM. Step 5 (the session's own target address) is the fix; until then a
  session stack is left running on the VM.
- **OpenStack readiness reads the board VM (resolved 2026-10-09).** The
  OpenStack adapter gains `address(role)`, the role's management address, and
  `loot.ground_truth(wargame_id, host)` puts it in place of the host in
  `BOARD_API_URL`; the readiness probe and the session baseline both go through
  it on any substrate that has `address`, so the docker path is unchanged.
  Before this fix the OpenStack ground truth had been read from the compose
  board on the platform VM, not the board VM the red team attacks: a baseline
  and readiness verdict taken from a target nobody was attacking. No compose
  board runs on the VM now. Also: a second open session gets 409 on every
  substrate, any exception after the session row is created closes it, the
  docker open reads the host directory before taking down the old stack, and
  each compose step gets only what is left of a 540 s server-side deadline
  (the client waits 600 s).
- **All attack cases now leave from the attacker box (2026-10-09).** HTTP cases
  used to be sent by the platform's own `requests` session straight to
  `board.com`; after the compose split that name resolved to the public
  internet, so the attack missed the range (FN) and hit a real site. `fire`
  now runs every case, HTTP included, through the Kali launcher as a `curl`
  argv (`--path-as-is` keeps `%2e%2e` traversal), so the traffic crosses
  pfSense/Suricata and carries the origin country from `set-origin` SNAT. A
  request that does not reach the target raises instead of recording a miss.
  The dead `http`/`target_url` plumbing through `fire`/`run`/`views`/`run.py`
  and the `--target` flag went with it; `core_loc` fell 463 -> 461. This was a
  pre-existing flaw (a single-network docker artifact), not caused by the
  split. Live on OpenStack: board-sqli-search from origin tw scored TP with
  alerts at src_ip 120.96.0.10; the benign case scored TN.
- **The tests floor is set to the post-trim count (2026-10-09).** The hard
  review cut over-built step-1 tests (deadline arithmetic, duplicate curl-argv
  shape, YAML-structure assertions already guarded elsewhere); net seven fewer
  test functions. The behaviour each removed test covered is still pinned by a
  kept test or by test_compose/test_corp_compose.
- **FSL_TOOL_IMAGE must be set on the OpenStack VM (found 2026-10-09).** The
  OpenStack launcher requires the launched image to equal the attacker role
  name `fsl-kali`; the var was unset on the VM and defaulted to `fsl/kali:mvp`,
  which broke tool cases there too. Set in the VM's openstack.env; a rebuilt VM
  lost it (2026-10-11: every harness case refused on 'ru'), so
  `deploy/openstack/platform.yaml` now writes it. Whether the
  attacker image should resolve from the substrate in code rather than from an
  env var is left open (STATE backlog 0).

## 2026-10-09 — /attacks/ wears the origin; sqlmap `?sort=` extraction verified negative

`POST /sessions/<id>/attacks/` recorded the requested origin in the case meta
and picked the launcher segment, but never applied the SNAT. On OpenStack the
source country is set only by `set-origin`, so an API-only caller fired from
whatever origin `/api/attacker/origin/` had last set — the recorded origin and
the on-wire source could diverge. `fire_attack` now calls `attacker.wear_origin`
for the chosen origin before firing (one proxy round trip), the same call the
red console makes when an origin is picked; front-door attacks (no origin) wear
nothing. Tests: `test_an_attack_wears_the_origin_before_firing`,
`test_an_attack_with_no_origin_wears_nothing`, and the cost test now asserts
firing from an origin reads the range once and wears the origin once. core_loc
unchanged; tests 1226 -> 1228.

Verified on the live OpenStack range that `board-sqli-orderby-sqlmap` does not
auto-extract: sqlmap `--technique=BT` judged `sort` not injectable and dumped
nothing (4 s, exit 0). This matches the standing note that the case is a
detected probe, not shaped for the dotted-column ORM bypass of CVE-2021-35042.
The `order_by(sort)` sink is present in the board source and the image bundle
hashes to the current source, yet the board on the current slot did not reflect
`?sort=` (no reorder for any value; dotted extractvalue/updatexml payloads
returned 200 with no error under DEBUG=True), so the manual error-based leak
recorded earlier (`~8.4.11`) did not reproduce from quick probes. Re-confirm the
manual extraction after a live-cloud board rebuild (step 8).

## 2026-10-09 — Board runs with DEBUG=False

`wargames/board/app/board/settings.py` ran `DEBUG=True`, which a production app
would not; set to `False`. Static still serves (whitenoise middleware +
`CompressedStaticFilesStorage`), `ALLOWED_HOSTS=["*"]` keeps host checks from
400ing, and no test asserts DEBUG or the debug error body. Consequence: the
CVE-2021-35042 `?sort=` order_by injection no longer leaks error-based (MySQL
1105 was only visible because DEBUG rendered the traceback), leaving blind
extraction only. Blind extraction is still practical for a lesson: the boolean
oracle reads off the rendered post order, about 1,350 requests to pull all three
accounts with sqlmap's boolean technique, and those requests are easy for the
IDS to catch. So `?sort=` blind SQLi stays the board's loot path (keep
DEBUG=False), with `/internal/auth-users` accidental exposure as an optional
quieter tier. The current case (`--technique=BT`, no forced dotted injection
point) still does not auto-complete; point sqlmap at the CVE (dotted
`table.column` prefix, `--technique=B`). The sink itself is unchanged and still
demonstrable (500 FieldError on a bad field). Takes effect on the live board
only after an image rebuild.

## 2026-10-09 — board order_by SQLi extracts with sqlmap (level 5), no bespoke tool

With DEBUG=False the error-based channel is gone, but the CVE-2021-35042 order_by
injection is still exploitable by the reusable tool. The old case aimed sqlmap at
`?sort=created_at` with `--technique=BT --level=3`, which cannot reach the sink:
Django skips validation only for a dotted value, and the injected term after the
first dot lands in a RawSQL ORDER BY expression where a constant subquery is
folded/dropped (manual `(SELECT SLEEP(n))` did not delay). sqlmap's stock
low-level payloads do not fit that context, so it reported "not injectable".

Fix: aim sqlmap at the dotted injection point `?sort=posts_post.id*` (the `*`
force point) with `--level=5 --risk=3`. At level 5 sqlmap uses its ORDER BY
payloads, breaks out with `)`, and finds both boolean-based (`) AND x=(SELECT
CASE WHEN (..) THEN x ELSE (SELECT a UNION SELECT b) END)-- -`) and time-based
(`) AND (SELECT .. FROM (SELECT(!SLEEP(n)))x)-- -`) blind injection, then dumps
`auth_user`. Verified on a local board build at HEAD (fsl/board:mvp): dumped
usernames admin, jiwoo, minseo. No dedicated exploit tool was added — the user
ruled that out for lack of reusability; sqlmap with the right flags does the
extraction.

Not done here: the dump stays on the attacker box; crediting the board loot
objective still needs the dump POSTed to `/loot/` (console operator or a later
harness feature, not a bespoke tool). On the OpenStack slot the board image is
drifted and does not run the sink (`?sort=zzz` returns 200, not 500) — a slot
rebuild is needed before this case extracts there. product_loc 8081 -> 8086
(the case + comment); core_loc, tests, services unchanged.

## 2026-10-09 — corp cases fire real exploits via a reusable nonce prefetch

Live verification (local corp build at HEAD: WordPress 6.6.2 + the three pinned
plugins) found all three corp CVEs real but every corp case non-functional as
written: each sent an empty nonce, and corp-rogue-admin used form_id 5 (the
login form) not 4 (registration). The CVEs are missing-authorization (no
capability check) but still require a public anti-CSRF nonce that an anonymous
visitor reads from the page.

Reusable fix (the user ruled out a bespoke per-exploit tool): redteam/tools.py
gains apply_prefetch/fetch_argv — a request may declare prefetch: {from, pattern};
the harness GETs that page through the attacker box, captures the token with the
pattern's first group, and substitutes {nonce} into the request. harness.fire
calls it once (core_loc 461 -> 462, a recorded gated +1; the fire signature was
folded to one line to keep the change minimal). Cases fixed: corp-option-flip
(wpgdprc nonce from /), corp-content-write (easy-post nonce), corp-rogue-admin
(form_id 4, um_register_form nonce), and benign corp-normal-registration. UM
registration is independent of users_can_register, so no reordering is needed.

Verified end-to-end through the real harness code: corp-option-flip flips
users_can_register 0 -> 1. Each raw CVE was confirmed by hand (post 1 defaced;
a new unauth-registered user became administrator via the homoglyph
wp_capabilities field).

Open (corp target bug): the block theme twentytwentyfour does not render the
plugin shortcode forms (UM register, rbsm submit) on the front-end — do_shortcode
renders them, the page does not — so the per-form nonces for corp-content-write
and corp-rogue-admin are not exposed on any public page (only wpgdprc, enqueued
globally, is). Ship corp with a classic theme (or fix block-theme content
rendering) so the forms render; a classic theme could not be installed here
(none bundled, WordPress.org unreachable from the container). tests 1228 -> 1231.

## 2026-10-09 — prefetch review fixes (Host header, GET exit code)

A hard review of the prefetch feature found a high-severity bug: the prefetch
GET (`fetch_argv`) carried no `Host` header, but the platform routes one nginx
entrypoint to the board/corp vhosts by the `Host` header that `fire_attack`
injects on the POST only (`views.py`). So a corp prefetch GET reached the board
vhost, found no nonce, and every corp case aborted with ToolUnavailable before
firing — the feature was non-functional in the real multi-vhost deployment (the
local end-to-end run masked it because its launch stub added the Host itself).
Fix: `apply_prefetch` forwards the case request's headers (the Host views.py
set) to `fetch_argv`, and a test now asserts the GET carries the Host. Also
check the GET's curl exit code so an unreachable target reports that, not a
misleading "token not found". Both fixes are in `redteam/tools.py` (product_loc,
core_loc unchanged at 462).

## 2026-10-09 — Red console submits loot; the objective model stays as two kinds

The board loot objective (`loot_verified`) was scored against a session-start
snapshot but nothing in the red-team flow submitted the extracted data to
`/loot/` — only the acceptance test did, by reading ground truth directly. A
three-lens agent review (MVP, architecture, soundness) converged: the one real,
AD-independent gap is the missing submission; close it minimally, reuse
`loot.matched`, add no new schema, and keep `loot_verified` and
`effect_observed` as separate models (do not force effect objectives into
submit-and-compare, and never verify against a platform-held/HMAC value — truth
stays a read-back of the target's own store).

Built: a "submit stolen loot" panel in the red console (`red.html`), shown only
when the scenario's `objective_model` is `loot_verified` (the catalogue now
carries `model`). The operator pastes the pairs they exfiltrated as JSON; the
console POSTs them to the existing `/loot/`, which verifies against the snapshot.
No planted canary was added: the board hashes are already per-rebuild dynamic
(salts rotate, ephemeral db), so they are the dynamic secret. The general
cross-substrate "planted objective secret" primitive (db/file/ad adapters, HMAC
derivation, a reachability framework) was deliberately NOT built — YAGNI for two
scenarios, and the hard part for AD is the ground-truth read seam, not planting;
let a real second/AD scenario pay for any abstraction. core_loc unchanged (462);
product_loc 8138 -> 8185; tests 1231 -> 1232. Console JS not live-run; unit and
console tests cover the wiring.

## 2026-10-10 — Concurrent docker sessions (build steps 4, 5, 6; step 8's test)

Commits bbde53d..2b7ded3. On the docker substrate each session's stack is the
compose project `fsl-<id>` and sessions run side by side.

- Roles resolve to compose services by label: `declaration.yaml` gains a
  `compose:` section (role -> service), and `docker.py` picks the container
  with that `com.docker.compose.service` label in the session's project.
  `container_name` pins are gone from `session.yaml` and the wargames; the
  control plane keeps `fsl-platform`, `fsl-elasticsearch`, `fsl-kibana`,
  `fsl-collector`. Containers are `fsl-<id>-<service>-1` and map back to the
  declared host names inside `docker.py`, so nothing outside the adapter
  learns the new names.
- Networks. The edges (`edge`, `edge-br`, `edge-hk`, `edge-us`) stay shared in
  `compose.yaml` with fixed subnets: Docker refuses overlapping subnets, and
  the subnet carries the origin for GeoIP. `estate` is session-owned, with no
  fixed subnet. The platform joins each session's `estate` at open
  (`docker network connect`, alias `platform`) and leaves it at teardown; a
  leftover control-plane `fsl_estate` is ignored when a session owns `estate`.
- Deviation from a confirmed item. The spec's confirmed item says only
  `estate`/`mgmt` float per session. `mgmt` stays shared: Elasticsearch,
  Kibana and the collector live on it and every session's Filebeat must reach
  Elasticsearch, and a per-session `mgmt` would give the adapter two `mgmt`
  segments to choose between. Only `estate` floats.
- Concurrency: opening a session tears down only the stacks of ended sessions.
  Docker opens at most `FSL_MAX_SESSIONS` sessions (default 2) and answers
  409 past that; OpenStack keeps one (see the session cap entry below). Close
  still does not tear down.
- Shared edges mean `board.com`/proxy would resolve to every session. At open
  the session's proxy is aimed at its own WAF through `/label/origin`; Kali
  uses `http://fsl-<id>-proxy-1:8081`; launched tools get `--add-host
  board.com`/`corp.com` at the session WAF; `/label` is a per-project named
  volume.
- `Docker.address(role)` is the role's `estate` IP. Loot ground truth reads
  the session's own board; the effect runner uses the session's corp-db.
- Filebeat writes `fsl-logs-${FSL_SESSION}-<day>`; `/ingest/` reads
  `fsl-logs-<session>-*` (`ELASTIC_SESSION_INDEX`, empty on OpenStack, which
  keeps `ELASTIC_INDEX` through the shared collector). The canary and
  `ingest/elastic.py` are unchanged.
- Suricata `HOME_NET` is the four WAF edge subnets plus 10/8, 172.16/12 and
  192.168/16, because a floating `estate` is drawn from Docker's private pools.
- Rules, validate, suppressions (stored with their session, migration 0014)
  and the attacker box, origin and label endpoints take `session` from the
  query or body and fall back to the newest session, open or not. The red console
  sends its session id. On docker the red terminal is `/terminal/<id>/`,
  proxied to `fsl-<id>-kali-1:7681`; OpenStack keeps `/vm-terminal/fsl-kali/`.
- `bin/verify` waits for the platform on `/api/sessions/`; `/api/rules/` needs
  a session stack.

Known open: `deploy/suricata/rules` is one bind mount shared by every session's
sensor, so applying a rule writes the shared file and reloads only that
session's sensor (superseded by the step 7 entry the same day: the mount is
gone and each sensor is seeded at open). `/vm-terminal/` is
still broken on compose (pre-existing). The reachability middleware covers
only the newest session's `estate`. Two POSTs within milliseconds can race
(pre-existing).

Environment: the platform VM 192.168.0.210 has no node, so the 12
console-behaviour tests and `test_the_report_survives_a_real_interpreter` fail
there; they pass locally.

Metrics: `metrics.json`, `bin/measure`.

Live acceptance (`bin/verify`, substrate docker, including
`test/test_concurrent_sessions.py`): passed, on the acceptance VM
192.168.0.220 rather than 192.168.0.210; see the live acceptance entry below.

## 2026-10-10 — CRS starting configuration (spike closed)

Measured 2026-10-09/10 on the platform VM with an isolated stack:
`fsl/board:mvp` behind the pinned `owasp/modsecurity-crs` image,
`MODSEC_RULE_ENGINE On`. The attack is sqlmap at `?sort=`, with the case's argv
and again with `--random-agent --tamper=space2comment,between,randomcase`; the
benign case is the O'Brien search.

| Posture | sqlmap `?sort=` | Benign O'Brien search |
|---|---|---|
| No WAF (control) | injection identified in 324 requests (boolean and time blind) | - |
| PL1-PL3 | not injectable; 403 x2065 (stock), x2508 (tamper) | 200 |
| PL4 | - | 403 (920273 invalid character, 949110 anomaly) |

`/`, `/?sort=posts_post.id` and `/?sort=-created_at` pass with 200 at PL1-PL4.

Conclusion: the default PL1 already blocks the attack and passes the benign
search, so there is nothing to tune at the default. Following the confirmed
lesson item that removing false positives is the core WAF job, the lesson
starts over-blocking at PL4 and the learner tunes it (a lower PL, or a rule
exclusion for 920273 on the search argument) until O'Brien passes while every
SQLi variant stays blocked. The Kibana highlight spike stays open.

## 2026-10-10 — The WAF lesson (build step 7)

Built on docker; OpenStack is untouched. Live acceptance (`test/test_lesson.py`)
passed (4 passed; see the seeded-logs item and the live acceptance entry below).

- Two settings on `Session`, chosen at open: `guidance` (bool, default off)
  and `defense` (a name, default `full`), plus `Session.waf` holding the
  applied CRS tuning. `baseline` already names the ground-truth snapshot, so
  the setting is `defense`. Defaults keep every existing caller and the
  acceptance suite on the old request shape.
- `defense` and `lesson` live in `wargames/<id>/scenario.yaml`, validated at
  discovery: each defense is a CRS tuning (checked by `rules/crs.py`) and a
  rule file that must exist in `deploy/suricata/rules`; a lesson is a string
  key prefix and cases that must exist in the scenario's case file. A scenario
  without `defense` (corp) accepts only the default and applies nothing.
- `rules/crs.py` is a new seam, the only file that knows the CRS exclusion
  hook path and the nginx reload. Measured on the pinned image (2026-10-10,
  isolated `crsprobe` stack on the platform VM): the hook
  `/etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`
  is picked up by `Include .../rules/*.conf` and is writable by the container's
  `nginx` user; `nginx -t && nginx -s reload` re-reads the ModSecurity files
  (O'Brien went from 403 at PL4 to passing after writing a PL1 `SecAction`
  and reloading); a path-scoped `ctl:ruleRemoveTargetById=920273;ARGS:q`
  passed O'Brien on `/search/` and still blocked it on another path; a broken
  file fails `nginx -t` with the file and column. A Suricata container with no
  rules directory starts with "No rule files match" and loads a seeded file on
  `suricatasc -c reload-rules`, so no entrypoint copy is needed and
  `deploy/suricata/rules` is not mounted at all.
- VERIFY is counted on blocks with the target as first witness (answer to
  open question 2). An sqlmap variant leaked when the rows it dumped match a
  `(username, hash)` of the session snapshot, read through `loot.matched`, not
  a new reader. It is held only on positive evidence: no match, exit 0, the
  `[*] ending` line, no crash (traceback, user abort, missing host), and
  either sqlmap's "all tested parameters do not appear to be injectable" or a
  dump that matches nothing. Live (2026-10-10, acceptance VM, session 79,
  captures in `platform/tests/fixtures/sqlmap-waf-*.out`): at PL4 with and
  without the 920273 exclusion, the stock variant drew 2065 403s and the
  tamper variant 2563 and concluded not injectable in 13-18 s; the tamper run
  also printed "heuristics detected that the target is protected by some kind
  of WAF/IPS" and three "unable to connect" lines. The WAF log shows those
  were the board's 500 answers to `?sort=7306`-style probes cut by
  ModSecurity after the headers were sent ("header already sent"), so a
  connection error sqlmap recovered from no longer voids its conclusion; one
  that stops it before concluding still leaves it inconclusive. Otherwise it is inconclusive (`lesson.diag.inconclusive`) and
  VERIFY does not pass; "no dump" alone is not a block (review finding). The
  403 count is recorded and not judged. A benign case is
  served on a 2xx `http_code`. A leak found by VERIFY also credits the
  objectives it proves (question 4). `meta.blocked` is written for lesson
  cases only, so the wargame's `_game` is unchanged outside the lesson.
- Seeded logs by replay at open (question 3): a guided session replays the
  lesson's cases once after the posture is applied, marked `meta.seed`; VERIFY
  judges only its own run. Measured live 2026-10-10: a guided open took 82 s
  and one VERIFY about 33 s (`test/test_lesson.py`, 4 passed on the
  acceptance VM). If a
  replay at open cannot run, the open answers 503 and the session is closed;
  its stack stays until the next open takes closed stacks down.
- Seed and VERIFY replays are left out of `/score/` TP/FP/FN/TN, the alerts
  they drew and the game, because they are the platform's replays, not the
  red team's attempts. A leak a replay found keeps its objective credit: the
  target's own records say the data left.
- The same `local.rules` for both defenses in the MVP (question 1); the
  difference between `minimal` and `full` is the CRS paranoia level (4 and 1).
- Two cases added, none removed: `board-sqli-orderby-sqlmap-tamper` (random
  User-Agent, tamper scripts; a defence keyed on sqlmap's own User-Agent, CRS
  913100, lets it through) and `board-normal-sort`, which fails a tuning that
  over-blocks the `sort` argument. Both sqlmap cases gained `--disable-hashing`
  (present in the Kali image's sqlmap 1.10.9): without it `--batch` accepts
  sqlmap's offer to crack the pbkdf2 hashes and the dump never ends; with it
  the stock case dumped all three accounts in 166 s against the board with
  no WAF (2026-10-10, `crsprobe` on the platform VM). That output is the test
  fixture `platform/tests/fixtures/sqlmap-orderby-dump.out`.
- A scenario without `defense` still has its sensor seeded with
  `deploy/suricata/rules/local.rules` at open; dropping the shared mount had
  left corp's sensor with no rules (review finding).
- `core_loc` rises 462 -> 526 (+64): `rules/crs.py` 56 lines (validation is
  most of it, because its input is written into ModSecurity configuration),
  `suricata.seed` and the `mkdir -p` on write +7, `harness.fire` returning
  what the attacker box printed +1. The plan estimated +40; validation and
  rollback took the rest. Recorded with `bin/measure --save` (question 5).
- `crs.apply` waits for the reload to take effect (live finding: `nginx -s
  reload` returns while the old workers still serve, and a request in the same
  second met the old tuning). It reads the master's worker PIDs from `/proc`
  before the reload and polls until none is left, refusing after 5 s;
  measured on the pinned image, the worker set changed within about 0.3 s.
  `core_loc` 526 -> 538 (+12).
- Final review (2026-10-10): the wait ends when a worker that was not there
  before the reload is up, not when every old worker has exited, because an
  old worker draining a time-based sqlmap request can outlive 5 s while nginx
  already serves the new tuning. No new worker in 5 s means the reload did not
  happen: the previous file is restored and reloaded, and the tuning refused.
- Final review: VERIFY must not pass without the target's own witness. A
  docker board session whose accounts cannot be read (or read empty) at open
  is refused with 503 and closed (OpenStack keeps its readiness refusal and
  its blind open); `/verify/` answers 409 for a session with no snapshot; and
  a sqlmap run is held only on its own "not injectable" conclusion with no
  dumped row. A dump that matches no snapshot account is inconclusive, not
  held. Unit tests now stand in a one-account snapshot by default instead of
  refusing the read. Live negative control: with 949110 and 959100 removed at PL4
  the stock case leaked all accounts and VERIFY failed in 135 s;
  `test/test_lesson.py` 5 passed on the acceptance VM. `core_loc` 538 -> 539
  for the rollback reload (the branch total, with the harness change, is 543;
  see the pre-push review entry).

## 2026-10-10 — Concurrent sessions capped on docker

The first live acceptance on the 8 GB VM ran out of memory: 7-8 session stacks
had piled up (72 `fsl-<id>` containers), because one host allowed any number
of open sessions and the suite opened sessions faster than it closed them. One
session stack takes roughly 1.5 GB; on the 4 GB platform VM, Elasticsearch was
OOM-killed.

- Docker opens at most `FSL_MAX_SESSIONS` sessions (default 2,
  `platform/fsl/settings.py`) and answers 409 past that
  (`platform/api/views.py`, 9c93a87). A substrate that declares no cap,
  OpenStack, stays at one.
- The acceptance suite closes every session it opens at the end of each test,
  module and run.

## 2026-10-10 — Live acceptance of the MVP build (push gate)

Where: a dedicated OpenStack VM `fsl-acceptance` (192.168.0.220, flavor
`m1.platform8`, 8 GB / 2 vCPU), created 2026-10-10 because the 4 GB platform
VM 192.168.0.210 cannot hold two session stacks plus Elasticsearch. Substrate
docker, HEAD 69db444.

Result: `bin/verify` all green. Unit 1351 passed; acceptance 145 passed, 0
failed, in 42 min 31 s; ratchet no regression (`core_loc` 538, `tests` floor
1326 on this date; `metrics.json` holds the record). Lowest available memory
during the run was 2.5 GB, with 23 containers.

Runs on the way:

- Run 3 (before step 7): 111 passed, 12 failed, 18 errors. sqlmap spent 50+
  minutes cracking the dumped pbkdf2 hashes under `--batch` (fixed with
  `--disable-hashing`); the API and the adapter disagreed on which session a
  session-less call meant (fixed); tests read the API or applied rules before
  opening their own session (fixed); `FSL_PUBLISH=0.0.0.0` on the VM
  (environment).
- Run 4 (with step 7): 140 passed, 5 failed. The tamper variant was judged
  inconclusive behind the WAF (judgement fixed with live captures); tests
  whose attack the now-blocking WAF stopped before reaching the estate (each
  test now tunes its own session's WAF through `PUT /waf/`); a suppression
  silenced the previous session's sensor (fixed by opening first); a
  suppression on a torn-down session could never be restored (product fix
  76ec988); `PUT /waf/` returned before the nginx reload took effect (product
  fix 1f53fb3).

After the OOM, the platform VM 192.168.0.210 was restored to origin/dev
(870b15f) with substrate openstack.

## 2026-10-10 — Pre-push adversarial review of the whole branch

A final review of 870b15f..HEAD found one high-severity hole and four smaller
defects; all are fixed (d18bf97, 60aa192 and their follow-ups).

- **VERIFY could pass with no target records.** A docker board session opened
  even when its accounts could not be read, and VERIFY then matched every dump
  against an empty snapshot. A loot_verified session now refuses to open
  without a readable, non-empty snapshot; `/verify/` answers 409 without one;
  a dump that matches no snapshot account is inconclusive, and "held" needs
  sqlmap's own "not injectable" conclusion with nothing dumped. A live negative
  control (blocking turned off for the session) now shows VERIFY reporting the
  leak and failing.
- **A WAF tuning reported as refused while already live.** `crs.apply` now
  returns once a new nginx worker is up; old workers may keep draining slow
  requests. No new worker within 5 s restores the previous file and refuses.
- **Session-less writes reached a closed session's still-running stack.**
  Writes that name no session go to the newest open session and answer 409
  when none is open; a write naming a closed session is refused. Reads that
  name no session still use the newest session.
- **A suppression on an ended session was marked restored on any range
  error.** It is now marked restored only when the session's stack is
  verifiably gone.
- **The acceptance suite closed sessions it had not opened.** It now closes
  only the sessions it opened, including the one `redteam/run.py` announces.

core_loc 538 -> 543: +1 for the rollback reload in `rules/crs.py`, +4 in
`redteam/harness.py` for closing its session when a case fails midway and
announcing the session id the suite needs for cleanup.

## 2026-10-10 — Kibana opens ready: data view, alert search, dashboard

A learner opening Kibana saw "Welcome to Elastic — Start by adding
integrations" and had to build a data view before seeing an alert.

- **The Welcome screen is gated by data views, not by an advanced setting.**
  `home:welcome:show` is a browser localStorage key, not a uiSetting; Kibana
  8.15's home page shows Welcome only when `isNewKibanaInstance`, i.e. when
  `hasUserDataView()` is false
  (https://github.com/elastic/kibana/blob/v8.15.0/src/plugins/home/public/application/components/home.tsx:
  "export const KEY_ENABLE_WELCOME = 'home:welcome:show';",
  "this.endLoading({ isNewKibanaInstance: !hasUserIndexPattern });"). Importing
  the data view removes it; nothing writes that key.
- **Saved objects import.** `POST /api/saved_objects/_import?overwrite=true`
  with `kbn-xsrf`, multipart field `file`
  (https://www.elastic.co/docs/api/doc/kibana/v8/operation/operation-importsavedobjectsdefault:
  `overwrite` "Overwrites saved objects when they already exist."; `kbn-xsrf`
  "Cross-site request forgery protection"; `file` "A file exported using the
  export API."). Overwrite makes every bring-up idempotent. The ndjson in
  `deploy/kibana/objects.ndjson` is Kibana's own `_export` of the objects,
  with timestamps and versions stripped, so no migration rewrites it.
- **Default route.** `defaultRoute` = `/app/discover#/view/fsl-alerts`
  (https://www.elastic.co/guide/en/kibana/8.15/advanced-options.html: "The
  default route when opening Kibana."). The 8.15 docs describe only the UI for
  advanced settings; the write goes to `POST /api/kibana/settings`
  `{"changes": {...}}`, the route Kibana's own UI uses
  (https://github.com/elastic/kibana/blob/v8.15.0/packages/core/ui-settings/core-ui-settings-server-internal/src/routes/set_many.ts:
  "router.post({ path: '/api/kibana/settings', validate }"). Undocumented, so
  version-bound; Kibana is pinned to 8.15.0.
- **The session in Discover.** Documents carry no session field; on docker the
  session is the index. Filebeat writes data streams, so hits live in
  `.ds-fsl-logs-<id>-...`; `_index : fsl-logs-<id>-*` matches them (checked on
  the acceptance VM: 10932 hits for session 15, equal to its index), while a
  leading wildcard on `_index` is refused by Elasticsearch. Discover's URL app
  state replaces the saved search's query and columns rather than merging, so
  the link carries the full query, the columns and the sort, and a test holds
  them equal to the saved search. On OpenStack every session writes
  `fsl-logs-shared-*`, so the link narrows by time only.
- **Runtime fields, not ingest changes.** Suricata and ModSecurity name the
  same facts differently (`alert.signature` / `transaction.messages.message`,
  `src_ip` / `transaction.client_ip`, ...). The data view folds them into one
  column each with Painless runtime fields, leaving the ingest pipeline and
  `ingest/elastic.py` untouched.

`platform/kibana.py` is the one file that knows the Kibana API. core_loc,
dependencies and services unchanged.

## 2026-10-10 — Lesson guidance drawn over the real Kibana

User request: guidance on top of the real Kibana UI, a red box and a label,
driven by the lesson step, with the panel text as fallback. This closes the
Kibana highlight spike.

- Feasibility was checked live on the acceptance VM: the Kibana iframe is
  same-origin, so the console reads `frame.contentDocument`; a fixed overlay
  with `pointer-events: none` lets every click reach Kibana. Selectors are
  Kibana's own `data-test-subj` values, checked in the elastic/kibana v8.15.0
  source (the pinned image).
- The overlay re-queries its selector every animation frame and keeps no node
  references, so Kibana re-rendering or navigating inside the frame does not
  strand it; it hides when the target is missing or scrolled out of the pane.
  The label goes on whichever side of the target has room.
- The sub-steps and selectors are a small list in `blue.html`, not in
  `scenario.yaml`: they describe Kibana's and the panel's UI, which every
  scenario shares; only their text is per lesson (`<lesson.text>.coach.*`).
- Verified live in a guided board session (session 195, opened from the
  start-as-a-lesson button of the time): boxes over the alert table, a row's expand toggle and the panel's
  Apply button. Console code is product code; `core_loc` is unchanged.

## 2026-10-10 — Kibana opens clean; the lesson is a floating note

User feedback on the live lesson.

- The Discover callout "Get the best look at your search results / Take the
  tour / Dismiss" is `DocumentExplorerUpdateCallout`
  (elastic/kibana v8.15.0
  `src/plugins/discover/public/application/main/components/document_explorer_callout/document_explorer_update_callout.tsx:25`
  `CALLOUT_STATE_KEY = 'discover:docExplorerUpdateCalloutClosed'`, read at :27-30
  and checked at :48 `if (calloutClosed || !capabilities.advancedSettings.save)`).
  Kibana's `Storage` wrapper JSON-parses localStorage
  (`src/plugins/kibana_utils/public/storage/storage.ts:29`). No advanced
  setting turns it off, so the blue console sets the key, with the legacy
  table's `discover:docExplorerCalloutClosed` (`document_explorer_callout.tsx:27`)
  and the no-data popover's `data.noDataPopover`
  (`src/plugins/unified_search/public/query_string_input/no_data_popover.tsx:15`),
  in its own localStorage, which the same-origin `/kibana/` frame shares,
  before the pane loads. Verified live: the callout that showed in session 195
  was gone in 196 and 197 in the same browser profile.
- "Unsaved changes" appeared because the pane opened the saved search
  `#/view/fsl-alerts` with an `_a` query that differs from the saved one. The
  pane now opens an unsaved Discover state (`#/?_a=(columns,
  dataSource:(dataViewId:fsl-logs,type:dataView),query,sort)`) with the same
  columns, query and sort. Verified live: no badge, the query bar reads
  `(...) and _index : fsl-logs-197-*`.
- The lesson is a note floating over the console from the start (user
  correction: never a column). It is fixed bottom-right over the full-width
  pane, folds to its header, drags by its header with pointer capture (the
  Kibana frame ignores the pointer during the drag so it cannot swallow the
  move), and goes back to the corner. Fold and place are per viewer in
  localStorage (`fsl-lesson-note`, try/catch). A coach box on a Kibana target
  is drawn under the note, one on a note control above it, and a coach step
  on a note control unfolds a folded note.

## 2026-10-10 — A compact note; the guide follows the learner's clicks

User feedback, live on the acceptance VM (session 198).

- The note is at most 26rem tall and scrolls inside; it leads with the
  current step, and the goal shows as one line with a Details toggle.
- The guide advances when the learner clicks the highlighted target, the
  main mechanism: the overlay keeps `pointer-events: none`, so the click
  reaches Kibana or the control first, and a capture-phase listener in the
  same-origin Kibana document (or a listener on the note control) moves the
  guide on in a following task. Back and Next stay as the fallback. Live, a
  click on the alert table selected a cell in Kibana and moved the guide to
  "expand a 403 row".
- The label over a target is the step's own short instruction, one line with
  an ellipsis, placed above the target or below it, never over it.

## 2026-10-10 — The lesson teaches the tuning; the WAF pane is per session

User feedback (PM): the lesson listed practice steps without teaching how to
tune a WAF, and the blue console's WAF pane did not work at all.

Theory cards. Five folded cards above the guide, the READ step's "theory"
part. Every claim is from a primary source, fetched 2026-10-10:

- Paranoia level, https://coreruleset.org/docs/2-how-crs-works/2-2-paranoia_levels/ :
  "The paranoia level (PL) makes it possible to define how aggressive CRS is";
  "A higher paranoia level makes it harder for an attacker to go undetected.
  Yet this comes at the cost of more false positives". Default level 1 and
  the blocking/detection variables,
  https://raw.githubusercontent.com/coreruleset/coreruleset/main/crs-setup.conf.example :
  "A paranoia level of 1 is default"; "only the rules up to
  tx.blocking_paranoia_level affect the" anomaly score.
- Anomaly scoring, https://coreruleset.org/docs/2-how-crs-works/2-1-anomaly_scoring/ :
  "The rules just handle detection, adding to the anomaly score if they
  match"; a CRITICAL match "would increase the anomaly score by 5"; the
  default inbound threshold is 5. Rule 949110,
  https://raw.githubusercontent.com/coreruleset/coreruleset/main/rules/REQUEST-949-BLOCKING-EVALUATION.conf :
  `TX:BLOCKING_INBOUND_ANOMALY_SCORE "@ge %{tx.inbound_anomaly_score_threshold}"`,
  msg "Inbound Anomaly Score Exceeded". Live, session 199's audit record of
  the O'Brien search: 920273 "Invalid character in request (outside of very
  strict set)", `ARGS:q=O'Brien`, tag `paranoia-level/4`, then 949110 "Total
  Score: 5".
- False positives and exclusions,
  https://coreruleset.org/docs/2-how-crs-works/2-3-false-positives-and-tuning/ :
  "When a genuine transaction causes a rule from CRS to match in error it is
  described as a false positive"; the log gives "The rule ID of the matched
  rule" and the matching data; "False positives are particularly likely to
  happen when operating at higher paranoia levels"; "removing rule 920230 for
  that specific location only"; runtime (ctl) exclusions "must be placed
  before the CRS has been included", which is why the platform writes
  REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf. Its example 7 is
  `SecRule REQUEST_URI "@beginsWith /dynamic/new_post" "...,ctl:ruleRemoveTargetById=941150;ARGS:text_input"`.
- ModSecurity v3 reference,
  https://github.com/owasp-modsecurity/ModSecurity/wiki/Reference-Manual-(v3.x) :
  `ctl:ruleRemoveTargetById=981260;ARGS:user` "white-list the user parameter
  for rule #981260"; REQUEST_FILENAME "holds the relative request URL without
  the query string part".

The page does not itself rank the two fixes; the card calls the narrow
exclusion the recommended fix on the grounds above (a level change switches
off every rule above it everywhere; the CRS example removes one rule at one
location). Paranoia level, anomaly score, rule exclusion and the CRS and
ModSecurity names stay in English in the Korean text.

WAF terminal. `/vm-terminal/fsl-waf/` ssh'd to the WAF's mgmt address, which
compose sessions do not have. The per-session route mirrors
`/terminal/<id>/` with the least change: the WAF image has no ttyd, so a
fourth ttyd in the platform (`-a`, port 7693, `/waf-terminal`) runs
`waf-terminal.sh <id>`, which refuses anything but digits and runs
`docker exec -it fsl-<id>-waf-1 bash` (as the image's `nginx` user, who
can read the exclusion file and the audit log). nginx sets `?arg=$session`
from the path and drops the client's query, behind the same
`auth_request /terminal-allowed`. `GET /api/sessions/<id>/` names the pane's
URL (`waf_terminal`), so OpenStack keeps `/vm-terminal/fsl-waf/`. The coach
step after Apply highlights the WAF tab and gives two commands, verified live
in session 199 after applying `920273 ARGS:q /search/`:
`cat /etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`
printed the SecAction (level 4) and
`SecRule REQUEST_FILENAME "@beginsWith /search/" "id:10001,...,ctl:ruleRemoveTargetById=920273;ARGS:q"`;
`grep Brien /var/log/modsecurity/audit/audit.log | tail -n 1 | grep -oE '"(ruleId|data|message)":"[^"]*"'`
printed 920273 with `ARGS:q=O'Brien` and 949110. The shell's hostname was
fsl-199-waf-1's container id. The step text naming those paths is a
recorded exception to the `rules/crs.py` seam: a person reads them, the
platform does not.


## 2026-10-10 — The learner tunes CRS in the WAF terminal (overturns a confirmed item)

User ruling (PM). It overturns the confirmed item in the living-doc artifact
37HeLkkLEFQgVWbwLuXH7S, quoted here in English: "editing happens inside the
platform (settings/rules API): CRS tuning (PL, exclusions)". Reason given:
real CRS tuning is editing the exclusion file on the WAF host, `nginx -t`,
`nginx -s reload`; VERIFY judges from the target's records, so the platform
need not hold the tuning.

- The note's tuning form (PL select, exclusions box, Apply) is gone. The
  learner works in the session's WAF terminal (`/waf-terminal/<id>/`). The
  WAF image (owasp/modsecurity-crs, Debian 13) has `ed` and `sed` but no `vi`
  or `nano`, checked live; adding one would mean building our own WAF image
  instead of pulling it by digest, so the lesson teaches a heredoc append
  (`cat >> REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf <<'EOF'`). No image,
  service or dependency was added.
- The note's hint shows the complete commands first, with a toggle to hide
  them: the first stage of the confirmed hint-fade rule (complete, blank,
  none), kept to one stage for this one lesson.
- Coach steps: alerts, expand, rule, dashboard, WAF tab, then five steps in
  the terminal (audit log, show the file, edit, `nginx -t`, reload), Replay,
  Verify. A terminal step boxes the pane. A click inside the terminal cannot
  be seen from the console, so every label carries small Back/Next buttons;
  the note keeps its pair for a step whose target is not on screen. Polling
  `GET /waf/` to detect the edit was not added: it is one `docker exec` per
  poll for a step the learner can move on from.
- `PUT /api/sessions/<id>/waf/` stays as the agent path and for
  `test/test_lesson.py`. `GET` now reads the session's file through
  `rules/crs.py` (`crs.read`, `crs.parsed`): the paranoia level from
  `tx.blocking_paranoia_level`, every `ctl:ruleRemoveTargetById` /
  `ctl:ruleRemoveById` with its `@beginsWith` path, commented lines skipped,
  continued lines joined, plus the raw `file`. A closed session reports its
  record with `file: null`. `core_loc` 543 -> 559 (+16, `rules/crs.py`): the
  price of the API telling the truth after a terminal edit.
- Live, session 200 on the acceptance VM: in the WAF terminal the heredoc
  appended the exclusion, `nginx -t` said "test is successful",
  `nginx -s reload` started the signal process, `GET /waf/` reported
  `{"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}`, and Verify
  passed ("2 of 2 attack variants leaked nothing", every benign case
  answered).

Korean terms. The ko strings and the touched `*.ko.md` files now use the
product terms as CRS and ModSecurity write them instead of translations (the
old Korean terms are glossed in English; the current ones are rows of
`docs/vocabulary.md`):

| old | new | source |
|---|---|---|
| the literal Korean translation of "paranoia level" | Paranoia Level (PL) | https://coreruleset.org/docs/2-how-crs-works/2-2-paranoia_levels/ ("The paranoia level (PL)") |
| anomaly scoring (lowercase title) | Anomaly Scoring, inbound anomaly score | https://coreruleset.org/docs/2-how-crs-works/2-1-anomaly_scoring/ |
| the Korean word for "threshold" | inbound anomaly score threshold | same page ("inbound anomaly score threshold of 5") |
| the Korean translations of "rule exclusion" and "exclusion" | rule exclusion | https://coreruleset.org/docs/2-how-crs-works/2-3-false-positives-and-tuning/ ("rule exclusions") |
| the Korean term for false positive (in the CRS cards) | false positive | same page ("it is described as a false positive") |
| the Korean translations of "audit log" and "audit record" | audit log | https://github.com/owasp-modsecurity/ModSecurity/wiki/Reference-Manual-(v3.x) (`SecAuditLog`) |
| the Korean translation of "rule ID" | rule ID | same reference (`id` action) |
| CRS "rule" in the formal Korean word | CRS "rule" in the console's existing loanword for a rule | — |
| the Korean translation of "true negative" | TN | the en table already says TN; no translated term |

The scoreboard's Korean TP/FN/FP tiles stay: they label the platform's own
TP/FN/FP counts, not a CRS term. (Superseded by R1 below, 2026-10-11, and by
the 2026-10-13 Korean-terms entry: the tiles are gone and no score label
carries the Korean TP/FN/FP words of `docs/vocabulary.md`; the Korean false
positive stays only as the CRS term in the lesson's cards.)

## 2026-10-11 — Console redesign: the approved mockup, plain-language results, the guide says what to type

The five console screens (main, session, blue, red, closed session) were
rebuilt to a static mockup the user approved, with two rulings the user added
on top of it. The layout follows patterns from training platforms and
product-tour libraries, used as references, not copied:

| reference | what it gave |
|---|---|
| TryHackMe rooms (https://tryhackme.com/) | the split view: the task beside a live machine, here the note over the tool pane and the red console's large terminal |
| HTB Academy (https://academy.hackthebox.com/) | hint before solution: the Hints tab holds reasoning, the full answer is folded under Solution |
| Instruqt (https://docs.instruqt.com/) | a check the learner runs, answering pass or fail with what failed: the Check tab over `POST /verify/` |
| Dreamhack (https://dreamhack.io/) | progress shown as counts: "step n/N", objectives "lost x/y" |
| driver.js (https://driverjs.com/), Shepherd (https://shepherdjs.dev/) | the step popover anchored to the highlighted element: "n / N", title, one line, dots, Back/Next/close |

Rulings by the user:

- R1. No TP/FP/FN/TN labels anywhere a person reads, and no "zero-sum
  balance": PASS/FAIL and a plain-language diagnosis. The closed session leads
  with the primary score (objectives lost, whether each was noticed, lost and
  unnoticed counting double), then sentences with counts and case names
  ("caught 7 of 8 attacks · missed 1 (name)", "3 of 4 benign requests passed ·
  wrongly blocked 1 (O'Brien search)") and that a case counts once however
  many alerts it drew. The API keeps `tp`/`fp`/`fn`/`tn` and `game` for agents.
  `test_strings.py` fails on those tokens in any string-table value; 172 dead
  keys (the removed blue dashboard and the zero-sum scoreboard) went with them.
  (The label part superseded 2026-11-15: "Detection results are labelled
  정탐, 오탐, 미탐 and 정상 통과".)
- R2. The guide itself says exactly what to type. A terminal step's popover
  shows the command in a copyable block and one line on what it does, placed
  in the pane's bottom right so it does not cover the output. The commands
  are declared once, in the lesson definition (`lesson.steps[].command` in
  `scenario.yaml`), not in the string table: a command is the same in both
  languages. `nginx -t` and `nginx -s reload` became one step
  (`nginx -t && nginx -s reload`), so the board lesson has eleven steps. The
  note keeps only reasoning in Hints; the WAF banner names only the box and
  the CRS directory.

Data added for the screens, kept small: `category`, `difficulty`, `minutes` in
`scenario.yaml` (validated, optional); counts of attacks, benign cases,
objectives and lesson steps in the catalogue; `kind` and `ready`
(`Session.ready_at`, migration 0016, set when opening finishes, existing rows
backfilled with `started_at`) on every session; `result` (objectives lost,
unnoticed, total; the last VERIFY verdict, its diagnosis and the number of
runs) on finished sessions in the list and on every session's detail;
`waf_box` and `waf_rules` on the detail; `max_sessions` on `range/ready`.
The lesson step a viewer reached is per-viewer state in localStorage, like
the note's fold.

Rejected: dragging the note (the mockup anchors it; a fixed place keeps the
popover's placement predictable); a scrim over the terminal (it would hide
the output the step asks the learner to read); putting the commands in
`strings.html` (identical in both languages, which the table's translation
test refuses, and two copies to keep in step).

Live, on the acceptance VM (session 202): opened from "Start as lesson",
walked through the eleven steps typing each popover's command into the WAF
terminal, VERIFY passed (both sqlmap variants leaked nothing, the four benign
cases passed), closed; the closed page showed PASS, 0/3 objectives lost, and
no hand-run case to judge. The note pill first sat at 54 px and covered
Kibana's second toolbar; it moved to the empty part of Kibana's top bar.

## 2026-10-11 — A site browser in the console; the WAF lesson rewritten for complete beginners

The user asked for the target site inside the console, and approved a
seven-step script for a learner who has never seen a WAF, with the ruling that
a beginner runs the exclusion with one button in the terminal and types it only
on the "Do it yourself" path.

Site browser. The blue console's Website pane frames `/site/<session>/<host>/`,
which the platform's nginx proxies to that session's WAF with the scenario's
`Host`, so the WAF judges every page the learner opens and a block is its real
403 and a record in Kibana. Requests carry the platform's `edge` address and
`X-FSL-Case: browse` (set by nginx, overriding the browser); `/score/` leaves
`browse` out as it leaves out seed and VERIFY replays, since browsing is not a
case. The route is on port 8002, an origin of its own, with a CSP sandbox that
keeps the origin: the target is where the red team plants script, and on the
console's origin that script could drive the console. An opaque-origin sandbox
on 8000 was tried first; the Claude desktop browser refuses such frames
(`ERR_BLOCKED_BY_CLIENT`), and it also refused the cross-origin frame on 8002,
so the live walk used headless Chromium. Cookies are stripped both ways, so the
pane cannot log into the target. Docker only (`SITE_PORT`); the red console
has no pane. Cost: `core_loc` 559 → 560 (the newest-first read below).

Lesson. Eleven steps became seven, each advanced by a check the platform makes
and declared in `scenario.yaml` (`check.kind`: `alert`, `click`, `answer`,
`choice`, `waf`, `served`, `verify`); Back and Next stay. One line of plain
language comes with each step's pass. Help climbs nudge → pointing (the red
box) → answer → "Do it for me", on the Hint button, after 60 s, or after two
wrong answers; doing it for the learner is recorded per session. The audit-log
grep, showing the whole file, the separate reload and up-front theory left the
path; theory stays in the note. The terminal command uses absolute paths,
appends only if the line is missing, and is run with `term.paste(command +
"\n")` plus `term.input("\r")`; `PUT /waf/` stays for agents and is the
fallback when no terminal opens. `POST /ingest/` takes `within` (seconds) and
then reads the newest records first, because one VERIFY run leaves more than
the 5000 records a read takes and the learner's alert would be the one cut.

Sources:
- OWASP CRS, "False positives and tuning": tune a false positive away with a
  rule exclusion as narrow as one rule, one variable, one location —
  https://coreruleset.org/docs/concepts/false_positives_tuning/
- OWASP CRS, "Paranoia levels": higher levels trade more false positives for
  detection — https://coreruleset.org/docs/concepts/paranoia_levels/
- netnea, "Handling false positives with the OWASP ModSecurity Core Rule Set":
  find the rule id and the parameter in the log, then write
  `ctl:ruleRemoveTargetById` —
  https://www.netnea.com/cms/apache-tutorial-8_handling-false-positives-modsecurity-core-rule-set/
- Cloudflare WAF, troubleshooting managed rules (false positives): find the
  blocking rule in the event log, then add an exception —
  https://developers.cloudflare.com/waf/managed-rules/troubleshooting/
- AWS WAF, testing and tuning protections —
  https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html
- Elastic, Discover and KQL (the filter the learner clicks, and writes on the
  stretch path) — https://www.elastic.co/guide/en/kibana/current/discover.html,
  https://www.elastic.co/guide/en/kibana/current/kuery-query.html
- Diátaxis, tutorials: a lesson the learner completes by doing, with the
  explanation kept out of the path — https://diataxis.fr/tutorials/
- Nielsen Norman Group, onboarding tutorials: short, contextual, skippable —
  https://www.nngroup.com/articles/onboarding-tutorials/
- Killercoda's `{{exec}}` action, which runs a command in the learner's
  terminal on a click — https://github.com/killercoda/scenario-examples

Live, on the acceptance VM (session 204, mine), headless Chromium against
http://192.168.0.220:8000: board home and a search in the Website pane; the
O'Brien search showed the WAF's 403 and the step passed on its new alert in
about 17 s; the filter button narrowed Kibana to the O'Brien 403s; 949110 got
"that is the score total rule", 920273 passed; `ARGS:q` passed; "Run in
terminal" appended the line and printed "test is successful"; the O'Brien
search returned the results page; VERIFY passed. The board holds no post
matching "release", so that search shows the empty results page (200).

## 2026-10-11 — Developer tools for the site browser; one place for the guide's words

The user (PM) asked for a DevTools-like Network panel on the site browser, the
full URL with a "Not secure" marker in the address bar, and four fixes to the
lesson guide seen on step 1.

Recording. nginx cannot hand a response body to anything without a scripting
module, so the site route now passes through the platform: nginx on 8002 →
`/site-proxy/<session>/<host>/` (`platform/api/site.py`) → the session's WAF,
with the exact path and query in `X-Site-Uri`. The view records each request
in memory, the last 200 per session, bodies cut to 64 KB, and serves them at
`GET /api/sessions/<id>/site/requests/` (`?after=`) and `.../<id>/`. Memory,
not a table: the panel is a debugging view of the current session, and a
restart losing it costs nothing that scoring reads. Two guards come with it:
8000 answers 404 for `/site-proxy/` (on the console's origin the target's
pages would run as the console), and the same-origin POST check skips that
path so the target's own forms still submit. The marker `X-FSL-Case: browse`
is now set by the recorder. No new dependency (`requests` was there); core_loc
unchanged.

Guide. The popover is the only place for the step's words and Back/Next; the
note's Steps tab lists the steps with the current one marked and its status.
A step names the pane it needs; until that pane is shown the popover says
"open Website / Kibana / WAF on the left" and the box is on that rail button,
then it moves to the address bar, the Kibana element, the WAF pane or the
note's Verify button. A target wider than 480 px gets the popover under its
right end, not in the middle of the page. Checks are automatic, so the Check
button went; a status line says "Checking...", what is missing, or "✓" and what
was found, 1.2 s before the guide moves on.

Why step 1 showed no red box: lesson v2 drew the box only from the second hint
level (the "pointing" rung of the ladder), so every step started without one.
It was not the cross-origin frame: no step ever pointed inside the site page.
The box is now drawn from the start of every step; the hint's second rung says
"look where the red box is". A console test walks all seven steps in both the
guided and the "Do it yourself" mode and asserts each box is drawn on a
target the console can reach, never inside the site frame; the live walk
(session 205, headless Chromium) saw the box on every step and ended in
VERIFY PASS.

## 2026-10-11 — Review fixes: an unforgeable browse marker, a bounded site proxy, hints on the session, terms with sources

A review of the site browser and the lesson, and a full `bin/verify` on the
acceptance VM that timed out after `docker compose restart platform` (waitress
"Task queue depth" growing), produced these fixes.

Score. The browse exclusion keyed on `X-FSL-Case: browse`, which the red team
could send by hand or set with `POST /api/attacker/label/`, hiding its own
alerts from `/score/`. Each session now has a secret marker
(`Session.browse_marker`, `browse-` + 32 hex digits from `secrets`, migration
0017); `site.py` sends it, `_evidence` leaves out only detections carrying it,
and the API shows it as `browse` (detections, detection detail with `raw`, the
Network panel), so a red team reading the platform API does not learn it.
Kibana shows it; Kibana is the blue team's. The label endpoint refuses labels
starting `browse`. A literal `browse` is an unknown marker and is scored.

Site proxy. `X-Forwarded-For` is no longer forwarded (the learner's LAN
address reached the target and its audit log). Unknown session 404, closed
session 409, before any upstream call. A failed upstream is a 502 naming no
internal host. The upstream timeout is (3 s connect, 20 s read) instead of
60 s; the response is streamed and only its first 64 KB kept; a session's
records are dropped when it closes. The earlier note that the target's
cookies "never land on the platform" was wrong: nginx drops `Set-Cookie`, but
a script on the target runs on the platform's host and cookies are not
isolated by port, so `document.cookie` could set one the console would send.
The console uses no cookies today; README and ARCHITECTURE now say so.

Thread exhaustion after a restart. Not verified on the VM (no access during
the live run); the fixes remove every way found for a request to hold a thread
long. Kibana set-up was already in the background; `register_pipeline.py`
(up to 30 × 7 s against a slow Elasticsearch) ran in the foreground before
waitress and now runs in the background too. Polled reads were the likely
load: every open lesson tab ran ingest + detections (two `docker network`
calls each, 30 s timeout) and `GET waf/` (`docker exec`, 60 s timeout) every
5 s, and the Network panel polled every 2 s, all including for closed sessions
and hidden tabs. Now: `GET waf/` reads with a 10 s timeout; ingest and
`/detections/` reuse a session's segments for 30 s; the console polls only
while the tab is visible and the session open (re-reading the session every
30 s), and `site/requests/` answers 409 for a closed session. waitress goes
from 8 to 16 threads: the platform serves long requests by design (verify,
tool cases, session open), and 8 left no room for the console's polls beside
one of them. Not changed: `effect.read_changes` (corp objectives, 60 s binlog
read on the red console's 10 s poll); it is serial per tab and bounded.

Lesson. The terminal command appended `id:10001`, the id `crs.rendered` gives
the first `PUT /waf/` exclusion, so after a tuning `nginx -t` failed on a
duplicate id and left the file broken. Hand-written rules now take
10100-10199 (`crs.rendered` uses 10000-10020; ModSecurity's reference manual
leaves 1-99,999 for local use). The command copies the file to `.bak`, drops an
earlier `id:10100` line, appends, and reloads only if `nginx -t` passes, else
copies the `.bak` back; a test runs it in `sh` with a stand-in nginx. Hint and
do-it-for-me use is recorded through `POST /api/sessions/<id>/lesson/hints/`
on `Session.hints` instead of localStorage, and shown beside PASS/FAIL. The
note and its pill start below the site toolbar and the WAF banner. Each step's
pointer (`point`), the theory cards and the hint cards moved from `blue.html`
into `scenario.yaml`; `blue.html` (1354 lines) is split into `{% include %}`
files for the site browser, the Network panel and the lesson. `kibana.py`
reported an HTTP error as "could not reach Kibana" after 60 retries; it now
waits on 502/503/504 and reports any other status once with its body.

Removed: the strings `lesson.check.checking` and `lesson.coach.count` (in no
template); `test_browsing_is_marked_so_the_score_never_takes_it_for_a_case`
became `test_the_site_route_strips_cookies_both_ways` (it checked only nginx's
cookie lines; the score check is
`test_alerts_drawn_by_browsing_are_left_out_of_the_score`).

Terms (strings.html both halves and the Korean docs):

| Was | Now | Source |
|---|---|---|
| 949110 "'too many warnings'" | its msg, "Inbound Anomaly Score Exceeded" (English in Korean too) | CRS `rules/REQUEST-949-BLOCKING-EVALUATION.conf`, rule 949110 `msg:'Inbound Anomaly Score Exceeded (Total Score: ...)'` — https://github.com/coreruleset/coreruleset |
| "Kibana is the WAF's logbook; one row is one request" | "In Discover's document table one row is one document, here one request" | Kibana 8.15 Discover docs — https://www.elastic.co/guide/en/kibana/8.15/discover.html; Kibana's `i18n.locale` offers en, zh-CN, ja-JP, fr-FR only (https://www.elastic.co/guide/en/kibana/8.15/settings.html), so Kibana's labels stay English verbatim |
| arrow (English and Korean) | expand icon (English and Korean, the Korean with the loanword for "icon") | as above |
| Kibana query (English and Korean "search term") | KQL query (English and Korean with the loanword for "query") | https://www.elastic.co/guide/en/kibana/8.15/kuery-query.html |
| false positive (Korean theory) | the practitioner term for false positive with the English in parentheses first, then the term alone; "missed" for a false negative and "wrongly blocked" for a false positive | Cisco Korean documentation's term for false positive (`docs/vocabulary.md`, rows `false positive (FP)` and `false negative (FN)`) |
| the loanword for "rule" | the formal Korean word for "rule" | AWS WAF Korean developer guide (its words for "rule" and "rule group") |
| rule exclusion | rule exclusion with the Korean translation in parentheses on first mention | AWS WAF Korean developer guide |
| "objective" left in English inside the Korean credited line (`red.loot.credited`) | the Korean word for objective | the console's own word for objective elsewhere |
| Open ELK / "in ELK" (English and Korean) | Kibana | the pane is Kibana |
| "Attention required", "Developer tools" (`site.dev.toggle`) and "View source" in Korean | kept | Chromium `components_strings_ko.xtb` |
| "WAF practice" (ARCHITECTURE.ko) / "running a round" (README.ko) | "WAF lesson" / "running a session" (README's "Running a round" → "Running a session") | the console's own words |

Metrics after these commits: core_loc 560 (unchanged), product_loc 11191 (+126,
not gated), dependencies 6, services 9, tests 1472 (+31). Correction: commit
ed9f2d9's message says product_loc 10983, but the `metrics.json` it saved holds
11065, which is what `bin/measure` reports for that tree; 11065 is the right
figure for that commit. History is not rewritten.

## 2026-10-11 — A closed session's result is stored, not rescored on every list

Measured on the acceptance VM by the coordinator: `GET /api/sessions/` took
6.4 s for 25 rows and `?state=closed&limit=10` 5.7 s, against 0.01 s for
`?state=open`. Each closed row ran `_result` → `_evidence`, a full correlation
over the session's detections (thousands for a lesson, after VERIFY runs).
`bin/verify` probes readiness with a 5 s curl, so after `docker compose restart
platform` it never passed, and the main page was as slow.

The result is now stored on the session (`Session.result_cache`, migration
0018) beside the inputs it was computed from: `ended_at`, the number of hints,
and per table the last id and row count of detections (plus how many carry a
marker, since ingest marks old rows), cases and objectives. A list reads those
aggregates (three queries per session) and rescores only when they differ, so
evidence ingested after close still reaches the result. Keying on the inputs
rather than invalidating at each write point (ingest, loot, verify, hints,
cases) means no write path can be missed. `bin/verify` now probes
`/api/sessions/?state=open`, which proves the platform answers without
scoring anything. Open sessions are unchanged: the list gives them no result.

Metrics: core_loc 560, product_loc 11206 (+15, not gated), tests 1475 (+3).

## 2026-10-11 — Images come prebuilt from ghcr.io; the platform VM pulls, never builds

The platform VM built six images on every first boot (`up -d --build`), so a
rebuild took as long as the slowest build and depended on every upstream
download working that day. Docker is here to bring the platform up fast; a VM
should pull.

- `.github/workflows/images.yml` builds platform, board, corp, corp-db, kali
  and proxy for `linux/amd64` on every push to `dev` and on manual dispatch,
  and pushes `ghcr.io/nekonic/fsl-<name>:<commit sha>` and, from `dev` only,
  `:dev`, with `GITHUB_TOKEN` (`permissions: packages: write`), as GitHub's
  "Publishing Docker images" guide does. Actions are pinned to commit SHAs
  (checkout v7.0.1, setup-buildx v4.4.1, login v4.6.0, build-push v7.4.0);
  layers are cached in the Actions cache (`type=gha`, one scope per image).
  GHCR rather than Docker Hub: the repository is on GitHub, the token is the
  workflow's own, and no second account or secret exists.
- Every compose service with `build:` also names
  `ghcr.io/nekonic/fsl-<name>:${FSL_IMAGE_TAG:-dev}` and keeps `build:`, so
  `docker compose pull` serves a VM and `--build` a developer. The
  `fsl/<name>:mvp` tags are gone; the platform passes `FSL_IMAGE_TAG` to the
  session stacks it starts, and `redteam/tools.py` runs the kali image of the
  same tag. Third-party images keep their pins.
- A package GitHub creates is private on first push even in a public
  repository ("the default visibility is private", GitHub Docs, "Configuring a
  package's access control and visibility"); each of the six is made public
  once in its Package settings, or the VM's anonymous pull fails.
- cloud-init writes `FSL_IMAGE_TAG=<checkout commit>` to `/opt/fsl/.env`, runs
  `bin/fetch-geoip` (no credential: Elastic's endpoint), and the unit pulls
  `compose.yaml` and `session.yaml` and runs `up -d`. A failed pull is not
  fatal (`ExecStartPre=-`), so compose falls back to building; the rebuild
  script refuses before deleting anything when an image for the commit is not
  anonymously pullable, which covers both "CI not finished" and "still
  private".
- The platform VM's default flavor is `m1.large` (8 GB RAM, 4 vCPU, 80 GB, the
  classic OpenStack default flavor of that name), created once by an admin if
  absent.

The range key: the platform made its range ssh key on its own data volume, so
a new VM made a new key and the fabric reported keypair drift; the range had
to be torn down with every platform rebuild. Considered: a Heat parameter
carrying the private key (refused: Nova's metadata service serves user data to
every process on the VM, containers included, the reason the password is
already kept out); regenerating the key and rebuilding the range on every
platform rebuild (works, but loses the range and costs a full image/slot
cycle). Chosen: the key lives on the operator's machine (`--range-key`,
default `~/.ssh/fsl-platform`, 0600), copied once from the running platform
when absent, and `bin/platform-rebuild` writes it into the new VM's data volume
over ssh, as it appends the password. The keypair and the range's VMs keep
trusting the platform, so the range can stand through a replace.

`bin/platform-rebuild` (not yet run): checks the six images for the ref's
commit on ghcr.io, keeps the key, backs the store up with `bin/backup` over
ssh, deletes and recreates the stack with `flavor` and `ref`, appends the
password, writes the key, restores the store, recreates the platform and waits
for `/api/sessions/`. Unverified hypothesis: Nova leaves the `mgmt` port the
old platform attached behind, detached, and the next `POST /api/range/fabric/`
attaches the new server; to be checked on the first real run.

Docker was not running on the development machine, so the six images were not
built locally; the workflow passes actionlint. Metrics: core_loc 560,
dependencies 6, services 9 (unchanged), tests 1475 -> 1494.

## 2026-10-11 — Proposed, not built: one command for the whole cloud, and golden images from CI

Asked: one click builds everything, platform VM and range, from prebuilt
images. Plan only; the user asked for the plan before any code.

(a) One command. Extend the rebuild script into `bin/cloud up|down`. `up`
creates the stack if absent (`--replace` replaces it as above), waits for the
platform, then calls the platform's own range API in the order the code
requires: `POST /api/range/fabric/` (stop on `drifted`); `GET` then `POST
/api/range/images/` until `clean` (stop at once on a `failed` image, and on a
`missing` image with no bundle, which the platform cannot build: today
`fsl-pfsense`); `POST /api/range/slot/`; poll `GET /api/range/ready/` until the
slot phase leaves `NOT_STANDING`/`REBUILDING`; `POST /api/range/configure/`,
retried while the VMs' ssh comes up; poll `ready` until true. `down`: back up
the store, keep the key, `DELETE /api/range/slot/`, `DELETE
/api/range/fabric/`, `openstack stack delete`; golden images stay in Glance.

(b) Golden images from CI. Today the images step boots a builder from
`ubuntu-24.04` with the host's setup bundle as user data, snapshots it, and
names the image by the bundle's digest, so it builds only when an image is
missing or its scripts changed, and the images outlive the platform stack.
Proposed: a workflow builds each Linux host's qcow2 from the same bundle
(Ubuntu cloud image, the bundle as a NoCloud seed, QEMU with KVM until the
`fsl-image-ready <digest>` line on the serial console, then `qemu-img convert
-c`), and publishes it as a GitHub Release asset named by host and digest.
GitHub: "Each file included in a release must be under 2 GiB. There is no
limit on the total size of a release, nor bandwidth usage." KVM: GitHub's
changelog (2024-04-02) says hardware acceleration is available on hosted
Linux runners with 2 vCPUs; it does not mention nested virtualisation, so
whether a full VM boot works there is unverified. The images step would then,
for a missing image whose digest has a release asset, create the Glance image
and import it with `POST /v2/images/{id}/import` and `{"method": {"name":
"web-download", "uri": ...}}` (Glance "Interoperable Image Import";
`web-download` is in the default `enabled_import_methods`, and `GET
/v2/info/import` says whether this cloud allows it), falling back to the
builder. Alternative if CI cannot boot VMs: build once on the cloud as today
and publish with `openstack image save`, or keep the platform build, which
already caches by digest.

pfSense: nothing built or published. Unverified hypothesis, pending another
agent's licence research: the trademark policy permits non-commercial
redistribution of "bit-for-bit identical copies of official pfSense releases";
an installed disk image is not such a copy, and the policy sends unaddressed
uses to legal@netgate.com. Automating its install would mean driving the
online installer's console (no scripted install exists), not done.

## 2026-10-11 — OPNsense at the edge, one base image, cloud.yaml

Asked (PM, approved): replace pfSense with OPNsense; the cloud holds exactly
one uploaded image, Ubuntu 24.04, and everything else is built from it; every
value that differs between OpenStack clouds lives in one settings file.
Clarified by the user: the base image is Canonical's stock
`noble-server-cloudimg-amd64.img`, uploaded unmodified; nothing is baked in.
Built in four local commits; nothing ran against a cloud.

**Why OPNsense.** pfSense CE has no cloud image and no scripted install, and a
built pfSense image may not travel under the name (entry above). OPNsense
publishes a preinstalled `nano` disk image for each major release (January and
July; updates have no images) with a SHA256 in the release announcement and an
OpenSSL signature over the unpacked image (docs.opnsense.org/manual/install.html;
docs.opnsense.org/releases/CE_26.7.html: 26.7.6 on 2026-10-08, on FreeBSD
15.1). Licence: BSD 2-clause, Deciso B.V.; trademark policy: the name may be
used to promote OPNsense-based products, a derivative name needs permission
from project@opnsense.org (opnsense.org/legal-guidelines/). So the project
builds the image from the official release on each cloud, never publishes it,
and keeps its Glance name private; "based on OPNsense" is the public wording.

**The image is configured offline, through the importer.** The nano image
creates `/conf/config.xml` from the stock default on first boot, which assigns
only LAN (static 192.168.1.1/24) and WAN; the third NIC, mgmt, would get no
address, so a platform could not reach a fresh edge, and OPNsense runs no
cloud-init. Linux cannot write the image's UFS. The boot-time importer
(`opnsense-importer -b`, read from opnsense/core) offers, for a few seconds,
to import `conf/config.xml` from another disk. The builder boots the image once
under QEMU (KVM if nested virtualisation is there, TCG otherwise) with a FAT
seed disk and answers that prompt over the serial console. The image's
config gives root no password and only the platform's key, so the published
default password `opnsense` never exists on it; changing it after boot, as
first asked, would have left it live until then. Considered: rebuilding the UFS
with `makefs` from a read-only copy (file flags and boot blocks at risk);
writing the image over the builder's own disk and snapshotting it (no
qemu-img, and the running system pages from the disk being overwritten).

**Upload.** The platform creates the Glance record first and hands the
builder its `PUT /v2/images/{id}/file` URL and a fresh Keystone token in user
data, outside the bundle; the builder is deleted once the image is active and
is never snapshotted. Considered: the builder serving the file and Glance
`web-download` (the controller does not reach tenant networks); the platform
pulling and re-uploading (the default security group shuts the builder off).
The token is project-scoped for its lifetime (an hour by default); an
application credential limited to that PUT would narrow it, not built.

**Configuration after boot.** `configure/` renders the whole config.xml for
the slot (WAN with the first origin gateway and 29 IP aliases, LAN with the
estate gateway, opt1 mgmt by DHCP, the tenant MTU, outbound NAT off, block to
self before pass on WAN and LAN, hardware offloading off, IDS on the WAN in
pcap mode, one syslog destination), stages it with a Suricata `conf.d`
include (our rule file, the unix-command socket, an EVE syslog output with
alerts and HTTP records as `suricata`) and reboots the edge, then checks it
after a new `kern.boottime`. HOME_NET is the estate and mgmt only: OPNsense's
suricata.yaml template sets EXTERNAL_NET to `!$HOME_NET`, and the shipped
rules match `$EXTERNAL_NET -> $HOME_NET`, so pfSense's HOME_NET (every origin
too) would hide every attack. IDS rather than netmap inline: inline netmap on
VirtIO is unreliable (opnsense/src#324) and the sensor only detects.
Considered: the REST API (needs an API key, and the first key can only be made
from a shell); editing config.xml in place with OPNsense's PHP (internal API,
unversioned).

**Rule path fix.** On openstack the rules editor wrote and reloaded
`/var/lib/suricata/rules/local.rules`, a file the edge's Suricata never
loaded. The sensor host in `declaration.yaml` now names its rule file
(`/usr/local/etc/suricata/rules/fsl.rules`, the one the include loads) and its
reload command (`suricatasc -c reload-rules` on the include's socket);
`settings.py` derives `FSL_SENSOR_RULES` and `FSL_SENSOR_RELOAD` from it, and
`rules/suricata.py` takes the path as a parameter. `configctl ids reload`
was not used: it sends USR2 and returns before the rules load, the failure
mode `test_sensor_reload.py` already records; `suricatasc` answers
`"return":"OK"` when they have, so the reload check is unchanged.

**One base image.** Every builder boots `compute.base_image`; `Host.base` is
gone. `fsl-kali` built on a second image, `kali-rolling`: it now builds on
Ubuntu, enabling `universe` and `multiverse` itself (nikto is in multiverse)
and linking dirb's word lists where the motd points (`wordlists` is
Kali-only). Nothing else assumed more than the stock image: the platform VM
and the builders install what they use (tests check the package lists).

**cloud.yaml.** `deploy/openstack/cloud.example.yaml` (committed) is copied to
`cloud.yaml` (ignored). `platform/range/cloud.py` validates it and reports
every problem by dotted key; the password is read from `password_file` or
`password_env`, never written there. `bin/platform-rebuild` (now `--cloud`,
`--ref`) and the new `bin/cloud up|down` drive the openstack CLI's `OS_*` and
the Heat parameters from it; the template has no defaults and writes the
values to `openstack.env`, where the platform reads them; `settings.py`,
`fabric.py` and the declaration lose their cloud defaults (RegionOne,
ubuntu-24.04, m1.small, the inside CIDRs, the pfSense image name). Flavors
are per role (`builder`, `range`, `edge`); the availability zone applies to
every server the project boots.

Unverified until a cloud run: the importer's console strings and device name
(`vtbd1`) under QEMU; that OPNsense 26.7 accepts the minimal config.xml and
its legacy `filter`, `ssh` and `virtualip` shapes; that `conf.d/*.yaml`
overrides `rule-files` and `outputs`; the mirror layout
(`<mirror>/<version>/OPNsense-<version>.pub`); TCG boot time on a builder
without nested KVM.

Metrics: core_loc 560 (unchanged; `rules/suricata.py` gained a parameter on
existing lines), dependencies 6, services 9, tests 1494 -> 1551.
Correction: the four feature commits' messages give tests 1499, 1506, 1524
and 1540, because `bin/measure --save` ran before the new test files were
added to git and it counts tracked files only; measured on each commit's
tree, the figures are 1515, 1524, 1540 and 1551. History is not rewritten.

## 2026-10-11 — Review fixes to the cloud path: failed stacks, builders, the edge flavor, networks, the disk upload, old releases

An adversarial review of the OPNsense/cloud.yaml/`bin/cloud` commits found
seven defects; all fixed locally, none run against a cloud.

- **Failed stacks.** A stack in `*_FAILED` has no `address` output and was
  taken for absent: `up` tried to create a same-named stack, `down` said there
  was nothing to take down. `bin/platform-rebuild` now reads `stack_status`:
  `*_IN_PROGRESS` is refused, `*_FAILED` is deleted (`--wait`) and created
  again by `up` and deleted by `down` without asking a platform.
- **Builders block the stack delete.** A leftover `fsl-build-*` server keeps a
  port on the Heat-owned `fsl-platform` network. Every stack delete first
  deletes servers named `fsl-build-*` that carry the `fsl_image` property
  (the platform's mark; a server without it is not ours).
- **The edge flavor.** The OPNsense image sets `min_ram` 3072, so an edge on
  the `range` flavor fails at boot. `compute.flavors.edge` is required.
  Checking the flavor's RAM against the image was not built: Nova refuses the
  boot with its own message, and the key being required is what was missing.
- **Network overlaps.** `cloud.yaml`'s networks are refused when they overlap
  Docker's default local address pools (172.17.0.0/16, 172.18.0.0/16,
  172.19.0.0/16, 172.20.0.0/14, 172.24.0.0/14, 172.28.0.0/14 and
  192.168.0.0/16 in /20s: `localScopeDefaultNetworks` in moby
  `daemon/libnetwork/ipamutils/utils.go`; the dockerd reference documents the
  option, not the defaults), any subnet in `compose.yaml` (mgmt
  172.31.0.0/24, the four edges) or a declared origin.
- **No token on the builder.** The builder used to get a project-scoped
  Keystone token in user data (readable through Nova; an hour's lifetime
  against a TCG build of unknown length). It now gets no credential: it
  writes the qcow2 to `/var/lib/fsl-serve`, starts `python3 -m http.server
  8080` as the transient unit `fsl-serve`, and prints the disk's SHA256 on
  its ready line. The platform reads the line through Nova (the authenticated
  channel), pulls the disk over the platform network, refuses it on a SHA256
  mismatch, then creates the Glance record and PUTs the file with a token
  taken just before. The earlier entry rejected pulling because the default
  security group shuts the builder off; the upload builder now joins
  `fsl-range`, which the fabric already makes and the edge image already
  requires. A `queued` record left by an interrupted upload is filled on the
  next call, not duplicated. The disk passes through the platform container's
  temporary directory (about the qcow2's size) for the duration of one call.
- **Old releases.** Changing `opnsense.version` left `fsl-opnsense-<old>` in
  Glance for good; the plan now lists the project's private images and
  reports any `fsl-opnsense-*` image outside the current names as a leftover,
  only when it carries `fsl_bundle`.

Still unverified until a cloud run: everything in the entry above, plus that
`systemd-run` keeps `fsl-serve` running after cloud-init's `runcmd` ends and
that the platform container reaches a builder's port 8080 on the platform
network. The build-script tests check strings and their order, not behaviour.

Metrics: core_loc 560 (unchanged; nothing under `scoring/`, `ingest/`,
`rules/` or the harness changed), dependencies 6, services 9; tests rise
(see the commit that saves `metrics.json`).

A re-review of these fixes found three more, fixed on top:

- `fsl-range` lets any IPv4 in on any port, and the builder sits on the
  platform network, so joining it opened every port to anything routing
  there. Upload builders now join `fsl-build`, made by the images step if
  absent (so `POST /api/range/images/` before the fabric works): one ingress
  rule, tcp 8080 from the platform's own address on the build network
  (`FSL_OPENSTACK_PLATFORM`'s port), replaced when the platform's address
  changes; Neutron's default egress stays (the builder downloads).
- `bin/cloud up` deleted leftovers before the slot stood on the new images,
  so a superseded edge image could go while the edge still booted from it.
  Leftovers are now removed after the range is ready, and an image any
  server in the project boots from is never a leftover.
- Stack deletion removed every `fsl-build-*` server with `fsl_image` in the
  project. It now lists only those with a port on this stack's `network`
  resource (`openstack server list --network`); with no such resource it
  removes none.

## 2026-10-11 — The range resets itself after a session closes

Observed live on OpenStack: a session close Nova-rebuilds every slot VM from
its image, the rebuilt OPNsense edge holds no slot configuration (no Suricata
rules, WAN addresses or log forwarding), `ready/` reads "the sensor rules are
off baseline", and every later `POST /api/sessions/` is a 409 until someone
calls `POST /api/range/configure/`. The acceptance suite opens and closes many
sessions, so everything after the first close failed.

Ruling (user): resetting the range is automatic. After the close-time
rebuild, `platform/api/reset.py` starts a daemon thread in the platform
process that polls `plan_slot()` until every VM is ACTIVE, then runs
`configure_slot()` holding `RULE_CHANGES` (as `POST /api/range/configure/`
does), retrying while the rebuilt VMs do not answer ssh (`RangeUnavailable`),
for up to 30 minutes. A VM counts as rebuilt only once the thread has seen
Nova show it out of ACTIVE (REBUILD) and back, so a status read that still
shows the pre-rebuild VM ACTIVE is never configured; a VM never seen leaving
ACTIVE within 2 minutes fails the reset rather than risk configuring the old
disk. The close request answers at once (measured: rebuild to
ready about 1 min 47 s, configure's edge reboot wait alone allows 15 min).
While it runs, `ready/` reads phase `RESETTING` and a refused session open
says the range is resetting; a failure reads `RESET_FAILED` with its reason,
and `POST /api/range/configure/` stays the manual retry and clears it. This
supersedes the 2026-10-03 line that the wait-ACTIVE -> configure sequence is
the console's job, not the close's: a REST client (the acceptance suite, an
agent) has no console to sequence it.

The state is a module-level dict in the platform process, not a database row:
the platform runs one process, a restart loses only an in-flight reset
(`ready/` then falls back to its derived phase and `configure/` fixes it), and
a migration for it would buy nothing. No dependency, no service; Docker is
unchanged (it has no `rebuild_slot`).

Not chosen: Nova snapshots of the configured VMs, rebuilt from instead of the
golden images. Configure always applies the repo's current config
(`deploy/opnsense/`, the rule file, the collector address); a snapshot would
freeze whatever config was pushed when it was taken and drift silently from
the repo, and would need re-taking after every config change.

The acceptance harness (`test/conftest.py`) waits on `ready/` (up to 10
minutes) when a session open is refused for a reset, at start-up and before
the red team run, then retries the open once; no assertion changed.

## 2026-10-11 — The platform's own network keeps its default gateway when a session opens

Observed live on the platform VM (Docker Engine 29.1.3, the Ubuntu `docker.io`
package): opening a Docker-substrate session runs `docker network connect` on
the platform container for the session's `estate`; that network became the
platform's default gateway, Docker moved the 8000/8002 publish onto it, and the
in-flight `POST /api/sessions/` through the published address never got its
reply (about 11 minutes, via `FSL_PUBLISH`). Through the management address the
same run passed. Docker documents that the default gateway "may change
whenever a container's network connections change", that `gw-priority`
defaults to 0, and that "when a network should always be the default gateway,
it is enough to set its `gw-priority` to `1`"
(https://docs.docker.com/engine/network/, "Connecting to multiple networks");
the Compose spec exposes it per service network as `gw_priority`
(https://docs.docker.com/reference/compose-file/services/#gw_priority).

Ruling: `compose.yaml` gives the platform's `edge` network `gw_priority: 1`,
the network that was already its default gateway, so nothing changes until a
session connects, and a session network (priority 0) can no longer take it.
Not chosen: passing `--gw-priority` on the `network connect` itself; the
platform image's docker CLI is 27.5.1 (API 1.47) and the option needs API 1.48.
A test pins exactly one prioritised network on the platform service.

## 2026-10-11 — The edge is read back until its sensor has started, not at the first answer after the reboot

Observed live during the acceptance run on OpenStack: one automatic reset
failed with "its sensor is not running" although Suricata was running a few
seconds later. The edge booted at 09:46:55 and rc started Suricata at 09:47:03;
`configure_edge` took the first `verify` answer after the boot time changed,
which can land in that gap, since sshd answers before rc reaches Suricata.

Ruling: after the reboot, `configure_edge` reads the edge again, every
`EDGE_POLL` (15 s) up to `EDGE_SETTLE_READS` (8) times, until it holds every
gateway address, its sensor runs, it logs to the collector and its WAN rule is
in pf; only then, or after those reads, does it judge drift as before. A
genuinely broken edge is reported about 2 minutes later than before; a
reading taken between sshd and rc is no longer one.

## 2026-10-11 — WAF tuning reads the WAF's layout from the declaration, so it works on the OpenStack WAF VM

Ruling from the user: everything that works on docker must work on OpenStack.
`PUT /api/sessions/<id>/waf/` never did: `rules/crs.py` hard-coded the
container's exclusion file (`/etc/modsecurity.d/owasp-crs/...`), its reload
(`nginx -s reload` as the container user) and its pid file (`/tmp/nginx.pid`).
The `fsl-waf` VM keeps CRS in `/etc/nginx/modsecurity/crs`, runs nginx under
systemd with `/run/nginx.pid`, and is reached over ssh as `ubuntu`.

Ruling: `crs.Layout` (exclusion file, reload command, pid file) defaults to the
container's facts; the OpenStack overlay of `declaration.yaml` names the VM's
under the `fsl-waf` host (`rules`, `reload`, new `pid`), the same pattern as
the edge's `rules`/`reload` for `rules/suricata.py`, and `settings.FSL_WAF`
carries them to `crs.apply`/`crs.read`. No substrate branch in `crs.py`.
`deploy/waf/setup.sh` creates the exclusion file group `adm`, mode 664, so the
ssh user (in `adm` by the Ubuntu cloud image's default user groups) writes it
without root, as the container user does; only `nginx -t` and
`systemctl reload nginx` run under sudo. No sudoers file is added: the cloud
image's cloud-init already grants `ubuntu` passwordless sudo, which
`range/waf.py` relies on today, so a narrower rule would not narrow anything.
core_loc grows by 9 lines (`rules/crs.py`, 560 to 569), the cost of naming the
three facts instead of hard-coding them. Still docker-only: the WAF terminal
(`waf-terminal.sh`) and the lesson's exclusion command in
`wargames/board/scenario.yaml`.

## 2026-10-11 — The WAF lesson runs on the OpenStack WAF VM: one command from the declaration, and the VM blocks

Following the ruling above. The WAF pane on OpenStack was already an ssh shell
on `fsl-waf` (`/vm-terminal/fsl-waf/`, `vm-terminal.sh`, user `ubuntu`); only a
test pinning it was missing, now added. The lesson's exclusion command named
the container's path and ran `nginx -s reload` unprivileged, both wrong on the
VM. `wargames/board/scenario.yaml` now writes `{waf_rules}` and
`if {waf_reload}; then ...; else <restore>; fi`, and `wargames.lesson` fills
them from `settings.FSL_WAF`, the same facts `crs.apply` uses, so the console,
the API and the hand-typed command cannot disagree. `nginx -t && reload` in one
condition keeps the old behaviour: reload only on a file nginx accepted,
restore otherwise. Not chosen: one command that probes both paths, which teaches
a path the learner's WAF does not have.

`deploy/waf/modsecurity.conf` had `SecRuleEngine DetectionOnly`; no decision
recorded a reason (ARCHITECTURE.md only said "still"), and the lesson passes
only when the attack is blocked, so the VM now runs `On` like the container
(`MODSEC_RULE_ENGINE: "On"` in `session.yaml`). CRS's own defaults match the
container's `PARANOIA: 1` and `ANOMALY_INBOUND: 5`.
## 2026-10-11 — OpenStack is a first-class substrate; no acceptance test is docker-only

Ruling by the user: every acceptance test must run and pass on substrate
openstack as it does on docker. Marking a test docker-only, or skipping it on
openstack, is not acceptable. This supersedes the 2026-10-08 spec's "Deferred
(OpenStack work, not MVP)" and the lines that called the OpenStack range out
of the MVP (`docs/OPENSTACK.md` §1, `docs/STATE.md`).

First step: `test/range.py` gains `ThroughPlatform`, chosen when
`/api/range/ready/` reports substrate openstack. It runs a role's command with
`docker exec fsl-platform python manage.py run_on_role <role> <argv-json>`, a
management command that calls the platform's own `substrate().runner(role)`
(the ssh path `vm-terminal.sh` also takes), so the harness adds no second way
to reach a VM, `range/openstack.py` stays the only file that knows how, and
`test/range.py` still imports neither Django nor `platform/range/`. The
`scorer` role still runs by `docker exec` on the platform container, as on
docker. No REST endpoint was added: the API has no call that runs an
arbitrary command as the attacker or returns the target's stored hashes, and
adding one would hand every console client a shell and the ground truth.

Open, recorded in `docs/STATE.md`: the corp wargame has no host on the
OpenStack range (no declaration entry, no golden-image setup, `fsl-waf` does
not name `corp.com`), so its live tests fail there with that cause; and
`COMPOSE_RANGE_ONLY` in `test/conftest.py` still skips 20 modules on
openstack, which this ruling does not allow. Closed 2026-10-17: see "No
acceptance test is skipped on OpenStack".

## 2026-10-11 — One wargame host image runs every wargame as its GHCR containers

Approved by the user: on substrate openstack, stop building one VM image per
wargame (`fsl-wg-board` from `wargames/board/image/setup.sh`; corp would have
added more). One fixed host image, `fsl-wargame-host`, runs each wargame as
the same GHCR images the docker substrate uses, from the wargame's own
`compose.yaml`. The images on the cloud stay five however many wargames
there are: the base, the OPNsense edge, the WAF, Kali, the wargame host.

Checked first: no earlier ruling rejects containers on a range VM or asks for
an image per wargame. The placement spec (2026-09-30) rejects a Kali
container on the platform VM ("Shares a kernel and the root Docker daemon
with the red team") and host-based sensors on target VMs; neither is this.
The 2026-10-08 spec's "VMs booted from the existing Glance snapshot" for
OpenStack was deferred, not decided, and the 2026-10-11 first-class ruling
superseded that section.

- **The image.** `deploy/wargame-host/setup.sh` on the stock Ubuntu image:
  `universe`, `docker.io`, `docker-compose-v2`, `/etc/docker/daemon.json`
  with the tenant MTU (`mtu`, `default-network-opts`, as the platform VM:
  1450 against Docker's 1500 hung TLS there), then `docker compose pull` for
  each shipped file. The declaration's host entry lists `wargames: [board,
  corp]` and `publish: {board: 8000, corp-wp: 80}`.
- **Registry access.** The range has no Internet; the builder has. The
  images are pulled into the host image at build time, at the platform's
  `FSL_IMAGE_TAG` (the checkout's commit on the platform VM). The platform
  renders each `wargames/<id>/compose.yaml` into the bundle with the tag
  written in, so the tag is in the bundle's digest and a platform on a new
  commit plans a new host image; a moving tag such as `dev` does not.
  Not chosen: the platform serving the images (`docker save` over ssh, about
  a gigabyte per reset) or a registry mirror on the platform (another
  service, and the ratchet's `services` may only fall).
- **The rendered file** (`range/wargame_host.py`): `build:` and `networks:`
  dropped (no source tree, and `estate` is `session.yaml`'s network), each
  container named by its service, the declared ports published. Published
  ports rather than host networking: board-db and corp-db would both bind
  3306 on the host. The databases are not published.
- **Start and reset.** `configure_slot()` ends with `start_wargames()`, which
  runs `sudo docker compose -p <id> -f /opt/fsl/wargames/<id>.yaml up -d
  --wait --pull never` per wargame through a new role, `wargames`, filled by
  the host (900 s each); a wargame that does not come up healthy is drift.
  Reset stays the Nova rebuild of every slot VM: the rebuilt host holds the
  images and no container or volume, and the automatic configure after a
  close starts every wargame freshly seeded. Not chosen: `compose down -v`
  and `up` without a rebuild; faster for this VM, but the edge's reboot
  already sets the reset's length, it would be a second reset path, and the
  rebuild also clears anything left on the host outside the containers.
- **Ground truth.** A role the host fills that `compose:` maps to a service
  (`board`, `board-db`, `corp`, `corp-db`) runs in that container: the runner
  wraps the command in `sudo docker exec [-i] <service>` over the same ssh.
  `api/effect.py` is unchanged and reads `corp-db`'s binary log inside the
  container; `api/loot.py` is unchanged and reads the board at the host's
  mgmt address on the published 8000. `run_on_role` and the acceptance suite
  reach the same containers as on docker. `sudo`, not the `docker` group:
  the group is root-equivalent, and `ubuntu` already has passwordless sudo.
- **The WAF.** The VM's `range.conf` proxied `corp.com` through a variable,
  which nginx resolves per request and which needs a `resolver` the VM never
  had, so `corp.com` would have answered 502; it now names `corp-wp:80`
  literally, resolved at start from `/etc/hosts`, where the slot writes the
  host's estate address for `board` and `corp-wp`. The OpenStack overlay no
  longer narrows `fsl-waf`'s names to `board.com`.
- **Flavor.** `compute.flavors` may name `wargames` (the example names
  `m1.medium`); without it the host takes `range`. Memory under four
  containers is not measured.

Removed: `wargames/board/image/` and the test that pinned its `setuptools`
line (a guard for a removed build path).

Unverified until a cloud run: `docker-compose-v2` supporting `up --wait
--pull never` on the archive's version; WordPress installing within the
900 s with no Internet; the old `fsl-wg-board` server, ports and image,
which the platform no longer declares and so neither deletes nor reports,
need deleting by hand once; Kali's `mgmt` port reaching the published ports
directly (recorded in `docs/OPENSTACK.md` §8). Metrics: core_loc 569
(unchanged by this work; the +9 is `rules/crs.py`, recorded above),
dependencies 6, services 9, tests 1600 -> 1624.

## 2026-10-12 — Management admits only the platform; the edge passes only http to the WAF; a second sensor watches the estate leg

Measured first, from Kali on the live OpenStack range: `nmap -sT` on its
`mgmt` subnet found the wargame host's 22, 80 and 8000 open (`curl
http://<host mgmt>:8000/internal/auth-users` answered 200 with every
password hash), the edge's 22, 80 and 443 (the OPNsense GUI) and the WAF's 22
and 80. Every range port sat in `fsl-range`, which admits any IPv4. And the
edge's WAN pass rule passed any destination, so Kali reached the wargame
host's estate address on 8000 and 80 through the edge, past the WAF.

- **Management.** A third fabric group, `fsl-mgmt`, with one rule: ingress
  from members of `fsl-reach`, the group of the platform's own `mgmt` port.
  Every range host's `mgmt` port is created in it, and `ensure_slot` moves a
  standing one into it (`PUT /v2.0/ports/{id}`), so an existing range
  converges at the next `bin/cloud up`. Not chosen: a host firewall on each
  VM (one per image, and OPNsense's own rules), or narrowing `fsl-range` (it
  also carries the origins' traffic, which may come from any address).
  Unchanged: Kali is still the `proxy` role and still reached by the
  platform over `mgmt`. Neutron's DHCP port has no security group and still
  answers DNS on `mgmt`.
- **The edge.** The rendered `config.xml` narrows the WAN pass rule to tcp 80
  at the WAF's estate address (`opnsense.settings(front=...)`). The image's
  build-time config keeps the open rule; no slot traffic crosses it.
- **The estate sensor.** On docker one Suricata shares the WAF's namespace
  and sees both legs; on OpenStack the edge sees only the WAN, so
  `test_map`'s inside-leg check had nothing to find. Approved direction
  (parity with docker, no extra VM): the wargame host runs docker's own
  Suricata image (the digest in `session.yaml`, pinned equal by a test) and
  `deploy/suricata/suricata.yaml`, from `deploy/wargame-host/sensor.yaml`,
  with host networking and `--af-packet` on the interface holding the host's
  estate address (the platform passes the address; the host finds the
  interface). It starts after the wargames in `configure_slot`, as a compose
  project like a wargame, healthy once `suricatasc -c uptime` answers. Its
  starting rules are the shipped `local.rules`, baked into the host image and
  mounted as the rule directory, so a reset restores them. The role is
  `estate-sensor`; the overlay's `compose:` (now merged like `roles:`) maps it
  to the service `suricata`, so the runner execs into the container, and the
  host entry names its rule file and reload command as the edge's does.
  `rules/suricata.py` is unchanged; `api/views.py` hands it one runner per
  declared sensor (`settings.FSL_EXTRA_SENSORS` beside the existing
  `sensor` settings) for seeding, validation, application and the baseline
  check. Docker applies one rule set to both legs, so both sensors take every
  change; a change one sensor refuses is put back on the ones that took it.
- **Its evidence.** A host entry may name `logs: {tag: path}`; configure has
  rsyslog forward each file to the collector under that tag, by the WAF's
  forwarding, now by tag (`range/waf.py`). The collector already decodes
  appname `suricata`; `fsl-reach` hears every sensor host. Measured: the
  host's http records reach Elasticsearch decoded, `fsl_source: suricata`,
  source the WAF's estate address.

Also measured: Kali and the WAF keep the `/etc/hosts` of the user data they
were booted with; after the board moved to the wargame host they had to be
deleted and booted again (`docs/OPENSTACK.md` §8).

Found by the full runs on openstack after this change, and fixed:

- A closed session's reset runs for minutes after the close answers. Tests
  that reach a host without opening a session (the corp modules,
  `test_attacker_reach`) ran into it; `test/conftest.py` now waits out a
  running reset (phase `RESETTING` or `REBUILDING`, or the reset state
  `running`) before each test on openstack. `CHECKING` is not waited on: a
  module's own noise rule set puts the range there on purpose.
- `bin/verify`'s rule check asked both sensors right after its own warm-up
  session closed; it now waits out that reset first.
- `test_suppression` restores its suppression right after the close, while
  the sensors are rebuilding. The restore raised and the record stayed in
  force, so every later session was refused as off baseline. A restore for an
  ended session on a substrate that rebuilds at close is now recorded as
  lifted without reaching the sensors: the rebuild already put the baseline
  back.

## 2026-10-12 — The acceptance suite shares sessions; the reset configures hosts side by side

The suite opened about 42 sessions on docker and 27 on OpenStack, and on
OpenStack every close costs a slot reset (93-107 s close to READY), so
opening sessions set most of its 47-50 minutes.

- **Shared sessions.** `test/shared_sessions.py` holds session-scoped
  fixtures, registered from `conftest.py` as a plugin. Each opens its session,
  does every write (fire, tune, apply rules, loot) and every live read
  (topology, `hostname -I`, sensor tail) inside the fixture, closes the
  session, and returns the recorded answers. Test bodies only assert, so the
  order does not matter, and no shared session stays open while another test
  needs the one OpenStack slot. Helpers that fell back to the newest session
  (`from_attacker`, `target_code`, the sensor tail, the corp helpers, the
  declared-range check) take the session explicitly. Steps a skipped
  compose-only test needs (topology, the canary, the probe past the WAF) run
  only on compose.
- **What shares.** The red-team run serves topology, evasion, strategy
  honesty, the board attack and the before-silencing check (its 12 cases fire
  every case those used). One rules session runs the buffer-less rule alone
  first, then baseline + ported rule + noisy rule, with the invalid-rule check
  at the start. One board session serves loot (fabricated loot before the
  real one), objectives, score reveal, the empty-objectives check and the
  canary. One session serves origins, rotation and the sqlmap tool case; one
  tuned session the map and the probe past the WAF (the map's tuning, which
  detects without blocking, lets the probe through as the old exclusion did);
  one the operator log and the attacker box; one each the corp rogue-admin and
  option-flip exploits for both corp modules; the suppression module silences
  once for its two tests; the guided lesson session is the first of the two
  isolated sessions.
- **Not shared.** The console attack in `test_front_door` (it proves the
  console path, which the red-team runner does not take); window correlation
  with strategy comparison (`tp == 1` for both strategies cannot hold beside
  another window case); the corp content overwrite; the indiscriminate
  defence (its catch-all rule set must stand alone); the two concurrent
  sessions; `baseline_rules` (a fresh session by design).
- **Result.** Sessions opened, by static count: docker 42 -> 21, OpenStack
  27 -> 12. Test functions unchanged (148 collected before and after).
- **Reset in parallel.** `configure_slot()` ran edge, WAF, collector,
  wargames, sensor and log forwarding one after another, so the wargames
  waited behind the edge reboot. It now runs one thread per host (edge; WAF;
  collector security group; wargame host: wargames, sensor, log forwarding in
  that order), waits for all, keeps the declared reporting order and raises
  the first failure in that order, all under the same `RULE_CHANGES` hold the
  reset already takes. Standard library threads; no dependency. Unverified
  until a cloud run: that nothing on the WAF or the wargame host needed the
  edge to be up (both are reached and log over management, which the edge
  does not route).

Metrics: core_loc 569 (unchanged), dependencies 6, services 9, tests 1647 ->
1649.

## 2026-10-12 — Merge: one way a rebuild lifts suppressions; the corp exploit checks share

Two branches fixed the same stuck suppression. Kept: the close that rebuilt
and handed the slot to the reset marks every open suppression restored at the
close time, and a restore of one already restored answers 200 with "already
restored". Dropped: the restore that skipped the sensors for any ended session
on a substrate that rebuilds, since it also lifted a suppression whose rebuild
had failed and whose sensor still ran without the rule. What remains of it is
the restore's existing fallback: for an ended session whose sensor does not
answer, a substrate that rebuilds at close counts like one whose stack is gone.
All tests from both branches stay.

The two corp exploit checks enabled on OpenStack (`test_corp_cve_rogue_admin`,
`test_corp_cve_option_flip`) opened no session of their own but repeated the
exploit the shared corp fixtures already fire; they now assert on those
fixtures' records (the option-flip fixture also records `default_role`). The
content overwrite and the corp site checks are unchanged. `bin/verify`'s wait
for a running reset polls every 2 s, as `test/conftest.py` does.

## 2026-10-12 — The close resets the edge and the wargame host in place

Ruled by the user: shorten the OpenStack reset as far as it safely goes.
Measured before: close to READY 95-116 s per session (Nova rebuild of all
four slot VMs about 30 s, the edge's config install and reboot about 30 s,
then the configure steps); 13 resets took about 23 of the 30:44 acceptance
run. This reverses OPENSTACK.md §6.1's earlier reason for rejecting
`docker compose down -v` on the wargame host ("the edge's reboot already sets
the reset's length"): the edge no longer reboots per session.

- **Edge: in place, verified by hash.** The session can change only
  `fsl.rules` (seeded on open); `config.xml` is the same rendered file every
  time, and only the platform reaches the edge's GUI and ssh (`fsl-mgmt`,
  2026-10-11). The reset writes the baseline `fsl.rules` back, compares
  `/conf/config.xml`, `conf.d/fsl.yaml` and `fsl.rules` by sha256, drops the
  pf states of every range subnet, reloads the filter and restarts Suricata
  (OPNsense configd `ids restart` and `filter reload`, opnsense/core
  `src/opnsense/service/conf/actions.d/actions_ids.conf` and
  `actions_filter.conf`), then waits for the Suricata socket and reads the
  edge back as configure does. Any mismatch or failed read-back falls back to
  the install and reboot.
- **config.xml is compared with what the edge recorded, not with the
  rendered file.** Seen on the live edge: after the install-and-reboot,
  OPNsense's boot migrations rewrite `config.xml` (uuids, model defaults,
  `persisted_at` stamps, a generated certificate ref; about 1100 diff lines),
  so its hash never equals the rendered one. `configure_edge()` ends by
  writing `/conf/fsl-settled` (the rendered config's sha256 and the settled
  file's sha256); the reset requires both to match. A missing record (an edge
  configured before this change) falls back once and records.
- **States by subnet, not `pfctl -F state`.** States are floating (`all`) and
  the pass rules keep state with `flags S/SA`, so flushing all states would
  drop the platform's own ssh session to the edge mid-reset, and `pfctl -i`
  matches no floating state. The reset kills states from and to each origin
  subnet and the estate (`pfctl -k <net>`, `pfctl -k 0.0.0.0/0 -k <net>`);
  mgmt is left alone.
- **Wargame host: in place.** `docker compose -p <id> down -v` per wargame
  and for the estate sensor, then the existing `up -d --wait --pull never`,
  sensor and log forwarding. The wargame containers run unprivileged, mount
  no host path and get no docker socket (now a test); `-v` removes the
  anonymous MySQL and WordPress volumes. rsyslog is stopped and the sensor's
  `eve.json` and rsyslog's imfile state removed so the forwarder starts the
  new log at offset 0; the sensor's baseline rules are written back.
- **Kali and the WAF are still rebuilt** (both hand out a root or blue-team
  shell, so state outside config can carry over), then their existing
  configure step (the WAF's audit-log forwarding; Kali has none).
- **Side by side.** The in-place resets start at once, beside the Nova
  rebuilds, under one hold of the rules lock; the seen-rebuilding check
  covers only the VMs the close rebuilt; polls are 2-3 s. The rebuilt side
  reads the cloud again before configuring: found live, the shape cached
  while Nova was rebuilding carried the WAF's old launch time, so ssh checked
  its new host key under the old alias and was refused until the deadline.
- **Recorded trade-offs, not verified threats.** The edge's isolation between
  sessions becomes "config verified by hash" instead of "rebuilt from its
  image": a change that leaves those three files alone (for example a
  package installed from the GUI's firmware page) would carry over. A
  container escape on the wargame host would persist into the next session,
  where a rebuild removed it.
- **Not changed.** `POST /api/range/configure/` (full configure, edge reboot)
  and `POST /api/range/slot/rebuild/` (every VM) keep their behaviour.

Measured 2026-10-12 on the test cloud, three board sessions opened and closed
through the API: close to READY 65.8, 65.9 and 60.1 s (was 95-116 s). All
three took the in-place path: the edge's boot time stayed that of the manual
configure before them, Suricata answered `ruleset-stats` with 4 rules loaded
and pf held the WAN pass rule; the wargame host kept its boot time and its
containers were created at each reset. The first reset after deploying fell
back to the install and reboot as designed (no `/conf/fsl-settled` yet).
## 2026-10-12 — The acceptance run is split across parallel pytest processes

Ruling: make the acceptance run as fast as possible with async and parallel
execution. Measured on OpenStack at 9367bbf: 30:44 for 148 collected tests,
13 sessions, about 74% of it the ~105 s range reset after each close.

- **`bin/acceptance` replaces `pytest test/` in `bin/verify`.** Standard
  library only (no pytest-xdist; `dependencies` stays 6). It starts N worker
  processes, N = `max_sessions` from `/api/range/ready/`, over disjoint module
  sets, plus one idle process beside them, then a solo process, and prints one
  line with the totals of every process's JUnit report. 148 tests collected
  before and after; every module runs in exactly one process (unit-tested for
  N = 1..4).
- **Idle beside the workers (the async part).** Only four modules need no
  session and no host: `test_fabric`, `test_geoip_durable`,
  `test_origin_placement`, `test_waf_geolocation` (Elasticsearch, the fabric
  answer, repo files). They skip the reset wait. Every other module that names
  no session runs a command on a range host and needs the range standing, so
  it cannot overlap a reset: on OpenStack the slot VMs are being rebuilt. With
  one slot this saves at most the time those four spent queued behind resets;
  the resets themselves stay serial until a second slot exists.
- **N workers.** Modules sharing a session-scoped fixture (read statically
  from `conftest.py` and `shared_sessions.py`) stay in one process; groups go
  heaviest first to the least-loaded worker by `test/durations.json`
  (estimated from the 2026-10-12 OpenStack setups; `--save-durations` writes
  measured ones). N = 1 runs every non-idle module in alphabetical order, as
  before. `test_concurrent_sessions` and `test_lesson` hold two sessions at once
  and run alone after the workers.
- **Every call names its session.** Beside another worker the newest stack is
  not the test's. Fixed: `from_attacker` in window correlation and strategy
  comparison, the corp content overwrite helpers, `origins_session` (lists
  origins inside its session), segmentation's `/api/attacker/`, criterion 1's
  `/api/rules/`, `segments()`. Modules that need a stack but open no session
  (`STANDING_STACK`) share one worker and one session it holds until its next
  open; `range.py` defaults a session-less call to it there and fails one made
  while the worker has its own session open. The red-team CLI built its
  launcher before the session existed and found the network on the newest
  stack at fire time; it now binds the launcher in the `announce` callback
  (`redteam/run.py`; `harness.py` unchanged).
- **Platform, minimal.** `GET /api/origins/?session=` (it always read the
  newest stack). Suppressions list `session_id`, so `defence_is_on` ignores a
  suppression on a session still open (another worker's) and still fails on
  one an earlier run left. Docker open: the open sessions are read inside a
  lock around the teardown of ended stacks, after the new row exists, so two
  opens at once cannot take down each other's new stack (before, `live` was
  read before the row was created). A stack of a session closed less than
  three minutes ago is kept: its Filebeat may still be shipping alerts the
  closed session is scored on, and another worker's open took it down
  mid-scoring. Same for a person closing one session and another opening.
- **Room.** An open refused for want of room (409 "already open on the
  range" or "resetting") waits until `/api/sessions/?state=open` is below
  `max_sessions` and the slot has settled, then retries; the red-team run is
  retried up to 3 times on a 409.
- **Split-mode skips.** Workers skip the per-process target probe and the
  terminal origin/label clear: `bin/verify` already opened a session on a
  healthy target, and `bin/acceptance` refuses to start with a session open,
  so those clears would act on another worker's session.
- **Estimates, not measured.** OpenStack N = 1: about 30 min (unchanged but
  for the idle four). OpenStack N = 2 once a second slot exists: the two
  worker sets are about 1,015 s each by the table, scaled to the measured
  total about 15-18 min, if two slot resets do not slow each other. Docker
  N = 2: about 60% of N = 1 by the table, bounded by the solo phase.
- **To check live.** Docker N = 2: no lost alerts (FN where N = 1 had TP);
  memory with up to two open and a few kept stacks (about 1.5 GB each); the
  standing session opens once. OpenStack with two slots: `run_on_role` names
  no session, so session-less host checks must target a slot; a close lifts
  every suppression and starts a reset, which would cross workers; the
  readiness check blocks on a suppression in force.

Metrics: core_loc 569 (unchanged), dependencies 6, services 9, tests 1653 ->
1675.

## 2026-10-12 — A second range slot on OpenStack, so two sessions run at once

Ruled by the user: make the acceptance run as fast as possible by standing a
second range slot on OpenStack, so `bin/acceptance` runs two workers. Quota
checked first (admin, `openstack quota show fsl-range --usage`): cores 20,
RAM 50 GB, instances 10, networks 100, subnets 100, ports 500, security
group rules 100, security groups 10. With two slots: cores 18, RAM 40 GB,
instances 9, networks 6, subnets 64, ports 25, rules 26, groups 6. Nothing
needed raising.

- **Slot identity.** `compute.slots` in `cloud.yaml` (optional, default 1,
  so other clouds change nothing) reaches the platform as
  `FSL_OPENSTACK_SLOTS` through the Heat stack; `max_sessions` is that count.
  Slot 1 keeps today's names, ports and metadata, so the live range was not
  touched; slot N>1 names servers and ports `<host>-N` and tags its servers
  `fsl_slot=N`. `OpenStack.in_slot(n)` is the slot-bound adapter: it reads
  only its slot's servers (and the platform), by their declared host name,
  so roles, runners, topology, the declaration's per-host facts (rule file,
  reload, logs) and the edge's rendered settings are the same in every slot.
- **Networks: a copy of the internet and the estate per slot.** Two edges
  cannot hold the same `.1` on one network, and the origin addresses are what
  the GeoIP placement, the map and the per-country scoring read. Each slot
  beyond the first gets `fsl-internet-N` (the same 30 origin /24s) and
  `fsl-estate-N` (the same estate CIDR), tagged `fsl.slot=N`; these networks
  have no router (the edge is their gateway), and on the test cloud Neutron
  created the 31 subnets with the same CIDRs as slot 1's. So every slot
  attacks from the same addresses and alerts are placed the same. Not chosen:
  per-slot origin subnets (a second set of addresses per country, so the
  GeoIP database and the map would have to know two ranges per country), or
  one edge for both slots (one sensor, one rule set and one reset for two
  sessions). `mgmt` stays shared (recorded deviation from one fabric per
  slot): each slot's hosts take their own DHCP address there and `fsl-mgmt`
  admits only the platform, as before. Opening the collector for one slot
  keeps the other slots' sender rules.
- **Alerts per slot.** Both slots send from the same origin addresses at the
  same time, so one index would score each session on the other's alerts.
  The collector's syslog input tags each line with the slot its sender's
  hostname names (`-N` before the domain; none is slot 1: `fsl-waf-2`,
  `fsl-edge-2.range.internal`, set by Nova from the server name and, for the
  edge, by the rendered `config.xml`) and writes it to `fsl-logs-slotN-*`
  (Filebeat `script` processor and an output `indices` rule); on OpenStack a
  session reads `fsl-logs-slot{slot}-*` (`ELASTIC_SESSION_INDEX`), as a docker
  session reads its own. Slot 1's rendered `config.xml` is unchanged, so its
  in-place reset still matches the hash its edge recorded. Not chosen: a
  collector port per slot (a static input per port in `filebeat.yml`), or
  filtering by sender address at ingest (the query lives in `ingest/elastic.py`,
  a gated core file, and filtering after the fetch would let two slots'
  traffic share one capped read of 5,000 documents).
  Before this change the OpenStack collector wrote `fsl-logs-shared-*`; old
  closed sessions keep their stored detections.
- **Session to slot.** An open takes, under a lock, the first slot no open
  session holds that reads READY, and records it on the session
  (`Session.slot`, with a unique constraint on the slot of open sessions).
  Every per-session range call goes to that slot (`_range(session)`), the
  close resets only that slot and marks only that slot's suppressions
  restored, and the reset state is per slot. Rule changes take a per-slot
  lock instead of the one `RULE_CHANGES`, so one slot's minute-long reset
  does not stall the other session's rule calls. Calls that name no session
  take the newest session's slot, as before; `run_on_role` takes `--session`
  or `--slot` and refuses neither when there is more than one slot; the
  console's VM terminals take the session (`?arg=<id>`, ttyd `-a`).
- **Readiness.** `GET /api/range/ready/` lists every slot (`slots`: number,
  holder, phase, checks) and puts the slot the next open would take at the
  top level, so the harness's room check and `bin/cloud` keep their shape;
  a held slot reads `IN_USE` and is not checked. `bin/cloud up` waits for
  every slot; `bin/verify`'s rule check waits out every slot's reset.
- **Image builders.** With both slots standing, the quota leaves room for one
  2-core builder. `ensure_images()` boots only as many builders as Nova's
  absolute limits leave room for against the builder flavor; the rest stay
  `missing` and boot on a later `POST images/` once a builder is deleted, so
  `bin/cloud up`'s loop builds them one at a time. With no room and no
  builder at work it answers 503 naming the fix (take slot 2 down or raise
  the quota). Not chosen: always serialising builders (a fresh cloud has room
  for all four at once).
- **Harness.** `ThroughPlatform.run` passes `--session`; beside another worker
  on OpenStack, session-less host checks open the worker's standing session
  (as on docker), and the per-test reset wait is skipped there, since every
  call reaches a slot its worker holds.

Unchanged: the docker substrate (its sessions carry no slot), slot 1's
names, and every assertion in `test/`.

Measured 2026-10-12 on the test cloud: slot 2 built through the API
(`fabric/`, `slot/?slot=2`, `configure/?slot=2` in 72 s) while slot 1 stayed
READY. Two sessions opened at once took slots 1 and 2 and a third got 409; one
case fired in each left from the same JP origin address (106.128.0.14), and
its alerts landed in `fsl-logs-slot1-*` and `fsl-logs-slot2-*` respectively,
each session ingesting only its own. Closing slot 2's session rebuilt
`fsl-waf-2` and `fsl-kali-2` only, slot 1 stayed `IN_USE`, slot 2 was READY
64.9 s later. Full `bin/verify` with two workers: acceptance 72 passed,
0 failed, 0 errors, 76 skipped in 737 s (was 30:44 with one slot, the same
counts); worker 1 12:08, worker 2 8:54; unit 1799 passed; `bin/verify` 937 s
in all. It failed only on the `core_loc` ratchet (569 against 560, known) and
on untracked files, because the VM's git index was not re-pointed at the
deployed commit this time.

Metrics: core_loc 569 (unchanged), dependencies 6, services 9, tests 1675 ->
1731.

## 2026-10-13 — The tutorial becomes a course; the lesson's state moves to the server

The user found the one lesson goal-less, thin and unguided, asked for a survey
of learning platforms and Korean vendors' writing, and approved the
recommended design: `docs/superpowers/specs/2026-10-13-blue-team-course-design.md`
(rulings D1-D11 there). In short:

- Build order: a shared foundation (ungated open path, server-side step
  progress and checks, check replays out of both scores, WAF snapshot at
  VERIFY and close, corrected goal), then the existing lesson made honest
  (Lesson / Practice / Wargame rungs, ticket opening, debrief), then a linear
  path of lessons 0-7 inside `wargames/board/scenario.yaml` (and corp).
- Lowering the paranoia level stays a passing fix (2026-10-10 kept); the
  result names the fix.
- Suricata lessons complete on detection and report in the second score only;
  the learner writes the signature in a console text area through
  `PUT /api/rules/apply/` (reverses "no rule editor", 2026-09-30, for
  Suricata signatures only).
- Leaks found by the learner's own VERIFY or a lesson check stay out of the
  first score.
- `board-easy`/`board-hard` as directories are retired: several lessons in one
  scenario descriptor prove "one image, many scenarios".
- The 60 s help timer no longer records a hint (changes the 2026-10-11
  approved script).

Not chosen: a triage/report track (one investigation lab only), virtual-patch
SecRules for corp, learner accounts, locked lesson order, per-lesson `.ko.md`.

### 2026-10-13 — The foundation, built

The five foundation items of the course design, as built (unit-tested only):

- The open path seeds and takes the lesson posture on every substrate. On a
  slotted range the Suricata seed is skipped for `local.rules`, which
  readiness has already read on every sensor; reseeding would reload a sensor
  that may be shared between slots (unmeasured, see "Suricata rule isolation"
  in the design).
- `Session.lesson_steps` (0020) holds each step's reached, passed, skipped,
  hint level and done-for-me; `lesson/steps/<step>/`, `.../check/` and
  `.../do/` record and judge on the server; the `accept` lists left the
  payload (the step commands and the answer and line strings followed in
  "Answer text and step commands withheld until earned", below).
  Done-for-me on the exclusion step adds the exclusion through `crs.apply`
  instead of typing the command into the WAF terminal: the server cannot
  type into the learner's terminal, and an agent must be able to call it.
- `REPLAY_MARKS` (seed, verify, check, replay) keep the lesson's own traffic
  out of both scores; VERIFY no longer credits loot.
- `Session.waf_snapshots` (0021) at each VERIFY and before the close rebuild.
- The goal line is corrected and pinned; `lesson.defense` is declared and
  validated.

Not yet proven live: `test_lesson` on OpenStack (now in the OpenStack run),
the server-side checks against a real slot, and the close snapshot before a
slot rebuild.

Metrics: core_loc 567 (unchanged), dependencies 6, services 9, tests 1740 ->
1769.

### 2026-10-13 — Package 1, built: the existing lesson made honest

The Package 1 items of the course design, as built (unit and console tests
only; nothing run live):

- `scenario.yaml` declares `lessons:`, a list (id, order, level, minutes,
  prerequisites, then the lesson as before); the board's one lesson is
  `waf-exclusion`. `Session.lesson` (0022) records which lesson a session
  runs; `POST /api/sessions/` takes `lesson` and `guidance: true` still means
  the first. This is the shape Package 2 fills (D11).
- Rungs (CS-A, HG2): `Session.mode` (0023) guided or self, switched by
  `PATCH /api/sessions/<id>/`, kept on every VERIFY case. Self mode strips
  the step commands from the payload and refuses hints and done-for-me
  (409), so an agent in practice gets no more help than a person. Wargame
  is the plain session.
- Opening (BR-B3, BR-B4, SA-A): the first open of a session lands on Goal;
  the ticket's second line is only what `GET /waf/` read; the starting card
  judges the seed replay with VERIFY's rules (`start` in the detail). The
  step list ticks passed steps only; a skipped one is hollow.
- Steps (CK-C3, CK-C4, RS-R1): step `sqlmap` (kind `replay`) after `retry`,
  so the board lesson is eight steps. The fix class (`lesson.fix_class`) is
  computed in product code from `crs.parsed` output already read by the
  check or the VERIFY snapshot; `rules/` is unchanged and `core_loc` stays
  567. Replay rows carry sqlmap's conclusion lines (`tools.conclusions`),
  the command, the 403 count labelled not judged, and a Kibana link on the
  marker (`kibana.marked` names the WAF's marker field). Unverified: that
  the KQL `transaction.request.headers.X-FSL-Case : "<id>"` matches in the
  live Kibana.
- Debrief (SD-A/B/C, KO-K5): `GET /api/sessions/<id>/lesson/debrief/`,
  rendered by one script in the Check tab and on the score page.
- Korean (KO-K1): R1 is read as covering the Korean TP/FN/FP words
  (`docs/vocabulary.md`) as score labels, so `score.caught` is the Korean for
  "detected" and the parenthetical Korean FN/FP words left the score labels;
  the Korean false positive remains only as the CRS term in the lesson's
  cards. (Superseded 2026-11-15: "Detection results are labelled 정탐, 오탐,
  미탐 and 정상 통과".)
- PG-1: `fsl-opened-sessions` in localStorage and `GET /api/sessions/?ids=`.
- OP-P3: lesson commands and rendering tested over every lesson and both
  declaration flavors; `settings.waf_layout` derives `FSL_WAF`.

Tests whose assertions changed with a ruling: the steps-tab and
verify-finish console tests (SA-A: a step left unpassed is hollow, not
ticked), the step-count test (eight steps) and the step after `retry`
(`sqlmap`); the home-card tests post `lesson` with the start. The console
fixtures mark the session visited so the folded-note tests keep describing
a later visit.

Not yet proven live: the regression replay's timing (13-18 s expected), the
Kibana marker link, the ticket and start card on an OpenStack slot, and the
debrief's evidence rows after a real ingest.

Metrics: core_loc 567 (unchanged), dependencies 6, services 9, tests
1740 -> 1810 (bin/measure).

### 2026-10-13 — Measured on OpenStack slot 1 before Package 2

Measured live on slot 1 of the test cloud, requests through the session's
WAF to the board on the wargame host, CRS at each paranoia level:

| Request | PL1 | PL2 | PL3 | PL4 | Rules at the first refusal |
|---|---|---|---|---|---|
| A Korean search ("Seoul restaurant recommendations", `board-normal-search-korean`) | 200 | 200 | 403 | 403 | 920272, 942460 |
| `<b>bold</b> text` | 200 | 403 | 403 | 403 | 941320, 942131 |
| `https://example.com/docs?page=2&lang=ko` | 200 | 403 | 403 | 403 | 931130 |
| `C++ & C# tips` | 200 | 403 | 403 | 403 | 942440 |
| O'Brien | 200 | 200 | 200 | 403 | 920273 |

- PL1 refused none of 26 realistic requests: no false positive at the
  default level (D1's question), so the PL4 start of `waf-exclusion` stays.
- From PL2 a board 500 reaches the client as 502.
- Suricata sid 9000001 at PL1: stock sqlmap at `?sort=` drew 897 alerts, the
  tamper variant 474, but 18 tamper requests reached the board unmatched,
  such as ``posts_post.id`=`posts_post.id`/**/ANd/**/8074=7435`` and
  `posts_post.id"/**/And/**/1602/**/BeTWEEN...`; `?sort=-created_at`
  matched nothing.
- Each slot has its own sensor rule files: a probe rule, sid 9099901, applied
  to slot 1 was absent from slot 2. This was the design's "Suricata rule
  isolation" check; it unblocks lessons 4 and 5.
- `POST /api/rules/validate/` with a broken rule answered `ok: false` and an
  output of Info lines only; Suricata's error was not shown.
- The exclusion posture `{paranoia 4, exclusions [949110, 959100]}` leaks on
  the OpenStack wargame host as on docker: sqlmap found boolean and time blind
  injection and dumped admin, jiwoo and minseo, and `/loot/` coverage was
  1.0. The board's `?sort=` sink is live there (U2/U11).

### 2026-10-13 — Package 2, built: the course on the board

Package 2 of the course design, as built (unit and console tests only;
nothing run live). `wargames/board/scenario.yaml` lists seven lessons:
`console-tour` (0), `read-the-block` (1), `waf-exclusion` (2),
`choose-the-level` (3), `ids-signature` (4), `ids-body-xss` (5) and
`assessment` (7). Lesson 6 (corp) is not built; it is open in
`docs/STATE.md` backlog 0.

- **The default lesson.** `default_lesson: waf-exclusion` keeps
  `{"guidance": true}` without a lesson, and a session whose `lesson` is
  empty, on the lesson they always ran, now that `console-tour` comes first
  by order. Not chosen: renumbering so the exclusion lesson stays first,
  which would misstate the recommended path.
- **Answers from the record.** Lessons 0, 1 and the Korean step of 3 accept
  the rule, or the variable, that the session's own ModSecurity detections of
  that request name (`of: rule|target`), with the CRS totals (949, 959, 980)
  left out. The answer is a fact of the session, not a key that could drift
  from the range; `949110` still gets its own explanation.
- **Lessons judged by their steps.** A lesson with steps and no `verify` step
  (0 and 1) refuses VERIFY with 400 and says `verifies: false`; its cases are
  only replayed at open so there are records to read.
- **Choose the level.** `solved_at: {paranoia: 2}` (from the measurements
  above, with `board-normal-search-korean` among the lesson's cases) stays on
  the server. VERIFY passes when every case passes, no exclusion was added
  and the level is not below it; a higher level that passes every case also
  passes, so the range, not the declared number, has the last word. Lowering
  the level stays a passing fix in `waf-exclusion` (D1); here it is the task.
  The level control in the note is `PUT /waf/` with the exclusions in force.
- **Each lesson names the cases its VERIFY judges** (`cases:`, as before), so
  `waf-exclusion`'s set is unchanged; the Korean case is in lessons 3 and 7.
  The assessment also judges the other ordinary pages, so blocking
  everything else cannot pass it.
- **IDS lessons (D2).** `detected_by: suricata`: only Suricata's alerts
  count, because ModSecurity's alerts on sqlmap would pass lesson 4 with no
  rule written. A case is detected when an alert on its marker mentions the
  case's `expect` (`SQL`, `XSS`), signatures that also fired on a benign case
  of the run left out, as `/score/` does. VERIFY waits up to
  `FSL_LESSON_ALERT_WAIT` (30 s) after the last case for every attack case's
  alert; benign cases are listed before the attacks so their alerts are in by
  then. The replays stay out of both scores (foundation) and no objective is
  marked. Each row carries TP/FN/FP/TN for agents; the console says
  "detected" and "no alert".
- **Lesson 4's posture** is `ids`: PL1 and `no-uri-sqli.rules`
  (`local.rules` without sid 9000001). With 9000001 loaded both sqlmap
  variants already draw SQLi alerts (897 and 474 above), so the lesson would
  pass before the learner wrote anything; without it nothing alerts on
  `?sort=` and the learner's rule is the one that must fire. The WAF stays at
  PL1: the sensor reads the request on its way in, before the WAF answers, so
  a 403 does not hide it (the 474 tamper alerts were measured at PL1). The
  answer kept on the server (and shown at the last hint) matches what a sort
  value is instead of a quote: `pcre:"/[?&]sort=[-\w.]*[^-\w.&]/i"`.
- **Lesson 5** keeps the `full` posture: sid 9000003 reads `http.uri` only,
  so the body XSS already passes it unseen. Its first step asks which buffer
  9000003 reads. `board-normal-comment` is the benign case in the XSS
  comment's request shape.
- **The rule editor (D3)** reads `GET /api/rules/`, checks with
  `POST /api/rules/validate/` and writes with `POST /api/rules/apply/` on the
  version it loaded. D3 names `PUT`; the existing endpoint is `POST` and is
  kept. Validate now adds `errors` (the `Error` lines of every sensor that
  refused) and reports the refusing output with the most of them, in product
  code (`rules/suricata.py` unchanged, `core_loc` 567). Why the error was
  missing: OPNsense's `suricata.yaml` template configures one logging output,
  syslog, so after the config loads nothing more reaches the console of
  `suricata -T` on the edge; only the Info lines printed before it remain
  (https://github.com/opnsense/core/blob/master/src/opnsense/service/templates/OPNsense/IDS/suricata.yaml,
  read 2026-10-13). The estate sensor on the wargame host runs docker's
  config, which has no `logging` section, so it prints the error. Unverified
  live: that the estate sensor's error lines now reach the editor.
- **"Do it for me"** applies the level, or appends the lesson's answer rule
  (both kept on the server), then judges the step.
- **Assessment** declares `mode: self` and no steps; the home card offers it
  as practice and wargame only.

Tests whose assertions changed with these rulings: the catalogue test now
lists the seven lessons in order and the exclusion lesson's card at order 2,
with `read-the-block` as its prerequisite and its `mode`.

Not yet proven live: every new lesson on a slot; the Kibana queries of the new
click steps (`url : *1=1*`, `url : *sort=posts_post.id*`); the Suricata marker
link (`http.request_headers.value`); the answer rules 9000101 and 9000102
loaded by both sensors; alerts reaching Elasticsearch within 30 s; the Korean
search at PL2 through the site browser.

Metrics: core_loc 567 (unchanged), dependencies 6, services 9, tests
1810 -> 1833 (bin/measure).

### 2026-10-13 — Answer text and step commands withheld until earned

Review of Package 2 found that X4 ("answer keys leave the session payload")
held only for the `accept` lists: `strings.html` shipped every lesson's
`<lesson.text>.answer.<step>` (the board's said "920273.") and
`<lesson.text>.line.<step>` to every page, and the guided payload carried the
exclusion step's command (`ctl:ruleRemoveTargetById=920273;ARGS:q`) before
the rule and target steps were passed.

- The 66 answer and line strings, both languages, moved to a
  `{% comment %}` section at the end of `strings.html`: still the one table
  for Korean, never rendered. `console/strings.py` parses it (the parser the
  string tests already used, now shared).
- A step's `progress` record carries `answer` (`{en, ko}`) once its hint
  level reaches 3 (`lesson.ANSWER`), `line` once passed, and `command` once
  reached outside self mode; the step's `command` in the payload follows the
  same rule. The console renders what it receives and refreshes the popover
  and the Hints tab's solution when a command arrives.
- Kept on the page: the theory and hint cards, some of which name the answer
  (the board lesson's "Why 920273?"). They are the Theory and Hints tabs'
  help, read when the learner opens them; withholding them is a product
  decision not taken here.
- The Practice label on the home page and the session page reads
  `result.lesson.mode`, the mode the last VERIFY ran in, and falls back to the
  session's mode only before a VERIFY.

Tests whose assertions changed: the Hints tab's solution test reaches the
exclusion step before reading the command, and asserts it absent before;
the flavor test marks every step reached before comparing commands.

### 2026-10-13 — The course run live on OpenStack; what the run broke

Branch deployed to the platform VM (192.168.0.210, two slots) over the `dev`
clone with rsync and a local `docker compose build platform` under the GHCR
tag; migrations 0020-0023 applied to the kept store (backup in
`/opt/fsl/backups/db-20261012T1816*-pre-course`). Every lesson was walked over
the REST API on a slot, then the full `bin/verify` ran with two workers.

| Lesson | Steps passed | VERIFY | Took |
|---|---|---|---|
| console-tour | 4/4 (2/4 before the site fix) | none | 29 s |
| read-the-block | 5/5 | none | 49 s |
| waf-exclusion | 8/8 with the site; 7/8 before | PASS, `path_target`; held at PL4, leaked 3 of 3 under {PL4, 949110, 959100} | 355 s |
| choose-the-level | 5/5 | PASS at PL2 (FAIL before the tamper fix) | 195 s |
| ids-signature | 6/6 | PASS, 2/2 detected, sort quiet | 179 s |
| ids-body-xss | 5/5 | PASS, 1/1 detected, comment quiet | 64 s |
| assessment (self) | none | PASS at PL2, `level`; FAIL at PL4 with 920273, 920272 and 942460 excluded on `ARGS:q` (the Korean search still 403) | 114 s |

The sqlmap cases send requests on the OpenStack Kali (1,973 403s for the
stock variant, no `--disable-hashing` error). Closing an `ids` session restored
slot 1's edge rules to `local.rules` (sids 9000001-9000004, 9000101 gone;
`rules_baseline` true), and `GET /waf/` on a closed session returned the
learner's last configuration.

Fixed, each measured first:

- `redteam/run.py` launched every case from slot 1's Kali whatever slot the
  session took; a slot-2 run hit slot 1's Kali mid-rebuild (ssh refused) and
  19 acceptance tests errored on the shared fixture. It now asks
  `in_slot(session.slot)`.
- The Website pane was docker only (`SITE_PORT` None), so the browse steps of
  four lessons could not pass on OpenStack. The proxy now reaches the slot's
  WAF over `mgmt` (the platform's port already reaches it through
  `fsl-mgmt`); the platform template opens 8002, and the live group got the
  rule by hand.
- From PL2, CRS 950100 and 959100 refuse a board 500 after its headers are
  sent and nginx drops the connection; when the tamper variant's heuristic
  probe drew one, sqlmap ended "unable to connect" after one request (4 of 10
  runs at PL2) and VERIFY read it inconclusive. The variant now passes
  `--skip-heuristics` (6 of 6 held at PL2; still dumps under the control).
- One red team run now leaves more than 5000 records (13,403), and the single
  capped read scored every case fired after sqlmap FN. A full ingest pages by
  `@timestamp` in `api/views.py`; `ingest/elastic.py` and `core_loc` are
  unchanged.
- The debrief after a live PASS listed no evidence (nothing had ingested the
  VERIFY run); the console ingests the run's window first. Its long request
  paths now wrap (the score page was 1,773 px wide at 1,440).
- console-tour and read-the-block showed a FAIL start card judged by VERIFY's
  rules, calling a curl SQLi the WAF answered 403 inconclusive; only a lesson
  with a VERIFY shows one.

Full `bin/verify` on OpenStack after the fixes: unit 2003 passed; acceptance
77 passed, 0 failed, 0 errors, 71 skipped (`COMPOSE_RANGE_ONLY`) in 1,448 s;
27 min in all; ratchet clean. The first run, before the fixes: acceptance 58
passed, 19 errors; the second: 73 passed, 1 failed, 3 errors (the
`test_corp_*` rogue-admin fixture found no `_wpnonce` once and passed on a
rerun; not explained).

Open, not decided here: the assessment's goal says "at the WAF's strictest
level", yet PL2 passes it (D1 keeps lowering the level a passing fix, named
`level`), and a parameter-scoped exclusion at PL4 did not serve the Korean
search (hypothesis, not checked: 920272 also matches it in `REQUEST_URI`).

## 2026-10-13 — The Korean search replaces O'Brien as the course's false positive

The user: O'Brien is not a search the club's users would make; a Korean search
being blocked is the realistic case. O'Brien was the lesson's false positive
only because it was the one measured on 2026-10-10, and it appears only at
PL4, which forced the "someone set the strictest level" opening. The
2026-10-13 measurement found the Korean search blocked from PL3 (920272,
942460) and other realistic false positives from PL2. The lessons move to the
Korean search; `board-normal-search-with-apostrophe` stays as a benign case
(benign cases are never removed) but no lesson is built on it. The rework of
the course follows a second survey of how learners actually work through
lessons (task classes of different problems, each changing one thing; worked
example first; judgement and volume as difficulty axes); its plan goes
through gate 1.

## 2026-10-13 — Scenario course: foundations, scenarios on live traffic, a GNS3 topology

The user judged the scripted step lessons the wrong direction: they teach a
tool's clicks, carry no traffic, ask for no judgement and repeat one task
without hints instead of harder tasks. Approved design:
`docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`.

- Audience: security-club freshmen who may not know networking; foundations
  F1-F6 come first, taught on the range.
- The unit becomes a scenario with continuous benign and attack traffic;
  difficulty rises by task class (judgement, availability vs blocking,
  missed attacks, unknown), support fades inside a class.
- An attack scheduled by a scenario is the red team's attempt: when it dumps
  the secret it submits the loot and the first score counts the loss (the
  target still decides). The learner's own VERIFY and lesson checks stay out
  (D7 kept for those).
- Blocked customer requests are counted in the second score (availability,
  as Locked Shields weighs uptime against attacks).
- Completion: over a final verification window every attack is held and
  every customer request served (the 2026-10-08 two-condition rule, judged
  over a window instead of one replay of each case).
- The topology is a real GNS3 project per substrate, served by a GNS3 3.1
  server in the platform's compose (`services` 9 -> 10, accepted); learners
  see it read-only; GNS3's MCP is for development only.
- O'Brien leaves the course and stays a benign regression case.

Not chosen: a topology generated or drawn by the platform alone (the user:
AI-drawn topologies invent layers that are neither network nor service);
GNS3 3.0.6 (no MCP, fails to open projects whose images are missing).

### 2026-10-13 — P1 built: the topology as GNS3 projects; GNS3 cannot open them without their emulators

Built: `deploy/topology/range-{docker,openstack}.gns3` (revision 9), the
consistency test against the declaration and the compose files,
`bin/check-topology` (gns3-server 2.2.61 and 3.1.0a6 each load both files:
2.2 validates its JSON schema, 3.1 upgrades to revision 10 and validates; names
kept), the `gns3` control-plane service (`services` 9 -> 10, accepted in the
ruling above; port 3080 published like 8000, opened in the platform security
group), `GET /api/topology/`, the per-session `project` overlay on
`GET /api/sessions/<id>/topology/`, `GET /api/sessions/<id>/topology/follow/`,
and the blue console's Topology pane. `platform/gns3.py` is the one file that
knows the GNS3 API (ARCHITECTURE's seam table; CLAUDE.md's list still needs
the line).

Measured against the image on Linux (and gns3-server on macOS): GNS3 3.1 opens
a project only by creating every node on its compute, and creation is not
inert. `qemu` needs `qemu-system-x86_64` (with it installed, qemu nodes create
without a disk image); `ethernet_switch` starts uBridge and a kernel bridge
(`compute/builtin/nodes/ethernet_switch.py`, needs uBridge built with its
`brctl` module and `CAP_NET_ADMIN`; Debian has no uBridge package); `docker`
needs a Docker daemon, and only `ImageMissingError` is tolerated as a degraded
node (`controller/node.py`). Without them both projects load and stay closed;
the web UI's map calls `POST /projects/{id}/open`, which needs
`Project.Allocate`, so the Auditor gets 403 on a closed project, while it sees
a project an administrator holds open (checked with a two-qemu-node project).
The design's "nodes are never started (no KVM, no privilege, no docker
socket)" therefore does not give a viewable project. Until that is decided,
`/api/topology/` offers the web UI only while GNS3 reports the project
`opened`, and the Topology pane draws the same file itself; the follow view
works either way.

Also found: a non-admin user's project list is empty unless the project is in
a resource pool the user has an ACE on (direct ACEs list only the user's own
projects); the console deep-links to the project instead. Installed with
`[ai-features]`, 3.1 tries to `git clone` its skills repository at start; the
image has no git, so it logs an error and fetches nothing. The two `.gns3`
files are 1,801 of the `product_loc` rise (JSON, indented as GNS3 writes it).

Open: give the GNS3 container `qemu-system-x86`, a uBridge build and
`CAP_NET_ADMIN` plus a Docker endpoint that reports the images missing (the
docker nodes then open degraded), or keep the console's own drawing as the
learner's view and GNS3 as the files' validator and the development MCP
server.

### 2026-10-13 — GNS3 holds the projects open; learners see the real web UI

The user chose the first option above: learners see GNS3's own web UI with the
range's project open, read-only. Built and measured on the platform VM
(192.168.0.210, branch synced over the `dev` clone, `docker compose build
gns3`):

- The image adds `qemu-system-x86` and uBridge 1.2.3 built from the
  `GNS3/ubridge` release tag (3.1.0a6 refuses uBridge below 1.2.3; 1.3.0 is
  four days old), with `setcap cap_net_admin,cap_net_raw+ep`; the server runs
  as `gns3` (uid 10002), which joins the Docker socket's group at start as
  `fsl` does in the platform.
- The service gets `cap_add: [NET_ADMIN]`, `/dev/net/tun` and the Docker
  socket; not privileged, no host network. Data moves from the `gns3data`
  volume to `/var/lib/fsl-gns3` bound at the same path, because the host's
  daemon resolves the docker nodes' bind mounts (GNS3's resources directory,
  each image's `VOLUME`s) on the host.
- Result: both projects `opened` within about a second each of the server
  answering, every node created and none started or degraded: docker 17 nodes
  (14 docker, 3 switches started as kernel bridges inside the container), 16
  links; openstack 15 nodes (5 qemu, 5 docker, 5 switches), 16 links. GNS3
  pulled nothing: the entrypoint rewrites the repo's `ghcr.io/nekonic/*:dev`
  tags to `FSL_IMAGE_TAG`, the tag the host runs, so every image was already on
  the daemon (third-party images are pinned by digest or version and were
  present). Without the rewrite each `:dev` image would be pulled (fsl-kali
  1.33 GB, corp and corp-db 1.1 GB each, board 0.6 GB, ...). A host that does
  not hold an image pulls it on open; a failed pull keeps that node degraded.
- Costs: 19 containers `GNS3.<node>.<project id>` in state Created on the host
  daemon, 4.1 kB each; `/var/lib/fsl-gns3` 19 MB; the image 1.06 GB, of which
  the added packages are 137 MiB (qemu-system-x86 63 MiB, qemu-system-data
  18 MiB); idle `fsl-gns3` 266-270 MiB RSS and 0.3-0.4% CPU; a restart reopens
  both projects in 18 s (stale containers are removed and recreated by GNS3).
- The learner (Auditor) sees the opened project's map through
  `fsl-auditor.html` on :3080, and is refused (403) start, open, close,
  delete, node and drawing create, image pull and user create; it can read the
  host's Docker image list.
- The `fsl-platform` security group lacked 3080 (stack made before P1); added
  as in `docs/OPENSTACK.md` §3.5.

Consequences: GNS3's admin now controls the platform host's Docker daemon, as
the platform container already does (`docs/THREAT-MODEL.md`); its password is
generated and never handed to learners. The GNS3 containers carry their
images' labels; an image built locally by compose carries
`com.docker.compose.project=fsl`, but compose and the platform's lookups filter
on running containers or `oneoff=False`, which these never are (`docker
compose ps` lists none; checked live).

Then the maps were made readable for a learner (segment zones, plain-words
notes, the sensor's namespace drawn; `docs/ARCHITECTURE.md`, The topology).
GNS3 3.1 rewrites a node's label to its name on load (`controller/node.py`),
so the plain words are text drawings beside the nodes, and the names stay the
host names the platform and the consistency test match on. A drawing whose
font is the 2.2 default (TypeWriter 10) is shown in Noto Sans by the 3.1 web
UI and any other TypeWriter text in the browser's serif, so every text is Noto
Sans. The web UI opens with its topology summary over the map; that panel's
visibility is a constant in the bundle, not a stored setting, so the learner
closes it once. Checked live on session 297 (board, slot 1): the blue
console's Topology pane frames the opened OpenStack project; "Follow a
request" on the Website pane's search for a Korean phrase, a Seoul restaurant recommendation (200, not blocked)
walks internet, fsl-edge, estate, fsl-waf (passed, no rule), fsl-wargame-host,
board-default, board (200). The hop list says the source is unknown: a
Website-pane request carries no origin address, and on OpenStack the platform
sends it to the slot's WAF over `mgmt`, not through the edge the walk draws.

### 2026-10-13 — P2 built: foundations F1-F6, answered from the learner's own records

Phase P2 of the scenario course design, as built and walked live on OpenStack
(platform VM 192.168.0.210, both slots). `docs/ARCHITECTURE.md`, "Foundations
F1-F6", has the units, the new step kinds and where each answer is read.

- **A group beside the lessons.** The units are a `foundations:` list in the
  board's `scenario.yaml` (ids f1-f6), not lessons ordered before the others:
  `wargames.lessons()`, the default lesson and the course's order stay as they
  are until P6 removes the old lessons, and the catalogue lists the group first
  as "Foundations" with minutes and what each unit teaches.
- **No question has a fixed answer.** Range facts come from the substrate's
  GNS3 project and the declaration, so F1 answers fsl-edge / fsl-platform /
  board-default on OpenStack and fsl-waf / fsl-elasticsearch / estate on
  Docker. On OpenStack Elasticsearch has no node of its own; it runs in the
  platform's compose, so the log store is the scorer's host; the OpenStack
  map's note for fsl-platform now says "log store (Elasticsearch)". Request facts come from the
  learner's own Website pane request, follow walk and records; counts from the
  sensor's http records; leaks from `/loot/` against the session snapshot.
- **F4 sends a second request.** The WAF's audit log is `RelevantOnly`, so a
  Korean search the WAF passed leaves no WAF record and no "WAF verdict" to
  read. F4 first asks which engine recorded the Korean search (Suricata only;
  the Kibana link for it shows every record, not only alerts), then has the
  learner search `<script>alert(1)</script>` and read the WAF record's `status`
  and `source_ip`. Not chosen: running F1-F4 at `minimal` so the Korean search
  is blocked, which would make the course's first request a false positive.
- **The learner runs sqlmap.** A `kali` step's command is the case's argv with
  the step's own `X-FSL-Case` marker (as the harness labels tool cases); the
  stamping proxy's label was not used because the Red console clears it when it
  opens. The run is recorded as an ordinary malicious case when the sensor's
  http records carry the marker and sqlmap's user agent, so it counts in both
  scores (it is the learner's red action, not a platform replay).
- **F6 hands in the loot inside the unit.** The step takes the pasted sqlmap
  table and credits it through the same code as `POST /loot/`, attributed to
  the kali case by its id. The red console's loot panel takes JSON only and
  attributes by a two-minute window from submission, which a freshman reading
  the output would often miss, and an unattributed objective counts as lost
  unnoticed. `_credit_loot` now keeps the matched accounts on the case it was
  attributed to (`meta.loot`).
- **F6's posture** is a new defense, `missed`: PL1 with 949110 and 959100
  removed (the measured leaking posture was PL4 with the same removals; PL1
  keeps F5 and F6 at the same level so only the removal differs).

Found live and fixed (each a commit):

- The topology overlay placed nothing on slot 2: OpenStack reports a slot's
  servers by their declared names and the overlay looked up `fsl-waf-2`. A
  Website pane request on slot 2 was drawn platform, unknown, fsl-waf with no
  source address, and F2's source question had no answer to read.
- Follow showed a blocked request with no rule ids: the blue console ingests
  only after a VERIFY. Follow now ingests the last 600 s first.
- The kali step's Kibana link put the alerts-only query in front and matched
  nothing.
- F6's run left 16,864 records and the first score said three objectives lost
  unnoticed (TP 0, FN 1) until something ingested; the kali check now ingests
  when it records the run (then: three lost, noticed; TP 1).

Live walk over the API (sessions 299-304, closed):

| Unit | Session (slot) | Result |
|---|---|---|
| F1 | 299 (1) | entry fsl-edge, logs fsl-platform, segment board-default passed; fsl-waf, fsl-elasticsearch, estate refused |
| F2 | 300 (2) | the Korean search 200; follow drew fsl-platform (10.31.0.238) -> mgmt -> fsl-waf (passed) -> estate -> fsl-wargame-host (sensor: 1 http record, 10.30.0.177 -> 10.30.0.184:8000, 200) -> board-default -> board; source 10.31.0.238, port 8000 (and 80), status 200 passed, 10.0.0.1 / 443 / 403 refused |
| F3 | 301 (1) | GET, /search/, q, 2xx passed; POST, the search words, 4xx refused |
| F4 | 302 (2) | engine suricata passed, modsecurity refused; `<script>` 403; status 403, WAF source_ip 10.31.0.238 passed |
| F5 | 303 (1) | `' OR 1=1--` 403, stopped at fsl-waf, rule 942100 passed (949110 explained); sqlmap from Kali via the platform's attacker runner, 20 s, sqlmap counted 1,973 403s, the edge sensor recorded 1,836 http records with the marker; 1,928 and 1,973 passed, 918 refused |
| F6 | 304 (2) | exclusions read from the WAF (949110 passed, 942100 refused); sqlmap 69 s dumped admin, jiwoo, minseo; the sensors recorded 2,304 (estate) and 2,233 (edge); a forged row matched nothing, the table matched 3; leaked 3; first score 3/3 lost, noticed |

Not proven: the learner's typing in the Red console's ttyd terminal (the live
runs used the attacker runner with `/etc/profile.d/fsl.sh`, the same proxy
environment); the Kibana views behind the `records: all` and kali links
(the queries were read, not opened in Kibana); the console walk of every unit
in a browser (only F2's follow view and F6's pages were captured); Docker.
Why the edge sensor recorded 7% fewer requests than sqlmap sent is not
measured (hypothesis: UDP syslog loss between OPNsense and the collector); the
10% tolerance covers it. Observed, not fixed: a closed session's first-score
table shows every objective kept when `/score/` fails to load (once, right
after close) although the header says 3/3 lost; the score page's note and
CLAUDE.md say sqlmap sends "about 94 requests", while these runs sent
1,973-2,304.

Metrics: core_loc 567 (unchanged; `elastic.suricata_marker` renamed from
private), dependencies 6, services 10, tests 1893 -> 1912 (bin/measure).

### 2026-10-13 — P3 built: customers who use the board for the whole session

Phase P3 of the scenario course design. `docs/ARCHITECTURE.md`, "Customer
traffic", has the mix, the generator, the API and the per-substrate table.

- **A customer request is a `CustomerRequest` row, not a `Case`.** The
  ruling counts each blocked customer request; a session at 1-2 requests a
  second makes 3,600-7,200 an hour. As cases they would flood `per_case`,
  break "one case is one decision", and make `correlate` (cases × detections,
  pure Python) grow with both: 600 customer cases against the 16,859
  detections of session 304 is about ten million comparisons on every score
  read. Instead score 2 gains a `customers` block computed in SQL
  (`Count` with filters; the alerted ones by a `marker IN (SELECT marker FROM
  detections)` subquery), the console says "Customer requests blocked: N of
  M" (R1, plain words), and TP/FP/FN/TN, `per_case` and the game are
  unchanged. Records arrive as JSON lines pulled by byte offset and stored with
  one `bulk_create` per 1 MiB.
- **Blocked means 403 from the defence.** Django's own CSRF 403 is recorded
  with `refused_by: "app"` (the generator recognises its page) and counted under
  `other`, so a broken flow is not charged to the defence. No answer within
  10 s is `unanswered`, kept apart.
- **Every request carries its own UUID marker,** the same shape as a case's,
  because a `user-` prefix would let a learner sort alerts into customers and
  attacks without judging them (task class 1).
- **Origins.** Customers never use the declared default origin, nor on
  OpenStack any address the attacker sends from: each origin's `source_ip`
  (the SNAT address `set-origin` wears) and the VM's unbound source, read with
  `ip route get` to the target (on slot 1 it is 1.128.0.10, Australia, not the
  default origin's address). Twelve personas are allocated by largest
  remainder over the declared weights the range offers: on OpenStack kr 9,
  us 1, jp 1, cn 1. The KR origin has two addresses in the declaration (its
  Cloudflare share) and one is the attacker's, so the nine Korean customers
  share the other; origins with a single address (tw, hk and ten more) are
  the attacker's alone and offer customers nothing. Raising KR's count would
  need new fixed IPs on the
  Kali port, which only a slot rebuild makes. Docker has no KR network, so
  its customers come from us, hk and br.
- **The SNAT conflict on OpenStack** (`set-origin` SNATs everything leaving the
  VM) is solved by account: the generator runs as `fsl-users` (`setpriv`),
  each persona binds its own origin address, and `POSTROUTING -m owner
  --uid-owner fsl-users -j RETURN` is inserted at position 1, before the
  `ORIGIN-SNAT` jump that `set-origin` appends. Not chosen: per-process binding
  alone (the SNAT rewrites the bound source too); SNAT with an address range
  (the kernel picks one address per source/destination pair, so every
  customer would look alike).
- **Shipped at start, not baked.** `deploy/kali/setup.sh` is unchanged. The
  Kali VM is rebuilt from its golden image at every close, and the image's
  bundle digest covers `deploy/kali/`: any change there marks the image not
  ready, and `rebuild_slot` then refuses every close's reset until the image
  pipeline has run. So `attacker.place_customers` creates the account, inserts
  the exemption and writes the program over the runner (`sudo`) each time the
  customers start; the program lives in `deploy/traffic/`, outside every
  image bundle.
- **Docker** runs the generator in `fsl-<id>-users`, a container from the Kali
  image started by the adapter on the personas' origin networks, labelled
  `fsl.customers=<id>`, removed at stop and by the next session open's
  cleanup. It is not a compose service: `services` stays 10 and
  `wargame_services` 4.
- **Rate**: default 1 request a second, cap 50 (P0's measured ceiling).
  Workers are `2 + 2 × rate` threads (at most 64) sharing one pace.
- **Lifecycle**: `PUT/GET/DELETE /api/sessions/<id>/traffic/`; the close
  stops the generator and reads its last records before the slot is reset,
  and goes on if the box is unreachable, keeping the error. The session page
  shows the switch only with `?traffic` in its URL.
- **The plan holds the seeded accounts' passwords** (jiwoo, minseo) and is
  0600 to `fsl-users`; root on the Kali VM can read it, and the red console's
  terminal is root. These are the board's seed values, public in this repo,
  and no objective is about them.

The closed-session score bug: `session.html` drew the first-score table from
`/score/`'s `breaches` and, when the call failed (or answered without its
tables), passed an empty list, so every objective read "Kept" while the
header, from `GET /api/sessions/<id>/`, said 3/3 lost. Now the table and the
second score say the score could not be read and the page reads it again
every 5 s, up to four tries. Why `/score/` failed that once is not
reproduced: session 304's score answers 200 in 0.6-1.4 s (1.7 MB, its
16,859 detection ids), and the platform container had been recreated at
04:01:27 during that session (the 849423d deploy), nine seconds of restart
being one way a single call fails right after a close.

Not run live: the deploy to the platform VM and the live run asked for (a
board session at PL2 with customers at 2 requests a second for five minutes
beside one sqlmap run) were blocked by the session's permission mode before
the first `rsync`; everything above is unit-tested only. What the live run
must show: the customers' source addresses in the WAF and Suricata records
differ from the attacker's; every customer request is recorded (records vs
the edge sensor's http events with their markers); the `<b>`, URL and
`C++ & C#` searches are counted blocked at PL2; the sqlmap case keeps its
own detections; ingest keeps up; the generator stops at close. Also unproven:
`setpriv`/`setsid` surviving `sudo` over the runner's ssh, and the Docker
container path against a real daemon.

Metrics: core_loc 567 (unchanged), dependencies 6, services 10,
wargame_services 4, product_loc 19,355 -> 20,234, tests 1912 -> 1947
(bin/measure).

### 2026-10-13 — Korean pairs of the learner's GNS3 maps

The user approved Korean copies of the two maps, for security-club freshmen who
read the console in Korean. `*.ko.gns3` is the fourth place Korean belongs
(CLAUDE.md, Working language).

- **A pair, not a second map.** `range-docker.ko.gns3` and
  `range-openstack.ko.gns3` are the English files with only the drawing text
  translated (title, zone titles, the notes beside nodes), in
  `docs/vocabulary.md`'s terms where it has one (Internet, service zone,
  management and monitoring zone, web firewall, attacker PC, perimeter
  firewall, log store ...; the Korean words are in the `.ko.gns3` files). Node
  names stay the host names: the platform, the follow view and GNS3 3.1's
  label rule all match on them. A text drawing's `width` is re-estimated for
  the Korean text; height, position and every rect and line are unchanged.
- **Every id is `uuid5(<English id>, "ko")`, the project name gets
  a suffix, the Korean word for "Korean" in parentheses.** GNS3's compute keeps nodes in one dict keyed by node id
  (`compute/base_manager.py` `create_node` returns the existing node for a
  known id), so a pair sharing node ids could not both be open. Rejected: the
  same ids (breaks opening both); random ids (no rule a test can rebuild).
- **The English file is canonical.** `test_gns3_topology.py` rebuilds the
  Korean file from the English one by the id rule and fails on any difference
  but the words; every Korean drawing text has Hangul and no English one does;
  no id repeats across the four files; the compose and declaration consistency
  tests run on both files of each pair. No generator script: an edit to an
  English map is redone on its pair by hand, and the test says where they
  drifted.
- **The console's language picks the map.** `GET /api/topology/?language=ko`
  serves the Korean project (and its `web_ui` deep link names the Korean
  project id); `en` or no parameter the English; another value is 400. The
  overlay and the follow walk keep reading the English file, since names and
  links are identical; the follow view draws the project the pane was served.

Checked: `bin/check-topology` loads all four files in gns3-server 2.2.61 and
3.1.0a6 (names kept); a local 3.1.0a6 controller loaded all four as four
projects with distinct ids, the Korean name accepted. Not checked: opening the
Korean projects on the live GNS3 service (the local controller cannot create
docker or uBridge nodes off Linux). Expected cost, not measured: opening the
pairs doubles GNS3's Created containers (19 to 38, about 4 kB each) and the
switches' kernel bridges, and lengthens the restart reopen (18 s for two
projects). There is no repo-wide Korean guard to widen: the console-template
test is unchanged, and the board wargame's own pages are Korean content.

Metrics: core_loc 567, dependencies 6, services 10 (unchanged); tests
1912 -> 1920; product_loc 19355 -> 19363 (bin/measure).

### 2026-10-13 — Customer traffic checked live (OpenStack, session 305, slot 1)

Deployed with the Korean GNS3 maps (all four projects opened in fsl-gns3;
migration 0024 applied). At PL2 with customers at 2/s and
board-sqli-orderby-sqlmap fired once (launched from origin ru): customers left
from kr 175.192.0.10, us 73.0.0.10, cn 36.128.0.10 and jp 106.128.0.10, none
from the attacker's origin; after 315 customer requests, 308 were served and 7
blocked, all 7 of them `search-unusual` (the `<b>`, URL and `C++ & C#`
searches measured in P0), each drawing an alert; comments (33), logins (12),
Korean searches (58) and post pages were all served. The sqlmap case kept its
own verdict (TP) in the second score. Closing stopped the generator
(`running: false`, 870 requests sent, 17 blocked) before the slot reset.
Open: 24 detections stayed unattributed in that session; not yet traced.

### 2026-10-13 — The 24 unattributed detections of session 305, traced

18 were alerts on customer requests whose records had not been pulled when
`/score/` was read, so their markers matched no `CustomerRequest` row; `/score/`
now pulls the records first while the customers run. The other 6 are Suricata
`FSL SQLi attempt - URI` alerts on sqlmap requests (5.188.10.10, inside the case
window) whose `http` records never reached Elasticsearch, so
`elastic._transaction_markers` had no marker to join. The collector's UDP
syslog input counted 20,538 receive-buffer errors of about 916k datagrams
(2.2%) since 2026-10-12; a sqlmap run sends about 2,800 records in 16 s. Not
fixed: Filebeat's `read_buffer` is capped by the host's `net.core.rmem_max`,
which is not namespaced, so the fix is a sysctl in the platform VM's cloud-init
and a rebuild, or TCP syslog. Every scenario run below still shows 0-18 such
alerts (session 313: 18, all Suricata, all marker-less, all from the attacker).

## 2026-10-13 — P4 built: the scenario engine and its console, run live with 1.1 and 2.1

Phase P4 of the scenario course design, as built and run on OpenStack
(platform VM 192.168.0.210, both slots, sessions 307-313).
`docs/ARCHITECTURE.md`, "Scenarios", has the descriptor, the engine, the API
and the console.

- **`scenario` names a course scenario too.** `POST /api/sessions/
  {"scenario": "2.1"}` resolves the wargame that declares it; ids are `N.N`, so
  they cannot be a wargame directory. `Session.scenario` stays the wargame; the
  course scenario is `Session.course_scenario` and its run
  `Session.scenario_state` (0025). `lesson`, `guidance`, `defense` and `mode`
  are refused: the scenario sets them.
- **One engine thread in the platform process,** resumed at boot by
  `fsl/wsgi.py`. Not chosen: a separate process. The state is one JSON column
  written under an in-process lock; on SQLite `select_for_update` is a no-op,
  so a second writer would lose updates. Proven live: the platform restarted at
  06:33:39-06:33:50 during session 313 and its attack due at 06:35:42 fired at
  06:35:43.
- **A scheduled attack is the red team's attempt** (ruling above):
  `meta.scheduled`, not a replay mark; a dump goes through `_credit_loot`,
  attributed to its case.
- **One triage item per marker:** each customer request, and each attack case
  however many requests it sent. Per request, one sqlmap run would be about
  2,000 items, and one case is one decision. The item id hashes the marker
  with the session's browse marker so it cannot be matched to `/cases/`; the
  session page hides scheduled cases from its activity while the scenario
  runs. `/cases/` itself still lists them (an agent can read it).
- **The window judges the class's completion** (the design's class table),
  which the first 1.1 run forced: session 312 judged all seven items right and
  failed on nine customers blocked during the window, which 1.1 asks the
  learner to judge, not fix. Judgement completes on the verdicts of the items
  first seen before the window (an attack fired inside it appears after "I'm
  done"); availability and unknown on `{served: all, held: all}`; detection on
  `{detected_by: suricata}`. Blocked customers and held attacks are reported
  beside every result. This reads instruction 4 of the P4 brief ("no customer
  blocked, every attack held, and the class's criterion") through the class
  table; if the base criteria were meant for every class, judgement scenarios
  need a posture with no false positive, which 1.1 by design has.
- **Stuck:** a hint is offered, not recorded. In a scenario session the step
  engine's hint after two failed checks becomes an offer. "The same WAF change
  re-applied" is a `PUT /waf/` that writes the file already in force; the 20 s
  poll cannot see an identical rewrite, and A-B-A is an undo, so neither counts.
  Found live: a poll landing between the write and the PUT's record called a
  new change a re-application (session 310); the PUT now compares with the
  file it read before writing.
- **CRS (instruction 6).** `rules/crs.py` takes the target `REQUEST_URI_RAW`
  and `thresholds {inbound, outbound}` as setvars on the level's `SecAction`;
  `GET /waf/` parses them back and a `PUT` without `thresholds` keeps them.
  `core_loc` 567 -> 580 (+13, all `crs.py`: the constants `THRESHOLDS`,
  `HIGHEST_THRESHOLD` and the `THRESHOLD` pattern 3, the check 5, the render 2,
  the parse 2, the return 1; the target is one alternation on the existing
  line). Reason: scenarios 2.1 and 2.3, the user-approved plan.
- **1.1's posture is PL2** with the `community` customers: the tuning has no
  per-path paranoia level, and PL3 everywhere blocks about 40% of customers.
  Measured at PL2 (session 306): 3 of 415 customer requests blocked, all the
  YouTube-link search (931130).
- **2.1 uses a `readers` profile** (`plain` without comments). Measured at PL3
  with `plain` (session 306): 291 of 728 blocked; Korean searches by 920272 and
  942460 on `ARGS:q`; Korean comments by 920272 on `REQUEST_BODY` and 942460
  on `ARGS:body`; and every page opened after a Korean search (home, post,
  newest, login, English search) by 920272 on `REQUEST_HEADERS:Referer`. The
  Referer stays in 2.1; comments are a second false positive and belong to 2.3
  (and `REQUEST_BODY` is not a tuning target).
- **Fixed in P3's generator:** the board answers in the customer's language,
  so a Korean customer's CSRF refusal (two flows of one persona racing the
  token rotation at sign-in) was Korean, and the generator, looking for the
  English sentence, recorded it as blocked by the defence. Session 307's
  window failed on exactly one such sign-in.

Live runs (OpenStack, sessions closed, slots reset):

| Session | Scenario, what was done | Window | Fix named | First score | Customers blocked (all / in window) |
|---|---|---|---|---|---|
| 308 | 2.1, no fix | FAIL: 156 customers blocked | none | 0 lost, sqlmap held | 273 / 156 |
| 307 | 2.1, narrow fix (920272 `REQUEST_URI_RAW` and `ARGS:q`, 942460 `ARGS:q` under `/search/`; 920272 `REQUEST_HEADERS:Referer`) | FAIL: 1 blocked, a Korean CSRF page counted as the defence's (fixed) | target | 0 lost | 82 / 1 |
| 309 | 2.1, the same narrow fix | PASS | target | 0 lost, sqlmap held | 84 / 0 |
| 310 | 2.1, over-broad: 949110 removed | PASS: sqlmap held | rule | 0 lost | 89 / 0 |
| 311 | 2.1, over-broad: 949110 and 959100 removed | FAIL: 1 of 1 attacks took data | rule | 3/3 lost (admin, jiwoo, minseo), noticed | 57 / 0 |
| 312 | 1.1, items judged (one wrong twice, hint offered and opened) | FAIL under the first rule: 9 blocked | none | 0 lost | 16 / 9 |
| 313 | 1.1, the same, platform restarted mid-run | PASS: 12 of 12 items right | none | 0 lost, both sqlmap runs held | 20 / 8 (reported) |

The narrow fix's class is `target`, not `path_target`, because the Referer
exclusion has no path. Removing 949110 alone did not leak: 959100 still
refused the board's 500s, so sqlmap found nothing (as P0 measured for the
thresholds); the window passed and the result names the fix `rule`. Only with
959100 removed too did sqlmap dump the accounts, the window fail and the first
score count 3/3 lost.

Screenshots (headless Chromium, en and ko): the home page's scenario group,
the briefing, the live strip, the Judge pane, the debrief and the session page
of 311 and 313.

Not proven: the Docker substrate; the detection and unknown classes (no
scenario yet); the idle and failed-check hint triggers live (unit only; the
triage trigger ran live); the console driven by a person end to end (the runs
used the API; the screenshots show the pages on those sessions); the
UDP-dropped marker (above).

Metrics: core_loc 567 -> 580 (crs.py, above), dependencies 6, services 10,
product_loc 22,385 -> 23,979, tests 1955 -> 2017 (bin/measure).

## 2026-10-13 — P5 built: scenarios 1.2-4.1, and the fixes before them

Phase P5 of the scenario course design, built and run live on OpenStack
(platform VM 192.168.0.210, both slots, sessions 314-326 on 2026-10-13 and
329-332 on 2026-10-14). `docs/ARCHITECTURE.md`,
"Scenarios", has the descriptor fields and the table of the eleven scenarios.

**Fixes first.**

- **The strip counts alerted requests, not alert rows.** It read 17,352
  "alerts" a minute during sqlmap because each Detection row (one rule message)
  counted. `live.alerted_per_minute` counts distinct markers that drew an alert
  in the last minute: each customer request once, each attack case once however
  many requests it sent (one case is one decision, as in the triage list).
  Detections without a marker (the UDP drops below) are not counted.
- **The Judge pane keeps its list clear.** With the pane open the list leaves
  the lesson note's column free (padding computed from the note's box), and the
  cards, the opened hints and a coach popover whose step points into the pane
  are moved into a dock above the list; they float again when another pane
  opens. Checked headless at 1440x900 and 1280x800 (below).
- **UDP syslog drops.** `deploy/openstack/platform.yaml` writes
  `/etc/sysctl.d/90-fsl-syslog.conf` (`net.core.rmem_max = 33554432`,
  `net.core.rmem_default = 4194304`) and runs `sysctl --system` first;
  Filebeat's UDP input sets `read_buffer: 32MiB` (the socket then shows
  `rb67108864`). Applied by hand on 192.168.0.210 at 06:59 UTC (the same file,
  `sysctl --system`, the collector recreated). The collector's
  `/proc/net/snmp` (its network namespace) around one stock sqlmap run: before,
  6,013 datagrams received and 445 receive-buffer errors (6.9% of that burst;
  21,709 since 2026-10-12); after, 0 errors over a stock run (6,597
  datagrams) and a tamper run (8,102). Measured again on 2026-10-14: the
  collector had received 534,475 datagrams with 0 receive-buffer errors since
  it was recreated (every P5 run), and 558,984 with 0 after sessions 329 and
  330 ran sqlmap on both slots at once (24,509 datagrams in 10 minutes); the
  host's own namespace also shows 0. Not yet proven: the cloud-init path on a
  rebuilt VM.

**Rulings.**

- **"Kind" in 1.3 is the attack pattern.** The brief asks 1.3 to judge "both
  kind and whether it succeeded" over several attack kinds; read as the attack's
  CAPEC pattern from the case file (CAPEC-66, -63, -126), asked beside the
  verdict when the completion says `pattern: judged`, judged against the
  case's own `pattern`, never shown on an item. The Korean labels follow KISA's
  vulnerability-assessment guide (2026 edition) for SQL injection,
  cross-site scripting (XSS) and path traversal (`triage.pattern.CAPEC-66`,
  `-63` and `-126`; the guide says "path tracing", the secure-coding guide
  "path manipulation", AWS's Korean docs "path exploration").
- **The availability completion may name thresholds.** 2.3 completes when the
  thresholds in force at the window's snapshot are at most 5 inbound and 4
  outbound (missing thresholds are the CRS defaults) as well as on served and
  held.
- **`REQUEST_BODY` joins the tuning targets** (one alternation in `rules/crs.py`,
  `core_loc` stays 580). A Korean comment at PL3 is matched by 920272 in
  `REQUEST_BODY`; the WAF terminal already accepted the exclusion, the API did
  not. The test that pinned `REQUEST_BODY` as refused now pins
  `REQUEST_BODY:x`, `REQUEST_BODYX` and `REQUEST_BODY_LENGTH`. Measured live
  (session 324): with `920272;REQUEST_BODY` excluded under `/posts/`, the next
  match on a Korean comment is 920272 on `ARGS:body`.
- **A person as the red team (4.2).** Not built: it needs a second person. The
  engine accepts `red: person` with no schedule; its window judges the
  malicious cases the person fired inside it (not replays) like scheduled ones.
- **4.1's unseen attack is an evasion of the covered family.** Nothing outside
  SQL injection at `?sort=` succeeds against the board without a planted
  vulnerability: the search, union and sign-in injections are parameterised by
  the ORM (and the sign-in and comment JSON posts are refused by Django's CSRF
  check), the templates escape the XSS, and the traversal reaches no file
  (all measured held in 1.3, below). Against PL1 these sqlmap tamper sets were
  all held, about 15-17 s each, "not injectable" (session 314):
  `modsecurityversioned,space2comment`, `modsecurityzeroversioned,space2comment`,
  `space2mysqlblank,versionedmorekeywords,randomcase`,
  `space2morehash,versionedkeywords`; and with 942100 and 942190 removed at PL1
  both the stock and the tamper case were still held. The first became
  `board-sqli-orderby-sqlmap-versioned`, fired only by 4.1. The new false
  positive is the club's code questions in comments (942100, 942190, 941100,
  941110, 941160 on `ARGS:body` at PL1), a new customer action `comment-code`
  in the `club` profile. Corp has real CVEs that succeed, but no customer
  traffic; a corp scenario needs P3's generator for WordPress first.
- **The English comments without a final period** the brief lists among 2.2's
  false positives were not reproduced: at PL2 every English comment of session
  315 (49) and of the probe (`Thanks for sharing!`, `Count me in for Saturday`)
  passed the WAF (the probe's reached Django's CSRF 403), and `C++ & C#` sent as
  the search form encodes it was served. 2.2's false positives are the `<b>`
  search (941320) and the YouTube link (931130), both on `ARGS:q`.

**Fixed after a live run broke it.**

- Session 317: a scheduled sqlmap that took the accounts failed to record its
  case, "database is locked", while other writers ingested; SQLite's busy
  timeout is now 30 s (was the driver's 5 s).
- Session 319 (1.3, customers at 4/s): every listed item was judged right and
  the window still failed, 148 of 152: four customer requests reached the store
  after I'm done with alert times up to 74 s before it. A judgement window now
  keeps the items listed when it opened and judges those; verdicts given during
  it still count.
- Session 320 (3.1): the rules step compared sids only, so fixing a value of
  sid 9000101 left it failing. A rule now counts when its sid is new or its
  text differs from the posture's.
- Session 321 (3.2): the debrief said "alerted" for attacks only the WAF saw
  and listed WAF records. A detection scenario's debrief now reads the
  detector its completion names.
- Session 324 (2.3): lowering the thresholds, the task, was named a threshold
  fix with the warning for raising them. Only a threshold above the posture's
  is a threshold fix now.
- A deploy (platform restart) during the close's background slot reset left
  slot 2's sensor rules off baseline and the slot refused sessions until
  `POST /api/range/configure/?slot=2`. Not fixed: a reset interrupted by a
  restart is not resumed at boot; deploy only when `/api/range/ready/` shows no
  slot resetting.
- The Korean debriefs (screenshots, 2026-10-14): a scenario with two final
  checks printed "Blocked during a final check" twice with nothing to tell
  them apart (session 321); each line now names its check by number. The 4.1
  debrief showed the blocked action as `comment-code`: the club profile's new
  action had no string; a test now holds every declared customer action to a
  label in both languages.
- `wargames/board/traffic.yaml` held literal Hangul although its header said
  `\u` escapes; the strings are escaped now, the parsed values unchanged.
- A fresh review of the scenario docs against the code corrected the
  README's final check (it named the availability rule for every class), the
  traffic API's profiles and payload, what the session GET drops from a
  worked scenario, `guidance` (true, not the id) and the board table's
  origins.

**Live runs.** One session per scenario, normally two final checks: first
with a wrong defence, then with a right one. Driven over the API (a script in
the session's scratchpad); verdicts were taken from the range's record
(`scenario_run._truths`), WAF exceptions from the rules and matched variables
on the customers' records, signatures written by hand. "First score" is the
session's objectives lost, out of 3 (the board's accounts admin, jiwoo,
minseo); every loss was noticed. Length is open to close.

| Scenario | Wrong defence: session, check, verdict | First score | Right defence: session, check, verdict (fix named) | Length |
|---|---|---|---|---|
| 1.1 | 331 #1: every item judged customer; FAIL, 7 of 9 judged right | 0/3 | 332: every item judged right, the ones the window listed judged again during it; PASS, 13 of 13 (6 customers blocked, reported, not counted). 331 #2 failed 13 of 14: the script judged before the window opened and missed the item listed last | 10.9 min (331), 7.7 min (332) |
| 1.2 | 317 #1: FAIL, 14 of 15 judged right | 3/3: the inherited exception lets sqlmap take the accounts | 317 #2: PASS | 14.7 min |
| 1.3 | 325 #1: FAIL, 49 of 53 | 3/3 | 325 #2: PASS, the pattern judged too (after the window fix; 319 failed both, 74/86 and 148/152, which found it) | 27.7 min |
| 2.1 | 308: no fix, FAIL, 156 customers blocked; 311: 949110 and 959100 removed, FAIL, 1 of 1 attacks took data | 0/3; 3/3 | 309: PASS (target); 310: PASS with 949110 removed (rule) | 6.8-7.3 min |
| 2.2 | 316 #1: FAIL, 10 blocked | 0/3 | 316 #2: PASS (path_target) | 13.0 min |
| 2.3 | 324 #1 (and 318 #1): thresholds 10,000/10,000, FAIL, the attack took data and the thresholds are above 5/4 | 3/3 | 330: thresholds 5/4 and seven exceptions, PASS (target; 324 #2 passed and was named threshold before that fix). 318 #2: thresholds lowered with exceptions missing, FAIL, 231 blocked | 23.8 min (324), 6.7 min (330) |
| 3.1 | 329 #1 (and 320 #1): the broken rule, FAIL, sqlmap not detected | 0/3 (the WAF held it) | 329 #2: sid 9000101 changed to `http.uri`, PASS; the steps rules, buffer, fix and done passed live | 8.1 min |
| 3.2 | 321 #1: a rule that also matched customers, FAIL, 30 customer requests alerted | 0/3 | 321 #2: PASS | 11.0 min |
| 3.3 | 322 #1: FAIL, the tamper variant not detected | 0/3 | 322 #2: PASS | 11.6 min |
| 3.4 | 323 #1: FAIL, the comment XSS not detected | 0/3 | 323 #2: PASS | 8.1 min |
| 4.1 | 326 #1: FAIL, 22 customers blocked (the code questions) | 0/3 | 326 #2: five exceptions on `ARGS:body` under `/posts/`, PASS (target) | 18.0 min |

A detection or unknown scenario held every attack at the WAF throughout, so
its first score stayed 0/3; only judgement (1.2, 1.3) and availability (2.1,
2.3) runs lost the accounts, and only when the posture or the learner had let
sqlmap through.

Screenshots (headless Chromium, Korean, 1440x900): every scenario's
briefing (opened from the strip of its closed session) and one debrief per
task class (325, 316, 321, 326, taken after the two debrief fixes were
deployed), in the session's scratchpad `p5/`.

Not proven: a person driving the console end to end (the runs used the API);
the Docker substrate; 4.2; the cloud-init sysctl on a rebuilt VM; hints
offered when idle in a P5 scenario (none of these runs idled with customers
blocked).

Metrics (bin/measure, 2026-10-14): core_loc 580, dependencies 6, services 10
(unchanged), product_loc 23,979 -> 24,662, tests 2017 -> 2052. `bin/verify
--fast`: 2310 unit and console tests passed.

## 2026-10-14 — P6 built: the older course removed

Phase P6 of `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`,
approved by the user (option a): foundations F1-F6 and the scenarios replace
the older course, so it goes. `2026-10-13-blue-team-course-design.md` is marked
superseded.

**Removed.** Lessons 0-5 and 7 (`lessons:` and `default_lesson` in the board's
`scenario.yaml`: console-tour, read-the-block, waf-exclusion,
choose-the-level, ids-signature, ids-body-xss, assessment) and everything only
they used: `POST /api/sessions/<id>/verify/`, `GET .../lesson/debrief/`, the
Lesson / Practice / Wargame rungs (`Session.mode`, `PATCH` on a session, the
self-mode refusals), the start card, the ticket, the level control, the Check
tab and its replay (`POST /attacks/ {lesson: true}`), the check kinds `alert`,
`waf`, `served`, `replay`, `verify`, `level` and `detect`, `controls`,
`solved_at`, the `of: target` answer, `{waf_reload}` in step commands,
`FSL_LESSON_ALERT_WAIT/POLL`, `kibana.marked` and `kibana.sensed`, and 451
strings in each language. Production: 19 files, -2,127 lines, +121, and
migration 0026; `product_loc` 24,662 -> 22,720.

**Kept.** The server-side step engine (reached, skipped, check, do, hints,
withheld answers and lines, commands revealed once reached), the kinds the
foundations and worked scenarios use (click, answer, choice, rules, sent,
kali, loot, triage), WAF snapshots (each scenario final check and each close),
the scenario debrief, the fix class (`lesson.fix_class(waf, posture)`; with no
lesson `waf` step left its path scope was always empty, so it is dropped: an
added exclusion with no path is `target`, with one `path_target`, as scenarios
were already judged), the Topology pane, customer traffic, the scenario engine
and every scenario, and the plain wargame session (guidance off). The rule
editor moved into the blue console's rules pane, where the detection and
unknown scenarios already showed it.

**Rulings.**

- `{"guidance": true}` alone opens the first foundation (f1); it opened the
  default lesson.
- `Session.mode` had no reader left and is dropped (0026). The other lesson
  fields stay: foundations and worked scenarios read `guidance`, `lesson`,
  `lesson_steps`, `hints` and `waf_snapshots`.
- 0026 also clears `result_cache`: cached results carried the removed lesson
  verdict. The first session list after the deploy rescored: 31 s for 25
  closed sessions on the live store (5.7 GB), then 4 s from the cache.
- Old data stays readable. `REPLAY_MARKS` keeps `verify`, `check` and `replay`
  (no longer written) so old sessions' replays stay out of both scores; a
  session whose lesson id is gone shows `lesson: null`, as before.
- A `mode` in a request body is ignored like any unknown field; scenarios no
  longer refuse it (`scenario_run.ASKED_KEYS`).

**Tests.** `bin/measure` counts 2052 -> 1981: 71 deleted, each one's sole
subject removed (VERIFY and its diagnosis, the lesson debrief, the rungs and
mode, the start card and ticket, the level control, the replay section, the
removed kinds, the hand-written exclusion command, the seven lessons'
content). 121 were retargeted at a foundation unit or a worked scenario because
they also guard shared behaviour (the step engine, the coach and note, hints
and done-for-me, withheld answers, seeds and old replays out of both scores,
the close snapshot, catalogue validation, the old-session read), and 17 adapted
where an assertion or fixture named a removed field. The floor drops by 71,
approved by the user.

| File | Before | Deleted | Retargeted | Adapted | After |
|---|---|---|---|---|---|
| test_lesson_console.py | 86 | 17 | 61 | 0 | 69 |
| test_lesson_api.py | 52 | 14 | 14 | 4 | 38 |
| test_lesson_steps.py | 27 | 9 | 18 | 0 | 18 |
| test_lesson_path.py | 17 | 10 | 5 | 0 | 7 |
| test_lesson_exclusion_command.py | 7 | 7 | 0 | 0 | 0 (removed) |
| test_lesson_path_console.py | 6 | 4 | 2 | 0 | 2 |
| test_lesson_debrief.py | 3 | 3 | 0 | 0 | 0 (removed) |
| test/test_lesson.py | 5 | 3 | 1 | 1 | 2 |
| test_scenario_discovery.py | 23 | 2 | 11 | 1 | 21 |
| test_console_behaviour.py | 23 | 1 | 3 | 3 | 22 |
| test_strings.py | 17 | 1 | 1 | 0 | 16 |
| test_lesson_flavors.py | 4 | 0 | 3 | 1 | 4 |
| test_site_browser.py, test_foundations.py, test_scenario_engine.py, test_scenario_course.py, test_scenario_console.py | - | 0 | 2 | 7 | unchanged |

The old `alert` and `served` console tests became `sent` tests (the poll is
never a wrong answer; a request seen in the Website pane triggers the check).

**Live (OpenStack, platform VM 192.168.0.210, 2026-10-14).** The store was
backed up to `/opt/fsl/backups/db-20261014-pre-p6.sqlite3`, the branch synced
and the platform rebuilt with both slots idle; 0026 applied to the kept store.

- Home page (Korean, headless Chromium): six foundations, eleven scenarios, one
  "Start wargame" button (`main.start`) per wargame card, no lesson card, no page errors.
- Session 250 (closed `assessment` session in practice mode, 7 seed and 7
  verify cases): lists with kind `lesson`, `lesson_id` null, no `mode`,
  `result` without a lesson verdict; the detail reads `lesson: null`; `/score/`
  TP/FP/FN/TN 0/0/0/0 with no case scored, as before the deploy; the score page
  renders (0/3 lost). Sessions 296-304 list and read.
- F2 (session 335, slot 2): the Korean search 200; follow drew fsl-platform
  (10.31.0.238) -> mgmt -> fsl-waf (passed) -> estate -> fsl-wargame-host ->
  board-default -> board; source 10.31.0.238, port 80 and status 200 passed,
  10.0.0.1, 443 and 403 refused; all five steps passed; the seed case is
  marked `seed`. (Session 334 was the script's first try: follow asked without
  the request id, 400.)
- 2.1 (session 333, slot 1): the narrow fix (920272 on `REQUEST_URI_RAW` and
  `ARGS:q`, 942460 on `ARGS:q` under `/search/`, 920272 on
  `REQUEST_HEADERS:Referer`) at PL3 put by `PUT /waf/` 8 s after open; the
  scheduled sqlmap at 242 s held (not injectable, 1,973 403s, detected); the
  final check PASS, fix `target`, 0 customers blocked in the window, 1 of 1
  attacks held (a second sqlmap inside the window also held); first score 0/3
  lost; 4 of 2,313 customer requests blocked, all in the seconds before the
  fix.

Not done: `CLAUDE.md` still says the lesson step text "edits the exclusion
file and reloads nginx, with the path and reload `wargames.lesson` fills in";
F6's step only reads the file now and only `{waf_rules}` is filled in. The
file is the user's to change.

Metrics (bin/measure): core_loc 580, dependencies 6, services 10
(unchanged), product_loc 24,662 -> 22,720, tests 2052 -> 1981.

## 2026-10-14 — The acceptance red team run waits for a slot like every other open

The P6 gate-2 `bin/verify` on the OpenStack VM ended with 19 errors, every one
at the shared `full_run` fixture: `redteam/run.py` got 409 on
`POST /api/sessions/` three times. A replay with a readiness watcher showed
the cause is in the suite, not in P1-P6: two workers share two slots, a close
resets its slot for about 70 s, and when a slot turns READY both workers open.
The other worker opens with a direct POST polled every 2 s (900 attempts); the
red team run opens from a `docker exec` and a Django start-up, seconds later,
and had 3 attempts, so it loses ties (replay: lost to session 354 at 05:42:43,
took the next slot as 355; the failing run lost all three).

The red team run now has the same budget as every other open, and retries
only a refusal for want of room: `redteam/run.py` prints the platform's 409
body beside the status (`raise_for_status` dropped it), so the suite tells
"already open" or "resetting" from any other 409 and does not spin on a real
failure. The old 2026-10-12 line above ("retries the open once") is superseded.

## 2026-10-14 — The learner's GNS3 map: only the defended network, the range's own addresses, fitted

The user read the learner's map and asked for interfaces and addresses on every
link end, the domains learners type, real icons, a map that fits the window
with the node list closed, an honest word about the red marks, and then (scope
change) no management or control plane on it at all.

- **Two maps per substrate.** The old files are now the system map
  (`deploy/topology/system/`, English, new `uuid5(id, "system")` ids, full
  declaration, for development and MCP; the GNS3 entrypoint's
  `/topology/*.gns3` glob never loads it). The learner map keeps the old ids
  and is the system map without `mgmt`, every host's mgmt link, the scorer,
  the control-plane containers and a proxy host of its own, plus the log
  store (`fsl-elasticsearch`) drawn unlinked, its note naming the WAF and the
  sensors that send it records. The test checks that projection against the
  declaration and compose. Not chosen: drawing record flows as dashed lines
  (no cable carries them; a note says it plainly).
- **The follow view walks the learner map.** A Website pane request starts at
  a `console` hop (the learner's browser, with the address the WAF records)
  and arrives straight at the WAF; a proxy-stamped marker is drawn from the
  attacker; the session overlay lists only the map's hosts and segments. F1's
  log store answer is `fsl-elasticsearch` on both substrates (was
  `fsl-platform` on OpenStack); F1's theory no longer describes `mgmt`.
- **A map per slot or session, from the range.** `interfaces()` on each
  adapter (OpenStack: `ip -o -4 addr`/`ifconfig` on each slot host over its
  own runner, `nsenter` into the wargame containers; Docker: MAC to
  `/sys/class/net`), `topology.labelled` to label each host's link end, and
  `api/maps.py` to load both languages at session open, after a slot's reset
  and on demand from `GET /api/topology/?session=`. Reading Kali's interfaces
  goes through the adapter's attacker runner, not `attacker.py`; it reads
  only `ip addr`. The platform signs in to GNS3 as admin to import (the
  password file is 0640 to the Docker socket's group; members are root on the
  host already).
- **Symbols.** The gns3-registry has no Kali, OPNsense, MySQL, WordPress,
  nginx, Django, Suricata or Elasticsearch symbol (its `symbols/` and the
  `kali-linux`, `opnsense`, `turnkey-wordpress`, `ubuntu-cloud` appliances
  name none); vendor logos from elsewhere were not taken (trademarks, no
  licence in the registry). Used: GNS3's bundled affinity set (ecceman/affinity,
  The Unlicense; referenced, not copied) for role and VM-versus-container, and
  the registry's `ubuntu.svg` for the Ubuntu wargame host (Canonical,
  CC BY-SA 3.0, Canonical's trade mark policy; fetched by the GNS3 image from
  gns3-registry commit fddde65, its `ubuntu.txt` kept beside it, uploaded by
  `provision.py`; not vendored in this repo).
- **Fit and the node list, within 3.1.0a6.** The web UI never reads the
  project's `zoom`, fixes its origin once at the first draw
  (`max(width/2, -min x + 30)`), and keeps the topology summary's visibility
  as a constant. So `fsl-auditor.html` opens the project in a same-origin
  frame, clicks the summary toggle, clicks zoom-out (0.1 a step) until the
  drawing fits, and pans once in moving mode with a synthetic mousemove
  (`movementX`/`movementY`; d3 never sees it, the moving directive does).
  Measured: 1400x860 and the 1600x1000 console both open at 0.8, the drawing
  inside the frame, summary closed.
- **The legend** (both languages): the map shows how the range is wired, the
  machines run in the range and not in GNS3, and the red link marks mean
  stopped in GNS3.

Live (platform VM, both slots READY): slot 1 and 2 maps loaded in both
languages in 5-20 s each (first load slower while GNS3 creates the docker
nodes); labels read from the range (slot 1 WAF `ens3 10.30.0.102/24`, slot 2
`ens3 10.30.0.177/24`, Kali `ens3 5.188.10.10/24 (+99)`, edge `vtnet0
5.188.10.1/24 (+29)`, wargame host bridges and each container's `eth0`).
Session 382 (board, slot 1): `GET /api/topology/?language=ko&session=382`
served `fsl-range-openstack slot 1` and the console's Topology pane framed it;
closed. Cost: GNS3 now holds eight projects open (four learner maps, four
slot maps); 58 GNS3 containers in state Created on the host (was 38), fsl-gns3
285 MiB RSS idle, `/var/lib/fsl-gns3` 23 MB.

Not done: the Docker substrate's per-session maps are unit-tested only (no
Docker range runs live); on the wargame host's two diagonal links the bridge
labels start under the host's icon; a platform restart forgets which maps it
loaded, so a map is refreshed at the next open or reset, not at restart.

Metrics (bin/verify --fast): core_loc 580, dependencies 6, services 10 (unchanged),
product_loc 22,725 -> 24,295, tests 1983 -> 2013.

## 2026-10-14 — The learner's GNS3 map without the legend, the filler or a floating node

The user judged the learner maps messy: a legend, filler lines, diagonal
labels running into links, two unlinked nodes, `(+99)` suffixes and Docker
bridge names. Both substrates and both languages change; the system maps do
not.

- **No legend, no filler.** The three legend lines, the Internet zone's
  "come from here", "(one slot)", "docker compose projects board, corp", the
  edge's vtnet line and Docker's origin count are gone. The title is
  `fsl range (<substrate>): the network you defend`; each node keeps one
  plain line (the domains stay on the WAF and the sites). The dashed box keeps
  a caption, `containers inside fsl-wargame-host`, because it is the only
  thing saying the containers run on that host.
- **The log store is linked the way records travel.** A `monitoring` switch in
  a titled Monitoring zone joins `fsl-elasticsearch` to the hosts that ship it
  records. On OpenStack each of the WAF, the edge and the wargame host
  forwards its own syslog to the collector (`range/openstack.py`
  `configure_waf`, `configure_edge`, the wargame host's `logs`), so the three
  are linked on the adapter of their management NIC, the one the records leave
  by. On Docker the WAF has no NIC on that network; `fsl-filebeat`, the
  session's shipper, reads the WAF's and Suricata's log volumes and is on the
  management network, so it is the one linked, its note saying what it reads.
  The test derives the members: on OpenStack the gateway, every `watches`
  sensor's host and every host with `logs`; on Docker every session service on
  `mgmt` sharing a volume with the gateway's or a sensor's service. The
  collector (`fsl-collector`) is not drawn: the log store stands for the
  platform's receiving end, as before. Monitoring links carry no address,
  because the NIC is on the management network, which the learner map does
  not show.
- **Suricata with no NIC is folded into its host.** GNS3 has no host-network
  container, and a NIC drawn for it would be false. Options were a floating
  node (rejected: the complaint), a fake link (rejected: false), or naming it
  in the note of the host whose NIC it uses. Chosen: the note. OpenStack's
  wargame host reads "Docker host; Suricata watches its estate NIC", Docker's
  WAF "web firewall (ModSecurity + CRS) and Suricata: ...". The edge already
  said "Suricata on WAN". The follow view never placed alerts on the Suricata
  node (it attaches them to the watching host), so nothing else moves.
- **Level labels.** GNS3 3.1 draws a `link_style.link_type: flowchart` link
  as right angles (a Z through the midpoint), and the controller keeps it on
  import; 2.2.61 still loads the file. A link between two nodes that are not
  level or upright is a flowchart link, so the estate switch, the monitoring
  switch and the wargame host's bridges read as buses and every label sits on
  a level or upright segment. Three hosts on both estate and monitoring
  cannot all be joined by straight level or upright lines (K2,3), hence the
  right angles. `topology.labelled` sets each label at rotation 0 beside its
  node on the side its link leaves: above a level line, clear of the 10 px
  status mark GNS3 puts 60 px from the node's centre, right of an upright one,
  and right-aligned with `text-anchor: end` on a node's left (the web UI keeps
  the style). A label's x, y are its text box's top-left (the web UI adds 3
  and 14 to reach the baseline). Only the default origin's address is shown;
  the host side of a Docker bridge (`br-...`) is left blank and the
  container's `eth0` address stays.
- **Checked by rendering, not by eye alone.** A local gns3-server 3.1.0a6
  (its own web UI, `fsl-auditor.html`) loaded each map with a fixture range,
  and a script in the page compared every interface label, node name and note
  with every icon, status mark, link path, zone border and the frame. Every
  overlap it found was fixed until it reported none; the live maps then
  reported none too.

Live (platform VM, OpenStack, both slots READY): deployed after the gate-4
`bin/verify` run ended `EXIT=0`; slot 1 and 2 maps reloaded in both languages
(slot 1 WAF `ens3 10.30.0.102/24`, wargame host `ens3 10.30.0.63/24`; slot 2
WAF `ens3 10.30.0.177/24`, wargame host `ens3 10.30.0.184/24`; Kali
`ens3 5.188.10.10/24`, edge `vtnet0 5.188.10.1/24`, containers' `eth0`), and
session 399's Topology pane framed slot 1's map in both languages; closed. The
in-page check reported no overlap, cut-off or floating node on any of the six
views.

Not done: the Docker learner map is rendered locally only (no Docker range
runs live); `fsl-collector` stays off the map.

## 2026-10-14 — The learner map drawn as lab topologies are: hostnames, short link labels, zone captions, an addressing table

The user rejected the learner map: prose notes beside nodes ("Docker host;
Suricata watches its estate NIC") and three monitoring links merged into one
right-angled bus. Both substrates and both languages change; the system maps
do not.

References, read before drawing:

- Cisco Networking Academy, *Lab – Troubleshooting Basic Single-Area OSPFv2
  and OSPFv3*, Topology and Addressing Table: each device carries its hostname
  (R1, PC-A), each link end its short interface name (G0/0, S0/0/1), nothing
  else on the drawing; the addresses are in a separate Addressing Table
  (Device, Interface, IP Address, Default Gateway, `N/A` for a router).
- NSRC workshop logical network diagram: short hostnames, addresses at link
  ends (a host's last octets, `0.241`), each segment labelled with its CIDR and
  name (`10.10.0.0/24 Classroom backbone`), groups as boxes with a short
  caption.

What the maps are now:

- **A node is its hostname.** Every note, the title and the legend are gone;
  a drawing is a zone box or its caption. The sites are named `board.com` and
  `corp.com`, the names learners type: RFC 1123 allows dots, and gns3-server
  2.2.61 and 3.1.0a6 keep the name on load (`bin/check-topology`, and the live
  server shows it). The range still calls them `board`/`corp-wp` (OpenStack)
  and `fsl-wg-board`/`fsl-wg-corp-wp` (Docker); `topology.shown_as` maps those
  to the domain from the declaration (the WAF host's `names`), and
  `overlay`, `follow`, `facts`, `api/maps.py` and the interface read use it,
  so the follow view and the overlay name the node the map draws.
- **A link end is `<interface> .<last octet>`** (`ens3 .102`, `vtnet0 .1`,
  `eth0 .3`); the zone caption carries the rest. A label sits above its line,
  or below it when the link climbs, so a diagonal link never runs through it.
- **A zone caption is the segment's name and the network the range holds
  for it** (`Application estate 10.30.0.0/24`, its Korean caption with the word for "service zone",
  `board_default 172.18.0.0/16`), added when the slot's or session's map is
  generated, from the interfaces read (the default origin's network on the
  internet side). The committed learner map holds the name alone, since the
  network is the range's. The box round the containers names their host
  (`fsl-wargame-host`), a container network's box the Docker network's name.
  Monitoring keeps its name alone: it rides on the management network, which
  the learner map does not show, and its links carry no address.
- **Every link is one straight line, and no two share a stretch or cross.**
  The old bus was GNS3 `flowchart` links, which overlap where they turn.
  Joining three hosts to both `estate` and `monitoring` (K2,3) with level and
  upright lines alone is impossible without overlap, so the WAF drops straight
  to `monitoring` and the edge and the wargame host reach it on a diagonal
  each; the wargame host fans to its two bridges on diagonals. The test
  computes every link from the node centres: no crossing, no collinear
  overlap at a shared node, no line within a symbol's width of another node.
- **The addresses are in an Addressing table** beside the GNS3 map in the
  Topology pane (`GET /api/sessions/<id>/topology/addresses/`): Device,
  Interface, IP address / prefix, Default gateway (Cisco's columns, `N/A`
  where the interface holds no default route), and Services (`board.com` and
  `corp.com` on the WAF, port 80; each site's database, 3306). It comes from
  the same range read as the map, kept per slot or session. The default
  gateway is read, not assumed: the interface read now also prints
  `/proc/net/route` (`netstat -rn` on OPNsense), and the gateway goes to the
  interface the default route leaves by. The ports are constants pinned by a
  test to `deploy/waf/range.conf`, the session WAF's `PORT` and the MySQL
  images.

Tests rewritten because the design changed (none weakened beyond that):
`test_gns3_topology.py` — the Korean-words test lets a caption naming a host
or network stay as the machine knows it; the RFC 1123 test accepts dotted
names; the learner-map projection, the symbol test and the log store test map
range names through `shown_as`; the sensor test is now
`..._is_folded_into_the_node_whose_nic_it_uses` (no note names it); the
right-angle test is now `test_every_learner_link_is_one_straight_line_...`;
the domain test checks the node names and the services; the legend test is now
`..._no_title_no_legend_and_no_note_only_a_caption_for_each_zone`. In
`test_gns3_maps.py` the label texts are `<interface> .<octet>`, a slot map
keeps the template's boxes (its captions gain a network), and a label on a
climbing link sits below it. Follow and console tests name `board.com`. New:
the no-crossing test, caption networks, route parsing, the addressing table,
its endpoint and console view, and the port pins.

Live (platform VM, OpenStack, both slots READY): deployed, slot 1 and 2 maps
reloaded in both languages; the in-page check found no overlap on any of the
four views. Slot 1: `fsl-waf ens3 .102`, wargame host `ens3 .63`; slot 2:
`.177`, `.184`; captions `Internet 5.188.10.0/24`, `Application estate
10.30.0.0/24`, `board_default 172.18.0.0/16`, `corp_default 172.19.0.0/16`.
Session 416's Topology pane showed slot 1's map and its Addressing table in
both languages; closed.

Seen live, left as the range has it: Kali's default route leaves `ens3` by
the edge's address on another origin's subnet (`1.128.0.1` on slot 1,
`73.0.0.1` on slot 2), so the table shows `5.188.10.10/24` with that gateway;
the edge holds no default route (`N/A`). Not done: the Docker learner map is
rendered locally only (no Docker range runs live).

## 2026-10-15 — The learner map is the company network the learner defends, named by role, one map per wargame

The user's verdict on the lab-style map: it still showed the training
platform (the `fsl-wargame-host` box, the `board_default`/`corp_default`
Docker bridges, every `fsl-` name), not the system the learner learns; the
link ends were all red; board and corp appeared together though a session
defends one wargame. Rebuilt as a logical diagram of the company web-service
network (Cisco NetAcad lab topology, NSRC logical diagram):

- **Nodes by role.** `customers` and `attacker` on `internet`; `firewall`
  (the OPNsense edge; its Suricata is folded in); `service-sw` with `waf` and
  the site (`board.com` or `corp.com`); on OpenStack `board-db-sw` behind the
  site with `board-db`, on Docker the database on `service-sw` (the Docker
  range has no edge and puts sites and databases on the estate); and
  `monitoring-sw` with `log-server`. The infrastructure rename is deferred by
  the user (STATE backlog); the real hosts keep their names and
  `topology.learner` maps them to the map's (hosts, roles, segments to
  switches, sensors to the node whose NIC they use). The overlay, the follow
  view, the f1 range questions (now `firewall`/`waf`, `log-server`,
  `board-db-sw`/`service-sw`) and the interface read go through it.
- **Labels are the real range's.** Attacker: its default-origin address
  (`ens3 .10` of 5.188.10.0/24). Customers: the first address of the box the
  customers run on in their busiest origin by `traffic.yaml` weight, the
  default origin left out as `attacker.customer_origins` does (`ens3 .10` of
  175.192.0.0/24 on both slots); unlabelled where the box holds none (Docker,
  whose customers' box starts with the customers). The site on `service-sw`
  carries the sites' host address (`ens3 .63` slot 1, `.184` slot 2: the WAF
  reaches `board.com` and `corp.com` there), on the database switch the site
  container's (`eth0 .3`). Zone captions carry the networks of the labels on
  their switch (`Internet 175.192.0.0/24, 5.188.10.0/24`, the Korean map with the Korean word for "Internet").
- **Log links are where records really go.** OpenStack: firewall, waf and the
  site, because the estate sensor runs on the sites' host and ships its
  eve.json (`logs:` in the declaration); the board app (gunicorn on :8000)
  ships nothing of its own, and the nginx in the logs is the WAF. Docker: the
  WAF alone (the session shipper reads the WAF's audit log and the Suricata
  volume, Suricata running in the WAF's namespace).
- **One map per wargame.** A template per substrate draws both wargames'
  site, database and database switch in one place; `topology.for_wargame`
  keeps the session's. Maps are keyed `slot <n> <wargame>` / `session <id>
  <wargame>`; a slot keeps its newest session's map. `corp` declares no
  customers, so its map has none. The templates are no longer copied into
  the GNS3 server (they draw every wargame); the old `fsl-range-*` projects
  and their 22 never-started `GNS3.*` containers were deleted from the
  platform VM by hand.
- **Every link end green.** GNS3 colours an end by its node's status. Each
  host is a `docker` node of `busybox@sha256:73aaf090…` (1.36.1, 2.2 MB) that
  only runs `sleep`, no console; the switches were already started.
  `gns3.publish` starts a map's nodes after opening it, turns `auto_close`
  off first (an import is made with it on whatever the file says, and a map
  closed when the learner's frame went away and stopped its nodes), and
  `provision.py` starts the display nodes (that image only) of every project it
  opens. The display nodes are display only: the real machines run in the
  range. What starting needed, measured on the VM: `busybox-static` in the
  GNS3 image (GNS3 refuses to start a docker node without it) and `pid:
  host` (uBridge moves the node's interface into the namespace of the
  container's host pid; without it the start failed).
- **Cost, measured on the platform VM** with slot 1 board and slot 2 corp in
  both languages: 26 display containers; their processes and runc shims 115
  MB PSS, their uBridge processes 12 MB PSS (43 uBridge processes in all,
  19 MB); `fsl-gns3` 293 MiB. About 5 MB a node, 63 MB a board map pair.
- **Removed: the addressing table** (its tab, en/ko strings, `GET
  /api/sessions/<id>/topology/addresses/`, `topology.addressing`, the
  default-route read in `range/interfaces.py`). The Topology pane's tab reads
  Network map in English and the Korean equivalent in Korean (the pane's key is
  `blue.pane.topology`; it reads Map since 9674d0e); no word a learner reads names GNS3 (the f1
  lesson text now names the hosts by role).
- **A customer request can be followed** (`?customer=<marker>`), starting at
  `customers`; the console's picker does not list them yet (STATE backlog).

Tests: 2027 before, 2033 after. Removed with the addressing table (6):
`test_the_addressing_table_lists_each_device_s_interfaces_on_the_learner_s_segments_and_the_services`,
`test_the_service_ports_are_the_ones_the_waf_and_the_databases_listen_on`,
`test_a_slot_s_addressing_table_is_read_once_and_kept_with_its_map`,
`test_the_addresses_endpoint_serves_the_session_s_table_and_says_why_when_the_range_cannot`,
`test_the_default_route_is_read_from_proc_or_netstat_and_held_by_the_interface_it_leaves_by`
(`test_gns3_maps.py`) and
`test_the_addressing_table_lists_each_device_s_interfaces_and_the_services_beside_the_map`
(`test_topology_console.py`). Added (12): a wargame's map shows only its own
site; no two nodes stand on each other; display nodes are one pinned idle
image; a node reached from straight above carries its name beside it;
customers unlabelled without an address on their origins; a session's map is
drawn for its wargame; a slot keeps its newest session's map; provisioning
starts only display nodes; a customer request's path (topology and API); a
corp case ends at `corp.com`; the Network map tab and no GNS3/`fsl-` in the
pane's strings. Rewritten because the design changed: in
`test_gns3_topology.py` the learner projection (now against the declaration
through `topology.learner`, per wargame), the switches test, the zone-title
test, the no-platform-word test (now also no `fsl-`, wargame host, `_default`),
the log test (log sources instead of management adapters, since the display
nodes' adapters mean nothing), the sensor-folding test, the geometry and
caption tests (run on every wargame's projection), the domain test (no
services table) and the symbol test (square or circle by the real machine,
since every node is now a container); in `test_gns3_maps.py` node and switch
names, the slot key with its wargame, the publish call list (adds `auto_close`
off and the node start), a climbing link's label beside the node; in
`test_gns3_follow.py` hop names (`waf`, `service-sw`, `firewall`,
`board.com`; the estate sensor's hop is the site) and a sensor-records test
whose request has no status, so the site hop's evidence comes from records
alone; in `test_gns3_service.py` `pid: host`, no template copied in and no
image tag rewritten; `test_foundations.py`'s expected answers.

Live (platform VM, OpenStack): sessions 436 (board, slot 1) and 437 (corp,
slot 2); both maps in both languages loaded, every node `started`, every link
end green; the console pane showed slot 1's map under Network map in
English and Korean; both closed. Session 434 and 435 failed to open on the first
deploy (`_maps_live` used the suppression query's `session__slot`); fixed and
tested before the run above.

## 2026-10-15 — The learner map's switches are sw1, sw2, sw3 and every link is labelled at both ends

The user's two objections to the role-named map: nobody names a switch
`service-sw` or `board-db-sw`, and some link ends had no interface label. The
lab topologies the map follows label every link end with an interface (Cisco
NetAcad lab topology) and number switches (`sw1` in the NSRC workshop logical
diagram).

- **Switch names.** `sw1` is the service segment, `sw2` the database segment,
  `sw3` monitoring, in that fixed order; `internet` stays the cloud. The zone
  captions already name each segment. The template's two database switches
  (`board-db-sw`, `corp-db-sw`, drawn in one place) became one `sw2` that both
  wargames' site and database hang off, as `sw1` already carries both sites
  (board on `e0`/`e1`, corp on `e2`/`e3`). Docker has no database segment, so
  its map has `sw1` and `sw3` and no `sw2`; numbering by role rather than by
  count keeps a name meaning one segment on both substrates and in the f1
  answer (`sw2` on OpenStack, `sw1` on Docker).
- **Both ends labelled.** A switch end carries the port the link uses in
  short form (`Ethernet2` is `e2`), read from the node's `ports_mapping`. A
  host end on `sw3` carries the NIC name alone (`vtnet2`, `ens4`), because its
  address is on the management network the learner does not see. The
  `log-server` end is the log store's own NIC on that network where it has
  one (Docker, `fsl-elasticsearch`'s), otherwise the platform VM's: the
  platform takes no SSH, so OpenStack reads its NICs with the same `ip -o -4
  addr` in the pinned `busybox` (already on the host for the display nodes) on
  the host network (`interfaces.on_this_host`), only when the map asks for
  the scorer host. The dual-homed site keeps `ens3 .63` on `sw1` and
  `eth0 .3` on `sw2`, one at each of its own link ends. The one end that can
  stay blank is Docker's `customers`: its box runs only while the customers
  do (unchanged).
- **Placement.** Three steep links climb into `sw3` side by side, so the old
  rule (right of the node, near its top) put three labels on one spot. A
  steep link's label now sits beside the line on the side the node's other
  links leave more room, above the node and past GNS3's status mark where the
  node's name is beside it (it stays right of the node where its name is
  above); a shallow link's label sits above or below the line by the same
  rule, clear of where the line runs under the text. GNS3's web UI places a
  link label's `y` as the text's top (`y += bbox.height` in its label
  converter), which the clearances assume.

Tests: 2033 before, 2037 after (`bin/measure`). Added (4): a switch end names its
port and a monitoring end only the NIC; the log server's NIC is the log
store's before the platform's; every link of every learner map (both
substrates, both wargames, both languages on OpenStack) is labelled at both
ends and every switch is `sw\d+` or `internet`; no two labels overlap and
none covers a node. Rewritten because the design changed: in
`test_gns3_maps.py` the assertions that switch ends and `monitoring-sw` ends
are blank (now port and NIC), the label-side test (side by room, and a
climbing link above a node named beside it), the label-format test (ports
and bare NICs besides `nic .octet`); switch names in `test_gns3_maps.py`,
`test_gns3_follow.py`, `test_foundations.py`, `test_topology_console.py` and
`test_gns3_topology.py` (`DATABASE_SWITCH` for the removed `SWITCH_SUFFIX`).

Live (platform VM, OpenStack): sessions 456 (board, slot 1) and 457 (corp,
slot 2), both languages: 12 and 11 links, every end labelled (`log-server`
`ens7` read from the platform VM), every end green, no label on another or
on a node; first try put `sw3`'s three climbing labels just above the switch,
between the converging lines and under GNS3's status marks, so they now sit
above the marks (`LABEL_ABOVE`). Sessions 454/455 were closed and the platform
restarted seconds later, which killed both slots' reset threads (slots stuck
CHECKING, ground truth unreadable); `reset_in_place` and `configure_rebuilt`
were run by hand on both slots and both returned READY. Restarting the
platform right after a close loses that slot's reset; a restart should wait
for `/api/range/ready/` to show no slot resetting.

## 2026-10-15 — Learner-map link labels carry the full address; the attacker node is `kali` with OffSec's dragon

The user asked for the whole address with its prefix at every host's link
end, and for the attacker node to be named and drawn as the Kali box it is.

- **Labels.** A host end reads `<interface> <address>/<prefix>` (`ens3
  10.30.0.102/24`, `vtnet0 5.188.10.1/24`, `eth0 172.18.0.3/16`); a switch
  end stays its short port (`e0`), a monitoring end the NIC alone. The
  lab-style `.<octet>` of 2026-10-14 is gone; the zone captions still carry
  the networks.
- **Room for them.** The columns right of the internet zone moved apart
  (firewall or Docker's WAF at x 0, `sw1` and `waf` 270, the site 540, `sw2`
  800, the database 1060) and the zones widened to match, the same in all
  four templates, so a 20-character label fits between its node and a zone's
  edge. The drawing is about 10% wider (1730 against 1580 units).
- **Clearances measured, not assumed.** In the 3.1.0a6 web UI (`getBBox` on
  the live map) a link label renders at its `x` + 3 with glyphs from `y` + 4
  to `y` + 23 (Noto Sans at 13.3 px, the style's 10.0 read as points, 6.4-6.6
  units a character, estimated at 7); a node's name at `x` + 3 from `y` + 1
  to `y` + 22 (14.7 px bold, up to 8.5 a character, estimated at 9). The status
  mark is a circle of radius 6, 60 along the link from the node's centre
  (`LABEL_DISTANCE = 60`, `r = 6` in the web UI's link widget). A shallow
  label rises 32 above its line or falls 6 below it, and its reach includes
  the mark; a steep label stands 10 aside of the line over a band widened by
  the mark's radius; a shallow label that would touch its own node's name
  goes to the other side of its line (`internet`'s `e0`). A new test holds
  every label of every generated map (both substrates, both wargames, both
  languages on OpenStack) clear of every link line, every status mark, every
  node's name, every zone edge and caption, by 3 units.
- **A relayout bug, caught live.** The first relayout rewrote every
  `width="…"` in a zone's svg, `stroke-width` included, so each zone drew as
  a solid block; no test looked at the stroke. Fixed, and a test now holds
  every learner zone to a 2-unit outline over a 0.06 fill with the box's own
  size.
- **`kali`.** The node `attacker` is now `kali` (`topology.ATTACKER`); the
  role stays `attacker`, so the follow view, the overlay and the lesson's
  range questions only see the new name (the f1 map text says `kali (the
  attacker's Kali Linux box)`, and that each link end names the interface
  and its address with the network prefix).
- **The Kali dragon, under OffSec's policy.** The Kali Linux Trademark
  Policy (https://www.kali.org/docs/policy/trademark/, updated 2025-06-10)
  covers the dragon (listed among the marks, `kali-dragon-tm.png`) and says:
  "We encourage others to use the marks so long as they are used to identify
  the products and services of OffSec." It also says: "Please do not modify
  the marks." and "When using an OffSec trademark in written materials, you
  should provide a statement indicating that the [trademark] is a trademark
  of OffSec." Its limits: "You can't put the trademarks on anything that you
  produce commercially (whether or not you make a profit) – at least not
  without receiving written permission." and "Any other use outside of the
  scope of the Trademark Policy is not permitted without express written
  permission of OffSec." The map's node is a Kali Linux box and the map is
  an internal, non-commercial training range, so the dragon identifies
  OffSec's product, as the policy encourages. Used: the press pack the
  policy links (gitlab.com/kalilinux/documentation/press-pack, commit
  360c018b, `Kali/Logomark/kali-dragon-black.svg`, sha256 `083264e7…`),
  fetched by the GNS3 image at build, checked by digest, given only `width`
  and `height` 60 (it has a viewBox and no size, and GNS3 sizes a node by
  its symbol: 135x135 otherwise), saved as `kali.svg` with a `kali.txt`
  stating the mark, the source and the change, uploaded by `provision.py`
  like the Ubuntu symbol; not vendored. The Topology pane's footer says
  "KALI LINUX™ is a trademark of OffSec." (en/ko). Not covered: if this
  training is ever sold, the policy's commercial clause needs OffSec's
  written permission; the dragon also drops the square/circle VM-or-container
  cue for that one node.

Tests: 2037 before, 2041 after. Added (4): no label on a line, a mark, a
name, a zone's edge or caption (6 maps); the Kali symbol's pinned fetch and
the `kali` node; the trademark line in the Topology pane (en, ko); zones as
2-unit outlines (4 templates). Rewritten because the design changed: the
label texts and the label pattern in `test_gns3_maps.py` (full address with
prefix), `label_box` (now `topology.label_box`, with the measured offsets),
`attacker` to `kali` in node and hop names (`test_gns3_maps.py`,
`test_gns3_follow.py`, `test_topology_console.py`), the symbol tests in
`test_gns3_topology.py` (the fetched list includes the Kali stage's files;
`kali` is exempt from square/circle and must be `kali.svg`).

Live (platform VM, OpenStack): deployed (`platform`, `gns3` rebuilt;
`fsl-gns3: symbol kali.svg uploaded`, the file `<svg width="60" height="60"
viewBox=...`), sessions 460 (board, slot 1) and 461 (corp, slot 2), both
languages. Slot 1: `kali` `ens3 5.188.10.10/24`, `customers` `ens3
175.192.0.10/24`, `firewall` `vtnet0 5.188.10.1/24`/`vtnet1 10.30.0.1/24`,
`waf` `ens3 10.30.0.102/24`, `board.com` `ens3 10.30.0.63/24` and `eth0
172.18.0.3/16`, `board-db` `eth0 172.18.0.2/16`; slot 2 the same with `.177`,
`.184` and 172.19.0.0/16. An in-page check over the rendered SVG (label
`getBoundingClientRect` against every node image, name, caption, status mark,
zone edge and link path) found nothing touching on any of the four views;
the nearest label to a mark is 2.6 px clear at the fitted zoom. Sessions 458
and 459 before them showed the solid zones above; the platform was restarted
for the fix while they were open (no reset running), then both were closed
and both slots returned to READY before 460 and 461 opened.

`bin/verify` on the platform VM (`FSL_PLATFORM_URL=http://192.168.0.210:8000`;
the port is published on 10.20.0.7, where Django answers 400 to that host
name, and not on localhost): all green, acceptance 74 passed, 0 failed, 71
skipped in 1002 s; ratchet holds (core_loc 580, tests 2041). The run before
it had one failure, `test_a_live_content_overwrite_is_credited_from_the_targets_own_row`
(the post was overwritten but session 466 credited nothing), in the effect
path this change does not touch; it passed on the rerun and is left as a
possible flake to watch.

## 2026-10-15 — Every learner-map host is one framed symbol; the WAF stays one-arm

The user approved two things: one frame for every host on the learner map,
and the WAF drawn where the range wires it.

- **One frame, one size, one line weight.** The square-for-a-VM,
  circle-for-a-container cue of 2026-10-14 told the learner nothing they act
  on, and the dragon had already broken it. Microsoft's Well-Architected
  guide (https://learn.microsoft.com/en-us/azure/well-architected/architect-role/design-diagrams,
  "Maintain consistency"): "Use standardized colors, casing, icons, icon
  sizes, line weights, line types, arrow heads, and border styles for
  similar elements." AWS's Architecture Icons guidelines
  (https://aws.amazon.com/architecture/icons/, the guidelines in the icon
  package, quoted by the user; the page itself does not carry the line):
  "Use icons at their predefined size, color and format in diagrams."
  GNS3's own affinity squares do not meet it: the green ones draw a
  16-unit ring, the blue and gray ones a traced outline of another weight.
- **What is built.** `deploy/gns3/symbols.py` runs when the GNS3 image is
  built and writes `host-client`, `host-router`, `host-shield`,
  `host-server`, `host-storage`, `host-statistics` and `host-kali` (`.svg`,
  60x60, viewBox 300): one `rect` (x/y 8, 284 square, `rx` 22, stroke 16,
  paper `#fffefe`) whose stroke alone differs, red `#e3292e` for the
  attacker, green `#109e00` for the WAF, blue `#2d67b9` for the router and
  for the sites and their databases, gray `#4d4d4d` for customers and the
  log server (affinity's own colours). The router took the firewall glyph
  while the edge was OPNsense; since the edge became an nftables router
  (2026-11-13) it wears affinity's router glyph (four arrows), in blue so
  it reads neither as a gray switch nor as one of the green WAF family. Inside it, the glyph of the bundled
  affinity square symbol of that colour (`affinity/square/<colour>/<glyph>.svg`
  in the installed gns3-server, The Unlicense), with the symbol's paper and
  frame paths dropped and its root style kept; the build fails if a bundled
  symbol stops being paper, frame, glyph. `provision.py` uploads them as
  before; the four learner templates name them. Switches and the internet
  keep the bundled `square/gray/switch.svg` and `globe.svg`. The system
  maps are not touched.
- **The dragon, framed and not modified.** OffSec's policy says "Please do
  not modify the marks." (https://www.kali.org/docs/policy/trademark/). The
  press-pack file (commit 360c018b, sha256 `083264e7…`) is still fetched at
  build and checked by digest, then placed whole as a nested `<svg>` with
  only `x`, `y`, `width` and `height` 24, 24, 252, 252 inside the red frame:
  its paths and viewBox are byte-for-byte the press pack's, and the frame is
  a separate shape around it. `host-kali.txt` states "KALI LINUX™ is a
  trademark of OffSec.", the source, the commit and the placement. Not
  vendored.
- **The WAF stays one-arm.** The range wires the WAF on the service segment
  beside the site (one NIC on `sw1` and one on monitoring): the sites'
  names are the WAF's (`declaration.yaml`, `fsl-waf` `names`), and it
  proxies to the site on the same segment, which stays reachable on that
  segment without it. The map draws exactly that. Fortinet
  documents this as a deployment
  (https://help.fortinet.com/fweb/581/Content/FortiWeb/fortiweb-admin/planning_topology.htm,
  found through search; the host did not resolve from here): "Deploy
  FortiWeb in a one-arm topology where FortiWeb receives only HTTP/HTTPS
  from the FortiGate VIP/port forwarding". Barracuda recommends the
  opposite as its default
  (https://documentation.campus.barracuda.com/wiki/spaces/BWAFv76/pages/2720191/Choosing+Your+Deployment+Mode):
  "This configuration is recommended because it provides the best security
  and can utilize all traffic acceleration features." and "Most secure
  deployment choice since backend servers are completely isolated." Two-arm
  would put the sites on a segment of their own behind the WAF, a range
  change on both substrates; kept as an option in `docs/STATE.md`, not
  built. No range or layout change here.

Tests: rewritten because the design changed (`test_gns3_topology.py`): the
symbol source test (a host must name a `host-*.svg` the image builds;
switches and the internet a bundled affinity square), the VM-versus-container
test (now: each role's symbol and its frame colour), and the Kali test (the
dragon fetched to `/dragon/`, digest-checked, built by `symbols.py`, placed
unmodified, `host-kali.svg`). Added (2): every built host symbol is one
frame with only its stroke colour differing, 60x60, stroke 16; a framed
glyph is the bundled glyph without its own paper and frame, and a bundled
symbol of another shape fails the build.

Live (platform VM, OpenStack): both slots READY and idle before the
restart; `platform` and `gns3` rebuilt from this commit (the dragon stage
printed `/dragon/kali-dragon-black.svg: OK`, `symbols.py` printed `built`
for the seven symbols and `host-kali.txt`, the global `KALI_PRESS_PACK`
reached the final stage) and restarted; `provision.py` logged `symbol
host-*.svg uploaded` for all seven. Sessions 494 (board, slot 1) and 495
(corp, slot 2), both languages: every host node (`customers`, `kali`,
`firewall`, `waf`, the site, its database, `log-server`) draws its framed
symbol, every node image is 60x60 in the project and 42x42 px at the fitted
zoom, and the in-page check over the rendered SVG found no label touching a
line, a mark, a name, a node image, a zone edge or a caption (nearest label
to a mark 2.6 px). Both sessions were closed and both slots returned to
READY.

## 2026-10-15 — The learner's network map is view-only

The Topology pane framed the whole GNS3 editor: back to projects, add node,
start/stop, project and map settings, the drawing tools, context menus and
consoles. The Auditor role refuses every write on the server, but the learner
still saw and could press controls that only fail, so the map read as a tool to
edit rather than a picture of the network. The read-only page
(`deploy/gns3/auditor.html`, same origin as the web UI) now injects a stylesheet
that hides that chrome and takes pointer events off the drawing, and swallows
every trusted click, double-click, context menu, key and drop, and every press
but a left press on the empty map. Moving mode stays on, so a drag pans and the
wheel zooms; a Fit to view button in the pane resets and refits. The selectors
come from the gns3-web-ui bundle in gns3-server 3.1.0a6 and were checked on the
live web UI; a newer web UI may rename them, so the test pins the list.
Not used: GNS3's lock action, which fixes items in place but leaves every other
control of the editor, and the web UI's internal `readonly` flag, reachable
only through Angular internals, not the DOM.


## 2026-10-15 — The platform VM's rebuild runs an unpushed commit with sideloaded images; run live twice

`bin/cloud up --replace` had never run against the cloud, and the commit to
prove it with (local `dev`, 136 commits past `origin/dev` = 8f9acb0) was not
on GitHub or GHCR. The user approved building the changed images locally and
moving them over ssh, with no push and no GHCR write.

- **`--sideload NAME=TARBALL`** on `bin/platform-rebuild` and `bin/cloud`. The
  VM still clones `platform.ref` and pulls every image at that commit; the
  rebuild then checks this checkout's HEAD out from a git bundle,
  `docker load`s each tarball and tags its image with the cloned commit,
  restores the store, and starts every service. MicroK8s names importing
  images from `.tar` archives without a registry "Image side-loading"
  (https://canonical.com/microk8s/docs/sideload).
- **The tag stays the cloned commit.** `FSL_IMAGE_TAG` is also the tag the
  `fsl-wargame-host` builder pulls board, corp and corp-db at from GHCR, and
  it is in that image's bundle digest. Tagging the VM with HEAD would plan a
  host image whose images GHCR does not have, and its build would fail. With
  the cloned commit the builder pulled 8f9acb0's (their contexts equal
  HEAD's) and run 1 rebuilt the host image in 3 min 43 s. Cost: the tag on
  that VM names two images GHCR holds differently, and a reboot's `compose
  pull` can replace them; push and rebuild instead.
- **Refused before anything is deleted:** an unknown or repeated name, a
  missing tarball, a tarball without exactly one
  `ghcr.io/nekonic/fsl-NAME:<commit>`, and any image, pulled or sideloaded,
  whose build context in `images.yml` differs between its source commit and
  HEAD. That last check caught the first attempt: the platform tarball was
  built from 1814e5c and the rebuild's own tests in `platform/tests` had
  changed the context.
- **`bin/backup` streams.** The store on the test range is 5.96 GB (1.88 M
  detection rows). The snapshot was an in-memory copy plus its
  serialization (about 12 GB on an 8 GB VM) inside a 120 s limit for the
  whole transfer, so the rebuild would have stopped at "no backup". It now
  goes through SQLite's backup API into a temporary file in the platform
  container and streams in 1 MiB chunks, giving up after 600 s of silence.
  Run 1's `bin/verify` on Linux then failed
  `test_nothing_is_named_like_a_backup_until_it_has_passed_the_check`:
  closing stdin raised `BrokenPipeError` when the command (the tests' `cat`)
  had already exited; the hand-over now ignores it, as `communicate` did.
- **Runs.** Run 1 (HEAD d20b35e, 54 min 33 s) and run 2 (HEAD 412e379, the
  fix, 28 min 18 s) both exit 0 untouched; the stage table is in
  `docs/OPENSTACK.md` §5.3. Both kept the range key (same fingerprint), the
  slots' servers and both slots READY; cloud-init installed `python3-venv`
  and `nodejs` and applied `90-fsl-syslog.conf`; the group has 8000, 8002 and
  3080; the store restored at 0026 with nothing left to migrate; `fsl-gns3`
  served the learner map to a board session's Topology pane. The store's
  transfer is most of the time (backup 8-12 min, upload 15-31 min).
- **`bin/verify` on run 2's VM**: unit and API tests 2450 passed; acceptance
  71 passed, 3 failed, 71 skipped in 947 s; ratchet holds (core_loc 580,
  tests 2056). The three failures are corp's binlog credits
  (`test_corp_authz` rogue admin and content overwrite,
  `test_corp_observe_live`): the change happened on the target and nothing
  was credited. Measured cause: both wargame hosts' clocks run 6.2 and 7.0 s
  behind the platform VM's, and `NTPSynchronized` is `no` on them (the range
  has no Internet). `_effect_window` matches a binlog time, written by the
  target's clock, to a case window on the platform's clock with 100 ms of
  slack (`scoreboard.CLOCK_SKEW`), so every change falls before its window.
  Run 1's verify had one of the three, the 2026-10-15 run before it one
  ("a possible flake"); the skew grows with the hosts' uptime. Not fixed
  here: it is the range's timekeeping, not the rebuild (backlog).
## 2026-10-15 — The learner map leaves the address off `kali`, `customers` and the Internet caption

The attacker's source address changes with every attack (origin SNAT picks the
country), and the customers come from several origins, so one address at their
link ends showed a single origin as if it were the only one. Their ends now
read the interface alone (`ens3`), the same interface chosen as before (the
default origin for `kali`, the busiest for `customers`), and the Internet
zone's caption is its name alone (`Internet`, and its Korean pair), without the origin
networks. Every other host end keeps `<interface> <address>/<prefix>`, a switch
end its port (`e1`), a monitoring end its NIC, and the other zones their
networks. Approved by the user.

## 2026-10-15 — The platform VM is the range's time source

Measured cause first (the rebuild entry above): the range has no Internet
and no NTP server, the wargame hosts ran 6.2 and 7.0 s behind the platform
VM, and corp's binlog credits fell before their case windows
(`scoreboard.CLOCK_SKEW`, 100 ms). Widening the slack would hide it; the
hosts now keep the platform's time.

- **Server.** The platform VM has the Internet and real time. Its cloud-init
  installs chrony (it replaces `systemd-timesyncd`) with
  `/etc/chrony/conf.d/fsl-range.conf`: `allow <network.mgmt>` (a new Heat
  parameter, `management`) and `local stratum 10`, so the range follows the
  platform's clock even if the platform loses its upstream; the scorer
  compares against that clock, not true time. No `cmdallow`: chronyc stays on
  loopback.
- **The way in.** `fsl-reach` takes udp 123 from members of `fsl-mgmt`
  (`remote_group_id`), and nothing else new. `fabric.plan` reports a standing
  `fsl-reach` without that rule as `ntp`, and `ensure_fabric` adds it, so an
  existing range converges at the next `bin/cloud up`. The 2026-10-12 fence
  is otherwise unchanged: `fsl-mgmt` still admits only `fsl-reach`, so no
  range host reaches another over `mgmt`, and a range host reaches the
  platform only on udp 123 (and 5140 for the declared log senders). Kali is
  a member of `fsl-mgmt`, so the attacker's shell can query the platform's
  NTP; `docs/THREAT-MODEL.md` says so.
- **Clients.** The Ubuntu hosts (Kali, the WAF, the wargame host) already
  run `systemd-timesyncd`; `range/clock.py` writes
  `/etc/systemd/timesyncd.conf.d/60-fsl.conf` (`NTP=<platform mgmt>`),
  restarts it and waits up to 30 s for the platform's first answer, or the
  step fails. `keep_time()` starts every Ubuntu host's chain in
  `configure_slot()` and `configure_rebuilt()`, and the wargame chain (so
  also the in-place reset), before the wargames start. Kali had no configure
  step; it is rebuilt at every reset and now gets this one. The platform's
  `mgmt` address changes when the platform VM is rebuilt, which is why the
  configure path writes it, not the host images. Not chosen: chrony on the
  hosts, which would need every host image rebuilt for a client the image
  already has. The edge: the rendered `config.xml` sets
  `system/timeservers` to the platform (OPNsense starts ntpd only when it is
  set, `plugins.inc.d/ntpd.inc` `ntpd_enabled()`), `ntpd/iburst`, and
  `ntpd/interface` `opt1`, so ntpd listens only on management. The first
  in-place reset after this change finds the config drifted and reinstalls
  and reboots the edge, as for any config change.
- **Docker.** Every container reads the host kernel's clock; nothing changes.
- **Result.** `bin/verify` on the platform VM after the change: acceptance
  74 passed, 0 failed, 0 errors, 71 skipped in 765 s (corp's three binlog
  credits pass; before, 71 passed and 3 failed in 947-1,149 s); no
  regression. The offsets are not measured separately: a host more than
  100 ms off would fail those credits again.

## 2026-10-16 — The follow view is removed

The user's ruling: the blue console's "Follow a request" view goes completely,
and the Topology pane keeps only the GNS3 network map. Nothing new replaces
it; a lesson step stays only where a pane that already exists shows its
answer.

- **Removed.** `GET /api/sessions/<id>/topology/follow/` (`session_follow`,
  `_followed`, `_sent`, `_site_record`); `topology.follow` and everything only
  it used (the walk, the hop evidence, the verdict and reach rules); the
  pane's Follow tab, request picker, drawn SVG map and hop list, and its
  strings in both languages; the Website pane recorder's `to` (the WAF
  address its socket reached, read only by the follow walk); the answer facts
  `source` and `port`; `platform/tests/test_gns3_follow.py`. Without the GNS3
  web UI the pane now says the map is not open instead of drawing it.
- **F2** (`lesson.follow`, now "The path of one request"): `search`, then
  `status`, read in the Website pane's developer tools (the existing Status
  column). The `follow`, `source` and `port` steps are gone: no existing pane
  shows the learner's source address or the destination port, and F4's
  `address` step already asks for a source address from a WAF record. The
  theory explains hops on the network map; the hint points at the Status
  column.
- **F5** (`lesson.attack`, now "Read one attack"): `attack`, `stopped`,
  `rule`, `sqlmap`, `requests`. `stopped` is read from the developer tools'
  "blocked by the WAF" badge and judged from the request record's own
  `blocked` mark (the map's gateway node, `waf`); `rule` is read in Kibana
  (`url : *search* and status : 403`, the row's `rule_id` field) and judged, as
  before, from the session's own ModSecurity detections. Both are judged on
  the server from the session's records, never from the browser.
- **Tests** 2069 -> 2044: the 26 follow tests and three pane tests go; two
  pane tests and two judging tests (`stopped` from the record, every
  pointed-at control exists on the blue console) replace them. `core_loc`
  is unchanged (580); `product_loc` 24562 -> 24091.
- **Run live 2026-10-16** (OpenStack, platform VM 192.168.0.210), deployed
  three times by `bin/cloud up --replace --sideload platform=... --sideload
  gns3=...` (`docs/OPENSTACK.md` §5.3), each with the platform image built on
  the VM from HEAD and the gns3 image from 1814e5c: 2535f30 in 25 min 55 s,
  3a7238d in 24 min 55 s, 470b1bb in 24 min 47 s (each about 10 min of store
  backup, 5.96 GB; all exit 0, both slots READY). A learner in Korean, headless
  Playwright, real panes only. F2 passed `search` and `status` (200 read in
  the developer tools' Status column) on every build (sessions 549, 551,
  553). F5 on 2535f30 (session 550) found two faults, fixed: the `rule` field
  holds the rule messages (`[Inbound Anomaly Score Exceeded (Total Score: 5),
  SQL Injection Attack Detected via libinjection]`) and `rule_id` the numbers
  (`[942100, 949110]`), so the step now points at and names `rule_id`
  (ce24871); and the sqlmap step's row with the sensor count left 1.2 s after
  the check passed, while the next step asks for that count, so a passed
  Kali step now stays until Next (3a7238d). On 3a7238d (session 552) that row
  pushed Next below a 1000-pixel viewport, because the popover was placed
  before the row was drawn; it is now placed again (470b1bb). On 470b1bb
  (session 554) every step passed: `attack`; `stopped` (403 with the "blocked by the
  WAF" badge in the developer tools, answered `waf`); `rule` (942100); `sqlmap` (41 s from the
  Kali terminal); `requests` (1903, the row's count). The two assumptions:
  the filter `url : *search* and status : 403` finds exactly the `' OR 1=1--`
  record (1 document, `/search/?q=%27%20OR%201=1--`, 403); and
  `[data-test-subj="field-rule_id"]` is Discover's field-list entry, not the
  expanded row (whose fields are `tableDocViewRow-<field>-value`, 25 to a
  page; `rule_id` is on a later page). The entry's Top values show 942100 and
  949110, and the row's grid shows `rule_id` too, so the step is answerable;
  F4's `field-status` and `field-source_ip` point at the same list.
- **`bin/verify` on 470b1bb** (on the VM, `FSL_PLATFORM_URL=http://192.168.0.210:8000`
  as §7 says; the platform publishes 8000 on the VM's address, so the default
  localhost failed the stack stage of a first attempt): unit 2441 passed in
  101 s; acceptance 74 passed, 0 failed, 0 errors, 71 skipped in 730 s across
  4 processes; ratchet holds (core_loc 580, tests 2045); 936 s in all. The
  rebuilt VM has no `.venv`; it was made by hand before the run.

## 2026-10-16 — bin/verify runs only what a change touches

Every check ran the whole unit suite (`--fast`, about 94 s, 2,457 cases) or
that plus acceptance on the live range (13–19 min, both slots), whatever the
change was. `bin/verify --changed [BASE]` now runs only the unit test files the
change reaches, and the ratchet; `--live` adds the acceptance modules it
reaches. Full and `--fast` behave as before.

- **Selection** (`bin/select-tests`, stdlib only). The changed files are
  `git diff --name-status BASE` plus untracked files (BASE defaults to the
  merge-base with `dev`; `A..B` takes commits only). A static graph of the
  repo links each file to what it runs — Python imports resolved with
  `platform/` or `test/` as the working directory, `pytest_plugins`, dotted
  module names in tests (`mock.patch` targets), the view module each URL a
  test requests resolves to through `fsl/urls.py`, the test conftest — and to
  what it reads: files named by repo path, path tail or basename, and files a
  test globs. A test file is selected when it reaches a changed file; reading a
  Python file as text (a seam check reading `views.py`) does not pull in what
  that file imports. A per-file reason is printed.
- **Safety.** Docs (`*.md`, `docs/`, `.claude/`, `metrics.json`) select
  nothing. The unit `conftest.py`, `pytest.ini`, `requirements.txt` and
  `fsl/settings.py` run the whole unit suite; so does any changed file that
  no test reaches. A range-facing change no acceptance test names needs all
  of acceptance. The ratchet runs in every `--changed` run, a docs-only one
  included (a test holds it).
- **Measured** on this tree, unit tests only, wall time of the whole command:

  | change | unit files | cases | wall |
  |---|---|---|---|
  | `--fast` (everything) | 146 | 2,457 | 94 s |
  | docs only (`1a97877`) | 0 | 0 | 1 s |
  | `bin/backup` fix (`412e379`) | 6 | 99 | 7 s |
  | follow view removal (`2535f30`, views, topology, templates) | 95 | 1,711 | 46 s |
  | learner map UI (`1814e5c`, templates, GNS3 page) | 86 | 1,586 | 47 s |
  | range NTP (`c4ee8d7`, `range/`, OpenStack tests) | 106 | 1,988 | 92 s |

  `api/views.py` imports most of `platform/` and most API tests request one
  of its URLs, so a change to any module it imports still selects most of the
  API tests; the saving is large for `bin/`, `deploy/`, test, stylesheet and
  docs changes and about half for console or view changes. Splitting
  `views.py` would sharpen it; not done here.
- **Tests** 2044 -> 2059 (14 for the selector, one for `bin/acceptance --only`).

## 2026-10-16 — The test count is reported, not gated

- **Ruling** (the user, 2026-10-16): remove the rule that `tests` may only
  rise. `bin/measure` still counts and prints it, marked `(not gated)` like
  `product_loc` and `wargame_services`; `bin/verify` no longer refuses a
  smaller count and lists it under `smaller:` instead.
- **Why.** The floor rewarded keeping tests that no longer earn their place:
  every removal needed `metrics.json` lowered by hand and a ruling, so
  restatements of constants and pins on implementation details stayed. A test
  audit is exactly removing the ones no one can justify; the commit that
  removes a test says why.
- **What still gates.** `core_loc`, `dependencies` and `services` may only
  fall, unchanged.
- **What still protects the hypothesis.** The benign cases in
  `redteam/cases/` stay, and TP > 0 and TN > 0 stay in "What must not break";
  neither depended on the count.
- **Tests.** The `--changed` ratchet test now regresses on a grown
  `services`; a new test holds that a falling test count passes and is
  reported.

## 2026-10-16 — Test audit: every test states its need or goes

The user: there are far too many tests (2,061 module-level test functions,
34k lines); for every test an agent must say why it is needed, and if it
cannot, the test goes; tests that should change, change.

- **The bar.** A test stays only if removing it would let a real defect ship
  that no kept test catches, and the defect matters to one of six needs: an
  invariant in CLAUDE.md "What must not break"; scoring (both scores,
  attribution, `expect`/`corroborated`, one case counts once); session
  isolation and the range's fences; a contract other code or the console
  relies on; a regression that happened (commit or entry cited); the
  ratchet, measure and verify tooling. Deleted: copy, markup, CSS and layout
  pins; duplicates (the strongest kept); constants and trivial getters;
  mock-was-called checks; removed features; unit re-tests of what acceptance
  proves for the same failure; anything whose need does not fit one line.
  Changed: source greps that could test behaviour (the deliberate source
  rules stay), over-mocked or slow tests, near-identical bodies merged into
  one parametrized test, assertions trimmed to the need.
- **How.** Eight agents, one per group of files, each wrote a verdict per
  test with a one-line reason; the verdict tables (2,059 rows: 820 kept, 333
  changed, 906 deleted) were working files and are not in the repo. Of the
  deletions about 160 were merges into a parametrized sibling, about 210
  pinned copy, markup or display, about 170 duplicated another test, about
  140 pinned a constant or schema, 13 tested dead code.
- **Numbers.** Test functions 2,061 -> 1,051; unit cases 2,459 -> 1,458
  (`bin/verify --fast` 93 s -> 49 s here); test lines 34,163 -> 23,362; test
  files 185 -> 165 (15 unit, 5 acceptance: `test_corp_cve_option_flip`,
  `test_corp_cve_rogue_admin`, `test_corp_site`, `test_fabric`,
  `test_corp_cve_content_write`).
- **Cross-group cleanup.** `test/test_corp_site.py` (one duplicate left) and
  `test/test_fabric.py` (a duplicate of `test_api_fabric.py`) are deleted
  and gone from `bin/acceptance`'s lists, `test/conftest.py` and the split
  test; `test_corp_cve_content_write.py`'s helpers moved into
  `test_corp_authz.py`, which already held the live content-overwrite test;
  `test/durations.json` drops the five modules. Where two groups each
  deleted a test in favour of the other's, one was restored, merged where
  they overlapped: the topology picture places each alert on the segment it
  arrived on, marks the outside, counts the unplaced, and counts every alert
  against one address named by its zone (two unit tests in
  `platform/tests/test_topology.py`); `harness.run` opens a session of its
  scenario, records each case in it and closes (`test_harness.py`); the fix
  is named by how narrow it is (`test_lesson_steps.py`, parametrized). An
  unknown origin is still refused through `attacker.find` by
  `test_origins.py::test_an_origin_that_does_not_exist_is_refused`.
  Helpers nothing imports any more are removed (`ROLES`, `BOARD_DB`,
  `GATEWAY` in `test/range.py`).
- **The noVNC console endpoint is removed.** Its tests went as dead code, and
  nothing calls it (no template, script, nginx or compose reference since the
  pfSense pane went, 2026-10-08), so `GET /api/range/console/<host>/`,
  `OpenStack.console()` and the last test of it in `test_range_slots.py` go
  too; this reverses "kept but unused" above.
- **Proven live 2026-10-16** (OpenStack, platform VM 192.168.0.210). Acceptance
  edits were mechanical (deleted tests, removed imports, merged asserts).
  Deployed by `bin/cloud up --replace --sideload platform=... --sideload
  gns3=...` (`docs/OPENSTACK.md` §5.3), the platform image built on the VM
  from ee2e5b9 and the gns3 image from 1814e5c: exit 0 in 27 min 37 s (about
  10 min of store backup, 6.02 GB), both slots READY. `bin/verify` there
  (`FSL_PLATFORM_URL=http://192.168.0.210:8000`, the `.venv` made by hand
  again): unit 1458 passed in 49 s; acceptance 45 passed, 0 failed, 0 errors,
  30 skipped in 728 s across 4 processes (75 collected); ratchet holds
  (core_loc 580, tests 1051); 876 s in all. No test needed a fix.

## 2026-10-16 — Retention is set by config, at its minimum

The platform store on the test range reached 6.02 GB, 97% of it
`api_detection` (1.9 M Suricata and WAF records over 144 sessions, nearly all
from tests and live runs). Every rebuild and `bin/cloud down` copied the
whole store to the operator's machine (about 10 of a rebuild's 25 min), six
6 GB copies piled up in `backups/`, and the big store slows ingest. The user:
make retention adjustable by config and set it to the minimum for now.

- **`FSL_RETAIN_CLOSED_MINUTES`** (default 60; `platform/fsl/settings.py`,
  set in `compose.yaml`'s platform environment, so the Docker range and the
  OpenStack platform VM take the same value; an operator overrides it in
  `/opt/fsl/.env`). A session closed longer ago than that is deleted with its
  cases, detections, customer requests and objectives (all `CASCADE`);
  suppressions are kept with their session cleared (`SET_NULL`), so a rule
  still commented out keeps its record to restore. Open sessions are never
  touched. `platform/api/retention.py` runs at start (a thread in
  `fsl/wsgi.py`, beside the scenario resume) and at the end of every close,
  one session per transaction so a large first prune does not hold the
  store's write lock for long. Nothing in `scoring/`, `ingest/` or `rules/`
  changed.
- **What reads a closed session, and why 60 minutes.** A closed session is
  read right after its close by: ingest and score (`POST .../ingest/`, `GET
  .../score/`; the harness and acceptance's `score_when_ready` poll for up to
  150 s), the stack that outlives it while Filebeat ships its last alerts
  (`STACK_OUTLIVES_ITS_SESSION`, 3 min, read from the session table), the
  learner's score and debrief in the console (`/scenario/debrief/` opens once
  the session is closed), the closed-session list and comparison
  (`?state=closed`, `?ids=`), and acceptance's session-scoped fixtures, which
  close a session and read it back during the run (the longest run measured
  was 947 s). `bin/verify` then removes the run's own sessions with `bin/prune
  --ids`, which ignores ids already gone. The acceptance criterion
  `test_criterion_2_redteam_run_produces_a_closed_session` the task named no
  longer exists (the test audit removed it). `bin/measure` and `metrics.json`
  read no sessions. The longest of these is acceptance at about 16 min, so 60
  min keeps every flow with four times the margin and is the minimum chosen;
  the cost is that the console's list of past sessions shows only the last
  hour.
- **Backups.** `bin/backup` writes the snapshot with `VACUUM INTO` instead of
  the backup API, so the free pages pruned sessions leave are not shipped; it
  still writes a temporary file in the platform container and streams it in
  1 MiB chunks (2026-10-15 "`bin/backup` streams"). After the new copy passes
  `integrity_check` it removes older `db-<UTC stamp>.sqlite3` files beyond
  `--keep` (default 1, the new one included); a file named otherwise (such as
  `db-20261014-pre-p6.sqlite3`) is never removed. `cloud.yaml` gains an
  optional `backups: {keep: 1}`, read by `bin/platform-rebuild` and `bin/cloud
  down`; a `cloud.yaml` without it parses and keeps one. On the VM the code
  keeps one copy in `/opt/fsl/backups`, the store it was restored from; every
  rebuild makes a new VM.
- **The next rebuild.** The VM gets this at the post-push `bin/cloud up
  --replace`. That backup is taken from the running VM, whose store is not
  pruned yet, so it is still about 6 GB (minus free pages); the new VM prunes
  at its first start, and every backup after it carries about an hour of
  closed sessions plus the open ones.
- **Proven live 2026-10-16** (OpenStack, platform VM 192.168.0.210), before
  the push, by `bin/cloud up --replace --sideload platform=... --sideload
  gns3=...` with the platform image built from 6234510 and the gns3 image
  from 1814e5c: exit 0 in 30 min 5 s, both slots READY. Its backup of the old
  VM (already `VACUUM INTO`) was 5,929,553,920 bytes against a 6,018,662,400
  byte store, 144 sessions and 1,905,655 detections, in about 14 min, and
  `backups/` dropped the previous 6 GB copy (keep 1). The new VM pruned at
  its first start: 144 closed sessions -> 0 (no session was open; detections
  1,905,655 -> 0) in about 1 min 45 s. The store file stays 5,929,553,920
  bytes, 1,447,562 of its 1,447,645 pages free, because SQLite does not
  shrink a file without `VACUUM`; the next `bin/backup` was 335,872 bytes in
  0.8 s, and `backups/` again kept only it. During that first prune one tick
  of the scenario engine logged `database is locked` and the next tick ran;
  no other error. `bin/verify` there (`FSL_PLATFORM_URL=http://192.168.0.210:8000`,
  the `.venv` made by hand): unit 1462 passed in 49 s; acceptance 45 passed,
  0 failed, 0 errors, 30 skipped in 692 s across 4 processes; ratchet holds
  (core_loc 580, tests 1055); 838 s in all. No test needed a fix. The
  `PytestUnhandledThreadExceptionWarning` in the unit run is a test artifact:
  an `fsl-scenarios` thread left running past its test calls
  `close_old_connections()` in its `finally`, which pytest-django refuses
  ("Database access not allowed"); the platform's own log has no such
  exception.

## 2026-10-17 — An error in the scenario engine's connection cleanup no longer stops the engine

`scenario_run._run` called `close_old_connections()` in a `finally`, outside
the `try`, so an exception there left the loop and the `fsl-scenarios` thread
died; scenarios then stopped advancing until a scenario open or a learner
verify started it again. Seen only in unit runs: a test that opened a
scenario started the real thread, which outlived the test and was refused the
database by pytest-django in a later one
(`PytestUnhandledThreadExceptionWarning`). Now each of `tick` and
`close_old_connections` is caught and logged on its own; the unit conftest
stubs `ensure_running` for every test (tests drive `tick` directly), and one
test holds that a failing cleanup does not end the loop.

## 2026-10-17 — Errors swept before the push

The user: before pushing, every error must be caught. Swept on 2026-10-17:
the unit run with every warning shown (`-W default`, `PYTHONDEVMODE=1`,
tracemalloc); the platform VM at 6234510 since its deploy (compose logs of
every service, `fsl-platform.service`, chrony, cloud-init, the boot journal);
each slot's WAF, Kali, wargame host containers and OPNsense edge through the
platform's own runners; the console in headless Chromium (home, blue panes,
red, session page, en and ko, one session opened and closed); and the skip
reasons of the last acceptance run.

| Found | Where | Cause | Fix |
|---|---|---|---|
| `database is locked` in a scenario tick during the first prune | platform log | one session's cascade (up to hundreds of thousands of detections) deleted in one transaction held the write lock past the 30 s busy timeout | retention deletes detections and customer requests 2,000 rows per transaction, then the session (7dd9ab9) |
| 80 `Could not close node ... No such file or directory: 'docker'`; 52 display containers left running; stale container names; UDP ports kept | gns3 log | GNS3 closes a docker node with `docker exec`; the image had no docker client | the gns3 image installs Debian's `docker-cli` 26.1.5 (API 1.45; the daemon accepts 1.44 and up) (c98f649) |
| 12 `Controller not found error ... (DELETE)` | gns3 log | publishing DELETEd a project GNS3 never held; GNS3 logs each 404 at ERROR | the platform lists projects and deletes only a listed one; `status()` reads the list (c98f649) |
| `failed to put data stream: no matching index template found for data stream [fsl-logs]` | collector log | Filebeat names a data stream after its template (`fsl-logs`), outside the pattern `fsl-logs-*`; once per fresh Elasticsearch | `setup.template.pattern: fsl-logs*` (58f3b73) |
| nginx `connect() failed (111: Connection refused)` (502); `curl: (22) ... 502` in `bin/verify` | platform log, verify log | nginx started before waitress listened | nginx is tested, then started once 127.0.0.1:8001 accepts; the restart poll no longer prints the failures it waits through (c86983d) |
| 17 `[warn] an upstream response is buffered to a temporary file` | platform log | detections and score responses outgrow nginx's memory buffers | `proxy_max_temp_file_size 0` (c86983d) |
| `af-packet: ens3: AF_PACKET tpacket-v3 is recommended for non-inline operation` | estate sensor, both slots | `ens3` matched no `af-packet` entry and there was no `default`, so Suricata used built-in values and skipped its tpacket-v3 default | a `default` entry (d0d23ac); deploy 1 showed it never reached the hosts: the wargame host stays standing across resets and had the config only from its image, so every sensor start now writes the platform's `suricata.yaml` to the host first (1efa522) |
| `Implicitly cleaning up <HTTPError 503>`; unclosed `records.jsonl` | unit run | Kibana bring-up kept a not-ready HTTPError open; the customers never closed their records file | closed; `Customers.run` joins its workers, then closes the file (e2e399c) |
| 47 `ResourceWarning`s: sockets, files, SQLite connections | unit run | test fixtures that shut servers down without `server_close()`, unclosed socketpairs, an sshd log handle, in-memory store copies, a request thread's connection | each closed in its test (e2e399c); the importer test now joins its console thread before its sockets close, which the VM's Python 3.12 run caught (`Bad file descriptor`; aa03264) |
| `GitPython is not installed. Cannot clone repository`; `Failed to initialize skills repository` | gns3 log, every first start | 3.1's copilot (installed with `[ai-features]`, without which the server does not start) clones `github.com/gns3/gns3-skills` at start; 3.1.0a6 reads no setting to turn it off | the image sets the copilot's `enabled` to `False` in `skills_config.py`, and the build fails if the line is gone (60a7197); the 2026-10-13 note that it "logs an error and fetches nothing" is superseded |
| `kibana answered 415 to .../api/saved_objects/_import?overwrite=true: Unsupported Media Type`; the Kibana pane's data view and saved search were never imported | platform log, deploy 2 | bring-up retried only 502, 503 and 504; a starting Kibana answers `/api/status` 503 but a multipart import 415 (measured: 503/415 for about 7 s, then 200/200), so bring-up gave up; it showed once `--force-recreate` started Kibana beside the platform, as every fresh VM boot does | bring-up asks `/api/status` first and imports only once it answers (d41cec2) |
| `Generating configuration: templates...failed` at every edge boot, both slots | OPNsense system log | the early-boot hook `rc.syshook.d/early/15-templates` renders every template before OPNsense's migrations fill model defaults; our config.xml had no `dnsmasq`, `Syslog/general` or `unboundplus`, so three templates raised (`'dnsmasq' is undefined`, measured by re-running the generator on the edge against the pre-boot copy in `/conf/backup`); each service rendered its own templates again as it started, so nothing ran misconfigured | config.xml carries the 26.7 defaults for the three models, copied from a migrated edge without `persisted_at` (fba99ae); the edge image is rebuilt for it |
| the collector still logged the data stream error after the first deploy of the fix | collector log, deploy 1 | a sideloaded rebuild checks HEAD out under running containers; a bind-mounted file keeps the cloned commit's copy, and `compose up -d` recreated only the services whose image changed | `compose up -d --force-recreate` after a sideload (ac339c2); the fix itself was proven on a throwaway Elasticsearch 8.15.0: `filebeat setup --index-management` failed with the old pattern and created `fsl-logs` with the new |

Third-party, no action: Kibana 8.15.0's one start-up `ERROR` from
`plugins.elasticAssistant` ("Platinum, Enterprise or trial license needed";
the plugin has no setting to turn it off, and the cluster runs the basic
licence) and its start-up `WARN`s for unset encryption keys, cookies over
http, legacy OpenSSL, the reporting privilege default, the screenshotting
sandbox and task manager capacity; Elasticsearch's JVM `COMPAT locale
provider` warning; Kibana's own CSP, COOP and `Permissions-Policy` console
messages and its `user_profile` 404 with security off; ttyd 1.7.7's
`unknown option: arg` and its `beforeunload`; GNS3 web UI's cross-origin
autofocus; headless WebGL stalls; uBridge's `netlink ... attribute type 7`
kernel lines; GNS3's advice on inotify limits and compute authentication;
Ubuntu cloud image boot messages (GPT before growpart, MMCONFIG, IMA,
`EXTRA_OPTS`, `dnsmasq`); an OPNsense kernel notice `Limiting ICMPv6
destination unreachable output` 5 s after its 03:01 `periodic daily` syslog
archive (the sender is not established; nothing failed). Expected, not
faults: 409 on open while a slot is taken or resetting (acceptance waits on
it), 409 on closing a closed session (acceptance's teardown), 400 for a rule
that does not parse and the edge's matching `suricata -T` errors, 404 for an
unknown case. Each `django.request` line is printed twice (Django's DEBUG
console handler and waitress's root handler), which is format, not an error.

Acceptance skips: all 30 of the last run skip with "exercises the compose
range; the scored range here is openstack" (test_concurrent_sessions 2,
test_ready 2, test_topology 2, test_window_correlation 3, test_board_exfil 4,
test_event_time 2, test_judge_isolation 4, test_segmentation 3,
test_terminal 1, test_attacker_box 2, test_front_door 3, test_operator_log 1,
test_strategy_comparison 1): Docker-substrate tests by design. None skips for
a missing fixture, an unreachable host or a range not ready.

Tests added only where a defect was real: retention deletes in batches;
publishing a project GNS3 does not hold sends no DELETE; the gns3 image has
the docker client and fetches no skills; Filebeat's template pattern covers
its template name; a sideload recreates every service; a sensor start
carries the sensor config; Kibana bring-up waits for its status; the edge
config carries the three models.

**Proven live 2026-10-17** (OpenStack, platform VM 192.168.0.210). Four
deploys by `bin/cloud up --replace --sideload platform=... --sideload
gns3=...`, each found what the next fixed: e2e399c in 13 min 30 s, 1efa522 in
8 min 31 s, d41cec2 in 8 min 33 s, and the final fba99ae in 14 min 33 s
(the edge image rebuilt for its config); all exit 0 with both slots READY.
The platform image was built on the VM from each HEAD; the gns3 image from
1efa522, whose `deploy/gns3` is HEAD's (1814e5c's no longer is). `bin/verify`
on fba99ae (`FSL_PLATFORM_URL=http://192.168.0.210:8000`, the `.venv` made by
hand): unit 1469 passed, no warnings; acceptance 45 passed, 0 failed, 0
errors, 30 skipped (the reasons above) in 751 s; ratchet holds (core_loc
580, tests 1062); 885 s in all. The sweep after it: the platform log holds
only the expected 409, 400 and 404 lines; the gns3 log no error, its four
maps' 28 display containers and none exited; the collector logged nothing;
Elasticsearch and Kibana only the third-party lines above; both edges booted
with `templates...done` (the earlier `failed` lines in the same day's log are
the deploys before the fix and the generator run against the pre-boot copy);
both estate sensors start with no `af-packet` warning; the WAFs', Kalis' and
wargame hosts' journals hold no error and no container restarted; the
console sweep (session 655, en and ko) shows only the third-party messages
above.

## 2026-10-17 — The coach finds every step's target

The user: in the blue console the coach said "the highlighted spot is not on
screen ... Kibana may still be loading" on F1 step 2 with the Topology map in
view, and on other steps too. A headless sweep (Playwright, Chromium, 1440x900)
opened every foundation F1-F6 and both stepped scenarios (1.1, 3.1) on the
platform VM, in Korean and English, went to each step, opened the pane the
step names (or pressed its Kibana filter), and read where the red box was.
Screenshots of every step are in the session's scratchpad (`coach/`).

| Step | `point` | Before (fba99ae) | Cause | Fix |
|---|---|---|---|---|
| F1 entry, logs, segment | `pane`, `opens: topology` | no box, "Kibana may still be loading", ko and en | a `pane` step was measured on `#pane-frame`, the Kibana/WAF iframe, hidden while the topology, site, Judge or rules pane is open | the pane is `#pane-body`, the area every pane is drawn in (2ea48a5) |
| F5 sqlmap, requests; F6 sqlmap, loot, leaked, lost | `pane` | boxed only while the Kibana or WAF frame was open; none on Topology or Website | the same | the same |
| every step with no target in view | — | the line always blamed Kibana | a fixed string | `lesson.coach.missing` takes `{0}`, the rail label of the step's pane (2ea48a5) |
| F5 stopped (en) | `panel: #site-dev-toggle` | the popover sat at its static place over the rail and the address bar; the Website button could not be clicked | each pane switch ran `triageDock`, whose `dockedIn` reset the popover's `left`/`top` even when it did not move; the coach places it again only when its target moves | `dockedIn` leaves an element already in place alone (ef864c1) |
| every Next and Skip | — | found on the first deploy of the fix: 124 `database is locked` 500s over one sweep, and the skip of F1 entry and 1.1 open was lost | Next posts the left step's skip and the next step's reach at once; each is a read-then-write transaction, and under SQLite's DEFERRED begin the second to upgrade its lock deadlocks and gets SQLITE_BUSY at once, without the 30 s busy timeout (two threads on a file database: DEFERRED fails in 0.21 s, IMMEDIATE commits both) | `transaction_mode: IMMEDIATE` (Django 5.1+) (39750bb); none since |
| F4 find (ko) | `kibana: docTableExpandToggleColumn` | "No results" in Discover; pressing the filter four more times over 100 s did not change it | the filter was pressed 2 s after the probe; the WAF record is searchable after about 6 s (measured); the same address again is a fragment navigation, which does not refetch | the filter (and the Kali step's Kibana link) reloads the frame when it already shows that address (e331372) |

The GNS3 web UI and the website are other origins (their own ports), so
nothing inside them is looked up; their steps point at the pane. `kibana` and
`first` are looked up only in the Kibana frame, the one same-origin frame,
and a step that names them must `opens: elk`.
`test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console`
(extended from the foundation-only panel check) holds every `point` of every
foundation and stepped scenario to the rendered console; a pane step is
boxed whichever pane is open, and stays placed when the pane is opened again;
pressing a filter again reloads Kibana.

**Skip replaces "Do it for me".** The user: replace it with Skip, and remove
do-for-me entirely. The last rung of the hint ladder is now Skip
(`lesson.skip`, "Skip" and its Korean in `strings.html`; `lesson.SKIP_OFFERED`): it records the
step skipped through the step-record API that Next already uses and moves on;
on the last step it records the skip and closes the popover. Nothing is
entered, fired, applied or credited for the learner, so a later step that
reads a skipped step's record stays unanswerable (`lesson.check.unrecorded`)
until the learner does that step or skips it too. Removed: `POST
/api/sessions/<id>/lesson/steps/<step>/do/` (`views.lesson_step_do`,
`_put_rule`, `_kali_do`, `_loot_do`), the `do` hint level,
`progress.done_for_me` and `help_counts.done_for_me`,
`views.SERVER_ONLY_STEP`, the rules step's `rule:` and the sent steps' `site:`
in `scenario.yaml` (read only by do-for-me), and the strings `lesson.do`,
`lesson.helped`, `result.helped.do`. `result.scenario.helped` is `["hint"]` or
empty.

**Proven live** on the platform VM (192.168.0.210), deployed by `bin/cloud up
--replace --sideload` (platform image from each commit, gns3 from 1efa522):
ef864c1 in 24 min 43 s, 39750bb in 8 min 36 s, e331372 in 8 min 47 s. The sweep on
39750bb: 72 step views (36 steps, ko and en), 71 boxed on the step's own
target; the 72nd, F4 find in Korean, is the reload above. The six pane steps
without `opens`, viewed again on the Topology pane: 12 of 12 boxed. Skip on
one step of each kind (F1 entry answer, F4 search sent, F4 engine choice, F5
sqlmap kali, 1.1 open click, 3.1 rules click): offered after the fourth hint,
labelled with the Korean `lesson.skip`, recorded skipped and not passed, the coach on the next step,
6 of 6. No popover over the rail; no `database is locked` since 39750bb.
The sweep again on e331372: 72 of 72 step views boxed (69 on their own step;
the other three are English views of sent steps the Korean pass had already
passed in the same session, so the coach opened past them), 12 of 12 pane
steps boxed on Topology, F4 find in Korean boxed after one more press of the
filter (the reload), Skip 6 of 6 as above, no popover over the rail, no
`database is locked` and no 500 in the platform log; every session the sweeps
opened (657-686) closed.

## 2026-10-17 — No acceptance test is skipped on OpenStack

The user: docker-only tests should have been deleted; under the 2026-10-11
ruling no acceptance test may be docker-only or skipped on openstack. The last
run still skipped 30 tests in 13 modules through `COMPOSE_RANGE_ONLY`. Each
was judged with the test audit's bar (2026-10-16): it runs on both substrates
through the existing seams (`test/range.py`, the platform API), or it goes
because it checks a compose-only mechanism or repeats a test that already
runs on OpenStack. `COMPOSE_RANGE_ONLY`, the skip in
`pytest_collection_modifyitems` and the `on_compose()` branches in
`shared_sessions.py` are gone; nothing in `test/` skips by substrate.

| Module | Tests | Outcome |
|---|---|---|
| `test_attacker_box` | 2 | run everywhere; the first keeps "the console's direct address is one of the box's own" and drops "the proxied address is not the box's": that is compose's proxy container, and on OpenStack the box wears the origin itself (SNAT), so the two are one address by design; HTTP attribution by `source_ip` is proven by `test_window_correlation` on both |
| `test_board_exfil` | 4 | run everywhere, unchanged |
| `test_concurrent_sessions` | 2 | run everywhere, unchanged (two slots) |
| `test_event_time` | 2 | run everywhere, unchanged |
| `test_front_door` | 3 -> 2 | the shell probe runs everywhere (its alerts now come from `terminal_session`); the inside leg reads the session's detections through the API, so the estate sensor (the WAF-to-target leg on OpenStack) counts; the console attack deleted, a duplicate of `test_map`'s placement of `tuned_session`'s console-fired case in Russia (`5.188.10.0/24`) |
| `test_judge_isolation` | 4 + 1 | run everywhere; the gateway is the operator's host only on docker, so each host now also probes every address of `fsl-platform` the topology API lists and the published address, and counts a reach only when the scoring API (`/api/range/ready/`) or Elasticsearch itself answers (the wargame host's own published 8000 is the board app); it opens its own session; `test_terminal`'s one test moves here, probing the same addresses instead of the compose name `platform` |
| `test_operator_log` | 1 | run everywhere; it found a product defect (below) |
| `test_ready` | 2 -> 1 | the canary runs everywhere; "the range reports itself ready" deleted: docker answers `ready: True` as a constant, `conftest.stack_is_up` already asserts OpenStack's readiness before any test, and asserted mid-run beside a second worker it failed on the other slot's legitimate reset |
| `test_segmentation` | 3 -> 0 | deleted: "cannot reach the target directly" and "can reach the way in" repeat `test_attacker_reach` (`http://board:8000/` from Kali) and `test_board_exfil` (200 through `board.com`); "share no segment" checks docker network membership, while on OpenStack Kali and the wargame host share `mgmt` by design and the fence is the security groups, scanned on both by `test_attacker_reach` |
| `test_strategy_comparison` | 1 | run everywhere, unchanged |
| `test_terminal` | 1 -> 0 | moved into `test_judge_isolation` |
| `test_topology` | 2 | run everywhere; `full_run` now reads the topology on both |
| `test_window_correlation` | 3 | run everywhere, unchanged |

25 of the 30 run on both substrates; 5 deleted. The harness gained two
substrate-neutral ways, no second way to reach a VM: on OpenStack
`test/range.py` runs the attacker's commands in a login shell (`bash -lc`),
because the terminal there is an ssh login that gets the proxy and
`FSL_TARGET` from `/etc/profile.d/fsl.sh`, which compose sets on the Kali
container for every process; without it the label never stamped a request
and `$FSL_TARGET` was empty. And the probe helpers read the session's
suricata detections through `/api/sessions/<id>/detections/` and
`/api/detections/<id>/` (the stored eve event) instead of tailing one
sensor's `eve.json`, which on the OPNsense edge is empty (its eve goes to
`/var/log/suricata/suricata_<date>.log`).

**Product fix.** The operator log was always empty on OpenStack: the
terminal is an ssh login as the cloud user, only root's `.bashrc` sourced
`operator-log.sh`, and `deploy/kali/setup.sh` never made `/var/log/fsl`.
Now setup makes `/var/log/fsl/commands.log` (0666, as `/label/active`) and
sources the hook from `/etc/bash.bashrc`, which every interactive bash reads;
a unit test holds both lines. The Kali image's bundle changed, so the
sideloaded rebuild carried a `fsl-kali` tarball too; a standing slot keeps
its Kali until its next reset, so one session per slot was opened and closed
before the run.

**Proven live 2026-10-17** (OpenStack, platform VM 192.168.0.210). Deployed by
`bin/cloud up --replace --sideload platform=... --sideload kali=...
--sideload gns3=...` (platform and kali images built on the VM from 1fd5be3,
gns3 from 1efa522): exit 0 in 12 min 33 s, both slots READY, both Kalis
rebuilt from the new image by a reset. The 11 modules alone (`bin/acceptance
--only`): 26 passed, 0 failed, 0 skipped in 463 s. `bin/verify` on b324ba5
(test-only on top of the deploy; `FSL_PLATFORM_URL=http://192.168.0.210:8000`,
the `.venv` made by hand): unit 1474 passed; acceptance 70 passed, 0 failed,
0 errors, 0 skipped in 997 s across 4 processes (70 collected, was 75);
ratchet holds (core_loc 580, tests 1055); 1,131 s in all. The range was
shared with another session's live walks this day; acceptance ran only
while no other session was open.


## 2026-10-17 — Learner text is plain: titles say what the learner does

The user reviewed every learner-facing string (936 keys in
`strings.html`, en and ko, the 58 withheld ones included) and ruled:

- No drama or mission framing. A title says what the learner does: "A quiet
  shift" is "Telling customer requests from attacks", "My range" is "Reading
  the practice network's map", "An evening on your own" is "Combined
  exercise". A situation states the configuration and the traffic, not a
  story (no inherited admin, no colleague, no evening).
- No unexplained jargon. Where the field names the thing, its name is used:
  false positive, anomaly threshold; in Korean the terms of
  `docs/vocabulary.md` (rule, target), which the table had mixed.
- "Range" is not a learner word: it becomes "the practice network", or "the
  platform" where the sentence meant the platform (Korean likewise).
- The topology pane has one name, Map (Korean likewise one word): the rail
  button (`blue.pane.topology`), its tab (`topology.view.map`) and every
  lesson sentence; "network map", "topology" and "map" variants go.
- A label says what it does: "I'm done" is "Start final check", the Judge rail
  button is "Alerts", "Validate" is "Check rules", "Why?" is "Explanation",
  "Hint" is "Show a hint", "Show me where" is "Show it on screen", "Open" on a
  card is "Expand", "Go to the range" is "Start"; every sentence naming one of
  them follows. The left rail is "the left menu", the strip "the status bar at
  the top".
- Red team stages: the Korean for `stage.maintain-presence` and
  `stage.complete-mission` now reads as keeping access and reaching the
  objective; en keeps Mandiant's "Maintain presence" and "Complete mission".
- The brand (`common.brand`) is unchanged for now; the user renames it later.

Counts: 194 keys changed (345 en and ko values), 2 deleted
(`session.blue.blurb`, `session.red.blurb`, with their two `<p>` and the two
lines that filled them in `session.html`), 18 added (`case.<id>` labels for
every case in `redteam/cases/` that had none). The session page's activity
list and case table and the red console's case list now show the label (the
red console keeps the id under it, since the operator's commands carry it);
the debrief and lesson rows already looked labels up. The do-for-me strings
(`lesson.do`, `result.helped.do`) and the coach's not-found fallback are left
as they were; another branch removes the feature. Outside the table: the
English learner maps' zone caption "Application estate" is "Services" (the
Korean pair already said services segment), the two `scenario.yaml`
descriptions match the new en wargame descriptions, and README, ARCHITECTURE
(en and ko) and OPENSTACK quote the new titles and buttons.

Two errors found in the review and fixed with it: F1's hint and withheld
answer said to leave out `attacker` and `customers` on the internet switch,
but the map's node is `kali`; and `lesson.kali.where` sent the learner to Red
at the top right, where it sits only in the phone layout; on a desktop the
link is at the bottom of the left menu. The withheld answer for F1's map step
had become the same sentence as the step's coach text, which
`test_strings.py` refuses (an answer must not ship in the page); it now names
the button ("Press the Map button in the left menu"). One console test
expected a missed case named by its id; it now expects the label.

**Proven live 2026-10-17** (OpenStack, platform VM 192.168.0.210). HEAD
321f0c0 deployed by `bin/cloud up --replace --sideload` (platform image built
on the VM from it, kali from 1fd5be3, gns3 from 1efa522) in 9 min 33 s;
`bin/verify` there: unit 1474 passed; acceptance 70 passed, 0 failed, 0
errors, 0 skipped in 1009 s. A headless sweep (Playwright, Chromium, ko and
en) of the home page and catalogue, the session page, every blue pane, the
red console, every step of F1-F6 and the coach steps of 1.1 and 3.1 found
three faults, fixed: while both slots reset, the home page listed the
readiness API's English operator reason ("the range is resetting ...") in
the Korean console too; it now shows `range.resetting` (75ef719). nginx
still logged `[warn]` temporary-file buffering for Kibana, the terminals and
the website, since `proxy_max_temp_file_size 0` was set on the API location
only; it is set for every location, with a 1 MB request body buffer
(a55dc74). The Map pane's GNS3 web UI loaded Google Analytics on a first
visit and sent its beacons from the learner's browser; the read-only sign-in
page sets the web UI's `statistics_command` to `false`, and its titles say
Map, not Network map (9674d0e, the gns3 image rebuilt). Redeployed 9674d0e
(platform and gns3 images from it, kali from 1fd5be3) in 9 min 26 s;
`bin/verify`: unit 1476 passed; acceptance 70 passed, 0 failed, 0 errors, 0
skipped in 987 s; ratchet holds (core_loc 580, tests 1057). The sweep again:
72 of 72 step views boxed; Skip on six steps offered as the Skip button (`lesson.skip`), recorded
skipped and not passed, the coach on the next step, 6 of 6; no learner-visible
text (page text, titles, placeholders, labels; 4 briefings, 72 step views, 16
page views) holds the retired Korean words for range (the loanword and the
native word), rail, map, topology, "do it for me" and "why?", their
English or the deleted blurbs, the brand aside; the page's string table
matches the 191 shipped keys of the approved review table except the Korean
`main.title` (kept by the merge), the two stage names without the review's
"[check]" marks, and `common.brand` (unchanged by this ruling); the console
shows only the third-party messages of "Errors swept before the push" and the
WAF's 403 to the learner's own probes; the platform log holds no ERROR,
Traceback or `[warn]`, only the expected 409, 400 and 404. The gns3 log held
1,397 `Invalid token` errors, every one a WebSocket with `token=null` from a
Firefox on the operator's machine holding a Map page opened before the
redeploy; none came from the sweep's sessions (777-840, all closed).

## 2026-10-17 — Korean-first learner text and docs

- **Ruling** (the user, 2026-10-17): the Korean is written Korean-first, from
  the meaning, not translated from the English sentence, and in the usage of
  Korean security practitioners and educators. Where practitioners and the
  norms of the National Institute of Korean Language or published lists of translation-sounding patterns
  disagree, practitioners win; those norms and lists were not consulted. The
  English stays canonical for what a document or string says; the Korean
  decides how it is said.
- **The style guide** (a working file, not in the repo, like the test
  audit's tables) was built from pages fetched on 2026-10-17: Dreamhack and
  Theori (public Path and Unit pages, the Unit API, 175 wargame
  descriptions; lectures and quizzes need a login), Igloo, AhnLab ASEC and
  the TrusGuard IPS manual, ESTsecurity, AWS Korea's WAF false-positive
  guide, Penta Security, Monitorapp, KISA, Logpresso's Sonar manual and the
  Elastic Korean guidebook; an addendum added open Korean teaching sources
  (Life Coding, BoB course material on GitLab, HSPACE's blog, dictionary and lab
  READMEs, Kakao Cloud tutorials, Programmers, KERT and other club repos),
  with translations (MDN, the OWASP Top 10, Juice Shop, Google Cloud) marked
  and weighted lower. SK Shieldus, NAVER Cloud, WikiDocs and Cloudflare
  answered 403 and are not used; personal posts without a track record were
  rejected. Its main choices, with the counts behind them:
  - Register: the formal polite ending for explanations and notices; the
    polite imperative for a step the learner performs, purpose first ("to do
    X, do Y"); the "try ..." imperative for hints; no formal imperative, no
    formal question ending, no second-person pronoun "you" (Dreamhack's 175
    descriptions: formal polite endings 98 and 92, polite imperatives 40 and
    31, the informal polite register about 20; the formal question ending and
    the pronoun appear only in two community challenges and in translations).
    Questions end in the polite question form, "what is ...?" or the quiz
    form "X is/are?"; feedback is "correct" / "wrong" with one reason.
  - Titles end in a noun or the "-ing" noun form, never a sentence ending.
  - Requests are described as flowing in, occurring, blocked, allowed or
    matched; never as "reaching" (0 hits for a request, packet or traffic
    reaching).
  - Terms (`docs/vocabulary.md` has each row): false positive (75; the longer
    "false detection" form 0), false negative and true positive; detection
    (700; the alternative word 3); alert (92) for what reaches the analyst;
    threshold (11; the alternative word 0); signature (141); web firewall as
    one word (34 against spaced 8); source/destination IP (88/82; the
    loanword "source IP" 0); exception handling and exception rule (the word
    "suppression" 0, "whitelist" 0); "true/false positive judgment" for
    triage; severity as "risk level" (39; "severity" 5); "mock hacking" for
    penetration testing (54; the loanword for "penetration test" 0); status
    code (14 against the unspaced spelling 1 in the addendum's corpus,
    reversing the first pass); HTTP method (58; the loanword 6); shell and
    web shell in the loanword spelling (32 against the other spelling 4,
    Dreamhack's noted); the loanword for "rule" in prose and the formal word
    on product screens, "rule ID" for a sid; "training ground" / "training
    environment" for a cyber range (the loanword "range" 0).
- **Vocabulary** (`docs/vocabulary.md`; each row holds the old and the new
  Korean term): changed rows are cyber range, penetration test, initial
  access, severity and its levels, suppression (the action and the object),
  triage, correlation, enable and disable a rule, solved, externally exposed,
  IP range, time range, auto-refresh, web firewall (now one word),
  information asset (now one word), and rule id (sid), newly settled.
- **The string table** (6e3a2f0): all 951 Korean values (893 shown, 58
  withheld answers and pass lines) were read; 532 Korean values were
  rewritten from the meaning, and 183 English values changed to say the same
  thing. The practice network shown to learners is the "practice network"
  wording of `range.healthy` and `session.close.rebuilds`, the Map pane
  `blue.pane.topology`; the Korean GNS3 pair names its zones service,
  monitoring and internal-database network (drawing text only, in
  `deploy/topology/range-*.ko.gns3`).
- **Reviewer pass** (16e951d): a second reader went through the 951 values
  against the guide and changed 62 (61 Korean, 1 English): steps the learner
  acts on became the polite imperative instead of narration, hints and
  nudges the "try ..." form; multi-word button names are quoted where the
  bare name misparses (the Run in terminal, Start final check and Check run
  result buttons); the "my run" calques went; two meanings that had drifted
  were restored (`score.primary.how`, `score.customers_note`); "record"
  became "log" where a sensor's log is meant; F1 asks for the one "received
  first" everywhere. F2's title promised following the path, which no step
  asks for: it is now "Sending a web request and reading its status code" in
  both languages. No answer key, check fact or placeholder changed.
- **Docs sweep** (the user: every document, no exceptions):
  English, each checked against the code by grep, not memory:
  `README.md`, `docs/ARCHITECTURE.md`, `docs/OPENSTACK.md`,
  `docs/THREAT-MODEL.md`, `docs/STATE.md`, `docs/state/now.md`,
  `test/README.md`, `CLAUDE.md`, `.claude/skills/orchestrate/reference.md`
  (`SKILL.md` was current) and the 2026-10-13 scenario-course spec. Kinds of
  staleness fixed: ports and the platform VM's security group (8002 and 3080
  open beside 8000 and ssh); the control plane and image list (`gns3`, seven
  images); commands and flags (`redteam/run.py` has no `--target`, it takes
  `--platform` and `--tool-target`; `bin/platform-rebuild --sideload` and the
  `--force-recreate` after it; `bin/backup --keep` and `backups.keep`;
  `bin/verify --changed`, `--live`, `--fast`, and the hand-made `.venv` on the
  VM); the acceptance split (the solo phase) and skips (70 collected, none
  skipped by substrate); retention, `VACUUM INTO` and IMMEDIATE transactions
  described where the store is; the errors-swept mechanisms (nginx started
  after waitress with `proxy_max_temp_file_size 0` everywhere, Kibana
  bring-up waiting on `/api/status`, the gns3 image's `docker-cli` and its
  copilot skills off, publishing deleting only a listed project, the estate
  sensor's `default` af-packet entry, OPNsense's model defaults); the Map
  pane (its name, no usage statistics) and the blue panes (developer tools,
  Alerts, IDS rules); F1's answers named as the map names them (`firewall`,
  `waf`, `log-server`, `sw1`, `sw2`); F2's and F5's steps and titles; quoted
  labels taken from the string table ("Start final check", "Show a hint",
  "Show the new hint", "Start the same lesson again", "Caught ..."); the
  console's four screens, not five; ModSecurity blocking, not detection-only
  (`SecRuleEngine On`), and the defender's WAF settings and shell in the
  threat model; `tests` reported, not gated, and "floor" gone outside dated
  history; done backlog items checked off (test audit, `test/` on OpenStack);
  CLAUDE.md names both `.ko.gns3` files and says Korean is written
  Korean-first; the skill's seam list gains `rules/crs.py`, `kibana.py` and
  `gns3.py`; one Korean word in `docs/ARCHITECTURE.md` removed.
  Korean: `README.ko.md` and `docs/ARCHITECTURE.ko.md`, the only `.ko.md`
  files, rewritten in full from the updated English, section for section, in
  the formal polite register (both were in the plain declarative register
  and had fallen behind: 263 and 1,461 lines against 562 and 1,840), with the
  guide's terms, labels quoted from the string table's ko values, and no use
  of the loanword for range.
- **"Lesson", not "unit"** (the user, 2026-10-18): a foundation unit is called
  a lesson (the loanword) in every Korean place. The string table's last
  seven occurrences of the native word for "unit" (the foundations group note
  and the six `lesson.<id>.verify` lines) became the loanword for lesson,
  which the rest of the table already used (the lesson note, `lesson.done`);
  answers and placeholders unchanged. `docs/vocabulary.md` gains the row
  lesson / unit, and its `shell` row takes the guide's settled spelling (the
  other spelling noted as
  Dreamhack's form). `bin/verify --changed`: unit 817 passed, ratchet holds.
- **Proven live 2026-10-18** (OpenStack, platform VM 192.168.0.210). HEAD
  1fc2bc8 deployed by `bin/cloud up --replace --sideload` (platform image
  built from it; gns3 from 9674d0e, whose `deploy/gns3` is the same; kali
  from 1fd5be3) in 9 min 14 s. The Korean map captions need no gns3 image:
  the platform reads `deploy/topology/*.ko.gns3` from its `/src` mount and
  imports them into GNS3 when a session's map is published
  (`api/maps.py`). `bin/verify --changed 9674d0e`: unit 817 passed, ratchet
  holds. `bin/select-tests` named all 32 acceptance files only because no
  acceptance test names the two `.ko.gns3` files; their change is drawing
  text, so no acceptance ran and the sweep checked the map instead. A
  headless sweep (Playwright, Chromium, 1440x900, ko and en) of the home
  page, catalogue, session page, every blue pane, the red console, every
  step of F1-F6, scenarios 1.1 and 3.1 and the 2.1 briefing, which also
  measured every text node against its clipping box, the viewport and
  `text-overflow`, found two faults, fixed in 6b72876: the coach popover
  broke Korean words mid-word (three examples, one of them the developer tools label, `site.dev.toggle`), so the
  console sets `word-break: keep-all` for Korean, with `overflow-wrap:
  break-word` for a word longer than its box; and the red console's case
  list cut both sqlmap variants' labels to the same prefix in both languages,
  so the label wraps (the id, command and path lines keep their ellipsis,
  the summary is the row's title). `bin/verify --fast`: unit 1476 passed.
  Redeployed 6b72876 the same way in 9 min 19 s and swept again: 72 of 72
  step views boxed, 12 of 12 pane steps boxed with the Map open; Skip on
  six steps offered as the Skip button (`lesson.skip`), recorded skipped and not passed, the coach
  on the next step, 6 of 6; no clipped or cut text except those deliberate
  ellipses; no learner-visible text (page text, titles, placeholders,
  labels; 6 briefings, 72 step views, 16 page views) holds the retired Korean
  words for range and unit, "why?", "do it for me" or the other words of the
  previous sweep; the Map pane draws the Internet, the service network
  10.30.0.0/24, the internal database network 172.18.0.0/16 and the
  monitoring network (their Korean captions) with
  no text overlapping another (English likewise); the console shows only
  the third-party messages of "Errors swept before the push", the WAF's 403
  to the learner's own probes and two requests aborted by a pane switch; the
  platform log holds no ERROR, Traceback or `[warn]`, only 409 (a session
  opened while a slot reset) and the site proxy's 403.

## 2026-10-18 — Foundations run back to back in one session; Kali steps move on by themselves

- **Ruling** (the user, 2026-10-18): F1 to F6 run in one session, one after
  another, without closing; the next lesson starts by itself when the last
  step of the previous one passes. A Kali step moves on after its pass like
  every other step, as long as nothing the learner needs disappears. Scenarios
  stay one per session.
- **Before.** A foundation's last step showed "Lesson complete." and nothing
  else; F1 to F2 meant closing the session (a slot reset, about 60 s on
  OpenStack) and opening F2 from the catalogue. A passed `kali` step waited
  for Next (3a7238d), because the step after it asks for the count its row
  shows.
- **The API.** `POST /api/sessions/<id>/lesson/ {"lesson": "f2"}` moves an
  open guided session to any foundation: the unit's declared defense is
  applied in place when it differs (the CRS tuning through `crs.apply`, as
  `PUT /waf/`; the IDS rule file only when the posture's file changes, as at
  open), `Session.lesson`, `Session.defense` and `Session.lessons` (`[{id,
  started_at}]`, migration 0027) are updated, the unit's seed cases are
  replayed as an open does, and the answer is the session detail with
  `lessons` and `next_lesson`. 409 for a closed, scenario or unguided session,
  400 for an id that is not a foundation (the open's own refusal of an unknown
  `lesson` is a 400 too). Any foundation is accepted; the console offers only
  the next by `order`.
- **Per lesson.** Step records are `lesson_steps[<lesson>][<step>]` and a
  hint is `{lesson, step, level}`: F2-F4 share the step id `search`, F5 and F6
  `sqlmap`. Migration 0027 moves each session's records under its lesson,
  names the lesson in its step hints (a scenario's own hints keep their
  shape) and writes the first `lessons` entry of a foundation session.
- **Windows.** A unit judges only what happened since it started: `sent`
  checks count Website pane requests made after it, the `rule` answer
  ModSecurity records after it, a `kali` check reads the sensor from the later
  of the step's reach and the unit's start, `of: lost` counts objectives
  achieved after it, and the steps' Kibana links open from it. The first unit
  of a session keeps the session-wide windows.
- **Why no reset.** The board is `loot_verified`: an objective is lost when
  submitted loot matches the accounts snapshot taken at open, and nothing a
  foundation does changes those accounts (sqlmap reads them). The baseline
  taken at open stays the ground truth for F6. The only posture change is F6's
  `missed`, applied in place on the open WAF; F1-F5 all run `full`, so F1-F5
  change nothing on the range.
- **The console.** On a foundation's last step pass (or Skip, the ladder's last
  rung) the coach says "Lesson complete. Next lesson: <title>" (ko: `lesson.next.ready`)
  with a "Next lesson" button (`lesson.next.start`),
  and 2 s later posts the switch and reloads the page into the next unit,
  which lands on its Theory card as a first open does (the landing and step
  keys are per lesson). After F6: "All foundation lessons complete." (`lesson.course.done`),
  then ingest, `POST /close/`, and the session page.
  The last step follows the long-pass rule of every other step: when its pass
  line is longer than `SHORT_PASS_CHARS` (F3's `count`, F5's `still`), the
  lesson does not move on by itself; the status says to press Next and the
  learner presses "Next lesson", which is disabled while "Preparing the next
  lesson…" shows (live review round 9).
- **Kali steps.** The 1.2 s pass pause applies to `kali` too; the step after a
  Kali step shows that step's row (requests per sensor, the Kibana link),
  re-read by a poll of the Kali check after a reload. 3a7238d's
  keep-until-Next is removed; 470b1bb's re-placement of the popover when a row
  is drawn stays, since the row now makes the next step's popover taller.
  Reaching a Kali step (F5's sqlmap steps, F6's `dump` and `replay`) writes
  the marker to the stamp proxy over ssh before the reply, about 1.9 s live
  against 0.1 s for other steps, and the command text comes only in that
  reply, so F6 `replay` showed no command for about 2 s (live review round
  10). The write stays ahead of the reply, so no request typed from the shown
  command goes out unlabelled. Each step instead says `has_command`, and the
  card shows "Preparing the command…" with a disabled Copy until the reply
  brings the text; a failed reply says so in the card.
- `bin/verify --changed`: unit 821 passed; `--fast` 1483 passed; ratchet
  holds (core_loc 580; tests 1057 -> 1063, reported). `bin/select-tests`
  named all 32 acceptance files (no acceptance test names the changed
  files); the one that exercises foundations is `test/test_lesson.py`.
- **Run in terminal, two faults the live run found.** 2ea48a5 removed
  `runCommand` with Do it for me but left the button's listener, so "Run in
  terminal" (F6's first step) threw a ReferenceError and did nothing
  (c7a69c5 restores it; its two lines no longer speak of nginx's 'test is
  successful' or of the platform applying an exception). On OpenStack the
  WAF pane is an ssh login (`vm-terminal.sh fsl-waf`) whose prompt comes
  about 10 s after ttyd's `term`; the command pasted at once was lost
  (26c1c80: the console waits up to 30 s for a last line ending in `$` or
  `#`, then pastes). Unit tests: 1063 -> 1065.
- **Proven live 2026-10-18** (OpenStack, platform VM 192.168.0.210; kali
  image 1fd5be3, gns3 9674d0e, platform built from each commit). a9bab72
  deployed by `bin/cloud up --replace --sideload` in 9 min 12 s; migration
  0027 ran on the restored store (session 866's F1 records moved under
  `f1`, its `lessons` written). Headless Playwright (Chromium, 1600x1000,
  Korean), F1 started from the catalogue. Sessions 867-869 found walker
  faults (it answered before the coach had moved on) and the dead Run
  button; c7a69c5 deployed in 9 min 16 s; session 870 ran F1-F6 in one
  session (a walker restart in F6, no close) and found the lost paste;
  26c1c80 deployed in 9 min 45 s. Session 871, one browser, no restart:
  opened 17:59:26 UTC, closed by the console after F6 at 18:04:39, 5 min
  13 s; 27 of 27 steps passed, no wrong answer, hint or skip; per lesson F1
  14 s, F2 13 s, F3 17 s, F4 44 s, F5 65 s, F6 110 s; each next lesson
  started 6.5-9.4 s after the previous one's last answer (the switch, its
  seed replay, the reload), on its Theory card. F5's Kali step moved on by
  itself and the requests step showed the requests line "1539 requests (fsl-edge 1539)" in Korean, answered
  1539. F6's switch applied `missed` in place: the WAF file Run in terminal
  printed held `ruleRemoveById=949110` and `959100`, sqlmap dumped admin,
  jiwoo and minseo, and loot, leaked (3) and lost (3) passed; the session
  page shows 3/3 lost. `/api/range/ready/` every 5 s: slot 1 IN_USE from
  open to close and READY after it, no reset in between; the platform log
  holds no 500 or ERROR. `bin/select-tests` named all 32 acceptance files,
  so only `test/test_lesson.py` (the foundations' module) ran on the VM: 1
  passed in 88 s. Every session the runs opened (867-871) is closed.

## 2026-10-18 — The red console is Kali and a browser; the blue console carries Kali for practice

- **Rulings** (the user, 2026-10-18):
  1. The red console offers no prepared attacks: every case runner is
     removed from the UI (the case list, Run all, the per-case run buttons,
     the recording and route controls). The red console is the Kali terminal
     and a browser (the Website pane the blue console already has, pointed at
     the target, with its address bar and developer tools), plus the session
     header and the loot submission. The attack and benign cases, the harness
     and the API endpoints the acceptance tests, `redteam/run.py` and the
     scenario engine's automated attacker use stay.
  2. The blue console's left menu gets a divider and, below it, a Kali
     terminal pane (the same Kali terminal the red console uses). In lessons
     and free practice the learner uses this one console for both sides;
     there is no Kali-only view in lessons. In the real wargame (person
     against person) the red player uses the red console and the blue player
     the blue console.
  3. No `fsl-` name the learner sees in the terminals or the UI (prompts,
     banners, `fsl-edge` in lesson rows, `fsl-<id>-waf`), without renaming
     the hosts or containers (that rename stays deferred, `docs/STATE.md`);
     no "REMOTE HOST IDENTIFICATION HAS CHANGED" warning in the WAF terminal
     after a rebuild, without weakening host-key checking for anything
     outside the range.
  4. P0: check whether the board's `/internal/auth-users` (every username and
     password hash) is reachable from Kali or the Website pane; block it at
     the right layer if it is.
  5. The course is integrated attack and defence lessons, then free practice
     (scenarios 1.1-4.1 with the automated attacker), then the wargame,
     person against person. The lesson redesign is pending approval.
- **Removed from the red console** (`red.html`): the case list (15 cases,
  attacks and benign, with each one's last run and objective), Run all,
  Attacks only, the per-case run button, the source-network picker, the box
  addresses (target, proxy source, direct), the recording window (name,
  route, attack checkbox, start/stop) and its status line, the run log, the
  "covers these stages" line, and the clearing of a stale proxy label on load
  (only the window set one). 54 string keys in each language went with them
  (`red.cases*`, `red.baseline.*`, `red.box.*`, `red.window.*`, `red.log.*`,
  `red.case.*`, `red.covers*`, `red.origin.*`, `stage.*`, `blue.nav.to_red`,
  `session.tile.cases`, `session.tile.case_count`). Three learner lines
  that named the red console now name the Kali pane; the score's
  no-benign warning no longer says to press Run all.
- **Kept, and why.** No endpoint is removed: each one the red console called
  is used elsewhere. `/api/origins/` and `/api/attacker/origin/` by
  `test/shared_sessions.py` and `test/conftest.py`; `/api/attacker/label/`
  by `test/conftest.py`, `test/shared_sessions.py` and
  `test/test_strategy_comparison.py`; `/api/sessions/<id>/attacks/` by
  `test/` (`test_lesson`, `test_suppression`, `test_concurrent_sessions`,
  `test_indiscriminate_defence`, `shared_sessions`), and the scenario engine
  fires through the same `views._fire`; `/api/sessions/<id>/cases/` by
  `redteam/harness.py`, the session page and the acceptance tests;
  `/api/wargames/<id>/cases/` by the unit tests (`test_board_wargame`,
  `test_api_redteam`, `test_lifecycle`, `test_session_close`), and it is the
  case catalogue an API client fires from; `GET /api/attacker/` by
  `platform/tests/test_origins.py`. `redteam/cases/` (attack and benign) and
  the harness are unchanged.
- **The red console now**: the session and wargame name, the objective
  chips, "Submit stolen hashes" (shown for `loot_verified`), and a rail with
  Kali (the session's `kali_terminal`) and Website (the blue console's
  `blue_site_script.html`, `blue_dev.html` and `blue_dev_script.html`). It
  still checks the objectives every 10 s (`POST /objectives/`).
- **The Kali pane in the blue console.** Below a divider in the rail, in its
  own iframe loaded once, so a running sqlmap survives a switch to Kibana. It
  shows when the session's `kind` is `lesson` or `scenario` and is hidden
  when it is `wargame`. How that was decided: `kind` is the one field that
  types a session (`_described`: `scenario` when `course_scenario` is set,
  `lesson` when `guidance` is set, otherwise `wargame`); a wargame session
  is the one opened without guidance from the home card's "Start wargame",
  the shape a person-against-person game takes (4.2, `red: person`). The
  defender there must not hold the attacker's shell. The Red link at the
  bottom of the rail is gone (in practice it is replaced by the pane; in a
  wargame it would hand the defender the shell), and the session page shows
  the red console card only for a wargame. F5's and F6's `sqlmap` steps now
  open the Kali pane (`point: {pane: true, opens: kali}`, "Open Kali in the
  left menu."). `GET /api/sessions/<id>/` names `kali_terminal` (the URL the
  red console used to read from `GET /api/attacker/`).
- **`fsl-` names.** `waf_box` is `waf` (was `fsl-<id>-waf`, the WAF
  banner). The Kali step's requests row names each sensor by its map name
  (`maps.learner(...).shown`: `firewall`, not `fsl-edge`). On OpenStack
  `vm-terminal.sh` runs `bash --rcfile <(...) -i` over `ssh -t`: the rc file
  reads `/etc/profile` and `~/.profile` (Kali's proxy variables,
  `FSL_TARGET` and the command log as at a login; checked live: the command
  reached `commands.log`), replaces `\h` in the prompt with the host name
  without `fsl-` (`ubuntu@kali`, `ubuntu@waf`) and prints `/etc/motd`; with
  a command sshd prints no Ubuntu banner or last-login line. Kali's motd
  ("FSL red team box", the red window) is rewritten. Compose's prompts were
  never `fsl-` (the container id), and its Kali shows the same motd.
- **Host keys.** `vm-terminal.sh` had `StrictHostKeyChecking=no`, which still
  printed the changed-key warning after every reset's rebuild. It now uses
  `HostKeyAlias=fsl-<server id>-<launch time>`, the alias the platform's
  runner already pins each server under (`OpenStack.host_key_alias`), with
  `accept-new`: a rebuilt server is a new alias, its key is learnt silently,
  and a changed key under a known alias is refused. Nothing outside the
  range's terminals changes.
- **P0, `/internal/auth-users`: not reachable; nothing to block.** Read-only,
  2026-10-18 on the live range (slot 1, before the deploy), from Kali through
  the platform's runner, with and without Kali's proxy, `curl --path-as-is`:
  `http://board.com` with `/internal/auth-users`, `//internal/auth-users`,
  `/internal%2fauth-users`, `/%69nternal/auth-users`,
  `/internal/./auth-users`, `/x/../internal/auth-users`,
  `/INTERNAL/auth-users`, `/internal/auth-users/`, `?x=1` and `;x`: 404 every
  time, and `Host: not-board` to the WAF's address 404; every other range
  address Kali knows (the edge's 30 origin gateways, estate and mgmt, the
  WAF's estate 80 aside, the wargame host's estate and mgmt, the platform's
  mgmt) on 8000 and 80: no connection (`000`), the WAF's estate 80 the WAF's
  own 404. Through the Website pane's proxy (`:8002/site/874/<host>/...`,
  hosts `board.com`, `board` and `10.30.0.63`, the same path variants): 404
  from the WAF (`Via: waitress`, the WAF's `nginx` 404 page); the proxy
  always sends to the session's WAF whatever host is named. The layers that
  hold: the WAF's `location /internal/ { return 404; }` in both `server`
  blocks (`deploy/waf/range.conf`, nginx normalises the path before matching)
  and the `fsl-mgmt` security group (2026-10-12). The tests that hold them
  already exist: `platform/tests/test_internal_blocked_at_waf.py`,
  `test/test_board_exfil.py` (two cases from Kali) and
  `test/test_attacker_reach.py` (folded into `test/test_range_isolation.py`
  on 2026-11-15); no test added. The board answers
  `/internal/auth-users` with no authentication of its own (`docs/STATE.md`
  backlog), so the WAF rule and the security group are the only guards.
- **Open.** In a wargame both players' Website panes share the session's site
  log and marker: the defender's Network panel lists the attacker's
  requests, and the attacker's requests through the pane are left out of
  `/score/` like browsing. Neither matters until 4.2 is built.
- **The coach beside the rail.** The first live look found the coach's
  popover, pointing at a rail button ("Open Kali in the left menu"), placed
  below the button and covering the rail's other buttons, Kali among them
  (the rail is longer now). A rail target on a vertical rail now takes the
  spot to its right first (51b28dd).
- `bin/verify --changed`: unit 1488 passed; ratchet holds (core_loc 580,
  product_loc 24361 -> 23996, tests 1065 -> 1066, reported).
  `bin/select-tests` named all 32 acceptance files (`views.py`,
  `openstack.py`, `vm-terminal.sh`, `scenario.yaml` are range-facing and no
  test names them), so the terminal- and Kali-related modules ran on the VM:
  `test_lesson`, `test_board_exfil`, `test_attacker_reach`,
  `test_operator_log`, `test_attacker_box`: 10 passed, 0 failed, 0 skipped in
  199 s.
- **Proven live 2026-10-18** (OpenStack, platform VM 192.168.0.210). 0a90806
  deployed by `bin/cloud up --replace --sideload` (platform and kali images
  built on the VM from it, gns3 from 9674d0e) in 24 min 56 s, most of it
  waiting for two sessions left open (874, 877, closed by hand) and the
  `fsl-kali` range image rebuilt for the new motd; 51b28dd (the coach fix)
  in 5 min 58 s. Before the deploy, the new `vm-terminal.sh` was run by hand
  inside the old platform container against slot 1: `ubuntu@waf:~$` and
  `ubuntu@kali:~$`, no host-key warning, `http_proxy`, `FSL_TARGET` and
  `PROMPT_COMMAND=_fsl_record` set, the typed command in `commands.log`.
  Headless Playwright, Korean, 1600x1000 and 390x844, sessions 880 (F5) and
  881 (wargame): the red console shows the objectives, "Submit stolen hashes" (`red.loot.heading`),
  Kali (the new motd, `ubuntu@kali:~$`) and Website (board.com, developer
  tools), nothing else; the blue console of the wargame has no Kali and no
  divider; its WAF pane reads `waf · ` plus the CRS settings label (`blue.waf.rules`) and the values, and `ubuntu@waf:~$`; the
  F5 blue console has the divider and Kali, the sqlmap step points at Kali
  with the popover to its right, and the terminal's text is the same after a
  switch to Kibana and back (the frame is kept); the session page of the
  lesson shows only the blue card. No page error. The P0 probe again after
  the deploy (slot 2, session 886): the same 404s from Kali, with and without
  the proxy, and through the Website pane's proxy; every other address `000`.
  Every session the runs opened (878-881, 886, and the acceptance run's) is
  closed.

## 2026-10-18 — Foundations rebuilt as integrated attack and defence lessons

- **Rulings** (the user, 2026-10-18, on the instructor, purple-team and UX
  reviews of F1-F6):
  1. A highlight points at the one element that holds the value to read,
     never at a whole pane; the note and its callout never cover it.
  2. Every search is typed in the board's own search box; the address bar
     only where the step says so (F2's missing post, F5's `)`).
  3. The developer tools look and read like Chrome's Network panel; no "WAF
     blocked" badge.
  4. Nothing internal reaches the learner: `fsl-`, `_index`, slot, the
     `X-FSL-Case` header, markers, case ids.
  5. No answer-giving chips or buttons: the learner writes the KQL; no
     answer in a theory card, a button label or the previous step's pass
     line.
  6. Every lesson's last step is solo: no highlight, no hint, only Skip.
  7. Help is a ladder per step: nudge, then hint, then Skip. Foundations
     have no answer rung.
  8. The learner types every attack and every WAF command; no prepared
     attack button, no "Run in terminal".
  9. Each lesson opens on the pane its first step uses.
  10. The units are called lessons in Korean too; Korean-first practitioner wording
      (`ko-style-guide`), plain titles.
  11. Kept: lessons back to back in one session; two scores, the target
      decides, benign cases stay.
- **Lead decisions on the spec's open points.** No step runs on one
  substrate only: F3 reads the two legs of one search by their destination
  (the request arriving at `waf`, and the one `waf` sends on to
  `board.com`, nginx's upstream), which both ranges record (docker's one
  Suricata in the WAF's namespace sees both legs; on OpenStack the edge
  sensor sees the first and the estate sensor the second). The `fsl-` host
  rename stays deferred (`docs/STATE.md` backlog 0). The red console as Kali
  and a browser, and the blue console's Kali pane, were built the same day
  (the entry above). Lessons stay in one session.
- **The lessons** (`wargames/board/scenario.yaml`; text ids `lesson.map`,
  `lesson.http`, `lesson.logs`, `lesson.xss`, `lesson.sqli`, `lesson.miss`;
  every one seeds `board-normal-search`):

  | Lesson | Defense, opens on | Steps | The learner |
  |---|---|---|---|
  | F1 Reading the network map | `full`, Map | 6 | reads board.com's Services address from its link label, board-db's subnet from its zone caption, the name of kali's network, picks in order the hosts a customer's search passes (`customers > firewall > waf > board.com` on OpenStack, `customers > waf > board.com` on docker), names the host that collects the logs; solo: board-db's address |
  | F2 Reading HTTP requests in DevTools | `full`, Website | 7 | searches with the search box; reads method, parameter, path and status in the Network panel, the parameter behind the board's new sort control; solo: the status of a post that does not exist (404) |
  | F3 Finding your requests in Kibana | `full`, Website | 7 | searches a word of letters and digits, writes KQL for it; the source IP of the event arriving at board.com (waf's address), the map host that uses it, the source IP of the same search arriving at waf (a customers address), its X-Forwarded-For; whether the WAF logged the search (no); solo: how many of their searches arrived at waf |
  | F4 Blocking an XSS request and writing an IDS rule | `xss-gap`, Website | 11 | `<script>alert(1)</script>`: 403, one 941 rule, Total Score 20; the mixed-case probe: 403 too; no IDS alert for either; writes a rule for `<script` in the URI, reads its sid from its alert, sees the mixed case slip past, adds `nocase`; solo: replays the mixed case (alerts) and an ordinary search (2xx, no alert) |
  | F5 Analysing SQL injection on the sort parameter | `full`, Website | 9 | reads the sort value; `?sort=...)`: 500, no WAF rule detected it; types sqlmap in the Kali pane, reads its verdict (not injectable), the run's source IP and 913100, the rule that named the scanner; reruns with `--random-agent`; solo: one rule that still blocked it |
  | F6 Finding the attack an over-broad exception let through | `overbroad`, WAF | 8 | greps the exclusion file for the parameter left out (`sort`); dumps the accounts with sqlmap and pastes the table; no alert from either engine; the attack's source in the edge's http events; the penalty total in the objectives card (22 = 2 x (2 + 4 + 5) when all three are lost undetected); deletes the exception and reloads nginx; solo: replays the dump (blocked, no loot) and sorts once (2xx, not logged) |

- **What the range showed before the build** (confirm-on-range, OpenStack
  slot 1, session 887, platform 51b28dd), and what changed for it:

  | Item | Found | Changed |
  |---|---|---|
  | Website pane at the sensors (CR-3, CR-6) | the pane went platform -> WAF `mgmt` address: no edge event, the WAF's X-Forwarded-For the platform's `mgmt` address (not on the map), no Suricata event for a blocked probe | the pane leaves from the customers side (PC-2); F3 and F4 depend on it |
  | `http.uri; content:"<script"` (CR-6) | matches the browser's `%3Cscript%3E`, misses `%3CScRiPt%3E`, `nocase` fixes it | none; F4 as designed |
  | XSS at PL1 (CR-5) | 941100, 941110, 941160, 941390, 949110; Total Score 20 for both cases | F4 accepts any of the four 941 ids; the score is 20 (four rules x 5) |
  | `?sort=title)` (CR-7) | 500, and ModSecurity writes a record for it (5xx is a relevant status) with an empty `messages` list | F5 asks whether a WAF rule detected it (`waf_detected`), not whether it is in the WAF log; a record with no `messages` is not a detection (ingest already drops it) |
  | sqlmap on `sort` (CR-8, CR-9) | 913100 in every default-UA record, absent with `--random-agent`, 942xxx still block; sqlmap's `<host>/log` empty when nothing is injectable | none; `sqlmap_found` reads that log, and F5's commands add `--flush-session` (a second run answers from sqlmap's cache otherwise) |
  | Over-broad exclusion (CR-10) | `ruleRemoveTargetByTag=attack-sqli;ARGS:sort` alone: the dump is blocked by 933160 (`attack-injection-php`); `OWASP_CRS;ARGS:sort` dumps all 3 accounts; sqlmap's WAF-detection probe trips 9000003, 9000004 and one CRS rule | `overbroad` excludes `OWASP_CRS` on `ARGS:sort`; F6's dump adds `--skip-waf`, or the run counts detected and the penalty is 11, not 22; F6 asks about alerts, not records (each 500 is a record with no rule) |
  | Seed replay (CR-12) | recorded once per unit with `meta.seed`, then dropped from scoring with the replays: TN 0 and "no benign" on every closed course | a benign seed counts as a benign case (TN >= 1); `no_benign` and `no_marker` are not shown in lesson sessions |
  | Learner map (CR-13) | the monitoring network has no address or subnet on the map | F1's `log_ip` became `log_host`: the host's name (management addresses stay off the map) |
  | Stamp proxy (CR-11) | every request typed in the Kali pane carried the label; alert events carry no headers (correlated through the http event) | none; no address-and-time fallback |
  | Kibana DOM (CR-4) | Kibana 8.15.0, not 8.8; flyout rows `tableDocViewRow-<field>-value`, virtualised | the `kibana` locators use the flyout's field filter to bring a row into view |
  | WAF terminal (CR-14) | `nano`, NOPASSWD `sudo`; reload `sudo nginx -t && sudo systemctl reload nginx` | F6's edit step is `{sudo}nano {waf_rules} && {waf_reload}` |

- **Platform changes as landed** (spec numbering):
  - PC-1 `/internal/auth-users`: no change; already 404 at the WAF (the P0
    probe in the entry above).
  - PC-2 the Website pane leaves from the customers side. On OpenStack
    `site.py` opens an ssh stdio stream to Kali (`OpenStack.opened`, new)
    running `attacker.as_customer`: a small Python bridge bound to a customers
    address, as the `fsl-users` account that Kali's origin SNAT leaves alone,
    to the WAF's estate address on port 80, so the request crosses the edge.
    On docker the platform binds its own address on the customers network
    and connects to the WAF's address there. The origin is the customers
    origin the scenario weights most. The marker stays on the wire; the stamp
    proxy now sets `X-FSL-Case` only when the request has none.
  - PC-3 highlight: the pane dimmed, a ring on the target, a one-line
    callout beside it (`<text>.callout.<step>`, `.then` for a two-phase
    point). Locators `panel`, `map` (node, link, label, zone, answered by
    `deploy/gns3/auditor.html`), `site` (the script nginx injects answers
    `fslLocate` from its parent console only), `dev` (`data-coach`),
    `kibana` (`doc`, `hits`, `query`, `sidebar`), `term` (a row of the
    xterm buffer). `point: {pane: true}` is gone.
  - PC-4 the note is a column beside the pane (340 px, 300 px at 1280 or
    less, a 44 px strip folded, a bottom panel below 1024 px): the step card
    on top, the theory card under it, the objectives card in F6, scenario
    cards and hints in the same column. A pass is said on the passed step;
    silent polls write nothing; the map refits on every open and resize.
  - PC-5 each lesson opens on its first step's pane; a step on another pane
    shows an "Open <pane>" button; every pane a step opens has
    `lesson.open.<pane>` in both languages.
  - PC-6 Kibana: `kibana.py` imports a data view per session, "Session
    logs" (`session-<pattern>`), when the session opens (`KIBANA_URL`, now in
    `compose.yaml`): the shared runtime fields plus `log_source`
    (`suricata` or `modsecurity`), `sensor` (map names: `firewall`,
    `board.com`, `waf`) and
    `request_headers` (one `Name: value` per header, `X-FSL-Case` left out);
    `sourceFilters` hide `_index`, `fsl_*`, `*X-FSL-Case*`, `log.*`,
    `message`, `agent.*`, `ecs.*`, `host*`, `input.*`, `error.*`,
    `http.request_headers*`, and `_index` leaves `metaFields`; a filter
    `log_source: exists` hides the range hosts' own syslog lines. The spec's
    ECS names `event.module` and `observer.name` were built first and found
    dead live: the index template maps both (empty) and Kibana 8.15 answered
    no hit for any query or filter on the runtime fields of the same name,
    while Elasticsearch with the same `runtime_mappings` matched; plain names
    no template maps (`log_source`, `sensor`) work. A lesson
    opens it with an empty query from the lesson's start; scenarios keep the
    alert query. Suricata `msg` lost the "FSL " prefix; every served rule
    file has a neutral header.
  - PC-7 DevTools as Chrome's Network panel: columns Name, Status, Type,
    Initiator, Size, Time; tabs Headers, Payload, Preview, Response; General
    (Request URL, Request Method, Status Code with its text, Remote Address,
    Referrer Policy), then Response and Request Headers with a raw view;
    Query String Parameters decoded, with source and URL-encoded views;
    clear, filter, Preserve log, type chips, F12 (also inside the site
    frame). The record drops the marker and rewrites `Referer`/`Origin` to
    `http://board.com/...`. Korean labels checked against Chrome's
    `ko.json`, English in Chrome's en-US casing. Not done: the side-by-side
    screenshot with real Chrome (the live review).
  - PC-8 terminals: docker prompts `kali` and `waf` too (Kali image PS1,
    `waf-terminal.sh` rc file); `~/.hushlogin` not needed (a command session
    prints no banner); reaching a Kali step writes its marker to the stamp
    proxy's `/label/active`, cleared on a lesson switch and at close, so the
    command has no `--headers`; no Run or copy button on any lesson step; the
    Kali row keeps only "Open Kibana at this run's time".
  - PC-9 session page: `per_case` rows carry `lesson`, `step` and `seed`;
    runs read "Lesson n · step m", cases by name, never by id; the course
    summary lists every lesson taken (`course` in the session detail);
    restart starts the first lesson with its defence; "about 94" gone; the
    catalogue's range controls only with `?operator`; foundations are called
    lessons in Korean too (`main.group.foundations`).
  - PC-10 postures `xss-gap` (PL1, `no-xss.rules`) and `overbroad` (PL1,
    `{tag: OWASP_CRS, target: "ARGS:sort"}`, `no-uri-sqli.rules`);
    `rules/crs.py` renders, parses and validates `tag`
    (`ctl:ruleRemoveTargetByTag`), core_loc 580 -> 584, recorded in
    `metrics.json`; `missed` removed; `lesson.fix_class` needed no change (a
    tag exclusion has a target and no path).
  - PC-11 map: the request path left to right in the four `.gns3` files,
    "IDS" beside `firewall` and `board.com` (OpenStack) and `waf` (docker);
    `topology.for_wargame` keeps a text that lies in no zone; "Loading the
    map..." until the auditor posts `fslMap: drawn`; the lone Map tab gone.
  - PC-12 board: a sort select (newest, oldest, title) on the post list
    sending `GET /?sort=`; the search button does not wrap. The board image
    is rebuilt.
  - PC-13 ladder: nudge, hint, Skip in foundations (`lesson.SKIP_OFFERED_IN_FOUNDATIONS`);
    worked scenarios keep the answer rung; `ok.<step>` sits in the withheld
    table and is served on pass; a test holds that no pass line names an
    option a later step of its lesson offers. "Do it yourself" only in F4
    and F6, ungraded.
  - PC-14 checks: kinds `waf_changed` and `replay`; `answer` with
    `form: order`, `wrong_if`, an inline `match` and `leg`; `rules` with
    `needs: nocase`; `kali` with `ua: any`. Facts: range `address`,
    `subnet`, `zone_of`, `path`, `logs`, `host_of`, `excluded_target`,
    `lost_points`; request `param_value`, `sensor_source` by leg,
    `forwarded_for`, `waf_logged`, `waf_detected`, `anomaly_total`,
    `alerted`, `alerted_sid`, `alerted_sid_present`, `hits`; Kali
    `sqlmap_found` (`attacker.sqlmap_found` reads sqlmap's log on the box),
    `kali_source`, `alerted_by`.
  - PC-15 Website pane: another host shows Chrome's "This site can't be
    reached"; reload turns into stop while loading, with a thin progress bar.
  - PC-16 case `board-sqli-orderby-sqlmap-random-agent`: the stock orderby
    case with `--random-agent` and the dump options.
- **A sideloaded wargame image reaches the range.** The new board (PC-12)
  must run on the OpenStack wargame host before it is pushed. `--sideload`
  now also writes `FSL_SIDELOADED=<names>` beside the password in
  `/opt/fsl/openstack.env`; the platform finds each wargame service whose
  image is exactly `ghcr.io/nekonic/fsl-<name>:<FSL_IMAGE_TAG>` (only
  `board`, `corp`, `corp-db` can match) and adds a generated bundle file,
  `deploy/wargame-host/loaded` (`<image> <image id> <url>`), so the image id
  is in the bundle digest and a new board is a new `fsl-wargame-host`. The
  builder pulls from GHCR as before, then fetches each image from `GET
  /api/range/images/sideloaded/<name>/` (`platform/api/sideloaded.py`,
  `docker save` on the platform; 404 unless the name is sideloaded and a
  declared wargame runs it), `docker load`s it and refuses unless the id
  matches. With nothing sideloaded for a wargame the bundle is unchanged.
  **Open:** a slot standing before the deploy keeps its old wargame host,
  since a close resets that host in place; `POST /api/range/slot/rebuild/`
  then `/configure/` brings the new one (`docs/OPENSTACK.md` §5.3). Making
  the reset Nova-rebuild a wargame host booted from an image other than the
  ready one is range logic in `openstack.py`, not done.
- **Removed.** Facts `entry`, `segment`, `lost`, `excluded`,
  `status_class`, `engine`, `waf_source`, `stopped_at`, `requests`,
  `leaked`, with `COUNT_TOLERANCE` and `lesson.within`; posture `missed`;
  step `query` chips and the per-step Kibana link; the answer rung in
  foundations; the note's Goal and Hints tabs and the Solution list with its
  copy button; "Run in terminal" and "Show command"; the Network panel's WAF badge and View
  source; the old text ids `lesson.range`, `lesson.follow`, `lesson.attack`
  and every foundation's `answer.*`, `line.*` and `fail.*` keys, with
  `lesson.answer.*`, `lesson.run.*`, `lesson.command.*`, `lesson.goal.*`,
  `lesson.replay.*`. Tests: 26 functions removed or replaced (among them the
  two Run in terminal tests, the seed kept out of both scores, the hint that
  gives the answer, the proxy to `fsl-<id>-waf-1`), 74 added; 1066 -> 1114.
- **The seams.** `api/site.py` no longer names the WAF container
  (`fsl-<id>-waf-1`); it reaches Kali only through `attacker.py` and the
  substrate's `opened`. The sqlmap log read is in `attacker.py`, the data
  view in `kibana.py`, the tag exclusion in `rules/crs.py`. Metrics:
  core_loc 580 -> 584, product_loc 23996 -> 25625, dependencies 6 and
  services 10 unchanged.
- **Proven live:** see "Foundations review loop, rounds 2-5" (2026-10-19): the walker passed 48 of 48 steps on d077869; e4a467e is deployed and smoke-tested only.

## Target and WAF realism after the round-2 live panel

- **Seed.** The board seeds 15 posts by admin, jiwoo and minseo over the
  previous four weeks, with 28 comments (some anonymous), instead of three
  posts stamped with one minute. Only those three accounts exist, so the
  `auth_user` loot and the objective tiers are unchanged. The customer
  traffic's `posts` list follows the seed (1 to 15; a test holds the pair).
- **`/internal/`.** The WAF no longer answers with nginx's own 404, which a
  prober can tell from the board's; it proxies the request to `/not-found/`,
  which the board does not serve, and relays Django's 404. The platform's
  ground-truth read still goes straight to `board:8000`.
- **Config file name.** The WAF's nginx config is `board.com.conf`
  (`deploy/waf/board.com.conf`, installed to `/etc/nginx/conf.d/`), no longer
  `range.conf`. Both substrates: the Docker WAF mounts `deploy/nginx/board.conf`.
- **Not done: paranoia in `crs-setup.conf` (id:900000).** `rules/crs.py` would
  write and roll back a second file and F6's line numbers would move; core_loc
  would grow.

## The Kali shell and the Kibana spaces after the round-2 live panel

- **Kali keeps `http_proxy`, no transparent redirect.** The Kali shell sends
  its web traffic through mitmproxy by `http_proxy` from
  `/etc/profile.d/proxy.sh`, not by an iptables redirect of port 80. A
  redirect cannot be proven offline, and it would push every port-80
  connection from kali (`nmap -sT`, `nc`) through mitmproxy, changing what
  the learner sees from the tools. `curl --noproxy '*'` still skips the proxy,
  as before.
- **Learner Kibana spaces stay listed.** Each session's Kibana data view lives
  in a space of its own, and the other sessions' spaces remain visible in
  Kibana's space switcher. The product has no learner identity: any session's
  console is reachable by its URL, so a per-space access check would protect
  nothing more than the URL already gives away.

## Kibana shows no platform name (round-2 realism M5, L1, L2)

- **What a learner can open.** The JSON tab prints `_index` and `_source`;
  Inspect prints the request (the `_source` excludes, the runtime mappings and
  their scripts); the data view page prints the pattern and the name; KQL
  autocomplete lists the fields. Each carried `fsl-logs-slotN-...`,
  `fsl_source`, `fsl_slot` or `X-FSL-Case`. None does now.
- **Names.** Indices are `logs-<session id>-<day>` on docker and
  `logs-<N>-<day>` on OpenStack (the data stream behind it is
  `.ds-logs-<N>-<day>-000001`); Filebeat's template is `logs-sensors` on
  `logs-*`, priority 150 over Elasticsearch's built-in `logs-*-*` (100); the
  data view is named `logs-*` (the space keeps "Session logs", the only place
  that name is shown); the engine is the ECS field `event.module`
  (`suricata`, `modsecurity`), `log_source` stays as the runtime field the
  lessons name; `event.*` joins the source filters, `fsl_*` and the marker
  patterns leave them (the fields no longer exist; the headers sit under
  `transaction.*` and `http.request_headers*`, still hidden).
- **Slot tag.** Filebeat still routes on `fsl_slot`, and the ingest pipeline's
  first processor removes it before the document is stored, so no mapping or
  document has it. It is not moved to `@metadata`: whether `has_fields`
  reads `@metadata` in the output selector was not provable offline.
- **Marker header.** `X-FSL-Case` is now `X-Request-ID`, a header gateways
  and load balancers set on every request, in `deploy/proxy/stamp.py`,
  `deploy/traffic/users.py`, `redteam/tools.py`, `ingest/elastic.py`,
  `site.py` and `kibana.py`; its value is still the case id. Nothing in the
  WAF, Suricata or the board sets that header (checked by search), so the
  stamp-only-when-absent rule is unchanged. Not chosen: removing the header
  after extraction (Suricata and ModSecurity record the request before the
  pipeline sees it, and the platform re-reads it from Elasticsearch at
  ingest), or storing the marker under a custom field (that field is a platform
  name too).
- **Syslog lines.** Filebeat drops a syslog event that is neither a Suricata
  nor a ModSecurity JSON line (`drop_event` on `not has_fields event.module`),
  so the index holds only the two engines' events and the Discover link no
  longer adds `log_source: exists`. Nothing read those lines.
- **Sensor script.** The `sensor` runtime field matched on the host names
  `fsl-edge` and `fsl-wargame-host`, which Inspect printed; it now matches on
  the sender's host name without its first dash-separated part, on both sides.
- **Operator objects.** The default space still holds `fsl-*` ids and "FSL ..."
  titles (saved search, visualizations, dashboard); a learner space cannot
  reach them. The ingest pipeline keeps its name `fsl-geoip`; no learner
  screen shows it.
- **Not proven offline.** Filebeat 8.15 with template `logs-sensors` on
  `logs-*` beside the built-in `logs` templates, nested `event.module` in
  `fields`, and `drop_event` on a syslog input. A live walk checks them.

## Round 3: what a learner can list on the attacker box and the WAF VM

- **Names.** On the OpenStack Kali the units are `web-proxy.service` and
  `ttyd.service`, the proxy script `/usr/local/lib/web-proxy.py`, the SNAT
  script `/usr/local/sbin/set-origin` and its nat chain `ORIGIN-SNAT`; nothing
  in `deploy/kali/setup.sh` carries the platform's name (a test holds it).
- **Modes.** `/var/lib/session/active` and `origin` are 0600 `ubuntu` (the
  account the platform logs in as; the proxy runs as root), the directory 0711,
  `/var/log/commands.log` 0622 `ubuntu`: `kali` can append, not read. The
  shell hook cannot read the marker as `kali`, so it falls back to
  `sudo -n cat`; the learner has passwordless sudo, so this hides the files
  from a casual `cat` and from `ls`, not from a determined learner. On docker
  the log is root 0622 and the marker volume stays readable.
- **Docker proxy address.** `http_proxy` is `http://proxy-<id>:8081`, an alias
  on the shared `edge` that only that session's proxy carries. Not chosen: a
  per-session `lab` network with the bare name `proxy`. `test_declaration`
  requires every compose network to realise a declared segment, the platform
  attaches itself to every project network, and Docker resolves a name that
  two networks carry by network order, which was not provable offline.
- **WAF hostname.** `waf`, set by the boot unit `set-hostname` (after
  `cloud-init.service`, before rsyslog and ssh) instead of at image build,
  because Filebeat takes the slot from the syslog sender name (`fsl-waf-2`) and
  a fixed name would put every slot's WAF log in slot 1. The unit writes
  `global(localHostname=<Nova name>)` to `/etc/rsyslog.d/05-sender.conf`
  (dropped if `rsyslogd -N1` rejects it) before renaming. Not proven offline: a
  live walk checks `hostname` on the WAF and that a second slot's WAF events
  still land in `logs-2-*`.

## Round 3: what a learner can reach through the Kibana pane

- **Problem.** The learner's space lists Stack Management, and `/kibana/`
  passed every path to Kibana, which runs without security: Ingest Pipelines,
  Index Management, Snapshot and Restore, the spaces of other sessions and the
  Dev Tools console proxy (`_search` on any index, with the raw `_index`,
  host names and container ids) were one click away, read and write.
- **Deny at the front.** `platform/nginx.conf` answers 403 to the APIs of
  Elasticsearch and Kibana administration (console, ingest pipelines, index
  management, snapshot and restore, transform, rollup, remote clusters,
  license, upgrade assistant, index lifecycle, watcher, the data views API,
  the spaces API except `internal/spaces/_active_space`, the security API,
  the settings API, saved objects import and export) and redirects the pages
  `app/management`, `app/dev_tools` and `app/home` to the same space's
  Discover. The list of what Discover needs was captured on the live Kibana
  with headless Playwright (load, expand a document, the JSON tab, field
  details and Visualize, Field statistics, the time picker, Open, a query, the
  data view picker and the Create flyout, GETs and searches only):
  `internal/security/*`, `api/core/capabilities`, `api/licensing/info`,
  `internal/licensing/feature_usage/register`, `api/banners/info`,
  `api/saved_objects_tagging/tags`, `internal/spaces/_active_space`,
  `internal/telemetry/config`, `internal/data_views/*`,
  `internal/index-pattern-management/resolve_index/*`,
  `api/content_management/rpc/*`, `api/index_patterns/has_user_index_pattern`,
  `internal/saved_query/_count`, `internal/bsearch`, `api/ui_counters/_report`.
  A deny list, not an allow list: an allow list would break on the first call
  the capture missed. `test_front.py` holds both lists against the pattern.
  What stays open: Discover's own searches (`internal/bsearch` is also what an
  ES|QL or an ad-hoc data view runs), so a learner who makes an ad-hoc data
  view on `logs-*` still sees every slot and every raw field. ES|QL is off
  (`enableESQL`; the 8.15 key was read from the uiSettings defaults on the
  page); the ad-hoc view has no switch in 8.15 and stays an unverified gap.
  Client-side navigation to Home or Stack Management from the app menu does not
  request the page, so the menu entries remain and open pages whose APIs answer
  403.
- **Operators.** Kibana publishes `127.0.0.1:5601` on the platform host; an
  operator reaches it whole through `ssh -L 5601:127.0.0.1:5601`. The platform's
  own setup (`KIBANA_URL`) talks to `kibana:5601` directly and is unaffected.
- **Not chosen: Elasticsearch security with a per-slot role.** Every
  Elasticsearch caller (platform, Filebeat, Kibana, the acceptance tests) would
  need credentials, and Kibana would need a sign-in the platform performs.
- **Space.** Named "SOC", id `soc-<pattern>` (not `session-`). Its settings:
  `enableESQL` false, `defaultColumns` the session columns (a new Discover tab
  showed only `@timestamp` once `transaction.*` and `log.*` were hidden),
  `defaultIndex` the space's data view (set by the platform, so the browser
  has no default to write through the refused settings API), `defaultRoute`
  the space's own saved search "Events" with the session columns. Spaces named
  `session-...` from earlier builds stay in Kibana as unused spaces.
- **Operator objects.** Titles lose "FSL" ("Alerts", "Overview", "Top rules",
  ...); the data view takes the same `sourceFilters` and field formats as a
  session view, so the operator alert search shows the session columns.
  Object ids keep `fsl-`, so an overwrite import replaces them instead of
  leaving a second set; they show only in the default space's URLs.
- **Ingest pipeline.** `fsl-geoip` is `geoip` (Filebeat's output and template
  default, `register_pipeline.py`, the acceptance tests); its description names
  no purpose. The old pipeline stays in a standing Elasticsearch: today's
  indices carry `default_pipeline: fsl-geoip` in their settings and would
  refuse writes without it, so it is not deleted.
- **Edge hostname.** `edge` and domain `localdomain` in
  `deploy/opnsense/config.xml` (slot N renders `edge-N`, `opnsense.HOSTNAME`).
  `log.syslog.hostname` was `fsl-edge.range.internal`. The `sensor` script now
  strips the domain and the slot number, then looks the name up whole and
  without its first dash-separated part, so `edge`, `edge-2.localdomain` and
  `fsl-wargame-host-2` all reach their map name. Not proven offline: the
  script's Painless and the in-place reset of a standing slot 1, whose
  recorded config hash changes with the hostname (a live walk checks both).

## Round 4: what the Kibana pane still showed (realism lens)

- **Default space refused.** `/kibana/app/...` and `/kibana/spaces/...` (the
  Default space and its space selector) answer 403 at the front; the Default
  space has every feature on and ES|QL in the picker. The console links only
  `/kibana/s/<space>/...`; an operator reaches the Default space on 5601.
- **Data views API.** `api/index_patterns/*` is denied like `api/data_views`,
  except `has_user_index_pattern`, which Discover calls.
- **Settings.** `internal/kibana/settings` is GET only (the UI writes advanced
  settings through it). Lookups with `namespaces=` answer 403, so a learner
  space cannot list the saved objects of another space. Not exercised against
  a live Kibana with a browser: a live walk checks that Discover still loads.
- **Space switcher.** `GET s/<space>/api/spaces/space` answers a list of the
  current space alone (name SOC); every other method on it is 403.
- **Names.** Operator saved objects lose `fsl-`: `logs`, `alerts`, `overview`,
  `alerts-by-engine`, `top-rules`, `waf-blocks`, `top-countries`
  (`DATA_VIEW`, `ALERT_SEARCH`, the default route). Objects with the old ids
  stay in a standing Kibana's Default space, unreachable from the learner
  proxy. The collector has hostname `siem` and Kibana `SERVER_NAME: kibana`,
  so documents' `agent.name` and `host.name` and the status page print no
  container id.
- **Data stream.** Filebeat's index is `logs-<slot or session>-sensors` (one
  data stream per slot, backing index `.ds-logs-1-sensors-<day>-000001`), not
  `logs-1-<day>` with the day twice. `logs-{slot}-*` and `logs-{session}-*`
  still match. Not done: Filebeat also creates an empty data stream named
  after its template (`logs-sensors`); stopping that needs either a template
  Filebeat does not create or a delete from outside, neither provable offline.
- **Hidden fields.** `src_ip`, `dest_ip`, `alert.signature` and
  `alert.signature_id` join the source filters (the data view shows the same
  values as `source_ip`, `destination`, `rule` and `rule_id`); the operator
  data view carries the same list.
- **Column widths.** The console's Discover link carries the widths the saved
  search sets (`grid:(columns:(...))`), so an IP never wraps in the table.

## Round 5: what the platform origin and the Kibana pane still showed (realism lens)

- **Default space.** `/kibana/s/default/...` and every path under `app`,
  `spaces`, `api` and `internal` without a space prefix answer 403 in one
  location. A full Discover load in a learner space asked for no such path
  (only `ui/` fonts and styles, `translations/` and `bundles/`). The internal
  settings route is GET only and exists only under a learner space.
  `app/observability`, `app/security` and `app/kibana_overview` redirect to
  Discover with the other disabled pages.
- **DEBUG off.** `compose.yaml` no longer sets `DJANGO_DEBUG`, so a wrong path
  on the learner's origin answers a plain 404 and a 500 prints no settings. The
  console is inline CSS and `fetch`es `/api/`, so no static file is served. A
  Django `Http404` under `/api/` (and `UnknownOrigin`) now answers JSON
  `{"detail": ...}` (`api/refusals.py`), as the other refusals do; the console
  reads `detail` or falls back to the status. The secret key: `entrypoint.sh`
  writes a random one to `/data/secret-key` (mode 600) when `DJANGO_SECRET_KEY`
  is unset and the file does not exist, and exports it; it is never printed and
  never replaced. Not written into `.env`: that file is rewritten by every
  platform rebuild and holds nothing the platform container needs, while the
  data volume also covers `docker compose up` on a workstation.
- **Learner map page.** `fsl-auditor.html` is `map.html`. The learner password
  is generated into `/var/lib/fsl-gns3/auditor-password` by the gns3 entrypoint
  when `FSL_GNS3_AUDITOR_PASSWORD` is empty (the admin password's way: mode 640,
  the docker socket's group), the platform reads it from the same mount at each
  call, and the old default `fsl-auditor` is gone. A standing gns3 container
  takes the new password when it is recreated (`provision.py` sets the user's
  password on every start). Image context changed: `deploy/gns3`.
- **Host names.** The collector's hostname is `log-server` and OPNsense's
  `firewall` (`firewall-N` in slot N), the names the map draws. The `sensor`
  runtime field matches the sender's host name against the host names without
  their first part and now also against the map names, so `firewall` and
  `firewall-2.localdomain` reach `firewall`.
- **Sender address.** Filebeat drops `log.source.address` (the management
  address of the sender) in the syslog input.
- **Hidden fields.** `http.*` (Suricata's own names beside `url`, `status` and
  `request_header.*`) and `data_stream.*` (the namespace is the slot) join the
  source filters. F4 listing `alert.signature*` while F6 hid them could not be
  reproduced offline: the live view's `sourceFilters` hold both, a session open
  re-imports the view with `overwrite=true` every time, and the platform log
  shows no refused import. A live walk re-checks F4.
- **Not done.** The slot number in Inspect, the space id and the index names
  stay: a shared Kibana needs a per-slot identifier, and renaming moves it.

## 2026-10-19 — Foundations review loop, rounds 2-5

Six reviewers per live round (design, UI, terms, AI-tone, realism and leaks,
first-time learner) read headless-Chrome screenshots of the walked lessons
F1-F6 and the report of each step; round 1 was the instructor and UX pair.
Counts are critical/high/medium/low per reviewer.

| Round | Commit | Counts |
|---|---|---|
| 1 | 326fa6f..f261301 | instructor 2/9/21/16, UX 2/13/28/13 |
| 2 static | strings, scenario | terms 1/6/9/19, AI-tone 1/4/23/27, lesson design 0/4/9/13 |
| 2 live | f261301 | design 2/3/6/11, UI 0/3/7/10, terms 0/0/4/8, AI-tone 0/1/9/23, realism 0/3/5/14, learner 5/2/14/10 |
| 3 live | f9d433b | design 2/0/4/15, UI 0/1/9/8, terms 0/0/4/9, AI-tone 0/0/8/28, realism 0/2/3/8, learner 0/8/10/11 |
| 4 live | 1dac802 | design 0/0/6/10, UI 0/0/4/8, terms 0/0/1/8, AI-tone 0/0/7/24, realism 0/1/4/8, learner 0/1/8/12 |
| 5 live | d077869 | design 0/0/4/9, terms 0/0/2/4, AI-tone 0/0/7/17, realism 0/0/2/7, learner 0/1/3/11; the UI reviewer did not finish (usage limits) and its partial work was lost |

The walker passed 48 of 48 steps in every run from round 2. Critical findings
fell to zero by round 4 and high to two (one each in realism and learner),
then to one learner high in round 5.

- **What changed (rounds 2-5, fixed in 326fa6f..60243e6).**
  - Learner text rewritten Korean-first: the ko strings for exfiltration
    (`result.lost`, `red.loot.heading`), true positive (`score.second.heading`,
    the `true positive (TP)` vocabulary row), the board's search box told
    apart from Kibana's KQL input box (`lesson.http.coach.search`,
    `lesson.logs.theory.discover.body`), practice environment
    (`scenario.shift.measured_by`, `range.healthy`), Map
    (`blue.pane.topology`), lesson (`lesson.next.start`) and Skip
    (`lesson.skip`). F4's fired step asks for
    the sid; the F3 count and F6 seen checks equal what Kibana shows; numeric
    answers accept `1,292`.
  - Coach: Kibana rows that know which leg of the proxy they show, callouts
    under the note buttons, a ring when the run finishes, the map hidden
    until fitted, command boxes that wrap only at spaces and carry a copy
    button, a rule editor that wraps with wrap-aware rings, callout placement
    by distance and leader cost.
  - Realism: the Kali VM user is `kali` with Kali's prompt, hostnames `kali`
    and `waf`, neutral unit and path names; the Website pane sends Chrome's
    headers, keeps cookies and lists favicon and cache rows; DevTools has the
    toolbar, a waterfall, type chips in Chrome's order, an Elements tree,
    Sources navigator and Console toolbar; the board seed is 15 posts and 30
    comments.
  - Leaks closed: a Kibana learner space "SOC" per session with only Discover,
    ES|QL off, admin APIs, the Default space and unprefixed paths answering
    403; index `logs-<slot>-sensors`, `event.module`, marker header
    `X-Request-ID`, collector hostname `log-server`, edge hostname
    `firewall`, `log.source.address` dropped, `http.*` and `data_stream.*`
    hidden; Django `DEBUG` off with a generated secret key; the GNS3 page
    `map.html` with a generated learner password; terminals at
    `/vm-terminal/kali/` and `/vm-terminal/waf/`.
- **Decided, not fixed** (the panel was told not to re-raise these):
  - `/internal/auth-users` stays on the board: `api/loot.py` is the one reader
    of the target's ground truth by design; Kali and the Website pane cannot
    reach it and the WAF answers it with the board's own 404.
  - No public service IP or DNAT on the edge; F1's theory says the practice
    network forwards without NAT. The firewall's WAN label on the OpenStack
    map is the edge's real address on an origin /24.
  - The developer tools button (`site.dev.toggle`) stays (F2 teaches opening DevTools with it; F12
    works too). DevTools Styles/Computed/Layout are empty (no CSS rule data
    is captured) and inert toolbar controls stay inert.
  - Map links of `customers` and `kali` carry no IP (their source address
    changes per origin). F1's db_ip repeats reading a link label (on the
    Docker map the variant would equal step 1). The last step of each lesson
    is solo by design.
  - Kibana 8.15 cannot switch off ad-hoc data views; the space switcher still
    lists other spaces and the app menu lists Home and Stack Management (their
    pages answer 403 or redirect to Discover). A per-slot number (space id,
    index name, Inspect) stays visible in a shared Kibana; it is neutral.
    Elasticsearch security with per-slot roles is not used; the `/kibana/`
    proxy refuses the admin APIs instead. Filebeat's empty data stream named
    after its template (`logs-sensors`) stays; learners' views never cover it.
  - The Kali shell keeps `http_proxy` instead of a transparent redirect;
    `/etc/os-release` and `uname` say Ubuntu (one cloud image); the label
    files are hidden from casual reads only (passwordless sudo, as on Kali).
    Docker Kali reaches its proxy as `proxy-<id>` on the shared edge network.
  - The CRS paranoia `SecAction` stays on line 1 of the exclusion file
    (moving it grows the gated `core_loc`). The `traffic.yaml` customer
    comment texts stay (changing the benign mix changes scenario 2.x's
    measured baseline).
- **Not verified.**
  - Round 6 (the panel under the convergence rule: a finding counts only if
    a Korean freshman learner would notice it on screen) and the full
    `bin/verify` with acceptance were skipped at the user's request, for time.
    The round-5 fixes (9f1f39d..60243e6) are deployed as e4a467e but were not
    re-reviewed live, and no live acceptance has run since the round-4 changes.
  - The round-6 smoke walk hit walker artefacts (an order answer sent as one
    item; the walker's answer source lacked the web process's in-memory
    website requests; the sort step needed the brand link first), fixed in the
    walker, not product bugs.
  - No taste items were collected; the convergence rule began with round 6.
- **Proven live 2026-10-19** (OpenStack, platform VM 192.168.0.210). The
  walker passed 48 of 48 steps on d077869 (round 5). e4a467e was then
  deployed with all five images sideloaded from it, both slots rebuilt onto
  the new Kali and WAF images and configured, `ready` true; that deploy was
  smoke-tested only. `bin/verify --fast`: 1666 passed.

## 2026-10-20 — The product is OpenStack-only; a newcomer's bring-up is the repo's job

Rulings by the user:

- **OpenStack only.** The product runs on OpenStack, on Kolla-Ansible 2026.1
  with `nova_compute_virt_type: "kvm"` (never `qemu`). This supersedes the
  2026-10-11 ruling "OpenStack is a first-class substrate; no acceptance test
  is docker-only" ("every acceptance test must run and pass on substrate
  openstack as it does on docker"): there is no second substrate to run
  beside it. The docker substrate (`platform/range/docker.py`, `session.yaml`
  and what hangs on them) is to be removed from the code; the plan is
  `docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`, decided
  with its D1-D4 as yes, not started. Docker stays as the way the platform VM
  runs the platform's own services from GHCR images (and the wargame host's
  and GNS3's container runtime); it is never presented as a separate way to
  run the product. Until the plan runs, the docker substrate still exists in
  the code.
- **A one-VM trial** on VirtualBox or VMware (any host OS) is for checking that
  the bring-up works, not for operating the product (`docs/OPENSTACK.md` §9).
  Nothing in the docs is host-OS-specific: no PowerShell, no Windows-only
  steps.
- **If the repo can make a reader's step unnecessary, the repo does it.**
  `.gitattributes` fixes line endings (no doc text about CRLF); the first
  `bin/cloud up` makes the range key; the `openstack` CLI is found beside the
  interpreter in `.venv`; a platform VM that never ran `fsl-platform` has
  nothing to back up, so `down` and `up --replace` proceed.

What newcomers hit, from two read-only audits that followed the docs on a
clean clone (one line each; all fixed):

- No range key on the first `bin/cloud up` (it refused); now made by the first
  `up`.
- The `openstack` CLI installed into `.venv` was not found without activating
  the venv; now found beside `sys.executable`.
- Line endings: no `.gitattributes`, so a CRLF checkout broke sideload
  tarballs and scripts; now pinned to LF. The ssh wait now reports
  the last ssh error, and cloud files are read as UTF-8.
- README led with Docker and called both substrates first-class; it now
  states the requirements and nine numbered steps, each with a check and a
  recovery, and what the cloud needs from Kolla-Ansible 2026.1, the external
  network and egress.
- The base image was uploaded as admin and `fsl-range` could not see it:
  `--public`.
- The installer's guided LVM gave Nova about 100 GB of 250 GB: extend the
  logical volume to the whole volume group.
- No way back when the platform VM never came up: `up` redoes the hand-over of
  a VM that never took it, and `down` / `up --replace` proceed without a
  backup when there was no `fsl-platform` to back up.
- A review found that path could lose the store: `up --replace` backed up VM
  A, the new VM's hand-over failed, the advice was `up --replace` again, that
  VM held no store, so the next one started empty and the next backup with
  `backups.keep` 1 removed A's copy. Now a VM made where no store stands (no
  stack, a failed stack, a VM that holds none, and `up`'s redone hand-over)
  gets the newest `backups/db-<UTC time>.sqlite3` that holds rows, named on
  the console, or starts empty and says so; a backup that holds no rows is
  passed over for that newest one; `bin/backup` removes no older backup when
  the store it copied holds no rows; the password line that marks a finished
  hand-over is written after the store is restored. This also closes "`up`
  after `down` starts with an empty store". Two smaller fixes from the same
  review: a stack that is not `*_FAILED` but whose `address` output cannot be
  read is refused by `up`, `up --replace` and `down` with nothing deleted
  (before, it was taken for a broken stack and deleted); the hand-over check
  counts only grep's 0 and 1, and any other answer (ssh failing) refuses
  instead of redoing the hand-over.
- Smaller: passwordless sudo and netplan lines for Kolla, range flavor
  `m1.medium` in the example, `OS_AUTH_URL` from `identity.keystone`, quota
  wording, when `ready` is true, VMware Workstation, `python3-venv`, 40 GB VM
  RAM.

The research behind it: no OpenStack-based range has a host-OS quick start
(KYPO/CyberRangeCZ's `kypo-lite` is Ubuntu with 48 GB RAM; its Windows path is
a separate VirtualBox sandbox tool without OpenStack); AIT AttackBed documents
numbered install steps, and StratoCyberLab states minimums on its first screen
and ends with a check step. Notes: `~/.cache/fsl-work/panel/ranges-broad-survey.md`,
`ranges-windows-research.md`, `kolla-windows-research.md` (outside the repo).

Not verified: the §9 one-VM trial has not been run end to end; the Kolla
`sudo` and netplan lines follow the docs only (kolla-ansible's `--become`
implies no password; the installer's netplan merge was read, not run). The
changed bring-up paths are unit-tested with fake ssh, Docker and OpenStack
CLIs only; none has run live on the changed code: `down` and `up --replace`
on a standing platform (`STORE_PROBE` over ssh), `up --replace` with the
first-range-key logic, plain `up`'s resume (`hand_over_done`, the redone
hand-over with its `sed` on `/opt/fsl/openstack.env`), and the restore of the
newest backup.

## 2026-10-20 — Live checks of the bring-up paths, and three fixes they led to

The bring-up paths changed earlier on 2026-10-20 (the entry above) had been
tested with fake ssh, Docker and OpenStack CLIs only. Two live runs on the test
cloud closed that. Notes: `~/.cache/fsl-work/notes/live-push-check.md` and
`live-fix-check.md` (outside the repo).

First run, on the code before the fixes, platform VM at 192.168.0.210:

- `bin/cloud up --replace --sideload` (store probe, backup, range key kept)
  passed in 27 min 13 s. A full `bin/verify` on the new VM passed: unit 1706,
  acceptance 73 passed, 0 failed, 0 errors, 0 skipped (1129 s), ratchet ok.
- Three bugs came out of it.
  1. `bin/cloud down` failed with 409 SubnetInUse on `fsl-mgmt`. Thirty-five
     detached `fsl-platform.mgmt` ports stood on it, one left by every platform
     VM replace since 2026-10-17: `_attach` pre-creates the port, Nova detaches
     it when the server is deleted and does not delete it, and teardown deleted
     only ports held by this platform. The bug is older than this branch. The
     ports were deleted by hand and `down` then passed (26 s).
  2. Plain `up` on a VM whose `fsl-platform` container was stopped and which
     had not taken its hand-over failed: the hand-over writes the range key with
     `docker exec`, which needs a running container, and the store probe had said
     "stored" because the volume file exists.
  3. The redone hand-over dropped `FSL_SIDELOADED` (its `sed` deleted the line
     and the resume does not write it again), so the next bundle was built
     without the sideloaded images.
- With the container started by hand and the password line removed, plain `up`
  passed (10 min 17 s). `down`, then `up --sideload`, restored the newest backup
  that holds rows (`db-20261020T041910Z`, 2 sessions) in 14 min 49 s.

The fix commit:

- `range/openstack.py`: `_attach` deletes detached `fsl-platform.mgmt` ports
  before it creates one, and `teardown_fabric` deletes detached ports on the
  fabric's networks.
- `bin/platform-rebuild`: `start_platform` starts the `fsl-platform` container
  and waits until it runs. The hand-over calls it before the range key write, and
  the resume and the replace call it before they take a key or a backup from a VM
  that holds a store.
- `bin/platform-rebuild`: `settings_rewrite` rewrites only the lines the
  hand-over owns: `FSL_OPENSTACK_PASSWORD` always, `FSL_SIDELOADED` only when the
  run sideloads. Every other line is kept and the file keeps mode 0600.
- `bin/verify --fast` passed 1711.

Second run, on the fixed code:

- Plain `up` with the container stopped and the password line removed passed in
  71 s; `FSL_SIDELOADED` was kept and no image was rebuilt.
- `up --replace --sideload` passed in 14 min 3 s and left exactly one
  `fsl-platform.mgmt` port; the old VM's detached port was deleted by `_attach`.
- `bin/cloud down` passed with no hand work in 32 s.
- `bin/cloud up --sideload` restored `db-20261020T050321Z` (3 sessions at
  backup time; retention dropped the closed ones at start, as before) in
  15 min 52 s, and the range was ready.
- The VM runs the fixed code, `ready` true, both slots READY, no open session.

Still open, not fixed:

- `bin/cloud down` refuses when a store sits beside a stopped platform container
  (it does not start the container first, unlike `up` and the replace).
- `resume` returns as soon as the API answers, before it checks the hand-over
  (`docs/STATE.md` backlog 0).
- The §9 one-VM trial has not been run, and the first range key was not made
  live (the key existed in both runs and was kept).
- After `down` then `up`, the `fsl-wargame-host` image was rebuilt both times;
  not investigated.

## 2026-10-20 — The one-VM trial and the last bring-up fixes

The previous entry ended with four items open and the §9 one-VM trial unrun.
This entry closes them. Notes: `~/.cache/fsl-work/notes/live-open-items.md` and
`s9-trial.md` (outside the repo).

The four items, fixed and run live on the test cloud
(platform VM 192.168.0.210):

1. `bin/cloud down` beside a stopped `fsl-platform` container. `down` now starts
   the container, backs up, waits for the API and then removes the range. It
   still refuses, deleting nothing, when ssh or Docker does not answer or the
   container does not start. Live: 40 s, a backup of 430,080 bytes that passed
   `integrity_check`, and the slot, the fabric and the stack gone.
2. `resume` checks the hand-over every time. Before, it returned as soon as
   `/api/sessions/` answered, so a container started before the password line
   was written skipped the redone hand-over and the range build failed. Live: with
   only the `FSL_OPENSTACK_PASSWORD` line removed and the container running,
   plain `up` redid the hand-over in 89 s. `openstack.env` came back with the
   same lines and mode 0600, and the key was unchanged.
3. The first range key, made live. With `~/.ssh/fsl-platform` moved away and no
   stack, `up --sideload` made the key (with its `.pub`), restored the newest
   backup that holds rows, rebuilt `fsl-edge` (it trusts the new key) and
   `fsl-wargame-host`, and reused `fsl-waf` and `fsl-kali`. It took 15 min
   53 s. The old key is kept in the operator's backup.
4. The wargame host rebuilt after every `down` then `up`. The cause was the
   platform's fixed IP: the list of sideloaded images in the bundle carried the
   URL each image is fetched from, so a new stack (Neutron gives the port a new
   fixed IP) changed the digest. The list is now `<image> <image id> <name>`,
   and the base URL goes in `served-from`, which the builder gets and the digest
   leaves out. Live: `down` 30 s, then `up --sideload` 8 min 56 s with no
   image built. The wargame host kept its digest `7bce304b14aea25e` while
   `FSL_PUBLISH` changed from 10.20.0.64 to 10.20.0.181.

A full `bin/verify` on the code with items 1 to 4 fixed passed: unit 1716, acceptance 73 passed, 0
failed, 0 skipped (1165 s), ratchet ok (`core_loc` 584, `dependencies` 6,
`services` 10).

The mode-digest fix. The run of item 3 showed that `setup.sh` was mode
0664 in the sideloaded checkout (umask 002) and 0644 in cloud-init's clone
(umask 022), and the digest hashed `st_mode & 0o777`. One commit therefore built
two digests, and a VM made without `--sideload` would have rebuilt every image
once. The digest and the archive now take only the executable bit, 0755 or 0644,
as git tracks it. Every digest changes once, when this rule begins. The test
`test_a_checkout_s_umask_does_not_change_the_digest_and_only_the_executable_bit_does`
holds it. `bin/verify --fast` passed 1717.

The §9 trial, run end to end on the code with the mode-digest fix, from an empty cloud (`docs/OPENSTACK.md`
§9):

| Stage | Time | Note |
|---|---|---|
| Platform tarball built | 1 min 21 s | |
| Test cloud `bin/cloud down` | 29 s | backup 438,272 bytes, integrity ok |
| Trial VM created | 37 s | |
| §9.1 netplan, sudoers, apt | 39 s | `kvm-ok` passed |
| §9.2 `install-deps`, `bootstrap-servers` | 76 s, 51 s | |
| §9.2 `prechecks` | 27 s | failed twice first (D1, D2) |
| §9.2 `deploy` | 11 min 39 s | failed once first (D3); `failed=0` |
| §9.2 `post-deploy` | 4 s | failed once first (D4) |
| §9.3 external network, project, flavors, base image | 3, 5, 1, 57 s | |
| README steps 2 to 6 | 17 s | |
| README step 7, `bin/cloud up` | 17 min 41 s | four builders in parallel |
| README step 8 | Start to session page 9.3 s and 6.9 s; close to ready again 80 s and 70 s | |
| Teardown | 25 s | |

At the end of the trial the VM used 26 of 39 GB of RAM and 57 GB of disk, with
a load of about 3. The nested platform ran the commit's code, and the range's
guests saw `vmx` and `/dev/kvm`.

Seven defects in the document came out of it, all fixed in `docs/OPENSTACK.md`
and `README.md`/`README.ko.md`:

- D1. `prechecks` stopped at "Checking docker SDK version". Fix: `pip install
  docker dbus-python` in the Kolla venv.
- D2. `prechecks` refused the `quay.io/openstack.kolla` images. Fix:
  `--use-test-images` on `prechecks` (`deploy` takes none).
- D3. `deploy` failed with "Address already in use" on port 3306: ProxySQL is
  enabled with MariaDB, not with HAProxy, and binds the VIP, which an all-in-one
  makes the host's own address. Fix: `enable_proxysql: "no"` beside
  `enable_haproxy: "no"`. The failed run was cleaned by removing the proxysql
  and mariadb containers, their volumes and `/etc/kolla/proxysql`.
- D4. `post-deploy` without `-i` looked for a missing inventory. Fix: `-i
  ./all-in-one`.
- D5. README step 8 said the blue console opens by itself. It does not: the
  session page has a "Blue team console" card with "Open". The page opens within
  seconds.
- D6. The timings: deploy 11 min 39 s, README step 7 17 min 41 s, and §9 now says
  it was run end to end.
- D7. The admin shell's `OS_*` variables must not be set for README steps 2 to 6,
  so §9.3 says to open a new shell.

Where the trial differed from §9 as written:

- The trial VM was a guest of the KVM test cloud, not a VirtualBox or VMware VM.
  The nested-virtualization setting, the promiscuous-mode setting and the
  adapters' modes of §9.1 were therefore not exercised, and §9's intro says so.
- It booted the stock Ubuntu cloud image, not the Server installer. The root
  disk was already 242 GB, so the `lvextend` step did not apply, and cloud-init
  had put DHCP on both adapters, which gave the two default routes that §9.1
  predicts and its netplan file removes.
- Its outer network was a VXLAN tenant network with MTU 1450, so the netplan file
  carried `mtu: 1450` on both adapters. Nova also refused a port with no fixed
  IP for the second adapter. Both belong to that host and stay out of §9.
- The repo came from a git bundle, because origin/dev lacked the commit, and the
  platform from `--sideload platform=...` (only the platform context differed
  from origin/dev). The fsl-range password was generated, not typed. Step 8 ran
  in a headless Chromium through an ssh tunnel, so a host browser reaching the
  floating IP was not tried.

The restore. After the trial, `bin/cloud up --sideload platform=<image of that code>` on the
test cloud took 11 min 55 s and restored `db-20261020T082615Z` (rule sets 232,
suppressions 79, no sessions). The waf, edge, kali and opnsense images stayed
ready on their digests; only `fsl-wargame-host` was rebuilt, once, because of the
mode rule above. Both slots were READY with all checks true.

Two full `bin/verify` runs on the same code, on that VM:

- First: unit 1717 passed; acceptance 72 passed, 1 failed (1257 s). The failure
  was `test_corp_authz`'s live content overwrite: WordPress answered `Invalid
  nonce.` to a nonce the test had just fetched. `bin/acceptance --only
  test_corp_authz` passed all 3 on rerun (118 s).
- Second: unit 1717 passed; acceptance 73 passed, 0 failed, 0 errors, 0 skipped
  (1155 s); ratchet ok; all green.

The nonce failure is the same one the backlog records ("unexplained test_corp_*
nonce error, once, passed on rerun"). It has now been seen twice, both times
passing on rerun. It stays open.

Not verified: the VirtualBox and VMware settings of §9.1; a host browser reaching
the floating IP; the 40 GB figure under load (the trial peaked at 26 GB used).

The last code before the move to the new cloud: the platform VM makes `/opt/fsl/.venv` itself (the cloud-init
`fsl-venv` unit, and `fsl-venv-checkout` after a sideload checkout), proven on a
fresh VM. The full `bin/verify` there: unit 1718; acceptance 73 passed, 0 failed,
0 errors, 0 skipped; ratchet ok; about 22 minutes. The squash into bf96876 kept
this code.

## 2026-10-20 — The product moved to a new OpenStack cloud

The user moved the product to a new OpenStack cloud on 2026-10-20. The previous
cloud (`master@192.168.0.100`, Keystone 192.168.0.110, platform 192.168.0.210)
is now in other use. The product no longer runs there, and we did not touch it.
`docs/OPENSTACK.md`, `deploy/openstack/network.yaml` and
`deploy/openstack/cloud.example.yaml` now describe the new cloud. Earlier
entries in this file keep the old addresses, because they record what happened
then.

The new cloud: Kolla-Ansible, ML2/OVN with Geneve, KVM. `con01`
(10.0.0.11) is the controller, with the API address 10.0.0.10. `com01`
(10.0.0.31) is the one compute node. `stg01` (10.0.0.41) holds Cinder. The
operator reaches 10.0.0.0/24 and the provider network (192.168.2.0/24) through a
VPN. The platform's floating IP is 192.168.2.247.

What had to be done on the cloud side:

- The admin made the flavors `m1.large` (8 GB / 2 vCPU / 60 GB) and `m1.medium`
  (4 GB / 2 vCPU / 30 GB), and uploaded `ubuntu-24.04` as a public image.
  `cloud.yaml` uses `m1.large` for the platform and `m1.medium` for the builder,
  range, edge and wargames.
- The root logical volume of `com01` was extended so that Nova reports
  `local_gb` 546.
- cinder-volume on `stg01` had been down since 2026-09-18. The rendered config
  named Kolla's default volume group `cinder-volumes`, which does not exist
  there. `cinder_volume_group: "ubuntu-vg"` in `globals.yml` fixed it. The product
  does not use Cinder.
- The project quota is 20 cores, 51200 MB of RAM and 10 instances. The user's own
  VM `FSL-front` (4 vCPU, 8 GB) uses 4 cores and 8 GB of it. The platform VM and
  one slot need 10 cores and 24 GB, so `compute.slots` is 1. A second slot would
  need 22 cores.
- `network.mtu` is 1442 here (Geneve). 1450 is right on VXLAN with ML2/OVS.

The first `bin/cloud up` on this cloud had no stack and restored the store backup
`db-20261020T111111Z`. It built all four golden images and then failed at
`configure/`: `POST /api/range/configure/` answered 409 "container corp-wp is
unhealthy".

- Cause. With ML2/OVN and no `[ovn] dns_servers`, Neutron announces the resolvers
  of the neutron-server host's `/etc/resolv.conf`, which under systemd-resolved
  is 127.0.0.53 (`get_dhcp_dns_servers` in `neutron/common/ovn/utils.py` falls
  back to `[ovn] dns_servers`, then to the system resolvers; it returns none when
  a configured server is 0.0.0.0, per
  https://docs.openstack.org/neutron/latest/admin/config-dns-res.html). The range
  hosts' systemd-networkd then sent 127.0.0.53 out of `ens3`. Every name lookup
  waited about 25 s (`getent` 24.6 s), and corp-wp's healthcheck (`wp core
  is-installed`, timeout 5 s) took 29.2 s.
- The fix. `platform/range/openstack.py` creates every range subnet
  with `dns_nameservers ["0.0.0.0"]`. The range has no Internet, so it needs no
  resolver. The product no longer depends on the cloud's `[ovn] dns_servers`,
  which an admin can still set for the cloud's other VMs.
- On the standing cloud the 32 range subnets were set the same way by hand
  (`openstack subnet set --dns-nameserver 0.0.0.0`), and Kali, the WAF and the
  wargame host were rebooted. After that `getent` failed in 0.03 s and `wp core
  is-installed` took 1.9 s. `bin/cloud up` then resumed and reported the range
  ready.
- A fabric made before this fix keeps the old subnets. `openstack subnet set
  --dns-nameserver 0.0.0.0 <subnet>` on each range subnet, then a reset or reboot
  of the hosts, brings it in line. `docs/OPENSTACK.md` §8 says so.

Standing now: the platform VM `fsl-platform` (`m1.large`, fixed 10.20.0.143,
`mgmt` 10.31.0.183) and slot 1 with `fsl-edge` (estate 10.30.0.1, `mgmt`
10.31.0.103), `fsl-waf` (estate 10.30.0.71, `mgmt` 10.31.0.235), `fsl-kali`
(`mgmt` 10.31.0.40) and `fsl-wargame-host` (estate 10.30.0.231, `mgmt`
10.31.0.204). The console is at http://192.168.2.247:8000/.

Full `bin/verify` on the new VM at 3da925e (2026-10-20, before the docker substrate removal, single slot): unit 1718 passed; acceptance 68 passed, 2 failed, 3 errors, 0 skipped in 10024 s. Every failure comes from the new cloud having one slot (`compute.slots` 1, because the user's VM `FSL-front` takes 4 cores and 8 GB of the project quota): the errors are `409 "1 session is already open on the range; close one first"` in the tests that need a second session, and the 2 failures are `test_strategy_honesty`, whose shared session was deleted by retention (`FSL_RETAIN_CLOSED_MINUTES` 60) because a one-slot run takes about 2 h 47 min. Three `test_lesson` tests passed in this run only because a leaked session was closed by hand during it. The later run, after the removal, is in "The docker substrate is removed" below.

## 2026-10-21 — The docker substrate is removed

The plan of 2026-10-20 (`docs/superpowers/specs/2026-10-20-remove-docker-substrate-plan.md`, D1-D4 decided yes) ran in the removal commit, then the documentation commits. The product runs only on OpenStack. Docker stays where the 2026-10-20 ruling kept it: the platform VM's own services, the wargame host and the GNS3 display nodes.

What went:

- `platform/range/docker.py`, `session.yaml`, `platform/waf-terminal.sh`, `deploy/nginx/`, `deploy/kali/Dockerfile`, `deploy/proxy/Dockerfile`.
- The docker learner map and its Korean pair, and the docker system map (`deploy/topology/range-docker.gns3`, `range-docker.ko.gns3`, `system/range-docker.gns3`).
- In `compose.yaml`: the four edge networks, the platform's attachments to them and the `session.yaml` mount. In `platform/nginx.conf` and `entrypoint.sh`: the per-session Kali and WAF terminal routes and the ttyd on 7693. In the collector's `filebeat.yml`: the two filestream inputs.
- The docker-only branches (D1: `open_session`, `for_session`, `has_stack`, the stacks kept after a close, the per-session GNS3 maps), the `host-rewrite` origin mode (D2) and the `openstack:` overlay of the declaration, now folded into the base (D3).
- In the acceptance harness: the `Docker` class, `DOCKER_HOSTS`, `segments()` and `recreate()`. The harness reaches the range only through the platform; only the `scorer` role runs with `docker exec` on the platform container.
- The `kali` and `proxy` images in `images.yml` and in `bin/platform-rebuild`.

Measured with `bin/measure` against `metrics.json`: `services` 10 to 5, `product_loc` 28192 to 25016, `tests` 1232 to 1198. `core_loc` (584) and `dependencies` (6) did not move, and `wargame_services` stays 4 because `bin/measure` now counts it from `wargames/*/compose.yaml` (D4).

Deviations from the plan, recorded in the commit messages:

- The stand-in for the range in the unit tests (`platform/tests/standin.py`) guards `subprocess.Popen`, not ssh, because `test_openstack_ssh` runs real ssh against a local sshd.
- The `kali` and `proxy` entries of `images.yml` and `IMAGES` went with the Dockerfiles, not in the bring-up commit, because the test that CI publishes exactly what compose builds and the one that ties `IMAGES` to the workflow fail otherwise.
- More tests were deleted than the plan's table lists, each for testing only a removed mechanism: the compose-versus-declaration checks in `test_declaration`, the session WAF health check in `test_deployment`, the docker board vhost in `test_internal_blocked_at_waf`, the refusal at open for unreadable board accounts in `test_loot_session_start`, and the `for_session` case in `test_substrate_choice`. The check that HOME_NET's public entries are the WAF's edge networks in `test_home_net` went with those networks.
- A write that names no session on a single-slot range now records none, as it already did on OpenStack. A board session whose accounts cannot be read is no longer refused at open; readiness blocks the slot instead.
- An origin's target URL is always `ATTACKER_TARGET_URL`. The per-origin WAF address was the docker shape.
- Found on the way: the two-session acceptance fixture left its first session open when the second failed to open, and every later module waited for a slot that never freed. It now closes the first session.
- `redteam/tools.py` `TOOL_IMAGE` defaults to `fsl-kali`, with a test.

Image digests (computed before and after the fold of the declaration, with the same inputs): `fsl-waf` is unchanged (5b1227892cf313e9). `fsl-kali` changes once, from f34cfaad783d7351 to bc3fa783269d30bc, because `deploy/kali/Dockerfile` was in its bundle (the bundle lists `deploy/kali` as a directory). The cloud builds a new Kali image and rebuilds the slots once. `fsl-wargame-host` is 9b691e0b491f9695 at tag c0ffee and MTU 1450.

Open, left as they are:

- `deploy/suricata/suricata.yaml` `HOME_NET` still listed the four former docker edge subnets (5.188.10.0/24, 177.54.144.0/24, 103.152.220.0/24 and 73.0.0.0/24), and the file still named the interfaces `eth0` to `eth4`. Settled the next day; see "2026-10-21 — The estate sensor's HOME_NET and a repeated lesson move".
- `deploy/proxy/stamp.py` and `deploy/kali/setup.sh` still name `/var/lib/session/origin`, which nothing writes now. Both are in the Kali bundle, so editing them would change its digest again. Removed on 2026-10-25: nothing in `platform/`, `deploy/`, `redteam/`, `test/` or `wargames/` wrote or read the path, so `stamp.py` now only stamps `X-Request-ID` from `/var/lib/session/active`, `setup.sh` no longer creates the file, and the Kali image digest changes once.

Live proof on the new cloud, 2026-10-20 to 2026-10-21:

- `bin/cloud up --replace --sideload platform=<image of the removal commit>`, from the checkout with the documents, passed in 19 min 44 s (18:41:36Z to 19:01:20Z). The store backup `db-20261020T184152Z` was taken and restored. Only `fsl-kali` was rebuilt, as computed above (its bundle held `deploy/kali/Dockerfile`); the `fsl-waf`, `fsl-edge` and `fsl-wargame-host` images were reused. The range reported ready. The VM then ran that checkout with the sideloaded platform image (`FSL_SIDELOADED=platform`).
- Full `bin/verify` on the VM, on the code with the docker substrate removed: unit 1575 passed; acceptance 65 passed, 2 failed, 6 errors, 0 skipped in 10241 s; ratchet ok (`core_loc` 584, `dependencies` 6, `services` 5, `wargame_services` 4, `product_loc` 25016, `tests` 1198). The unit count is lower than the 1718 at 3da925e because the removal deleted tests of removed mechanisms.
- The reference run before the removal, at 3da925e on the same cloud, is in "The product moved to a new OpenStack cloud" above: unit 1718 passed; acceptance 68 passed, 2 failed, 3 errors, 0 skipped in 10024 s.
- Every failure in both runs comes from the one slot (`compute.slots` 1; `FSL-front` takes 4 cores and 8 GB of the project quota). The 6 errors are `409 "1 session is already open on the range; close one first"`: 2 in `test_concurrent_sessions` and 4 in `test_lesson` (the two-session test, and the three later tests of the module, which cannot open a session while the module's `minimal` session is open). The 2 failures are `test_strategy_honesty`: its shared session from `full_run` was deleted by retention (`FSL_RETAIN_CLOSED_MINUTES` 60), because a one-slot run takes about 2 h 50 min; slot resets take 4 to 5 min on this cloud against 70 to 80 s on the previous one. Nothing failed because of the removal.
- The terminal-isolation test (`test_judge_isolation`) probes `/vm-terminal/kali/` and `/vm-terminal/waf/` instead of the removed `/terminal/` (found by the review before gate 2). Live result: on the VM, with the tree of the removal and the fixed `test_judge_isolation.py` copied in, `pytest test_judge_isolation.py` gave 5 passed in 162 s (2026-10-21).

Open from the live runs: the one-slot run outlives the retention window (either the harness keeps a session it still needs, or the window accounts for a long run); the rerun with `compute.slots` 2 waits for the user to raise the project quota to 24 cores, 65536 MB of RAM and 12 instances.

## 2026-10-21 — The estate sensor's HOME_NET and a repeated lesson move

The user decided both on 2026-10-21.

- `HOME_NET`. The four public /24s were in `HOME_NET` because on the
  docker substrate the WAF's outside address sat on those edge networks
  (f4b45cd). On OpenStack they are the origins Kali sends from on
  `fsl-internet`, so the estate sensor took the attacker for the inside
  network. `HOME_NET` is now 10.0.0.0/8, 172.16.0.0/12 and 192.168.0.0/16; the
  estate it watches is in 10.0.0.0/8. The `eth0`-`eth4` af-packet entries went
  too: the wargame host passes `--af-packet=<estate interface>`, which takes
  the `default` entry. The `fsl-wargame-host` bundle holds this file, so the
  rebuild built that image again.
- A repeated lesson move. `POST /api/sessions/<id>/lesson/` with the
  lesson the session is on appended a second entry to `lessons`, and the
  course summary listed the lesson twice (session 1070). It now answers the
  session as it is, with no WAF apply, sensor seed or log seed.
- Live proof. `bin/cloud up --replace --sideload platform=<image of the repeated-lesson-move fix>`
  passed (about 25 min, the wargame host image rebuilt). On that VM
  `bin/acceptance --only test_acceptance,test_ready,test_rule_variables,
  test_bufferless_rule,test_tool_cases` gave 14 passed, 0 failed, 0 errors,
  0 skipped in 1555 s, TP > 0 and TN > 0 among them. Through the API, session
  1077 (F1): two `POST /lesson/ {"lesson": "f1"}` left `lessons` as `[f1]`,
  then `{"lesson": "f2"}` made it `[f1, f2]`.
- After the pre-push review (a follow-up to the repeated-lesson-move fix): `bin/cloud up --replace
  --sideload platform=<image of that code>` passed in about 15 min. Session 1078:
  f1, then f2, then f2 again left `lessons` as `[f1, f2]`;
  `bin/acceptance --only test_judge_isolation` gave 5 passed, 0 failed, 0
  errors, 0 skipped in 158 s.

## 2026-10-21 — Two range slots on the new cloud

- The user had their VM `FSL-front` deleted, with its floating IP
  192.168.2.241, router `fsl-router`, network `fsl-net`, its subnet and the
  group `fsl-front-sg`. It held 4 of the project's 20 cores, which left room
  for one slot only. No snapshot was kept, at the user's word.
- `compute.slots` is 2 in the main checkout's `cloud.yaml`. The platform VM
  and two slots use 18 cores, 40 GB and 9 instances; the 2 cores left fit one
  image builder at a time. The quota was not raised.
- `bin/cloud up --replace` from the main checkout at dev's head, with no
  `--sideload`, ran 13:00-13:29Z and exited 0: backup of 22.8 MB
  (`integrity_check ok`, 6 sessions), new stack, store restored, the
  `fsl-wargame-host` image rebuilt for the new tag, slot 2 booted and
  configured, both slots READY. The VM runs dev from GitHub and GHCR.
- Full `bin/verify` on that VM: unit 1578 passed; acceptance 73 passed, 0
  failed, 0 errors, 0 skipped in 3853 s across 4 processes; ratchet ok
  (core_loc 584, dependencies 6, services 5). The 409 errors of
  `test_concurrent_sessions` and `test_lesson` and the retention failure of
  `test_strategy_honesty` from the one-slot run are gone.
- The rebuilt VM has new ssh host keys, and the operator machine's
  `known_hosts` held the previous VM's. The new fingerprints were checked
  against the cloud-init block of the VM's console log before the entry was
  replaced. `bin/cloud` and `bin/platform-rebuild` use their own scratch
  `known_hosts`, so only the operator's own ssh is affected.
- Backlog triage the same day: the reachability middleware and the session
  open race were already fixed in ac18e68; the WAF terminal item went with
  the docker substrate; `fsl-build` staying after `down` is recorded as
  intended.

## 2026-10-22 — A reset cut short by a restart, and corp's readiness

Two backlog items the 2026-10-21 triage found still real, fixed overnight
while the user was away, and one found by reading the live target.

- A reset cut short by a platform restart. Reset state lived only in the
  platform process, so after a restart the slot read idle and sat in
  `CHECKING`, or read READY over a half-reset estate. A claimed reset now
  leaves `slot-N` in `/data/reset-owed` until the reset ends idle, and the
  served process repeats each owed reset at boot as a close does:
  `reset_slot`, the suppressions it lifts, the in-place reset of the edge and
  the wargames, configure. The first version only configured the slot; the
  pre-push review showed that the wargame host and the edge are reset in
  place, not rebuilt, so it could hand the next session the last one's corp
  and board data, and the next effect snapshot would take that as its
  baseline. Rejected: configure only (that defect); a retry loop when the
  cloud is unreachable at boot (the file stays and the next start or
  `POST /api/range/configure/` recovers).
- corp's readiness. Its healthcheck passed once Ultimate Member was active,
  before the entrypoint made UM's forms, pages and the rbsm form, so a reset's
  `up --wait` could hand a session a half-set-up corp: the likely cause of the
  intermittent "no `_wpnonce`" and "Invalid nonce." in `test_corp_*`. The
  entrypoint now touches `/tmp/fsl-corp-ready` last (in the container layer,
  so a recreate starts without it) and the healthcheck requires it.
- Read live on slot 2: UM's forms are 5 (registration), 6 (login), 7
  (profile), so `corp-rogue-admin` and `corp-normal-registration` posted a
  form (4) that does not exist on the shipped image; they post 5, as the
  acceptance helper already did. `/submit-a-story/` localizes two `"nonce"`
  values (`rbGlobalSubmissionSettings`, `um_scripts`), so the prefetch and
  the test now name the first. The 2026-10-09 finding that 5 was the login
  form came from a local build; the block-theme item was likewise stale.
- Live proof, with this branch's platform and corp images sideloaded
  (`bin/cloud up --replace --sideload platform=... --sideload corp=...`,
  27 min, exit 0, twice): session 1103 on slot 1, a WordPress user planted,
  the session closed (Nova rebuilt the WAF and Kali at 15:59:48Z), the
  platform container restarted 40 s later. The slot read `RESETTING` again,
  Nova rebuilt both VMs a second time at 16:00:35Z, the slot was READY at
  16:03:57Z, `/data/reset-owed` was empty and the planted user was gone.
  Then the full `bin/verify` on that VM: unit 1581 passed; acceptance 73
  passed, 0 failed, 0 errors, 0 skipped in 3759 s; ratchet ok (core_loc 584,
  dependencies 6, services 5). After it, `bin/acceptance --only
  test_corp_authz,test_corp_observe_live` three times in a row, each across
  slot resets: 5 passed, 0 failed, 0 errors each (436 s, 411 s, 577 s), no
  nonce error. Four clean runs make the cause likely, not certain, so the
  nonce item stays open until runs on the GHCR image stay clean too.

## 2026-10-22 — PL4 and the Korean search

Measured live on session 1136 (slot 2) through the product's REST API:
`PUT /api/sessions/<id>/waf/` with `paranoia` 4 and the exclusions, then
`POST /api/sessions/<id>/attacks/` per case, and the ModSecurity audit log
read through `run_on_role gateway`.

- With 920273, 920272 and 942460 excluded on `ARGS:q` under `/search/`, the
  Korean search (`board-normal-search-korean`) still drew 403: 920272
  "Invalid character in request" matched `REQUEST_URI_RAW` (the raw query
  string carries the UTF-8 bytes), then 949110 at score 5. The 2026-10-13
  hypothesis named `REQUEST_URI`; the variable is `REQUEST_URI_RAW`, which
  `rules/crs.py` already accepts as an exclusion target.

| Exclusions under `/search/` at PL4 | Korean | O'Brien | `board-sqli-search` |
|---|---|---|---|
| 920273, 920272 on `ARGS:q`; 920272 on `REQUEST_URI_RAW` | 200 | 200 | 403 |
| the same plus 942460 on `ARGS:q` | 200 | 200 | 403 |
| 920273, 942460 on `ARGS:q`; 920272 on `REQUEST_URI_RAW` | 403 | 200 | 403 |
| 920272 on `ARGS:q` and on `REQUEST_URI_RAW` | 403 | 403 | 403 |
| 920272 on `REQUEST_URI_RAW` only | 403 | 403 | 403 |

- 942460 scores 3, below the threshold of 5, so it is not needed once
  920273 and 920272 are excluded. The SQLi search stays blocked by
  942100, 942130, 942180, 942330, 942390 and 942432 on `ARGS:q`.
- Not changed: the assessment and the lesson text. Whether they should
  teach the `REQUEST_URI_RAW` exclusion is a content decision, left open in
  `docs/STATE.md`.

## 2026-10-23 — A root shell on Kali and the lesson checks

Tester reports of 2026-10-21 on the foundations course, checked by three
review agents against the code and the live range, then fixed.

| Report | Finding |
|---|---|
| F4 step 3, "many errors on the IDS and log side" | Not reproduced; too vague to place. |
| F4 step 7, the theory example is not an XSS rule | True: the only example rule matches `/admin`; a learner who copies it passes step 7 and then gets "no log yet" at step 8. The nudge now says so. The step 7 check is unchanged (requiring `<script` would change what passes). |
| F5 step 1, no sort control | Fixed since: the tester's board image predated the sort control (2026-10-18). |
| F5 step 4, F6 step 2, "no request log from this step's command" after a finished sqlmap | The tester ran sqlmap in a root shell. `http_proxy` is set only in `/etc/profile.d/proxy.sh` (login shells) and `sudo` reset it, so sqlmap went straight to the WAF without the step's `X-Request-ID` marker that the check matches. The check never reads the command log; root's commands were logged. |
| F5 step 5, "no log for this request yet" | A consequence of step 4: the fact it reads was never recorded. |

- Fixes: the `kali` sudoers drop-in keeps `http_proxy` and `HTTP_PROXY`
  (`deploy/kali/setup.sh`); a fact check whose Kali step recorded nothing
  answers `lesson.check.kali_first`; `lesson.check.kali_none` names the root
  shell and says to return with `exit`; the F4 step 7 nudge names the
  `/admin` example.
- Rejected: matching unmarked requests to the step (a request could be
  credited to the wrong step); a transparent proxy with an iptables
  redirect (covers tools that ignore `http_proxy`, but a larger change than
  the report needs).
- Live proof on the platform VM with this code sideloaded
  (`bin/cloud up --replace`, 33 min, exit 0, the Kali image rebuilt). The
  first driver run landed on a Kali that stood through the deploy, still on
  the previous image: `sudo su` had no proxy, the step 4 check gave the new
  root-shell message and step 5 the new `kali_first` message. After the
  slot's close rebuilt its Kali (session 1141, slot 1): in `sudo su`, `sudo
  -s` and `sudo -i` `http_proxy` stays set; sqlmap run from `sudo su`
  passed step 4 (`lesson.sqli.ok.sqlmap`) and step 5 answered
  correctly; step 1's sort control was there.
- The run also showed that a deploy that rebuilds the Kali image leaves the
  standing slots' Kali on the old image until each slot's next close;
  slot 2 was brought up to date with `POST /api/range/slot/rebuild/?slot=2`
  and `/configure/?slot=2`.
- Full `bin/verify` on that VM afterwards: unit 1583 passed; acceptance 73
  passed, 0 failed, 0 errors, 0 skipped in 3969 s; ratchet ok.

## 2026-10-23 — A slot standing through a deploy is rebuilt onto the new images

A deploy that rebuilt an image left every standing slot on the old one: Kali
and the WAF until the slot's next close, the edge and the wargame host until
someone ran `POST /api/range/slot/rebuild/` and `/configure/` by hand.

- The slot plan marks a standing server `stale` when Nova's `image.id` for it
  is not its host's ready image. A server with no image id (boot from volume)
  is never stale, so nothing is rebuilt on a guess.
- `POST /api/range/slot/` has Nova rebuild the stale servers of a slot no
  session holds. `bin/cloud up` already sends it after the images and then
  waits for `REBUILDING` to end and configures, so `up` needs no new step.
- A held slot is not touched; the POST reports it blocked, naming the
  session, and `up` stops there rather than waiting for a `READY` an open
  session never gives. The close rebuilds the stale VMs, the edge and the
  wargame host included, and `reset_in_place()` skips them.
- `ready/` reads a free stale slot `STALE`, not `READY`, so no session opens on
  the old image. A session cannot take a stale slot, so the POST's check of the
  holders cannot race an open.
- Rejected: rebuilding at close only (the first session after a deploy would
  still run the old images); folding the check into `bin/cloud` (every UI
  action is REST first, and a by-hand `POST slot/` should do the same);
  always rebuilding the edge and the wargame host at close (close to READY
  took 95-116 s with every VM rebuilt and 60-66 s with the in-place reset,
  `docs/OPENSTACK.md` §6.1; staleness follows only a deploy).
- Live proof (2026-10-23, `bin/cloud up --replace --sideload
  platform=... --sideload corp=...` with this code, 34 min, exit 0). Before
  it, slot 1's `fsl-wargame-host` booted a wargame host image made on
  2026-10-20 (bundle `3a4ae90c`) and slot 2's one from earlier that day;
  Glance held three wargame host images. The run built the new wargame host
  image, rebuilt both wargame hosts onto it at 21:03:37Z, configured them,
  and both slots read READY; Glance then held one wargame host image. On
  both slots corp had `/tmp/fsl-corp-ready` and UM's forms 5, 6 and 7.
- What this corrects: the corp readiness fix and the corp case fixes of
  2026-10-22 were exercised by the full `bin/verify` and the three
  `test_corp_*` runs on slot 2 only where slot 2's wargame host happened to
  be rebuilt, and slot 1's corp stayed the 2026-10-20 image through all of
  them. The first run with the fixed corp on both slots is the full
  `bin/verify` after this deploy.
- Full `bin/verify` after that deploy: unit 1592 passed; acceptance 73
  passed, 0 failed, 0 errors, 0 skipped in 4083 s; ratchet ok.

## 2026-10-24 — A disabled rule is called disabled

The platform's way to take a Suricata rule out of the learner's ruleset
comments the rule's line out of the rule file until a time. It was named
"suppression" in the API, the model, the code and the docs. In Suricata a
suppression keeps the rule running and hides only its alerts: "Suppressions
can be used to suppress alerts for a rule or a host/network."
(https://docs.suricata.io/en/latest/configuration/global-thresholds.html).
Taking a rule out is disabling: "to disable rules use
/etc/suricata/disable.conf"
(https://docs.suricata.io/en/latest/rule-management/suricata-update.html).
The user ruled to use practitioners' terms as far as possible, so the feature
is renamed end to end. Behaviour is unchanged.

| Old | New |
|---|---|
| `GET/POST /api/rules/suppressions/` | `GET/POST /api/rules/disabled/` |
| `POST /api/rules/suppressions/<id>/restore/` | `POST /api/rules/disabled/<id>/enable/` |
| reply keys `suppressions`, `restored` | `disabled`, `enabled` (also the ingest reply's `restored`) |
| field `restored_at` | `enabled_at` |
| model `Suppression` (table `api_suppression`), related name `suppressions` | `DisabledRule` (`api_disabledrule`), `disabled_rules`; migration 0028 renames, rows kept |
| `platform/suppress.py`: `silence`, `restore` | `platform/disable.py`: `comment_out`, `uncomment` |
| rule file marker `# fsl-suppressed until <t>` | `# fsl-disabled until <t>` |
| views `suppressions`, `restore_suppression` | `disabled_rules`, `enable_rule` |
| `bin/backup` row `suppressions` | `disabled rules` |
| `test/test_suppression.py`, `platform/tests/test_suppress.py`, `test_api_suppressions.py` | `test/test_disabled_rule.py`, `test_disable.py`, `test_api_disabled_rules.py` |

- A rule file written before the rename can still hold `# fsl-suppressed`
  lines on a standing sensor, so `disable.MARKERS` also accepts the old marker
  when a rule is enabled; new disables write only `# fsl-disabled`.
- Migration 0028 was run on a copy of the platform store backed up on
  2026-10-23 (95 rows): the same 95 rows, byte-identical in every column, in
  `api_disabledrule`, and `api_suppression` gone. Unapplying 0028 stops in
  Django's content-type rename hook because `django.contrib.contenttypes` is
  not installed; the platform is rebuilt forward, never migrated back.
- The console has no screen for this feature, so no console string changes.
  The Korean docs had called it by the Korean word the WAF lessons use for
  CRS exclusions; they now use the Korean words for disabling a rule and a
  disabled rule.
- Decision entries above this one keep "suppression" as they were written.

## 2026-10-24 — How courses check a learner's rule

Asked by the user before ruling on F4 step 7, which passes as soon as any rule
is added while the side panel's only example rule (`content:"/admin";
sid:9100001`) is a valid rule for something else. What hands-on courses give
the learner and how they check the rule, from their pages or write-ups that
quote their checkers:

| Source | Given | Checked by | A valid but wrong rule is caught |
|---|---|---|---|
| SANS Holiday Hack 2022 "Suricata Regatta" (https://hackmd.io/@hamayanhamayan/SJnFgxLYj) | the required `msg` and a rules file | a `rule_checker` that counts matches: "we flagged 0 packet(s), but we expected 681" | at the writing step |
| TryHackMe "Snort Challenge – The Basics" (walkthroughs: https://cipherssecurity.com/tryhackme-walkthrough-snort-challenge-basics/) | a blank rules file and a pcap; in task 6 broken rules to fix | the learner types the alert count | at that question |
| TryHackMe "Snort Challenge – Live Attacks" (https://www.jalblas.com/blog/tryhackme-snort-challenge-live-attacks-soc-level-1/) | the attack traffic | the effect: "Block the traffic at least for a minute and then the flag file will appear" | at that task |
| HTB Academy "Working with IDS/IPS" (https://academy.hackthebox.com/course/preview/working-with-idsips) | an existing rule to extend | a typed answer; the rule itself is not checked (forum) | no |
| SuriCap, arXiv 2609.25901 (https://arxiv.org/html/2609.25901) | a scenario and pcaps, no starter rule | load check, visible and hidden tests with malicious and benign traffic, green/red feedback | at the writing step |
| Suricata docs "Adding Your Own Rules" (https://docs.suricata.io/en/latest/rule-management/adding-your-own-rules.html) | one example rule | "double check your rule by doing something that should trigger it" | not graded |
| LabEx "Writing Snort Rules" (https://labex.io/tutorials/linux-writing-snort-rules-656129) | the exact rule to type | `snort -T` only | no (the counter-example) |

Every graded source checks what the rule does, by running it; none passes
"any new rule", and none shows an unrelated complete rule as the only
reference. The candidates drawn from them are in the user-facing summary of
2026-10-24.

Ruling (the user, 2026-10-24): A + C. A: F4 step 7 (`write`) passes only when
the learner's own rule fired, as Holiday Hack's checker does: a `<script`
search sent from the Website pane after the last apply drew an alert from a
sid the learner added (`{kind: rules, match: '<script'}`). A failure says
which: no rule added, no search since applying, no sensor log yet, or "your
rule (sid N) raised no alert on the `<script` request", naming a URL it
alerted on instead when there is one. The learner presses the step's own
check button; the coach rings the rule editor, then the search box, then that
button (`until: applied`, nested `then`). Step 8 (`fired`) becomes reading
that alert's rule_id in Kibana (`about: write`, no new request). C: the theory
shows the rule's form with square-bracket blanks (`msg:"[alert description]"`,
`content:"[string to find]"`, `sid:[rule ID]`), which Suricata refuses as pasted,
in place of the complete `/admin` rule with sid 9100001.

## 2026-10-24 — A slot rebuilt onto a new image resets itself

The `bin/cloud up --replace` of 2026-10-23 built a new wargame host image, and
`POST /api/range/slot/` had Nova rebuild both slots' wargame hosts. Nova takes
the new image id at once, but the server reads ACTIVE for a few seconds before
REBUILD. The plan therefore read the slot not stale and ACTIVE, phase
`CHECKING`, which `bin/cloud` did not wait through. Its `POST configure/`
answered 200 against the VMs from before the rebuild, the rebuilt hosts came
up without the estate sensor, and both slots stayed `CHECKING` ("the sensor
rules are off baseline") until a configure by hand. The deploy before it
worked only because that configure first got 503 and retried.

The close-time reset already waits for this (`api/reset.py`: every rebuilt
server must be seen leaving ACTIVE within `REBUILD_SHOWN`, then ACTIVE again,
before configure). The stale rebuild now uses it.

- `ensure_slot()` returns the servers it rebuilt in `Plan.rebuilt`, and
  `POST slot/` reports them under `rebuilding`, as a close does.
- For a free slot with a rebuilt server, `POST slot/` claims the slot's reset
  and starts it with those servers. `ready/` reads `RESETTING` from the moment
  the POST answers, then `READY` or `RESET_FAILED` with the reason.
- The reset runs `configure_slot()`, not the close's in-place reset plus
  `configure_rebuilt()`: no session used the slot, so there is nothing to
  clear, and a whole configure is what the slot was given by hand before.
  `begin(..., in_place=False)` picks that branch.
- `bin/cloud` counts `RESETTING` as still booting, so it waits for the reset
  before its own `POST configure/`. That configure then runs a second time on
  the reset slot and changes nothing; skipping it per slot would take more code
  than it saves, and the slots that were not rebuilt still get the configure
  `up` always gave them. A by-hand `POST slot/` now needs no configure.
- A held slot and the close-time stale rebuild are unchanged. If the platform
  restarts during this reset, the owed marker makes the next start run a
  close's reset on that slot; the slot is free, so that is safe.
- The console's resetting notice no longer says the last session closed.
- Rejected: having `bin/cloud` wait for each rebuilt server to show REBUILD
  (a by-hand `POST slot/` would still race); treating `CHECKING` as booting
  (it is also a slot that will never be ready without a configure).
- Live proof (2026-10-24): `bin/cloud up --replace --sideload` with this code,
  on a run that built a new wargame host image while both slots stood free.
  `/api/range/ready/`, polled every 10 s, read `STALE` on both slots, then
  `RESETTING` for 38 polls (about 6 min), then `READY`; no configure was sent
  by hand and `up` exited 0 in 36 min.

## 2026-10-24 — Where a slot reset's time goes

The user asked why the acceptance run takes over 60 minutes. It runs about 20
sessions, and each close resets its slot; a reset takes 272-314 s from close
to the next open on this cloud against 60-66 s on the previous one
(`docs/OPENSTACK.md` §6.1). Measured read-only during a live `bin/verify`
(Nova instance action events, the platform's ssh commands sampled once a
second, session times from the store), four resets:

| Phase | Seconds |
|---|---|
| close to the rebuild request and the in-place reset start | 4-6 |
| Nova rebuild of the WAF and Kali (`compute_rebuild_instance`) | 16-19 |
| guest boot to ssh / cloud-init finished | about 45 / 55 |
| WAF and Kali path done after close (off the critical path) | about 75 |
| edge in-place reset | 3-5 |
| wargame host `down -v` | 12-17 |
| `up --wait` board | 115-120, 159-165 when the other slot starts board too |
| `up --wait` corp | 94-110 |
| sensor, rules, log forwarding | 9-11 |
| end of the chain to the next open | 17-32 |

The code path is the one the previous cloud ran in 60-66 s (the same `down
-v`, board then corp, the same healthchecks), so the same work runs about four
times slower on `com01`. Every reset initialises two MySQL data directories
and reruns migrate, seed and `wp core install`. Refuted as the cause: the
image format and Nova rebuild, the guest boot, the platform's polling, the
edge reset, the corp readiness fix of 2026-10-22 (the slowness predates it).
Unverified: why `com01` is slow (guests see QEMU's Sandy Bridge model; disk
type unknown).

Plan, repo only, in order of size: start board and corp side by side
(saves up to about 100 s); a 1 s healthcheck start interval (10-30 s); then
restore a clean data volume made at image build instead of initialising the
data on every reset (unmeasured, the largest). For the user: `com01`'s
`cpu_mode` and disk, and 4 vCPU for the wargame host.

Done, not yet measured live: `start_wargames()` runs each wargame's `up -d
--wait --pull never` at once, one ssh command each, and names every wargame
that failed; the four wargame healthchecks probe every second for their first
120 s (`start_interval: 1s`; the wargame hosts run Docker Engine 29.1.3, read
2026-10-24).

## 2026-10-24 — A reset restores pristine wargame data

What: the wargame host's image build starts each wargame once, lets it finish
its setup, stops it and keeps a copy of every container's volumes under
`/opt/fsl/pristine/<id>/<container><path>` (`deploy/wargame-host/pristine.sh
keep`, run by `setup.sh`). Every start of a wargame, at configure and at each
reset after `down -v`, now creates the containers with `up --no-start`, copies
the pristine data into each new empty volume of a container that has never
run (`pristine.sh restore`), then runs `up -d --wait`. MySQL then skips its
initialisation, the board skips migrate's table creation and creating its posts
and comments (its seed still sets the seeded accounts' passwords afresh), and
corp skips `wp core install` and its plugin setup. corp's entrypoint waits for
`wp db check` to pass, so `wp-config.php` is complete, before it asks whether
WordPress is installed (a review found that asking earlier could read a
half-written file and run the build-time setup again).

Why: about 60-65 % of each wargame's `up` was MySQL initialising its datadir
and about 25 % app setup, on a disk that takes about 27 ms per write
("Where a slot reset's time goes"). A copy of about 0.5 GB replaces that
work. The copy is made at image build, not on the host's first configure,
because the images it was made from are in the same host image: a new tag or
a sideloaded image already makes a new host image, so the copy cannot drift
from the images it runs with, and a rebuilt host needs no slow first start.

The fresh-secrets rule: every session starts from the same data, but nothing a
learner could carry from one session to the next may match. The board's
`seed` now sets each seeded account's password on every start, so each
session's hashes have new salts, and loot from an earlier session does not
match the next session's ground truth. It also moves the seeded posts' dates
to today. corp is scored by the binary-log changes after the session's
start, so an old change cannot be replayed into a new session. corp's
entrypoint now deletes `wp-config.php` before the WordPress image's
entrypoint runs, so each start gets new keys and salts (old cookies and nonces
do not validate), and on restored data it sets the admin password again, so
the admin hash is new too. The binary log stays on; the copied log holds only
build-time rows, which fall before any session's start.

The salts change on every start of the board container, not only after a
restore. Nothing restarts a wargame container during a session (no restart
policy, and the platform never restarts one), so a session's ground truth stays
fixed from its start snapshot to its close.

Rejected:

- A tmpfs datadir: a database container restarted during a session would lose
  the session's data.
- MySQL durability flags (`innodb_flush_log_at_trx_commit`, `sync_binlog`,
  doublewrite off): they shorten the writes but leave the initialisation, a
  smaller gain.
- Smaller redo capacity for the copy: no simple way with MySQL 8.4's
  `#innodb_redo` files; the copy keeps them (about 100 MB per datadir).

Not yet measured live.
- Live proof (2026-10-24, `bin/cloud up --replace --sideload platform=...
  --sideload board=... --sideload corp=...`, 41 min, exit 0; the stale-slot
  reset rebuilt both wargame hosts onto the image with the pristine copy).
  Both slots' sessions closed together, close to READY: 288 s on the code
  before the side-by-side start, 245 s with it, 117 s with the pristine
  restore. The full `bin/verify` on the side-by-side code took 3564 s for
  acceptance against 4038 s before. Sessions 1247 and 1249, opened on slot 1
  one after the other, held different salts and hashes for admin, jiwoo
  and minseo; 1247's hashes submitted to 1249 as loot matched no account
  (`"matched": []`), and 1249's own matched all three.
- Full `bin/verify` on the pristine-restore image: unit 1618 passed;
  acceptance 73 passed, 0 failed, 0 errors, 0 skipped in 2186 s (4038 s
  before the reset speed-ups); ratchet ok. The run now ends well inside
  `FSL_RETAIN_CLOSED_MINUTES` (60).

## 2026-10-24 — Supported Kolla-Ansible releases

The user ruled that the product supports OpenStack deployed with Kolla-Ansible
2025.1 or later; later releases are much the same.

The cloud the product runs on now (`con01`, `com01`, `stg01`, Keystone
10.0.0.10) runs Kolla images tagged 2025.2: `stg01` runs
`quay.io/openstack.kolla/cinder-backup:2025.2-ubuntu-noble`. The earlier docs
named 2026.1 because the previous cloud (192.168.0.100) ran kolla-ansible
2026.1, and the requirement was written from that cloud.

The README files, `docs/OPENSTACK.md` and `docs/ARCHITECTURE.md` (and its
Korean pair) now say "Kolla-Ansible 2025.1 or later". The install commands in
`docs/OPENSTACK.md` use 2025.2 (`stable/2025.2`, `constraints/upper/2025.2`,
`openstack_release: "2025.2"`) and the sources [K1]-[K8] point at 2025.2. The
quickstart page, the constraints URL (a redirect to `stable/2025.2` of
`openstack/requirements`), the Libvirt guide, the Neutron networking page and the
`stable/2025.2` globals, group_vars and neutron task files exist. The
2026-10-20 one-VM trial (§9) ran 2026.1; its 2025.2 commands were not run
again. The TaaS bug in §2.3 was measured on 2026.1 only; the same code is in
`stable/2025.2`, but it is not checked on 2025.x. Earlier entries and the
previous-cloud records in `docs/STATE.md` stay as written.

## 2026-10-24 — The reset's last serial steps and MySQL's rollback segments

What: the board no longer runs `makemigrations` (its migration is committed) and
runs `collectstatic` at build; the wargame host's `down -v` of every wargame and
the sensor run at once; the estate sensor starts beside the wargames; board-db
and corp-db start with `--innodb-rollback-segments=1`, kept in the compose
files so the pristine datadir is made with it; the Kali, WAF and wargame host
images purge and pin out `snapd` and `modemmanager`.

Why: a traced reset (86 s, one slot) still ran these steps in series, and both
rebuilt VMs spent 15-18 s waiting for `snapd.seeded` with no snap installed.
MySQL's InnoDB initialisation read about 720 undo pages one at a time for its
128 rollback segments per undo tablespace. Measurements and sources are in
`docs/TROUBLESHOOTING.md`.

Result: one slot 70-82 s, two at once 98 s (from 117 s). MySQL's start on the
range stayed at about 18 s: the restore's writeback shares the disk with it.

Rejected: deleting the spare redo files from the pristine copy (faster on
scratch datadirs, but the MySQL manual does not say they may be removed); a
smaller `innodb_redo_log_capacity` (same 32 files and syncs).

Tried and reverted: 4 vCPUs for the wargame host (`dba.medium`), which left
the reset time unchanged (one slot 78-79 s, two at once 99 s). Rejected after
a measurement: a copy-on-write restore on an XFS loop file, which saved 4-8 s
per restore and made every commit 2-2.5 times slower
(`docs/TROUBLESHOOTING.md`).

## Kibana's Home and Stack Management entries

- **Question.** Can the learner's embedded Kibana (8.15.0) drop "Home" and
  "Stack Management" from its menu with a Kibana mechanism, so the lessons
  show Discover only? The lessons point at Discover alone (`kibana:` points in
  `scenario.yaml` are `doc`, `hits` and `sidebar`, all Discover).
- **Already used.** The learner's space is created with `disabledFeatures`
  (`SPACE_FEATURES_OFF` in `platform/kibana.py`). Kibana's Spaces page says
  "You have control over which features are visible in each space" and
  "Controlling feature visibility is not a security feature"
  (https://www.elastic.co/guide/en/kibana/8.15/xpack-spaces.html). The spaces
  API says only "The list of disabled features for the space"
  (https://www.elastic.co/guide/en/kibana/8.15/spaces-api-put.html).
- **Home cannot be hidden.** In v8.15.0 the navigation drawer renders Home as
  an unconditional pinned item (`label: 'Home'`, `href: homeHref`,
  `data-test-subj: 'homeLink'`) and the `home` app is registered with
  `visibleIn: []`, so it is not a space feature and has no setting
  (packages/core/chrome/core-chrome-browser-internal/src/ui/header/collapsible_nav.tsx,
  src/plugins/home/public/plugin.ts at tag v8.15.0).
- **Stack Management cannot be hidden here.** The management plugin sets the
  app to `status: inaccessible, visibleIn: []` only when no management section
  has an enabled app (src/plugins/management/public/plugin.tsx at v8.15.0). A
  space switches a management item off only if a disabled feature declared it
  (x-pack/plugins/spaces/server/capabilities/capabilities_switcher.ts). The
  features already off remove Data Views, Saved Objects, Advanced Settings,
  Files, Rules, Connectors and Dev Tools. What is left does not belong to a
  space feature: the Elasticsearch-backed sections (Index Management, Ingest
  Pipelines, Snapshot and Restore, Transforms and others, shown to every
  caller because security is off), License and Upgrade Assistant, and Spaces
  (`spaces.manage` is a constant `true` in the Spaces capabilities provider).
  The documented per-UI switches (`xpack.index_management.ui.enabled`,
  `xpack.snapshot_restore.ui.enabled`, `xpack.license_management.ui.enabled`,
  `xpack.upgrade_assistant.ui.enabled`, `xpack.ilm.ui.enabled` and the like,
  https://www.elastic.co/guide/en/kibana/8.15/settings.html) cover only some
  of them: that page has none for Ingest Pipelines or Transforms, and none
  for Spaces. Hiding the entry for good would need Elasticsearch security with
  roles, which the "Round 3" entry above rejected.
- **Decision.** Nothing changes in the code. The entries stay; their pages
  answer 403 or redirect to Discover at the front (`platform/nginx.conf`).
  Hiding them with the DOM is not done. Not run live: the offline sources
  above were read, the menu was not re-captured.

## 2026-10-25 — F5's last step asks whether 913100 matched the rerun; a check reads the range once per session

- **F5 `still`.** The step asked for one 942 rule that detected the
  `--random-agent` run. The first run's log at step 7 already listed the same
  942 rules, so a learner could answer from memory. The step now asks whether
  913100 is in the rerun's WAF logs (`choice`, `present`/`absent`), read with
  `of: rule_matched, rule: "913100"` from the run's ModSecurity detections. The
  point of the step is the change: the new User-Agent no longer matches
  913100, while the 942 rules still match the payload (the pass line says so).
  A run that kept sqlmap's User-Agent answers `present`, because the answer
  comes from that run's records.
- **Answer checks read the range once.** In round 6, a wrong answer to F1
  `board_ip`/`db_ip`, F3 `site_source`/`client_source`/`xff`/`count` and F5
  `source`/`scanner`/`still` still showed "Checking..." 3.8 s after submit. The
  first check of a step read every map host's interfaces over SSH
  (`_map_found`, kept 30 s) and the cloud's segments (kept 30 s), and the F5
  checks ingested the last 600 s again (up to 5000 documents after a sqlmap
  run). The right answer came seconds later from the warm 30 s cache, so the
  wrong one looked slow. Now the interfaces read for the session's map at open
  answer its address questions until close, the segments are kept for an open
  session, and a recorded Kali run whose detections are held is not ingested
  again. Why these cannot change within a session: a slot is reset only when
  its session closes, and a run is recorded only after its logs have settled
  for `RUN_SETTLED` and is ingested at its recording. An empty read is not
  kept, and an address question the kept read cannot answer reads the slot
  again. Not measured live; the time saved is the SSH reads of the map hosts,
  one cloud segment read and one 600 s ingest per check.
- **Round 6's "remote address of the other slot" was a misreading.** F2
  (session 1311) and F5 (session 1317) showed `10.30.0.111:80`. Both sessions'
  slot holds the WAF at `10.30.0.111` on `estate` (`GET
  /api/sessions/<id>/topology/`); F1 (session 1318) ran on the other slot,
  whose WAF is `10.30.0.225` and board.com `10.30.0.48`. Every slot has its
  own `estate` network with the same CIDR, so addresses from two slots look
  alike. `site.egress_of` takes the address and
  the Kali box that opens the connection from the same slot adapter, so a
  request cannot leave its slot.

## 2026-11-13 — The product is Korean-only

The user's decision: everything a learner or operator sees in the product is
Korean, and there is no English version. Repo files for developers stay
English (code, identifiers, commit messages, docs, the state and decision
files); this is about the product, not the working language.

- **The console string table holds Korean only.** `strings.html` keeps one
  flat table (and one withheld table) under the same keys; the `en` tables,
  the header's language button, the `fsl-language` localStorage key and the
  `navigator.language` pick are gone. `t()` reads the one table; a missing
  key still shows as the key. `common.language` went with the button.
- **A pass line or a worked answer is one string.** The step's `progress`
  record carried `{en, ko}` for `ok`, `line` and `answer`; it now carries the
  Korean text (`console/strings.py` `line()`).
- **One learner map.** The English `deploy/topology/range-openstack.gns3` was
  removed and the Korean drawing took its path, its name now plain
  `range-openstack` and its project id the Korean file's, so the slot maps
  already loaded under that id keep their ids. `api/maps.py` loads one
  project per slot instead of one per language, `tidy` removes the English
  slot maps still held under the `range-openstack slot ` prefix, and
  `GET /api/topology/` takes no `language`. The pair test went with the pair;
  a test now holds that every drawn word on the learner map is Korean except
  host and network names and IDS, and none is on the system map. The system
  map stays English: it is for development and is never shown to learners.
- **`zone_of` accepts the Korean caption only.** It accepted the English
  caption too (`internet`) while the English map existed; no screen shows
  that word now.
- **What stays English on screen, and why.** Third-party tools framed in the
  console keep their own UI: Kibana (the platform sets no `i18n.locale`;
  Kibana's bundled translations are zh-CN, ja-JP, fr-FR and de-DE, no
  Korean — not re-checked against the running 8.x release), the GNS3 web UI,
  pfSense/OPNsense, the ttyd terminals and the tools run in them (sqlmap's
  output). The targets are what they are: the board is a Korean site, corp an
  English WordPress site. API error `detail` texts (for example a map that
  could not be loaded) stay English, as does the map page's own sign-in
  failure line in `deploy/gns3/auditor.html`: both are diagnostics, and
  Korean in those files would be Korean outside the places CLAUDE.md allows.

## 2026-11-13 — The six foundations become two courses

The product owner took F1-F4 live as a first-time learner and they failed him,
although six AI reviewers had found nothing (feedback in the session notes).
The lessons were rewritten, not reworded, and regrouped at his decision.

- **Two courses.** Course 1 (`course.logs.title`) is F1-F3 and only reads the range;
  it will later run many learners on one shared slot, so every step finds the
  learner's own request by their own search word or marker. Course 2
  (`course.attack.title`) is F4-F6 and changes the range (IDS rules, sqlmap, the WAF exclusion),
  one learner per slot. `scenario.yaml` declares `courses:`; lesson ids stay
  `f1`-`f6`, since the steps, defenses and records are keyed by them and a
  rename would only move names. The next lesson stays inside a course.
- **Theory out of the step flow.** A course opens on a briefing (what the
  course does, the reference cards folded, Start); the same cards stay in a
  left reference column (`lesson.ref.heading`) the rail opens. The note's theory card is gone. Start is
  the existing `POST .../steps/<first>/ {state: reached}`, so an agent needs no
  new call.
- **A highlight never shows an answer before the work.** A Kibana point may
  name `kql:`; the ring stays on the query bar until the learner's own
  submitted query matches. Every Kibana step in F3-F6 names it.
- **KQL is taught once and used.** The reference card lists field : value,
  wildcards, quoted values, and/or/not, ranges and field : *, with this
  range's field names; course 2 steps ask the learner to write the query
  rather than paste it.
- **F1 asks what the map shows.** The zone quiz is gone (no platform grades
  zone membership); F1 asks the attacker's and the web server's addresses,
  the path from kali, the DMZ network and the log server. The `zone_of` fact
  had no step left and was removed.
- **F3's last four steps were wrong questions.** They chained answers, said
  "destination" loosely, needed the WAF address recalled from the map, and
  assumed KQL edits. They are now: the count of the learner's own word, the
  source of the row whose `destination` is waf's address, of the row whose
  `destination` is board.com's, the host using it, X-Forwarded-For, and a
  count the learner writes with and/not. Addresses are in the reference
  column (`GET /api/sessions/<id>/lesson/addresses/`). The `waf_logged` fact
  had no step left and was removed; the WAF's logging policy is in the fields
  card.
- **The learner map is an enterprise logical diagram.** Zones internet, DMZ,
  DB zone and management network: DMZ and DB zone are the zone names of KISA's
  ISMS-P 2.6.1 (network separation into DMZ, server farm, DB zone, development
  zone and the like), which also lists a DB server in the DMZ as a defect, so
  board-db keeps its own zone; the earlier Korean names for a service network
  and a monitoring network were this project's words. Labels are addresses alone; no interface, port or
  Docker bridge name. Each IDS is a sensor box fed by a dashed line from the
  host whose traffic it sees (the edge and the wargame host really run them).
  Green arrows show the request flow internet → firewall → waf → board.com.
  The system map is unchanged.
- **Review includes an answer-blind walk.** A fresh agent given only the
  on-screen text and a description of each tool screen walks the lessons;
  rounds 1-3 went 43, 46 and 48 of 48 steps, each flagged step fixed.

## 2026-11-13 — FSL leaves the product's names; the prefix is `cr`

FSL is the name of the funding programme, not of the product. The console's
brand (`common.brand` in the string table, now also the default page title and
the source of the header mark `common.brand_mark`) says "cyber training range"
in Korean, the English prose says "cyber range", and every name the code
creates or reads takes the prefix `cr`. `range-` was rejected:
`platform/range/`, `range.openstack.connect`, `range.internal` and the project
`fsl-range` would read as `range-range` and make every grep ambiguous. `cr` and
`CR_` had no hit in the repo; the near miss `crs` (OWASP CRS) never appears as
`cr-` or `CR_`.

| What | Before | After |
|---|---|---|
| Brand | `common.brand` "FSL" + "training range", titles `FSL`, mark `F` | "cyber training range", default title from `common.brand`, mark from `common.brand_mark` |
| Django package | `platform/fsl/`, `fsl.settings` | `platform/cr/`, `cr.settings` |
| Range hosts, role images | `fsl-edge`, `fsl-waf`, `fsl-kali`, `fsl-wargame-host` | `cr-edge`, `cr-waf`, `cr-kali`, `cr-wargame-host` |
| Fabric | `fsl-internet[-N]`, `fsl-estate[-N]`, `fsl-mgmt`, `fsl-<origin>`; groups `fsl-range`, `fsl-reach`, `fsl-mgmt`, `fsl-build`; keypair and port `fsl-platform[.mgmt]` | the same with `cr-` |
| Tags and metadata | `fsl.segment.id`, `fsl.slot`, `fsl_host`, `fsl_slot`, `fsl_image`, `fsl_bundle`, builders `fsl-build-<host>` | `cr.segment.id`, `cr.slot`, `cr_host`, `cr_slot`, `cr_image`, `cr_bundle`, `cr-build-<host>` |
| Platform VM | stack and resources `fsl-platform`, `/opt/fsl`, `fsl-platform.service`, `fsl-venv`, the `fsl` drop-ins under `/etc` | `cr-platform`, `/opt/cr`, `cr-platform.service`, `cr-venv`, `cr` drop-ins |
| Compose | project `fsl`, containers `fsl-*`, volumes `fsl_*`, user `fsl` (uid 10001) | `cr`, `cr-*`, `cr_*`, `cr` (same uid) |
| Images | `ghcr.io/nekonic/fsl-{platform,gns3,board,corp,corp-db}` | `ghcr.io/nekonic/cr-…` |
| Settings | `FSL_*` | `CR_*` |
| In-range paths | `/opt/fsl`, `/var/lib/fsl*`, `/var/log/fsl`, `fsl-users`, OPNsense `fsl.rules`, `fsl.yaml`, `/conf/fsl-settled`, `FSLSEED` | `cr` forms, `CRSEED` |
| Wire and storage keys | `fsl.records=`, `fsl.customers=`, `fsl.exit=`, `fsl.platform.answer=`, thread names, `localStorage` `fsl-*`, `__FSL_AUDITOR__`, Elasticsearch `fsl_slot` | `cr` forms |
| Rule disable marker | `# fsl-disabled` | `# cr-disabled`; `# fsl-disabled` and `# fsl-suppressed` are still read |
| Test signatures | `msg:"FSL …"` | no prefix, like the shipped rules |

Left as they are: the cloud identity made by hand (Keystone domain `fsl`,
project and user `fsl-range`, keypair `fsl-claude`, the Glance family
`fsl-opnsense-<version>`), operator-machine paths (`~/.config/fsl`,
`~/.ssh/fsl_*`, `~/.ssh/fsl-platform`, `~/.cache/fsl*`), the repository name
`fsl-project-mvp`, and the historical records (this file,
`TROUBLESHOOTING.md`, archived plans, dated specs, the history in `STATE.md`
and `now.md`). Search those for the old names.

The live cloud keeps the old names until the code that made them takes it down
and the renamed code brings it up again (`docs/OPENSTACK.md` §5.4). Rejected:
teaching the new code every old name for one hop; the old checkout's
`bin/cloud down` already backs up the store and removes the old resources. The
one guard kept: a VM still holding `fsl_platformdata` makes `platform-rebuild`
and `cloud down` refuse, so a rebuild cannot read the old VM as empty and
delete it. Learners lose their remembered tabs and notes once
(`localStorage`), and the first image build replaces `fsl-opnsense-<version>`
under the same name because the edge's bundle changed.


## 2026-11-13 — The range is one range host; a slot is a compose project

Approved at gate 1 (option a2 of
`docs/superpowers/specs/2026-11-13-container-range-design.md`, measured in
`docs/superpowers/specs/2026-11-13-range-host-proto-results.md`). The user's
rulings, each recorded here:

1. **Two VMs in all.** The platform VM stays as it is (`cr-platform`,
   `m1.large`). One range-host VM, `cr-range`, on the existing flavor
   `dba.range` (6 vCPU, 16 GB, 60 GB), runs every slot as the compose
   project `sN`. No new flavor is asked for; the cloud's existing resources
   are used.
2. **The edge is a Linux router container.** `sN-edge` is alpine with
   nftables (`deploy/edge/`), holding only `NET_ADMIN`, never privileged;
   its rules are the OPNsense filter it replaces (the range never reaches the
   edge itself, anything crosses it). Suricata stays two separate containers,
   one per leg, as in the prototype. OPNsense goes: `range/opnsense.py`,
   `deploy/opnsense/`, the `opnsense:` section of `cloud.yaml` and the
   `fsl-opnsense-*` image. A real firewall product (OpenWrt with LuCI is the
   candidate) waits for a corp/DMZ lesson that needs one (`docs/STATE.md`
   backlog).
3. **Containment by configuration, and the configuration is tested.**
   Learner-facing containers (Kali, the WAF, the four target containers, and
   the edge) run with `cap_drop: [ALL]` and a listed set of capabilities,
   `no-new-privileges`, docker's default seccomp and AppArmor profiles,
   memory and process limits, no `privileged`, no docker socket, no host
   network or namespace, and no host path but the WAF's audit log directory
   (superseded by the 2026-11-14 entry "The WAF mounts its log file, not its
   log directory": it mounts the one file).
   Kali holds `NET_RAW` and `NET_ADMIN` (a SYN scan works, checked live) and
   the set-uid and file-owner capabilities its customers account and `sudo`
   need; the WAF holds what nginx needs to bind 80 and drop to www-data.
   dockerd runs with `userns-remap`, so root in a container is an
   unprivileged host user; the sensors and the nsenter addressing work under
   it (the sensors run `userns_mode: host`, measured live). Every slot
   network is `internal` with `gateway_mode_ipv4: isolated`.
   `platform/tests/test_containment.py` fails `bin/verify` when the rendered
   slot compose breaks any of this, and `test/test_range_isolation.py` is the
   live check (no range-host sshd, no platform, no Internet, no metadata
   service and no other slot from Kali, the WAF or the board). No gVisor.
4. **The sqlmap variant cases all stay.** The corp WordPress install's
   pretty-permalink loopback request to the real `corp.com` is a backlog line;
   in the slot, `corp-wp` maps `corp.com` to 127.0.0.1 (the prototype's fix),
   since the slot has no egress at all and the registration case needs the
   permalinks.
5. **The reset is the prototype's `reset_fast`.** `slot.sh reset N` recreates
   Kali and the WAF, removes and restores the targets from the pristine copy
   in parallel, flushes the edge's neighbour table and empties the logs in
   place; the edge and both sensors keep running and the platform reseeds
   their baseline rules. Nothing is rebuilt by Nova.
6. **`services` stays 5.** The per-slot compose file lives under
   `deploy/range-host/` as `deploy/wargame-host/sensor.yaml` did, and is not
   the platform's own stack; `bin/measure` does not count it (the user's
   ruling on the design's open question).

Found while bringing it up, and settled in code:

- The range host boots from the stock Ubuntu image with its setup bundle in
  the user data, and pulls its images from GHCR through a port on the
  platform's network (security group `cr-egress`, no ingress). Once setup
  reports ready the platform detaches that port, so the host keeps no way
  out and a rebuild of the platform's stack finds no port of it on the
  stack's network. Rejected: a range-host Glance image built by a builder,
  because the quota held no room for a builder beside the eight slot VMs the
  cut-over keeps until the range host is proven.
- Ubuntu's rsyslog drops to the `syslog` user and AppArmor confines it to
  `/var/log`, so the slot logs live in `/var/log/cr/sN/`; an ACL lets
  `syslog` read the WAF's audit log, which nginx writes as the remapped
  www-data (superseded by the 2026-11-14 entry "The WAF mounts its log file,
  not its log directory": the log is `0644` in `adm`, read without an ACL).
- The board's ground truth is read inside the board container (`api/loot.py`
  through the board role's runner); the board publishes no port.
- Every command goes to one host now, so the platform shares one ssh
  connection per range host (`ControlMaster auto`, `ControlPersist 60`), and
  the range host's sshd takes 256 sessions per connection; the time source
  and the collector rule are set once per range host, not per slot (ten
  slots configured at once restarted `systemd-timesyncd` past its start
  limit).
- `/api/range/images/` and `api/sideloaded.py` are gone with the image
  builder; `DELETE /api/range/leftovers/` removes what the VM range left, and
  `bin/cloud up` calls it only after every slot is READY.

## 2026-11-14 — The WAF mounts its log file, not its log directory

A review of the range host found that root in the WAF container could steer
root on the range host. The WAF mounted `/var/log/cr/sN/waf`, a directory
owned by the remapped range, so the learner (root in the WAF) could replace
`audit.log` with a symlink. Two host processes then opened that name and
followed the link: `slot.sh reset`, as root, emptied it with `: >` (a link to
`/etc/passwd` truncates the host's password file), and rsyslog's `imfile`, as
`syslog` in `adm`, read it (rsyslog's imfile documentation: "For symlink-ed
files this does **not** contain name of the actual file"), so a link to
another slot's log or to `/var/log/auth.log` shipped those lines as this
slot's records.

- **Ruling: the WAF mounts the one file.** `slot.yaml` binds
  `/var/log/cr/sN/waf/audit.log` onto `SecAuditLog`'s path; the directory is
  root's `0755`, which the container's root, mapped to an unprivileged range,
  cannot write. The WAF keeps writing its own log (owner the remapped
  `www-data` and `adm`, `0644`, which `syslog` reads without an ACL; a group
  outside the remapped range left the container's root, which opens the
  serial log in nginx's master, without `DAC_OVERRIDE` on it, and ModSecurity
  wrote nothing), and cannot rename, unlink or add a name. `slot.sh prepare` makes the
  directory root's, removes any other name in it and recreates `audit.log` if
  it is not a regular file, before every `up` and `reset`, which also clears
  what the old layout left. `acl` leaves the range host's packages.
- **Every other host-side operation was checked and none follows a learner's
  name.** Kali, the edge and the targets mount no host path. The targets'
  volumes are refilled from `/opt/cr/pristine` only while freshly created,
  empty and never started. The sensors' directories are root's and mounted
  only into the sensors, which no learner has a shell in. `slot.sh down`
  uses `rm -rf`, which does not follow links. The platform's reads of
  learner boxes (`operator_log`, loot, effect) run inside the container
  through `docker exec`. `nsenter -n` in `slot.sh` and `rangehost.listed`
  enters only the network namespace and runs the host's `ip` and `ethtool`
  on interface names, not paths.
- Rejected: keeping the directory mount and opening the log with
  `O_NOFOLLOW` in `slot.sh` (no POSIX shell way, and rsyslog has no such
  option for `imfile`, so the read path stays open); shipping the audit log
  through Docker's log driver (the WAF's stdout also carries nginx's own
  lines, and Filebeat's parsing would change).
- `test/test_range_isolation.py` proves it live: the WAF plants links to a
  host canary, `/etc/passwd` and another slot's log; a line the WAF writes
  reaches only its own slot's index; after the session's reset the canary is
  unchanged and absent from Elasticsearch, and the directory holds only
  `audit.log`. `test_attacker_reach.py`'s port scan, which scanned nothing in
  a slot (Kali has only `eth0`, its route out), became a scan from Kali of
  the range host, the platform and the range host's `mgmt` network in the
  same file.

## 2026-11-14 — Answer-blind walk round 16: what changed in the lessons and why

An answer-blind walk of both courses on the live range found nineteen
problems. The rulings that change behaviour, not only wording:

- **A pass never moves on by itself.** A short pass line (30 characters or
  fewer) used to advance after 1.5 s, a long one waited for Next. A learner
  who had learned to press Next after the tick pressed it once more after a
  short pass had already advanced, and skipped the next step unanswered (F2
  `parameter` to `sort`). Every pass now waits on its step with the tick and
  the blue Next; a long line still says to press Next. The lesson's last step
  keeps its rule: a short last pass opens the next lesson after 2 s.
  Supersedes the short-pass auto-advance recorded earlier.
- **F3's solo count needs the query.** Its count (`url` holds the word and
  `destination` is not waf's address) was already on the screen of the step
  before, so it could be answered by counting rows. The check now carries
  `kql`, a regular expression the learner's Kibana query must match; the
  console sends the query Kibana holds (`submittedQuery`) with every answer of
  a step that opens Kibana, and a query that does not match fails with
  `lesson.logs.wrong.upstream.kql` whatever the number. Rejected: a count the
  table cannot show (all searches, or extra searches): it depends on the
  learner's time range and still does not make the learner write `not`.
- **F3 drops `site_host`.** It asked for the name of the host whose address
  the step before had just asked for (waf), the same fact twice; `host_of` had
  no other user and is gone. The pass line of `site_source` now says the
  address is waf's and why.
- **F4 `fired` asks the alert's `destination`.** Asking its `rule_id` asked
  back the sid the learner had typed one step before. The destination is read
  from the alert (`alerted_destination`: `dest_ip` of the alerts the learner's
  own added rules raised) and is waf's address, which is what the pass line
  explains: only the sensor on the way in saw the blocked request.
- **No step gives its answer, or a later one, away.** F2's method step told
  the learner the search row's name began with `?q=` (the answer of
  `parameter`), F2's sort step that the new row began with `?sort=` (its own
  answer); both now say the name begins with `?`. F3's client step and the
  address reference said the browser connects from the customers place (the
  answer, and F5's Kali source in the same way); removed.
- **The result page numbers lessons as the catalogue does.** The catalogue
  numbers each course's lessons from 1; the session page numbered them by
  their order across the wargame (4 to 6 for the attack course). A session
  whose lessons all belong to one course now numbers them within it, names the
  course in the header, restarts "from lesson 1", and shows the course's own
  score note (`course.attack.scores`, or the course-free `result.scores`
  without sqlmap or lesson numbers for the logs course).
- **A run still being collected when Next is pressed keeps its window.** A
  poll of a Kali step that came back after the learner moved on was dropped,
  so the platform recorded the run (and passed the step) but the console kept
  the "collecting" row without a Kibana window, and later steps offered only
  the whole session. The console now keeps a late verdict's row, and recalls
  the run whenever the row it holds has no window.
- **Placement.** A map zone callout first tries spots outside the zone that
  overlap no other zone, before rows inside it (inside, F1's DMZ callout sat
  on sw1's link ends beside waf's address). A rule-line ring in the IDS rule
  editor is drawn inside its line, as terminal rows are, so it no longer cuts
  the rule above. The Top values callout keeps off every text line of the
  field popover ("Calculated from N records"). The console removes Kibana's
  `discover:searchText` (the Document panel's field search, which Kibana
  keeps across sessions) on every load.
- **The WAF keeps UTC.** Setting the WAF container's `TZ` to Asia/Seoul (as
  the Kali image is) was checked and rejected: ModSecurity writes the audit
  log's `transaction.time_stamp` in local time without a zone, and both the
  ingest pipeline and `ingest/elastic.py` read it as UTC, so a KST WAF would
  move every WAF detection nine hours.
- **F6's IDS miss is the defence, and the text says so.** sid 9000001 ("SQLi
  attempt - URI") is in `local.rules` and `no-xss.rules`, so the learner sees
  it on F4's rule screen; F6's `overbroad` loads `no-uri-sqli.rules`, which
  leaves it out. Shown live on the range host: the slot's estate sensor logged
  "3 rules successfully loaded" when F6 opened and 4 after the reset, and
  Elasticsearch has 2,121 alerts from 9000001 for the F5 run before and none
  for F6's dump of about 6,000 requests. The pass line now names the rule the
  lesson removed instead of saying the IDS has none. Many of sqlmap's ORDER BY
  payloads carry no quote, `-- ` or `union select` and would pass 9000001
  even when it is loaded (`docs/STATE.md` records it as fragile); that is a
  detection gap to measure, not changed here.
- **The router wears a router.** `host-router` (affinity's blue router
  glyph) replaces `host-firewall`; see the symbols paragraph above.

## 2026-11-14 — Answer-blind walk round 17: what changed in the lessons and why

An answer-blind walk of both courses on the live range found fifteen
problems. The rulings that change behaviour, not only wording:

- **A replay's ordinary search is no longer charged with the attack's
  alert.** F4's last step stayed "checking" on the ordinary search for over
  seven minutes. Root cause, measured in the slot's index: the mixed-case
  attack alerted at 23:50:27.649 and the ordinary search reached the WAF at
  23:50:31.159, 3.5 s later. `views._alerts_for` took every Suricata alert
  with the browse marker within `RECORD_SLACK` (5 s) of a request, so the
  ordinary search was judged to have drawn the learner's own rule, and the
  check failed on every poll until a search sent more than 5 s after any
  attack. The rule's `rev` was not the cause; the walk's other run spaced the
  two searches further apart. An alert now belongs to a request when its
  `http.url` is the request's; an alert without a url still counts on the
  browse marker. The console kept polling; nothing in its state machine was
  wrong.
- **F4's `nocase` step needs `rev` raised.** The card asks for it; the check
  now compares the rule's `rev` with its last case-sensitive version applied
  in the session (`lesson.raised_rev`) and says
  `lesson.xss.fail.nocase.rev` otherwise. A rule written with `nocase` from
  the start passes.
- **No step's answer is on the pane, the map or an earlier card.**
  - F4's first reading step asked the status, which nginx's 403 page shows
    in the pane. It now asks what `<` became in the request URL DevTools
    shows (`escaped`, `%3C`; the address bar shows `<`). The mixed-case
    step asks that request's Total Score in Kibana instead of the status,
    and the CRS reference no longer says CRS ignores case. Rejected: a WAF
    block page without the code, which changes the range image, sqlmap's
    view of the WAF and every lesson that reads a 403.
  - The Suricata reference no longer says `%3Cscript` is matched with
    `content:"<script"` (F4's rule).
  - F2's method and missing-post steps: the HTTP reference no longer says
    the browser uses GET or that 404 means a missing page, and the card no
    longer says post 9999 does not exist.
  - F3 drops `client_source`: its answer (the customers address) was the
    X-Forwarded-For step's, so the Document flyout was never needed. The
    `and not` count comes right after the first count, before any card or
    pass line says how many rows each leg leaves, and the steps after it
    read the row it leaves: its `source_ip`, then (solo) its
    `request_header.x_forwarded_for`. The count's pass line no longer
    explains the two legs; F1's path and waf pass lines no longer say waf
    opens a new connection or what lesson 3 reads.
  - F6's trace step asked the source IP of the 500 records, which is kali's
    address, on the map and asked in F5. It now asks how many 500 records
    the run left (`server_errors`). sqlmap prints the same count at its
    end; that is another tool's output, not our text, and the pass line asks
    the learner to compare the two. This reverses the earlier ruling that
    the count was not the question.
  - The catalogue's F6 summary and "learns" line no longer say the attack
    drew no alert (F6's alerts step), and the exception reference no longer
    says an excluded parameter is neither detected nor blocked.
- **The Website pane browses from customers, and the text says so once it
  is no longer an answer.** F1's path step starts at customers (the green
  arrow's start) instead of kali. The first text that names the Website
  pane's place is F3's X-Forwarded-For pass line; course 2's brief repeats
  it next to Kali's.
- **Console.** "Open website" loads the board's front page when the pane
  shows another page. Every pass that waits for Next says so, however short
  its line. The run-still-logging line shows once (the status line), not
  also under the check button. Callouts keep off Discover's histogram (its
  axis labels are drawn, not text), the whole Top values popover, and the
  DevTools toolbars and column header. The session page shows the WAF
  terminal tile in a lesson session only when one of its lessons edits the
  WAF (`changes_waf` on the catalogue card).
- **Still open.** F5's source step asks kali's address, which the map shows;
  the walk did not flag it, and it is left for the next round.

## 2026-11-14 — The acceptance suite runs one sqlmap case and fills the slots as they free

The user asked for the test runs, above all the live acceptance suite in the
full `bin/verify` (about 25 minutes, 91 tests), to be cut as far as they go
without weakening what they prove.

Measured first (the platform VM, four slots, read-only where a session was
not needed):

| Where the time went | Seconds |
|---|---|
| unit suite before the acceptance suite, one process on the 2-vCPU platform VM | 300 |
| warm-up session, then the wait for its slot's reset | about 120 |
| red-team run: six sqlmap cases (40, 40, 51, 51, 54, 53) | 290 of 306 |
| `origins_session`: 30 fires of the control case with `origin: rotate`, read by no test since 2026-10-16 | 64 |
| `test_range_isolation`'s nmap scan of the `mgmt` /24 | 136-152, and 44 of 258 hosts skipped by `--host-timeout` |
| each `range.run` call (a Django process in the platform container, then ssh) | about 3, before the command runs |
| a slot reset alone | 53 |
| the solo phase (two-session modules) after every worker had finished | 193 |
| worker imbalance: `test_range_isolation` had no entry in `durations.json` (weighed 10 s, took 546 s) | worker 3 904 s, worker 2 159 s |

What changed and why each keeps the proof:

- **One sqlmap case in the red-team run.** `full_run` passes
  `redteam/run.py --cases` a copy of `board.yaml` written in the platform
  container without the five sqlmap variants; `board-sqli-orderby-sqlmap`
  (the dump) and every benign case stay. No acceptance test reads a variant's
  verdict: they reached only the totals, which the remaining cases keep
  above zero (TP and TN). The cases stay in `redteam/cases/` (the gate-1
  ruling that kept them) and the console and lessons fire them as before.
  `CR_SQLMAP_VARIANTS=1 bin/verify` runs all six, for measuring detection
  against every variant's real traffic (the known gap: sid 9000001 misses
  many ORDER BY payloads). The tool path from an origin (`test_tool_cases`)
  still fires the dump from `hk`.
- **The rotation fires go.** `test_rotation_does_not_stay_in_one_place` was
  deleted on 2026-10-16 ("every test states its need or goes"); its 30
  attacks and the unread `map` read stayed in `origins_session`.
- **Probes side by side.** `range.run_side_by_side` runs a host's probes in
  one shell and returns each one's exit code and output, so
  `test_range_isolation` and `test_judge_isolation` make three calls per
  module instead of thirty-odd. Every probe is the same command from the
  same container; the attacker's batch now also carries the two
  connections that must succeed (the WAF and the board through the edge),
  so the batch is shown able to see a reach.
- **The scan scans every host.** `--min-hostgroup 256 --min-parallelism 256`
  scans the 258 addresses in 4-5 s with no host skipped (live: the WAF's
  port 80 is still reported open when listed); before, 44 hosts hit
  `--host-timeout 90s` and were never scanned. The test now fails when nmap
  skips a host.
- **Fewer sessions.** Each close costs a slot reset (53 s alone, 101 s for
  three at once). `baseline_rules` opened a session only to read the rules:
  each rule-changing session now checks its own rules on open
  (`runs_the_declared_rules`), which checks every such session rather than
  one. `test_enabling_brings_the_rule_back` reads the `disabled` session
  after its attack is scored instead of opening its own. The containment
  checks (`test_judge_isolation`, `test_range_isolation`) use the standing
  session; the planted-link test plants in it and closes it, and reads the
  host afterwards by slot (`run(..., slot=N)`) instead of opening a session
  to name one. The lesson's `minimal` session closes with the guided one
  instead of staying open through both course walks.
- **Groups fill the slots.** `bin/acceptance` starts one pytest process per
  group of modules sharing a session fixture and starts the next as soon as
  a slot is free, instead of four fixed workers and a solo phase after them.
  `test_concurrent_sessions` takes two slots and starts first; the
  two-session lesson test moved into it, so `test_lesson` takes one.
  Tests that tied two fixtures into one process moved to a module of the
  fixture they read (the rule tests to `test_rule_changes`, the
  empty-objectives check to `test_objectives`, the check before silencing to
  `test_board`, the real rule set's credit to `test_acceptance`).
- **The unit suite runs beside the acceptance suite.** Split over up to four
  processes by file size; in a full run it starts first at `nice -n 19` and
  its result is printed after the acceptance suite. `--fast` runs the same
  split in the foreground (locally 79 s to 37 s).
- **The warm-up does not wait for its reset.** It validates the rules on its
  own session's sensors before closing it; the acceptance processes wait for
  a ready slot themselves.

Not cut, and why:

- `PLANTED_WAIT` (60 s): it proves an absence (no host file shipped), so it
  stays a fixed wait.
- The three corp sessions: the binlog tests assert the credited set is
  exactly the one exploit's key, which one shared session could not show.
- `test_window_correlation` and `test_strategy_comparison` keep a session
  each: `test_strategy_comparison` asserts exactly one TP per strategy.
- The slot reset itself (53 s): platform and range code, not the suite.

First live run of the new suite (`bin/acceptance` alone, four slots, before
the scope fix in `test_judge_isolation`): 86 passed, 5 errors (that fixture),
1 skipped in 662 s across 14 processes, against 1101 s across 6 processes
for the previous full `bin/verify`. The red-team group took 99 s (540 s
before), `test_range_isolation` 224 s (546 s; its scan 10 s, 153 s before).
Full `bin/verify` with the fix, on the platform VM: 13 min 18 s start to
result (about 25 min before); acceptance 91 passed, 0 failed, 0 errors, 1
skipped in 746 s across 14 processes; the unit suite's two processes took
329 s and 192 s beside it. With the unit suite beside it the acceptance run
was slower than alone (746 s against 662 s; the platform VM has two vCPUs),
still shorter than running the unit suite first. `durations.json` holds the
larger of the two runs' seconds per module, so a module whose time varies
(the red-team group took 99 s and 248 s) is not started last. The full
`bin/verify` with those durations: 11 min 54 s start to result, acceptance
91 passed, 1 skipped in 665 s.

| Module | Before (s) | After (s) |
|---|---|---|
| test_acceptance (red-team run) | 540 | 99-248 |
| test_range_isolation | 546 | 224-246 |
| test_corp_authz | 303 | 385-387 |
| test_origins | 292 | 151-198 |
| test_lesson | 157 | 168-246 |
| test_concurrent_sessions | 36 | 160-246 (now also the two-session lesson test) |
| test_judge_isolation | 134 | 28 |
| test_disabled_rule | 131 | 93-108 |
| test_window_correlation | 87 | 40-97 |
| test_strategy_comparison | 29 | 83-162 |
| acceptance wall | 1101 | 662-746 |
| full `bin/verify`, start to result | about 1530 | 714-798 |

Per-module seconds include the wait for a free, reset slot, which now falls
on whichever group opens next; the wall time is the number that fell.

## 2026-11-14 — Answer-blind walk round 18: what changed in the lessons and why

An answer-blind walk of both courses on the live range found seventeen
problems. Two were left by ruling (Next skipping steps, and whether XSS
counts in the score); the rest changed as below.

| # | Finding | What changed |
|---|---|---|
| 1 | The browser's "leave site?" dialog on Next lesson and on close | Both ttyd terminals start with `-t disableLeaveAlert=true`; no console template registers `beforeunload`, so ttyd was the only source |
| 2 | F4 `write` passed `content:"/search/"` | `rules` checks carry `quiet_on` (two plain searches); a rule whose URI contents all appear in one fails with `<fail>.broad` before any alert is read (`lesson.alerts_on`). Applies to `write` and `nocase` |
| 3 | F4 replay sat at "checking" with such a rule | `views._benign_fault` names the fault (`.alerted` with sids and URL, `.status`, `.waf_logged`) and answers `loud: true`, which the console says even on a silent poll; the benign line reads `lesson.replay.failed` |
| 4 | F6 `narrow` silent on a deleted Paranoia Level line, then passed | `waf_changed` also needs the posture's level line; a deleted or changed one fails loud with `<fail>.paranoia` and the line to put back |
| 5 | Early answers: F5 source on the address table, 913100 in the CRS reference and the solo step's title, F4 941100 and 20 guessable | F5's source step asks the record count only Kibana shows (`run_records`: Top values' "Calculated from N records", equal to the Documents count; window or marker count accepted); the 913 row and 913100 in the step title are gone; every foundation answer read in Kibana carries `kql` |
| 6 | F3 count passed without Kibana | Its check carries `kql` (a `url` condition), as do `site_source` and `xff` |
| 7 | Two-way choices pass by trying the other option | Attempts were not recorded: `wrong` reset at two into a hint, so one wrong pick left no trace. Steps now keep `tries` and the result page counts the steps passed after a wrong answer (`retried`). Not penalised: that would change what the score means |
| 8 | F6 cost line said 8 points deducted when admin was not lost | The pass line follows the objective's row at pass time (`.undetected`, `.detected`, `.kept`); the nudge no longer says the current state |
| 9 | Contradictory run messages | A run counts as finished only when the last typed command holds the step's command words, so step 8 no longer shows step 4's "finished"; while the step's command runs the settling status and a red "no run yet" are cleared; a settling poll clears the red line; the `sudo su ... exit` sentence is gone (the prompt is root) |
| 11 | F2 rejected "200 OK" | `status` accepts the code with its reason phrase (`lesson.status_said`) |
| 12 | Same `lesson.check.wrong` for every wrong answer; hints unrelated | A wrong address that the map gives to a host names that host (`lesson.check.wrong.address_of`); a Kibana step whose query is wrong says what the query lacks (`<text>.wrong.<step>.kql`); F4 `rule`'s nudge is about reading the value, the KQL help moved to its kql message; F5 source has wrong_if for an address or a share |
| 13 | DevTools empty in course 2 | F4's probe card says to open DevTools first, and the encoded card to search again with it open. The network panel lists what it receives while open; why the earlier 403 row was dropped on open was not reproduced off the range |
| 14 | Three labels for one area; callout lines over the Field statistics tab; no callout on F5's 0-result step; Kali callout over the prompt | Count callouts all read one line saying it is the count of logs found, and the empty result one line saying no logs were found (0); the hit-count ring joins the Field statistics tab; a callout on a bare prompt goes below the prompt line. F5's `still` is the lesson's last step, which is solo by design (no highlight), so it gets no callout; its card now says what the 0-result screen means |
| 15 | Result page: one case named with "and 2 more" after lesson 1, score 1 and the mechanism note on course 1 | One case across lessons is named once with every lesson it ran in (`score.case_in_lessons`); a lesson session whose course has no `<course>.scores` (course 1) shows no score panels, per-request table, score note or lost-objectives figure |
| 16 | A line saying XSS requests are not counted | Wording only: the XSS searches sent from the Website pane are not attack runs the platform records, so they are not in score 2. What score 2 counts is unchanged |
| 17 | `/search` and `ARGS:sort` accepted; F5 sort line vs the brief; close confirmation; F1's pointless sentence | Both strict, each with its own message (`lesson.http.wrong.path.slash`, `lesson.miss.wrong.excluded.prefix`); the sort pass line says Django's `order_by()` builds the ORDER BY; the lesson's close-and-show-results button asks first, as the session page does; the internet/sw1 sentence is gone |

Left by ruling:

- **Finding 10** (Next skips a step and the result shows `lesson.skipped`) is intended.
- **Finding 16**: XSS is not scored; only the wording changed. Scoring the
  learner's own Website pane attacks would change what score 2 means, a
  product decision left open.
- **Finding 7**: wrong attempts are recorded and shown, not penalised, for
  the same reason.

The answers a Kibana check now needs a query for: F3 `count`, `upstream`,
`site_source`, `xff`; F4 `rule`, `score`, `upper`, `ids_none`, `fired`,
`slipped`; F5 `undetected`, `source`, `scanner`, `still`; F6 `alerts`, `seen`.
Each pattern is the point's own `kql` (or a `url` condition where the point has
none), so a learner who follows the card writes a query that passes.

## 2026-11-14 — Console text and UI slop removed

The user found the console full of generated-looking text and decoration. Two
read-only reviews (a tone review of 101 Korean strings, a UI review of 27 items
and two bugs, both at ed69a8c) were applied on the round-18 code. Where they
disagreed, removal won over rewording. What a step asks or checks, the answers,
and what either score means are unchanged; the scenario YAML keeps `minutes`
(the run length).

What went, and why:

| Where | Removed | Why |
|---|---|---|
| Catalogue | Page title and subtitle, the brand mark, time estimates, category, difficulty, scenario class and guidance chips, the "what you learn" and "what you practise" labels with the dot-joined `learns` lists, course and group subtitles, lesson-number pills | Unmeasured guesses (minutes, difficulty), metadata that repeats the title or the section numbering, and decoration. The outer heading is `main.scenarios`, since it holds lessons, scenarios and the wargame |
| Catalogue | The "start from this lesson" and "start the wargame" buttons | One action, one name: every row's button is `main.start`. The wargame's "without guidance" line became its row text |
| Catalogue | Kind pill, the scenario column naming the target on every row, the `›` chevrons | Each session row names what was taken: course and lesson, scenario number and title, or wargame and target |
| Session page | Console card with tiles (Kibana and log search, step progress again), coloured bar and hover lift, a line telling the learner to open the blue console | One `session.blue.title` button (and `session.red.title` in a wargame) |
| Session page | Kind pill, a "ready" pill with a pulsing dot | The breadcrumb names the kind; a state shows only while opening |
| Session page | The recent activity panel (`session.activity`) with its auto-refresh label in lessons | A lesson hides its automatic requests while open, so the panel was always empty |
| Result page | The score explanation printed three times (course paragraph, under score 1, a grey box of four notes) | One line per score: how a loss is decided and that undetected costs double; that a run counts once and is not added to score 1. Data-driven warnings stay. Course 2 keeps one line: Website-pane XSS searches are not in score 2 |
| Result page | The lost-objectives count (0/3) in the header, the kickers naming score 1 as primary and score 2 as reference, the lost and detected columns and the pill legend, the checked lesson-1 line naming one case "and 2 more" | The score card already shows the count; one plain result column says kept, lost and detected, or lost and undetected; the request table lists what passed |
| Result page | Three restart labels (from lesson n, the same lesson, the same scenario) | One label, `session.restart` (a scenario's result had said "the same lesson") |
| Lesson end | Green checks on every lesson and a "lesson completed" line after 0 steps passed | Each lesson shows how many of its steps passed (`lesson.steps.passed`); the line is `lesson.done` |
| Briefings | The course-guide kicker, the reference footnote and closing paragraphs that said it twice, the scenario briefing's chips and "about 15 minutes" | The time field already says the length; "about" was wrong for a fixed timer |
| Lesson note | A "press this button first" line under every open button; ring callouts that only name the ringed thing (search box, kali, board.com, DMZ, management network); the note's subtitle repeating the lesson title; the IDS rule header bar; the objectives card's title; placeholders that echo the question (value, number, method, three-digit number and the like, and the loot box's) | The button and the ring point already. The note is `lesson.note.heading` in lessons and `scenario.note.heading` in scenarios. Format examples (`lesson.map.placeholder.kali_ip`) stay |
| Strings and API | The six lesson and two course `summary` strings, the scenario `summary` strings, `learns`, and the `goal`/`learns` card fields | Never shown, or shown only in the removed catalogue lines |
| CSS | `.brand-mark`, `.lift` and `--shadow-lift`, the unused dot tones, the badge's dot | Nothing uses them any more |

Tone fixes (Korean-first, practitioner wording): no glosses of field terms
(red team, hash, CVE, Core Rule Set, percent-encoding, Paranoia Level,
ModSecurity variables); no scoring internals in learner text (how the platform
judges a dump, a "shown beside the result" line); measured-by lines no longer
restate the goal or the time line; one Korean word per thing (practice range,
log, benign search, rule_id, version, final check, show hint); one "loading"
form for every loading line.

Two open questions, decided:

- `lesson.fix.*` keeps only its first sentence. The second restated
  `scenario.risk.*`, and the closed session's page renders the same debrief
  (its `lesson.debrief.risk` section) right under the verdict banner, so no explanation is
  lost on the result page.
- The Korean word for "path tracing" was not found in a primary source as a
  name for path traversal. A Korean security press article keeps the English
  (boannews.com idxno=107983), so the console says "Path Traversal"
  (`docs/vocabulary.md`).

Not applied: the dash after `lesson.objectives.total` in F6's objectives card stays, because the dash
hides the penalty while F6's detection step is unanswered and the total would
give the answer away. `lesson.kibana.none` already used the Korean word for log. The F6 card keeps
its lost and detected columns (`lesson.objectives.col`): F6's steps name them.

Two bugs fixed:

- **A scenario's clock ran during its briefing.** The clock, the attack
  schedule and the final check were set when the session opened. Now `begin`
  writes `started: false`; the engine does nothing for such a session and
  `time_left` is the whole run. The briefing's Start posts
  `POST /api/sessions/<id>/scenario/start/`, which sets them from that moment,
  once; `verify-window` starts the clock first if it has not. Sessions from
  before carry no `started` key and count as started.
- **A reload could drop the lesson position.** The step shown lived only in
  the browser (`cr-lesson-step-<id>-<lesson>`); a browser without it (a new
  browser, a cleared store, a fresh test context) opened on step 1. The console
  now opens on the furthest step the server recorded as `reached` when the
  browser has no record of its own; a step the learner went back to in the same
  browser is kept.

## 2026-11-15 — Answer-blind walk round 19: what changed in the lessons and why

An answer-blind walk of both courses and scenario 1.1 on the live range found
23 learning-flow findings and 15 slop findings (S1-S15); docs review round 4
found two code bugs and three doc drifts. Rules applied: no text, ring or
wrong-answer line shows a step's answer before the step; a step that teaches a
tool needs that tool; the result shown is true; a reload loses no work; slop
is removed rather than reworded. What the score means is unchanged.

| # | Finding | What changed |
|---|---|---|
| 1 | The count of steps passed after a wrong answer read as "step 5" | Counts use the Korean counter word for items: `session.course.retried`, `session.course.skipped`, `session.course.steps` |
| 2 | F6 loot passed on the admin row alone, then the result showed every account as kept (`score.kept`) | The step passes only when the matched accounts cover every account in the session's snapshot; fewer fail loud with `lesson.miss.fail.loot.partial` (matched and total) and the box stays open. A partial paste still credits what it matched: the objectives follow the target's data, and the step asks for the whole table, so the result is true |
| 3 | A reload wiped Kali's scrollback | ttyd runs `vm-terminal.sh` inside `tmux new-session -A -s <host>-<session>`, the host without its `cr-` prefix (for example `kali-12`) (`TERMINAL_KEEP=1`, `platform/tmux.conf`: no status line, no alternate screen), so a reload reattaches to the same shell with sqlmap still printing. tmux is in the platform image; the Kali image is unchanged, since the range host pulls its images only at setup |
| 4 | An unapplied rule was lost on reload | The editor keeps the text in localStorage (`cr-rules-draft-<session>`, with its base version, try/catch) and restores it, saying so; apply drops it |
| 5 | "n" lines after a sqlmap run (run B) | Not reproduced; the scrollback that would show the cause was gone. Left; the tmux change keeps it next time |
| 6 | F2's DevTools answers guessable | A check's `dev` pattern needs `dev_request`, the row picked in DevTools while open, to be a recorded request matching it (`lesson.check.wrong.dev`). On method, path, status, parameter, sort and the missing post. GET/200/404 stay guessable as values; the guard makes the learner pick the row |
| 7 | F3 X-Forwarded-For and F5 record count passed on the query left from earlier steps | Their `kql` now needs the step's own condition: `x_forwarded_for` beside `url` (the card says to add `request_header.x_forwarded_for : *`, which leaves the upstream row), and `source_ip` beside the WAF log (kali's records) |
| 8 | The ring on board.com took in its IP label | `auditor.html` rings a node's icon and name only, not the interface labels |
| 9 | A wrong board address said it was the waf's address and gave 10.30.1.247, the last step's answer | `address_of` says only that it is another device's address, with no name or address |
| 10 | F2 sort's pass line and the catalogue named the SQL injection target | The pass line says only what the parameter carries; the catalogue's scenario `practise` lines are gone and 3.2's title says "sort parameter" (`scenario.writerule.title`) |
| 11 | "20" and "4" with the Korean unit word for points rejected | An answer that is a number with a one- or two-letter unit word is read as the number (`lesson._unit_dropped`); `%` is not a unit |
| 12 | "10.30.1.0", "q=" got a bare "wrong" | F1 DMZ and F2 parameter have `wrong_if` messages. `/search` stays strict, by round 18's ruling (Django's paths end in `/`; the step reads the URL as written) |
| 13 | F3 source's wrong address said "the device this step asks" | `address_of` applies only to map address steps; F3 source says which row to read |
| 14 | A stale `lesson.check.wrong` or red KQL line stayed after the fix | Typing, picking an order chip, or changing the Kibana query clears it |
| 15 | Lines naming the open button as "the card's" button | "The card's" removed (the button is above the card) |
| 16 | A line telling the learner to press `lesson.kali.check` while the check runs itself | Kali cards say the run is checked when it ends; the button stays to check sooner |
| 17 | Lost "yes" with detected "—"; a line placing the objectives table on the right | Direction fixed (below the lesson note). The dash stays, by the slop round's ruling: it hides the alerts step's answer |
| 18 | nocase passed itself with a line saying the nocase rule was applied | The pass line states the rule's state, which is true whether it was edited now or before |
| 19 | Slot addresses differ between sessions | Inherent to slots. No text says addresses stay the same; F1's waf pass line no longer says to remember the pairs |
| 20 | Course 1's end promised per-request results | The line is gone; the course end shows no scores |
| 21 | Scenario session page: "no attacks yet" beside listed alerts, minutes since open beside the scenario clock | An open scenario has no activity panel and shows only its start time |
| 22 | Scenario result in lesson words, an origin given as the code "ru", a final-check count of 0, an empty `lesson.debrief.risk`, customers twice, "no requests" beside 788 | Scenario words; origins named as countries (`scenario.origin.<code>`); a zero count and empty sections hidden; customer requests only in the debrief; `score.no_attacks_run` and no empty per-request table |
| 23 | A line telling the learner to press alerts in the left menu with the alerts already open | A `click` step whose pane is already open passes when reached |

| # | Slop | What changed |
|---|---|---|
| S1 | Corp card stretched | The grid aligns items to the start |
| S2 | Course-1 sessions showed `result.kept_all`; the practice column named the last lesson | The result cell shows objectives only for a course with a score; the row names the course |
| S3 | "Last session" lines; the wargame line twice; scenario lines restating titles | All removed |
| S4 | Time estimates (about 80 s, 4-5 min, 1-2 min, about 1 min) | Removed |
| S5 | Session page repeats the target; labels | The target and the progress label are gone; the breadcrumb names the target |
| S6 | Callouts that name what is ringed | Every lesson step's own callout removed; stage callouts that say what to do next stay; those naming a count, an empty result, Top values or the prompt are gone |
| S7 | F1 path asked three times, order shown twice | One question with how to take a button back; the order shows only as numbers on the buttons |
| S8 | Glosses | The glosses after customer PC (customers), WAF (ModSecurity), IDS (Suricata) and anomaly score, the percent-encoding gloss, "kali on the map" and the TP/FN/FP/TN gloss removed |
| S9 | Scoring internals in lessons | The "two scores" reference card and the course-end "score 1 · score 2" line are gone. F6's cost step stays, with the rule (difficulty, double when undetected) in its own card. "Score 2" became `score.second.heading` everywhere a learner reads it; the per-run line drops "not added to score 1" |
| S10 | Result page repeats and decorations | A missed attack is named once; outcome pills became coloured words (`score.lost_unseen`); the lost-objectives label beside the heading is gone |
| S11 | The "recorded run" label and card repeated on later steps; step counter in the panel | The label and the repeated card are gone (the open button carries the run's window); the counter is gone |
| S12 | End panel order and repetition | The pass line stays in place; the button names the next lesson once; the "press Next lesson" line is gone |
| S13 | One action, several names | The lesson end's button is `lesson.course.close`, as on the session page (`session.close.button`). Left: the scenario console has no end button (a scenario ends through its final check, and the session page closes it); `session.restart` names a different action from the catalogue's `main.start` |
| S14 | A "preparing the command" line for a URL | `lesson.command.preparing` now says loading |
| S15 | The reference column (`lesson.ref.heading`) stayed open across lessons | Its open state is kept per session and lesson, so a new lesson opens with it closed |

Docs review round 4:

- `<fail>.broad` named `quiet_on[0]` whatever matched; it now names the first
  listed URI the rule matches.
- `lesson.alerts_on` judged a rule with no URI content broad (`all([])`); such
  a rule is now not broad.
- README's "check that it works" follows the catalogue (course heading, the
  briefing's Start) in both languages; English names the Korean labels by
  their translation.
- ARCHITECTURE's scenario status lists `started`.
- The slot reset time: 43 s is the capacity measurement's `slot.sh reset`,
  53 s the 2026-11-14 acceptance round's entry; `now.md` and `test/README.md`
  name both sources.
- Docs review round 5: the English docs name Korean UI text by its
  `strings.html` key or an English description, since CLAUDE.md allows
  Korean only in four places.

## 2026-11-15 — Answer-blind walk round 20: what changed in the lessons and why

An answer-blind walk of both courses and scenario 1.1 on the live range (at
55c4fb6) found 19 learning-flow findings (F1-F19) and 9 slop findings
(F20-F28). Three were blockers. The rules are round 19's: no answer before
its step, a step that teaches a tool needs it, what the console shows is
true, a reload loses no work, slop is removed rather than reworded. What
either score means is unchanged; F6's cost step stays, since a lost and
undetected objective counting double is the product's core idea.

Blockers:

| # | Finding | Cause | What changed |
|---|---|---|---|
| F1 | Every c1 L2 DevTools answer was rejected with the row open | `SHOWN_CHECK` dropped a check's `dev`, so the console never sent `dev_request` and the server's `_dev_picked` always failed. Round 19's test drove the server alone | The shown check carries `dev: true` (never the pattern). A test now takes the step the server shows, answers it in the console with a row picked, and posts that body to the real check |
| F2 | Slot 1's map never loaded (404/409 on open) | `provision.py` opened every project when `cr-gns3` restarted while the platform deleted and loaded slot 1's map. The half-done load left that slot's switch TAPs busy in `cr-gns3`'s network namespace, and GNS3 names them from the node id, which was fixed per slot, so every later open failed the same way | The platform is the one loader: `provision.py` opens and starts nothing. `gns3.publish` imports with fresh node and link ids per load (`fresh_ids`; the project id stays) and retries a failed load (`LOAD_TRIES` 3, `LOAD_PAUSE` 3 s). The deploy recreated `cr-gns3`, which cleared the wedged namespace |
| F3 | c2 L3's last step sat on "waiting / checking" for 8 minutes until a reload | A silent poll waited `PATIENCE_FOR_RANGE_WORK` (15 min). The first poll after a sqlmap run does the run's heavy ingest; while it hung, every later tick returned at `checking` | Silent polls wait the normal 90 s, so a hung one is dropped and the next tick checks again (the run's case row already exists, so it is fast). A replay step also checks once its normal request is seen |

Other findings:

| # | Finding | What changed |
|---|---|---|
| F4 | Skip on a lesson's last step jumped to the next lesson with no end screen | The lesson end never moves on by itself: no 2 s switch, after a pass or a skip; the end card waits for its next-lesson button |
| F5 | The c1 end said the course was finished over "0 of 6 steps passed", under the last lesson's title | At the course end the card's title is the course's and its line (`course.logs.done`, `course.attack.done`) says that the last lesson ended; course 1's line also names course 2 |
| F6 | c2 L2's error status passed with DevTools closed | f5 `error` has a `dev` pattern, like F2's DevTools steps |
| F7 | c1 L3's search passed on the example word the step forbids | f3 `search` rejects `kim0413` |
| F8 | The result page under-counted skipped steps | The skipped count is gone from the course card; "n of N steps passed" already says it |
| F9 | The map ring covered the first digit of kali's address | A map ring shrinks its padding until it clears the map text beside the node (`clearOfText`) |
| F10 | After a rule was applied the ring still said to apply | Apply marks the learner's own new sids as added at once; the ring no longer waits for the check's reply |
| F11 | The hit-count ring took in the Field statistics tab | The ring holds the count alone |
| F12 | The Top values ring missed the record-count line the step asks for | A sidebar step rings Kibana's `dscFieldStats-statsFooter` when it shows, else Top values |
| F13 | Two wordings of the end-session confirmation, one promising a score c1 has not | One line, `session.close.consequence`, on the session page and the lesson end; the rebuild line is gone |
| F14 | The c2 end after a reload showed no course summary | The course end reads the session's own `course` rows (each now carries `text`), not `/api/wargames/`, whose failed or slow answer left it empty |
| F15 | Scenario 1.1's first step passed itself (the alert list opens by default) | The step is gone; 1.1 starts on the first judgement |
| F16 | An item read right while the count still said 0 right | The count updates from the POST's `right_so_far` |
| F17 | A quoted wildcard (`url : "*word*"`) got a bare "wrong" | Any KQL step answers it with `lesson.check.wrong.kql_quoted`: the star is literal inside quotes |
| F18 (#19) | c1 and c2 ran on different slots, so the addresses changed | A learner's next session cannot reuse the slot just closed: it is being rebuilt. The c2 brief says addresses can differ per session and where to read this session's (`course.attack.brief`) |
| F19 (#16) | "Checked when it ends" beside the check button | The sentence is gone from the Kali step texts and `lesson.kali.running`; the button stays to check sooner |

Slop, removed rather than reworded:

| # | Where | What changed |
|---|---|---|
| F20 | "Read, then press Next" under every pass | `lesson.status.press_next` is gone |
| F21 | Callouts repeating the step text | `lesson.dev.open`, `lesson.dev.row`, `lesson.kibana.query`, `lesson.kibana.write`, `lesson.kibana.expand`, `lesson.rules.press_apply` are gone; those stages draw only the ring. The leg-specific expand lines stay: they say which row |
| F22 | Penalty column and total in F6's objectives table | The table keeps objective, difficulty, lost, detected: what F6's steps read. The cost step and its rule line stay |
| F23 | Scoring internals on the result page | The counts-once note, the mechanism column with its note and the course-2 XSS line are gone. Whether a lesson session shows a score comes from the course card's `scored` flag (a course with a `kali` or `replay` check) instead of whether a `<course>.scores` string existed. The API still reports `corroborated` |
| F24 | Dot-joined home results | A lost cell is `result.lost` alone; the scenario help markers lost their dot |
| F25 | Step counter "(lesson n)" repeating the subtitle | The counter is `main.step` |
| F26 | Trademark line under the map | Moved to a small home-page footer (`topology.trademark`): the logo is OffSec's, so the notice stays |
| F27 | The run card inside the step card, naming the case | The run is a plain line with its Kibana link |
| F28 | Next and Skip both left an unsolved step | One button: it reads `lesson.coach.next` on a passed step and `lesson.skip` otherwise, and records an unpassed step as skipped. Skipping is no longer behind the hint rungs, since Next never was |

Judgement calls, decided:

- Scenario 1.1 marks each judgement right or wrong at once, so a learner can
  try the other verdict: kept. Immediate feedback is the scenario's teaching,
  and every try is recorded (`tries`).
- "Step 1/5" beside a passed step 1: gone with F15.
- "Opened 0 hints" and "kept all 3 objectives" for a scenario closed before
  its attack ran: kept. Both are true; the debrief says the attack did not run.
- The briefing's label headings and its "in progress" pill: kept. They are
  the briefing's structure, not decoration.
- c1 L1 path hint about the green arrows starting at the internet: kept; the
  learner's request leaves from customers, which hangs off the internet switch.
- c1 L1 log host: the zone ring holds two hosts, so the choice is narrow:
  kept. The step teaches reading the management zone, not guessing.
- Plain "wrong" for sw3, 942100 and 8: kept. Each is wrong and a specific
  line for each would teach the answer by elimination.
- c2 L3's parameter name read case-insensitively: kept; ModSecurity's
  `ARGS` names match that way too.
- A correct admin row alone does not flip the admin objective: kept by round
  19's ruling; the step asks for the whole table.
- The XSS sentence under the CRS anomaly heading, the two target cards'
  shared opening and one Start per line: left; not defects.
- Steps that say to expand a row whose value the table already shows: left;
  the expanded document is where later steps read fields.
- The last step's pass line below the next-lesson button: left by round 19's
  ruling (S12).

## 2026-11-15 — Answer-blind walk round 21: what changed in the lessons and why

An answer-blind walk of both courses and scenario 1.1 on the live range (at
b392748, images 7529bee) found 17 countable findings and no hard blocker; #8
could fail a learner who did everything right and #1 accepted wrong work. The
rules are round 20's: no answer before its step, a step that teaches a tool
needs it, what the console shows is true, a reload loses no work, slop is
removed rather than reworded. What either score means is unchanged, and the
target still decides every objective.

| # | Finding | Cause | What changed |
|---|---|---|---|
| 8 | Scenario 1.1: the note said every item was judged right, then the final check failed 16 of 17 | A customer item arrived after the last list read. The judge pane's 15 s re-read is skipped while an item's follow-up buttons show, and a judged attack's "did it get in" buttons stayed shown, so after the attack verdict the list never re-read until a reload | A verdict closes its follow-up buttons, so the re-read goes on. The learner's `verify-window` answers 409 with `unjudged` while an item listed so far has no verdict (`scenario_run.unjudged`); the console lists the items again and says how many are left (`scenario.done.unjudged`). The guided "start the final check" step is `triage` with `judged: verified` and passes once a window opened, not on the click; 3.1's done step too. The pass line of the all-items step says the items so far (`scenario.shift.ok.all`). The window still judges the items listed when it opened, as the briefing's measure says; the schedule's own window opens regardless |
| 1 | c1 L3 step 3 passed `not destination : <board.com>` and explained it as the waf's leg | The `kql` pattern only required `not destination:`, and both queries give one hit | On a `leg: upstream` check, a query whose excluded destination is board.com's own address (`views._site_addresses`, from the map) fails with the step's `kql` line (`views._excludes_the_site`). The pattern stays static; no slot address is written into the catalogue |
| 2 | c2 L1 step 2 (`%3C`) passed with DevTools never opened | f4 `encoded` had no `dev` | `dev: '^/search/\?(.*&)?q=[^&]*<script'`; the shown check carries `dev: true` (round 20, F1) |
| 3 | c2 L2 step 1 (sort value) passed with DevTools closed | f5 `sort` had no `dev` | `dev: '[?&]sort='` |
| 4 | A rule missing the `;` after `sid:` passed the syntax check and Apply, then the check said no rule was added | Not the hypothesis: `suricata -T` on the live sensor (Suricata 8.0.7) loads `... nocase; sid:9100001 rev:1;)` as one valid rule ("1 rules successfully loaded, 0 rules failed"), so there was no warning to catch. The platform reads a sid only as `sid:<n>` followed by `;` or `)` (`disable._SID`), so it saw no new rule | The syntax check and apply refuse a file with an active line whose sid the platform cannot read (`disable.unread`); the check answers `unread_sid: true` with the lines and the console says to end each option with `;` (`lesson.rules.sid_unread`). This lives in the platform's rule reading, not in `rules/suricata.py`, since Suricata accepts the rule: `core_loc` stays 584 |
| 5 | c1 L3 step 1 sat on "checking" with the example word | The `sent` check matched nothing and said nothing | A `sent` check takes `wrong_if`; a sent request matching it answers `<text>.wrong.<step>.<says>` with `loud: true` (`lesson.logs.wrong.search.example`) |
| 6 | c1 L2 sort hint said the new row appears at the bottom | The panel clears on navigation, so the row is the first | `lesson.http.nudge.sort` says the panel clears and the `?` row is at the top |
| 7 | `Total Score: 20` rejected though it is the rule value's own text | `anomaly_total` accepted the number alone | It also accepts `Total Score: N` and `(Total Score: N)` |
| 9 | Two totals for one judgement on the result page (17 and 27, later 31) | The debrief counted every item at read time; the headline the window's list | The debrief's triage line counts the last judged window's items (`scenario_run._triage_tally`); all items only with no judged window |
| 10 | "Lesson over" in a scenario | `finishedText` had no scenario case | A scenario says `scenario.note.done` |
| 11 | "The final check is running" after its result | The done step's pass line was about a moment | `scenario.shift.ok.done` and `scenario.fixrule.ok.done` say the final check was started |
| 12 | "No benign request was sent" beside 1372 customer requests | `scoring/metrics.py` warns when no benign case was correlated; customer traffic is not a case | The score API drops `no_benign` when the session has customer requests (`views.session_score`). `scoring/` is unchanged; the warning is still true and shown for a session with neither |
| 13 | A closed session's page kept its end button and showed "session N closed at <ISO time>" | A second close (double press) got the 409 and the page showed its detail and the button again | On a failed close the page reads the session; if it has `ended_at` it says it is closed and renders the result (`alreadyClosed` in `base.html`, used by the session page, the main page and the lesson end) |
| 14 | "PASS"/"FAIL" labels | Hard-coded English | `scenario.phase.passed` and `scenario.phase.failed` on the scenario banner, the session page and the home table |
| 15 | WAF `date` read "Asia" and UTC, 9 h behind Kali and Kibana | The WAF image has no tzdata, so `TZ=Asia/Seoul` became UTC named "Asia" | `vm-terminal.sh` sets `TZ=KST-9`, a POSIX zone that needs no tzdata. nginx's own error log and ModSecurity's audit log stay UTC: the ingest pipeline reads the audit log's zoneless `time_stamp` as UTC, and moving the process's zone would shift every WAF alert |
| 16 | A lesson's session page held one button | Lesson starts went to the session page; scenario starts already opened the console | A lesson's Start, and Start again on a lesson or scenario, open the blue console. The session page stays for the running list, closing and the result |
| 17 | Callouts repeating the step; c2 L1 step 1's ring on the search box while the card says to open DevTools first | Round 20 left the DevTools tab and rule-line callouts | `lesson.dev.tab.headers`, `lesson.dev.tab.payload` and `lesson.rules.add_line` are gone (ring only), with the English fallback for the rule line. f4 `probe` points `dev: toggle, until: dev_open` and then the search box (`until: dev_open`, new) |

Also fixed: `tests/conftest.py` clears `reset._states` between tests. A test
in `test_session_close.py` left slot 1 "resetting", so `test_api_ready.py`
failed whenever the size-ordered split put the two in one process; the new
tests changed file sizes and exposed it.

Judgement calls, decided:

- c1 L2 step 5 passing on the right row's Headers tab without opening
  Payload: kept. The `dev` gate makes the learner pick the row; the step
  teaches reading the request, and `q` is in the URL on the same row.
- c1 L3 step 5 passing without expanding the row: kept (round 20).
- c1 L1 step 3's edge across the "1" and the green-arrow hint: kept (round 20).
- c2 L3 step 3: a 1-row or 2-row paste not flipping "some accounts" or
  "admin account": kept. The objectives follow the target's own rules for
  what was taken; the platform does not decide them from the paste.
- The loot pass line saying "match" twice: fixed; `lesson.loot.matched` is
  the matched accounts in brackets after the pass line.
- c1's end naming course 2 with only an end button: kept. One session per
  course; course 2 starts from the catalogue after this one closes.
- The lesson end after skips not saying so: kept; the result page shows
  "n of N steps passed".
- Difficulty and penalty columns and alert counts per run on the c2 result:
  kept by round 20's rulings (F22, F23); a run's alert count is the evidence
  that one case counts once however many alerts it drew. The learner's XSS
  searches are not attack runs (round 18).
- Scenario: the red "no attack judged right yet" for one poll beside the
  card's "right": left; the next poll replaces it. "Objectives lost 0" in the
  strip: kept; it is the live state a defender watches, and an attack's
  verdict needs whether it got in, which the strip does not say per item.
- Scenario briefing labels, pills, "from:" labels, rule lines and the
  evidence log: kept by round 20's ruling; they are the evidence a judgement
  is made from.
- 1342 + 29 = 1371 of 1372: true; one request had no answer when counted.
  The session page's "step 4/4 · 0/3" with no verdict: left; the verdict is
  on the result.
- The home list missing session 1890: not reproduced; the list asks the ten
  newest closed sessions.
- Plain "wrong" for `created_at` and for a wrong count: kept by round 20's
  ruling (a line for each near miss teaches by elimination).
- c2 L3 step 8's text saying the attack is stopped with 403 while 10 sqlmap
  requests reached the app (500): left; the check is the replay's verdict
  (the run blocked, no loot), and the walk saw it pass.
- The c2 intro's XSS line under the CRS heading and the sqlmap option
  reference: left (round 20).

## 2026-11-15 — README and ARCHITECTURE are Korean only

The user ruled that the two documents kept in both languages are now Korean
only. `README.md` and `docs/ARCHITECTURE.md` now hold the former `.ko.md`
text, and the English versions and the `.ko.md` files are gone. Keeping two
languages in step cost a review pass per change and drifted in every docs
review round. Every other repo file stays English, as before.

## 2026-11-15 — Virtualenvs are made with uv

The user asked for uv in place of `python3 -m venv` and pip wherever the repo
builds a Python environment.

- The platform VM's cloud-init no longer installs `python3-venv`. It downloads
  uv 0.13.8's `uv-x86_64-unknown-linux-gnu.tar.gz` from the GitHub release,
  checks it against the release's published SHA-256
  (`5acfd917...57387d91`) and unpacks `uv` into `/usr/local/bin`. uv's
  installation page lists GitHub Releases as a way to install it and pins a
  version in the installer URL; the tarball and its checksum are used rather
  than piping `install.sh` so that the download is checked, as the platform
  image already does for ttyd.
- `cr-venv` at first boot and `cr-venv-checkout` after a sideload run the same
  `VENV_COMMAND`: `uv venv --clear --python /usr/bin/python3 /opt/cr/.venv`,
  then `uv pip install --python /opt/cr/.venv/bin/python -r
  platform/requirements.txt`. `--clear` is needed because `uv venv` refuses an
  existing environment (`python3 -m venv` reused it); the second run therefore
  rebuilds the environment from the requirements instead of upgrading in
  place. `.venv` stays at the same paths, so `bin/verify` and
  `.venv/bin/python` are unchanged. A uv environment has no `pip`;
  `.venv/bin/pip` no longer exists.
- No lockfile: `uv pip install -r platform/requirements.txt` resolves the same
  ranges pip did.
- The operator machine: `uv venv .venv`, then `uv pip install --python
  .venv/bin/python -r platform/requirements.txt python-openstackclient
  python-heatclient` (README step 3, `bin/verify`'s hint,
  `bin/platform-rebuild`'s missing-CLI message). `bin/check-topology` makes
  its per-release gns3-server environments with uv.
- Images. The platform and gns3 images install with `uv pip install --system
  --no-cache --compile-bytecode`, uv mounted for that one `RUN` from
  `ghcr.io/astral-sh/uv:0.13.8` pinned by digest (uv's Docker guide, "Using uv
  temporarily"), so uv is not in the image. Built by `images.yml` at the
  change: platform 88,144,333 bytes of compressed layers (91,327,086 before),
  gns3 250,373,788 (253,505,773 before). The board target keeps `pip install`:
  it stands for a deployed Django site, and its Dockerfile is part of the
  target, not of the platform's tooling. The Kolla-Ansible venvs in
  `docs/OPENSTACK.md` §2.1 and §9 stay as the upstream quickstart writes them:
  they run on the cloud's controller, not in this repo, and §9 records a run.
- The ratchet: `dependencies` counts the lines of `platform/requirements.txt`
  (`bin/measure`), so uv is not counted; it is a tool on the machine, like git
  and Docker, not a package the platform imports. `dependencies` stays 6.
- Live, 2026-11-15. Sideload path: on the standing VM, the uv install and
  `VENV_COMMAND` (as `cr-venv-checkout`) made `/opt/cr/.venv` (uv 0.13.8,
  CPython 3.12.3, no `pip`) and `bin/verify --fast` passed on it (909 + 669
  in 4 min 14 s). First boot: `bin/cloud up --replace` twice, at the uv
  commit (24 min 59 s) and at the RC-file commit (37 min 49 s); each time
  cloud-init finished `done`, `python3-venv` was not installed, `cr-venv`
  made `.venv` in about 2 s of CPU, four slots came up READY and the platform
  answered 200 at :8000. `docker compose run --rm --no-deps --user cr
  --entrypoint sh -v ./backups:/backups:ro platform` (README's restore) ran
  as `cr` with `/data` and `/backups` mounted.

## 2026-11-15 — The platform VM's key is a Nova keypair: `keys.key_name` and `keys.key_file`

The user asked what the "operator key" (운영자 키) was. It was the Nova
keypair the platform VM boots with and the private key `bin/cloud` and
`bin/platform-rebuild` ssh with, under a name the field does not use. The
config now uses OpenStack's own term: `keys.key_name` (the server's
`key_name`, as the Heat parameter already was) and `keys.key_file` (that
keypair's private key); in code `Cloud.key_name` and `Cloud.key_file`. The old
keys are not read: the loader refuses `keys.operator` as an unknown setting and
names the new ones. The live `deploy/openstack/cloud.yaml` (git-ignored) was
updated in place; its copy before is in
`~/.cache/fsl-work/backup-safe/cloud-yaml-20261115/`. The docs say "Nova
keypair" / "Nova 키페어" and show both forms of python-openstackclient's
`openstack keypair create`: `--public-key <file>` ("Filename for public key to
add") and `--private-key <file>` ("Filename for private key to save").

The user then called README step 6, a hand-written `export OS_AUTH_URL=...
OS_PASSWORD="$(cat ...)"` followed by `openstack keypair create`, slop that
nobody writes by hand. The keypair step is gone:

- `bin/cloud up` and `bin/platform-rebuild` import the keypair themselves
  before they create the stack (`ensure_keypair`): `openstack keypair list`,
  then, when the project has no keypair named `keys.key_name`,
  `openstack keypair create --public-key <key_file>.pub`. A keypair of that
  name holding another public key (`openstack keypair show --public-key`)
  stops them with the name and is never overwritten, since whatever booted
  with it would lose its key. The platform's `IMPORT_KEYPAIR` was not reused:
  it is the platform's own Nova call from inside the VM, and these scripts
  drive the openstack CLI from the operator machine before any VM exists.
- Credentials follow the next entry (an RC file); a `clouds.yaml` entry
  printed by `bin/cloud` was built first and dropped the same day when the
  user ruled for RC files.
- The same sweep replaced README's restore block (`docker run` on the image
  read back with `docker inspect`) with `docker compose run --rm --no-deps`
  on the `platform` service, and dropped a `PATH=` prefix from the cutover
  steps that the scripts never needed.

## 2026-11-15 — Example addresses are 10.10.10.0/24

The user ruled that 10.10.10.x is the default, so examples use it.
`cloud.example.yaml`'s Keystone is `http://10.10.10.10:5000`; the example
plan in `docs/OPENSTACK.md` §2.5 and §9 is the network 10.10.10.0/24, gateway
10.10.10.1, the all-in-one host and Keystone VIP 10.10.10.10 and the
floating-IP pool 10.10.10.20 to 10.10.10.99; README uses the same Keystone;
test fixtures that stand for a floating IP use 10.10.10.21. Values that record
the real cloud stay (Keystone 10.0.0.10, the provider network 192.168.2.0/24,
the platform's 192.168.2.247, `deploy/openstack/network.yaml`, history), and so
do range-internal addresses (10.20/10.30/10.31 and Docker's pools).

## 2026-11-15 — KVM is recommended, not required

The user: "kvm 안써도 돌아가잖아 느리게". This supersedes the 2026-10-20 ruling
"OpenStack only" in one point, `nova_compute_virt_type: "kvm"` "(never
`qemu`)": KVM stays Kolla's default and the recommendation, and a compute host
without VT-x or AMD-V may run `nova_compute_virt_type: "qemu"`, under which
the platform VM and the range host run under plain QEMU emulation, slower.
`docs/OPENSTACK.md` §2.2 and §9 say so; README already did.

## 2026-11-15 — The identity comes from an RC file on the controller node

The user ruled how credentials work: the operator runs everything on the
OpenStack controller node with an RC file, and `clouds.yaml` / `--os-cloud`
are not used.

- Admin steps run in a shell that has loaded `/etc/kolla/admin-openrc.sh`,
  which `kolla-ansible post-deploy` writes.
- The project user has an RC file of the same shape, for example
  `~/fsl-range-openrc.sh`: Kolla's variables with the user, the project and
  the password changed, and `OS_INTERFACE=public` because the platform VM
  calls the same interface and reaches the public endpoints. README shows it
  once and loads it once (`source`, install step 6); later steps show only
  their own command.
- `cloud.yaml` loses its `identity` section (`keystone`, `region`,
  `interface`, `domain`, `project`, `user`, `password_file`,
  `password_env`); the loader now refuses that section as unknown.
  `bin/cloud` and `bin/platform-rebuild` read `OS_AUTH_URL`, `OS_USERNAME`,
  `OS_PASSWORD`, `OS_PROJECT_NAME`, `OS_USER_DOMAIN_NAME`,
  `OS_PROJECT_DOMAIN_NAME`, `OS_REGION_NAME` and `OS_INTERFACE`
  (`cloud.identity`), and stop before any change, naming every missing one.
  A trailing `/v3` on `OS_AUTH_URL` is dropped, since Kolla's RC has none and
  others do. `Identity`'s repr leaves the password out.
- The password still reaches the platform VM as before, over ssh into
  `openstack.env`; only its source changed, to `OS_PASSWORD`.
- The RC file names domains (`OS_USER_DOMAIN_NAME`), where `cloud.yaml` held
  the domain's id. The Heat parameter `domain` and so `CR_OPENSTACK_DOMAIN`
  now carry the user domain's name, and the platform signs in with
  `{"domain": {"name": ...}}` (`range/openstack._signed_in`); Keystone takes
  either. A VM made before this change holds the id and needs the rebuild
  (`bin/cloud up --replace`) that brings the new image anyway.
- Live: the operator's RC file is `~/.cache/fsl-work/fsl-range-openrc.sh`
  (mode 0600, written from the old password file without printing it), and
  `~/.cache/fsl-work/os.sh` loads it instead of reading the password file.
  The live `cloud.yaml` lost its `identity` section; its copy before is in
  `~/.cache/fsl-work/backup-safe/cloud-yaml-20261115/`.

## 2026-11-15 — Answer-blind walk round 22: what changed in the scenario and why

An answer-blind walk of both courses and scenario 1.1 on the live range (at
bc4dbc3, images 82c3d64) found 12 countable findings, mostly in scenario 1.1;
both courses passed every step. The rules are round 21's: no answer before
its step, a step that teaches a tool needs it, what the console shows is
true, a reload loses no work, slop is removed rather than reworded. What
either score means is unchanged, and the target still decides every
objective.

| # | Finding | Cause | What changed |
|---|---|---|---|
| 1 | The refused final check showed the raw key `scenario.shift.fail.done` | `views._judge` answers `<text>.fail.<step>` for a triage check; 1.1's and 3.1's last step is `done` and neither had the string. The red line came from a loud check (#3) | `scenario.shift.fail.done` and `scenario.fixrule.fail.done`. `test_strings.py` checks every step whose kind can fail under its own key (`rules`, `sent`, `loot`, `waf_changed`, `triage`, an `alerted_destination` answer) has that line |
| 2 | The note said every item was judged right while the strip said 28 of 32 | `_judged_step` kept `passed` once set; `triage_passed(judged="all")` holds only for the moment it is read, and the console stopped checking a passed step | A failed `triage` check drops the step's `passed`. The console keeps polling a passed `triage` step while it is the current one and redraws it unpassed when a poll fails |
| 3 | "Failed twice on this step" and a red "no attack judged right yet" before the attack item was touched | Verified in code and by test: each verdict calls `changed("triage")`, which ran the current step's check loud (not a poll). On the attack step every customer verdict failed it, `_judged_step` counted the failure, and the second raised `scenario_run.stuck(..., "check", ...)` | A `triage` check is never counted as a try (it is not an answer the learner gave), and the verdict-driven check runs as a silent poll |
| 4 | Step 3 told the learner to press 새로고침, though new items appear by themselves | The judge pane re-reads every 15 s (round 21) | The button is gone; `scenario.shift.coach.all` says new items keep arriving |
| 5 | After the pass the final check stayed active, the hint offer stayed, counters kept rising, and the console had no end button | Customer traffic ran on after the pass; the strip only disabled the button while a window was open | A passed window stops customer traffic (`scenario_run._shift_over`) and `verify-window` answers 409 after a pass. The strip hides the final check button, the hint offer and the clock once passed, and shows the end button once any window is judged; ending asks with `session.close.consequence`, closes and opens the result |
| 6 | The open scenario's session page held one card and one button and said nothing of the pass | The page rendered the verdict only for closed sessions | An open scenario session with a judged window shows the verdict and the debrief beside its end button |
| 7 | The result table showed 20687 alerts for both sqlmap runs, under one name | Not one total shown twice. In the store (session 1929) each run has its own marker and its own 20687 alerts, 19751 WAF and 936 IDS, from 1973 requests each, at 02:53 and 03:03 UTC: sqlmap with `--flush-session` sends the same requests and every one is blocked, so both runs draw the same alerts. Both numbers were true; the rows were only indistinguishable | Rows of a scenario session carry the run's start time under the name (`per_case[].started_at`), so two runs of one case read as two runs |
| 8 | The refusal reason was cut off with "…" and squeezed the title | It sat in the one-line strip as a truncated span | The reason is its own line under the strip |
| 9 | A corrected answer sent during the ~6 s check was dropped, and the old verdict stood beside the new text | `answer()` returned while a check ran and disabled the submit button | The button stays; an answer sent during a check is checked next (the same answer again is not re-posted). A verdict is not shown when the field was edited during the check or a newer answer waits |
| 10 | Pills and badges on the scenario screens | | Phase, WAF state, item verdicts and timeline states are coloured words; the verdict box and the session page's banner drop the 통과/미통과 pill |
| 11 | A fact said twice | Badge plus sentence on each judged item and on the verdict; a big count plus its sentence on the detection card | One line each: the item's verdict line (`triage.said.right`, or `triage.said.wrong` when read back), the verdict sentence, the detection sentence |
| 12 | Parenthetical glosses | | Rewritten without brackets: `lesson.ref.fields.rows`, `lesson.ref.kql.body`, `lesson.ref.sqlmap.rows`, `lesson.ref.exception.body`, `lesson.loot.matched`, `lesson.xss.fail.nocase.rev`, `triage.waf.logged` |
| E01 | A second browser on a running scenario showed the briefing's Start | The briefing showed when this browser had no local "briefed" mark | The briefing shows only while the clock has not started (`started: false`); the local mark is gone |

Judgement calls, decided:

- c1 L2 s7 accepting `/posts/999/`, s5 passing on the Headers tab, the bare
  "wrong" for near misses, partial loot pastes not flipping objectives, the
  sqlmap option reference before L3, the c1 end naming course 2: kept by
  rounds 20 and 21.
- Suricata's raw English syntax errors: kept; they are the tool's own output.
- The c2 result's per-run alert counts and the 난이도/감점 columns: kept
  (rounds 20 and 21).
- The scenario debrief's evidence log, hint count and window line: kept;
  they are what the verdict was made from (round 21).
- "✓ 최종 점검을 시작했습니다." after the pass: kept; it is true, and the
  verdict now shows in the strip and the debrief.
- c2 L1 s10 passing at once when the rule already had `nocase` at rev:1: kept;
  the step's point is the case-insensitive match, and the no-`nocase` path
  still requires the rev bump.
- c2 L3 s8's "403" wording while sqlmap saw 500s, the 30 s close, rings on
  answer spots without text, the reload dropping half-picked order chips, the
  WAF terminal header: left.

## 2026-11-15 — Four commands on the controller: `bin/cloud init`, credentials in clouds.yaml

This supersedes "The identity comes from an RC file on the controller node"
(same day). The user: "자동화로 하면 rc 필요 없으니까 yaml로 그냥 처리해".
The manual setup was README steps 1 to 6 (admin commands, a venv, a key, a
copied `cloud.yaml`, a hand-written RC file); it is now, on the controller
node:

```bash
git clone https://github.com/Nekonic/fsl-project-mvp.git && cd fsl-project-mvp
uv run bin/cloud init
uv run bin/cloud up
```

- **`uv run`, no venv step.** First built with PEP 723 inline script
  metadata in `bin/cloud` and `bin/platform-rebuild`; replaced the same day
  by the uv project (next entry).
- **`bin/cloud init`, admin, idempotent.** Admin credentials come from the
  `kolla-admin` entry of `/etc/kolla/clouds.yaml`, which Kolla-Ansible's
  `post-deploy.yml` writes ("Template out clouds.yaml", `dest: "{{ node_config
  }}/clouds.yaml"`, mode 0600, `node_config` defaulting to `/etc/kolla`;
  template `roles/common/templates/clouds.yaml.j2`, first entry `kolla-admin`)
  on both stable/2025.2 and unmaintained/2025.1, so no `source` is needed.
  With `OS_AUTH_URL` set in the shell (after `source
  /etc/kolla/admin-openrc.sh`) it uses those variables instead. It finds the
  one `router:external` network (or the one `network.external` names); makes
  project and member user `fsl-range` when missing, with a
  `secrets.token_urlsafe(32)` password that is never printed; writes the user
  into `~/.config/openstack/clouds.yaml` as entry `fsl-range`, mode 0600,
  merged without touching other entries, right after the user is made so a
  later failure cannot lose the password; keeps an entry that signs in; stops
  when the user exists and no working entry holds its password, unless
  `--reset-password`. It never creates a flavor (the user ruled flavors are
  not created for them): it picks the smallest fitting existing one by RAM,
  vCPU, disk, keeping one `cloud.yaml` names when it fits, and gives a
  private one's access to the project. The platform needs 2 vCPU, 8 GB, 40
  GB; the range host 6 vCPU, 16 GB and also 40 GB of disk, which the plan did
  not state but a range host on a 0 GB flavor would not hold its images. It
  checks quota limits (2 instances, both flavors' cores and RAM, 1 floating
  IP), uploads `noble-server-cloudimg-amd64.img` as public `ubuntu-24.04`
  after matching `SHA256SUMS` when missing, makes `keys.key_file` with
  `ssh-keygen`, and writes `deploy/openstack/cloud.yaml` from
  `cloud.example.yaml`, changing only `cloud`, `network.external`,
  `compute.base_image` and `compute.flavors.*` line by line in an existing
  file so its comments and other values stay. It uses openstacksdk, not the
  CLI, so the new password is never on a command line. A review found five
  holes, fixed before the push: the clouds.yaml entry is written before the
  role is given and the file is checked mergeable before the user is made,
  so no failure leaves a user whose password no file holds; a non-active
  image (a cut-short upload leaves it `queued`) stops init; only public or
  project-owned images count as visible, since Glance lists hide community
  images; an unreadable `/etc/kolla/clouds.yaml` is named (openstacksdk skips
  it silently); a flow-style key that the line editor cannot set is refused
  instead of raising.
- **`up`, `down`, `platform-rebuild` read clouds.yaml.** `cloud.yaml` gains
  the required top-level `cloud:` (the entry name). `cloud.signed_in` reads
  that entry (`auth.auth_url`, `username`, `password`, `project_name`,
  `user_domain_name`, `project_domain_name`, `region_name`, `interface`
  defaulting to `public`) and stops before any change when it is missing,
  saying to run `bin/cloud init`. The scripts drop every `OS_*` variable from
  their environment and run the CLI with `OS_CLOUD` and
  `OS_CLIENT_CONFIG_FILE`, because openstackclient's argparse defaults read
  `OS_*` and would override the entry. The password still reaches the
  platform VM over ssh stdin. The RC code path (`cloud.identity`) and its docs,
  the README step 6 RC file and its PS1 snippet, are gone.

## 2026-11-15 — The repo is a uv project: `pyproject.toml`, `uv.lock`, `uv sync --frozen`

The user asked why the setup does not use `uv sync`. This replaces the PEP
723 inline metadata of the entry above and every `uv venv` plus `uv pip
install -r platform/requirements.txt` of "Virtualenvs are made with uv".

- `pyproject.toml` at the root: `[project] dependencies` are the platform's
  four (Django, PyYAML, requests, waitress); `[dependency-groups]` `dev`
  (pytest, pytest-django), `cloud` (openstacksdk, python-openstackclient,
  python-heatclient) and `gns3` (`gns3-server[ai-features]==3.1.0a6`, which
  the gns3 image installed unlocked before). `[tool.uv] package = false`
  (nothing to build) and `default-groups = ["dev", "cloud"]`. `uv.lock`
  (216 packages, one universal resolution for Python 3.12 and later) is
  committed. `platform/requirements.txt` is gone; nothing reads it.
- Operator flow: uv's sync page says "when `uv run` is used, the project is
  locked and synced before invoking the requested command"
  (https://docs.astral.sh/uv/concepts/projects/sync/), so README keeps
  `git clone && cd`, `uv run bin/cloud init`, `uv run bin/cloud up`, with no
  `uv sync` line. The scripts' shebang is `python3` again; `uv run` puts
  `.venv/bin` first on PATH.
- Everything else syncs from the lock with `--frozen` ("use the lockfile
  without checking if it is up-to-date"): `bin/verify` before its tests;
  `VENV_COMMAND` (first-boot `cr-venv` and the sideload hand-over) as
  `uv sync --quiet --frozen --project /opt/cr --python /usr/bin/python3`; and
  the platform and gns3 images, which bind-mount `pyproject.toml` and
  `uv.lock` and sync into the system Python with
  `UV_PROJECT_ENVIRONMENT=/usr/local` (uv's project config page: "To target
  the system environment, set `UV_PROJECT_ENVIRONMENT` to the prefix of the
  Python installation", "on Debian-based systems, this is usually
  `/usr/local`", warning that `uv sync` removes extraneous packages, hence
  `--inexact`). The platform image takes `--no-default-groups` (the four
  only), the gns3 image `--only-group gns3`. `.venv` stays at the repo root.
- Both images now build from the repo root (`context: .` with `file:` in
  `images.yml`, `build: {context: ., dockerfile: ...}` in `compose.yaml`;
  their `COPY` lines name `platform/` and `deploy/gns3/`). So that a sideload
  does not call every change in the repo a change to those images, their
  matrix entries carry `sources` (`platform pyproject.toml uv.lock`,
  `deploy/gns3 pyproject.toml uv.lock`), which `build_contexts` returns in
  place of the context.
- The ratchet's `dependencies` counted the six lines of
  `platform/requirements.txt`; `bin/measure` now counts `[project]
  dependencies` plus the `dev` group, the same six: 6 before, 6 after. The
  `cloud` and `gns3` groups are not counted; before, the OpenStack clients
  were installed by hand from README and gns3-server by the gns3 Dockerfile,
  neither in the count. `bin/select-tests` runs the whole unit suite on a
  change to `pyproject.toml` or `uv.lock`, as it did for `requirements.txt`.
- `.claude/settings.json` still allows `uv venv*` and `uv pip install*`; it
  was left as it is, since permission settings change only on the user's
  word.

## 2026-11-15 — The learner map is the slot's live wiring

The user: "이게 진짜 구성도를 해야지 가짜로 하면 의미 자체가 없어". The GNS3
learner map's hosts were idle busybox containers on the platform VM's own
Docker daemon, drawn from a hand-made `.gns3` file; only the link labels came
from the range. Its switches were not real either: `sw1` joined the router,
the WAF and board.com at once, `sw3` joined them to a log server, and
board.com hung off three switches.

The 2026-10-13 ruling against a topology drawn by the platform was about
invented elements, not about who draws it. The user: "ai slop이니까
못쓰게 한거지". A map in which every element comes from `docker network
inspect`, `docker inspect` and `ip addr` on the range host invents nothing,
so it meets that ruling; this entry applies it, it does not overturn it.

Built:

- `rangehost.WIRING`, one ssh round trip per read: the slot project's Docker
  networks (bridge name, subnet), each running container's service, network
  mode, `Args` and mount sources, `nsenter -n ip -o -4 addr` for each
  container not on the host network, and the `File=`/`Port=` lines of the
  slot's rsyslog file. `interfaces.wiring` parses it; `OpenStack.wiring()`
  runs it; `topology.graph` names it for the learner.
- What the map draws: each Docker bridge is one switch; each container
  interface on it is one link, labelled with its address; nothing else is a
  link. The Suricata sensors are on the host network, so each hangs off the
  bridge its `--af-packet=` names by a dashed 미러링 edge. Log forwarding is a
  dashed arrow from every container whose mount holds a file rsyslog
  forwards (both sensors and the WAF) to `log-server`, captioned 로그 수집기
  (5140/udp). `sw3` is gone: it was never a network. Customers are extra
  source addresses on the Kali container, so they are a line under the kali
  node, not a device.
- Zone captions come from who stands on the network, not from its name:
  kali makes it the 인터넷 구간, the router the DMZ, the wargame's database
  without the WAF the DB존, anything else the 웹 서버 구간. The slot
  agent's move of the web services behind the WAF (the user's ruling that
  Kali must not reach board or corp except through the WAF) therefore needs
  no special case: the map shows whatever the inspect shows.
- No live state: the user ruled that a stopped container means a broken
  range, so the map is read once when the pane opens; a container that is not
  running is not drawn.
- `GET /api/sessions/<id>/topology/` carries the graph as `map`; the console
  frames `/map/<session>/`, which draws it with cytoscape.js 3.34.4 (MIT,
  vendored, SHA-256 `081591ab…6cd8`) and the affinity symbols the GNS3 image
  built (Unlicense; the Kali dragon keeps its notice), read only, and answers
  the coach's `locate` and `fit` messages as the GNS3 page did.
- F1: the path now starts at kali (`kali > router > waf > board.com`), the
  board address is board.com's on the network it shares with the WAF, and
  the DMZ question reads the WAF's estate network, so neither layout breaks
  them.
- Removed: the `gns3` service and image, port 3080 and its security-group
  rule, `deploy/gns3`, `deploy/topology`, `bin/check-topology`,
  `platform/gns3.py`, the map publishing at start, and the platform's Docker
  socket, its docker group setup and the Docker client in its image. The
  socket was mounted only for `interfaces.on_this_host`, which read the
  platform VM's own NICs for a log-server label the map never showed; the
  platform VM's addresses already come from the OpenStack API (`describe`).
  `services` 5 -> 4, `dependencies` 6, `core_loc` 584.

Seen in the live wiring before the slot agent's change: board (10.30.N.59)
and corp-wp (.60) stand on `sN-estate` with the edge router's `lan`
(10.30.N.1), and `deploy/edge/edge.nft` forwards everything, so Kali could
reach board by address without the WAF. The map drew it as it stood.

Not chosen: containerlab or netlab (their graphs read only containerlab
labels, or a file), NetBox (three more services), draw.io and NeXt UI
(a document look, or unmaintained since 2017), keeping GNS3 with built-in
nodes (still placeholders).

## 2026-11-15 — The live map is laid out by the platform: zone columns, boundary devices, sensors below their bridge

The user rejected the live map's drawing ("야 저 구성도가 말이 된다
생각해?"): the sensors stood inside the internet and DMZ zone boxes, the log
arrows ran diagonally through devices and zones, board.com sat deep in the
DMZ with a long line reaching into the DB zone. The data was right; only the
layout changed. A follow-up ruling ("실제랑 같아야 그게 말이 되는거지")
limits the work to layout: nothing is drawn that has no counterpart in the
running slot, so no monitoring-network area, no cloud symbol for the internet
bridge (it is a real bridge), and no single bundled log edge.

- **Positions are computed in `topology.laid_out` and sent with the graph**
  (node `x`, `y`, `label` side; zone `box`; a log edge's `route` and `end`),
  so the layout rules are tested from the graph and the page only draws them
  with cytoscape's `preset` layout. Positions depend on membership alone, so
  the same wiring looks the same on every read and every slot.
- **Zone columns in traffic order**: the caption order (internet, dmz, web,
  database) left to right, every bridge on one row. A device on two zones
  stands in the gap between their boxes on that row, one link into each.
  A device on one zone stands on the row beside its bridge in the first or
  last zone (kali left, board-db right) and fans out below the bridge in a
  middle zone, its name on the outer side.
- **Sensors outside every zone**: a sensor is on no network (host network),
  so it stands below all zones, straight under the bridge it sniffs, joined
  by the dashed 미러링 edge whose label sits between the zone and the sensor.
  The bridge is the one `--af-packet=` names, or, for a sensor that runs in
  its own network namespace and names its own interface, the network that
  interface is on; a sensor moved into a slot container on the bridge needs
  no layout change.
- **Log edges at right angles**: the log server stands below the sensors at
  the first boundary device's x (the router). Each log edge drops from its
  source, runs on its own lane and enters a separate point on the log
  server's top, so the edges stay separate and none crosses a device or
  another zone.
- **Caption**: the internet zone reads 인터넷(모의), and the coach lines that
  named it follow.
- **Both wirings tested**: today's (board on `sN-estate` and its database
  bridge) and the coming WAF backend (`sN-estate` with only the edge `lan` and
  the WAF, `sN-web` with the WAF, board and corp) render with no special case;
  five tests hold the column order, sensors outside zones, devices inside only
  their own zone or on the boundary, log routes, and slot-independence.
  A rendering of both fixtures at 1600x1000 compared every label's box with
  every other label, icon, line and zone border and found no overlap.

## 2026-11-15 — Every surface signs in; Elasticsearch, the project password, ingress and the slots' kernel hardened

The user: "보안조치 싹다 하고 … 기능 안되는거 없어야한다", "초기 비밀번호는
admin/123456 무조건", and "Docker 소켓, 커널 공유도 보안 해".

- **Sign-in.** Django auth and sessions. `api.signin.SignedInOnly` answers
  401 to `/api/` and sends a page to `/login/` until the session is signed
  in; open are only `/login/`, `GET /api/auth/` (user and CSRF token) and
  `POST /api/auth/login/`. Migration 0030 makes `admin` / `123456` once;
  nothing asks for a change (the user's ruling), so THREAT-MODEL says the
  default stops nobody who knows it. Agents sign in over the same REST
  (`redteam/signin.py`, `CR_ADMIN_USER` / `CR_ADMIN_PASSWORD`, default
  admin/123456): `bin/cloud`, `bin/verify`, `bin/acceptance`,
  `redteam/run.py` and `test/conftest.py`, which routes `requests` through
  one signed-in session. Readiness polls ask `GET /api/auth/`, which answers
  before anyone signs in, so `bin/cloud up` still needs no person.
- **The other web surfaces.** `/vm-terminal/`, `/kibana/` and 8002's
  `/site/` take nginx `auth_request` to `/auth-check/` (Django, internal
  only; 8000 answers 404 to it from outside), which also keeps the range-host
  refusal it had through `/api/attacker/`. A 401 becomes a redirect to the
  login page.
- **XSS on 8002.** Cookies are per host, so the session cookie reaches 8002.
  It is HttpOnly; the CSRF token is kept in the session (`CSRF_USE_SESSIONS`),
  so no cookie hands it to page script; every unsafe method needs it; the
  platform sends no CORS header; nginx drops `Cookie` before the site proxy
  and never passes the target's `Set-Cookie`. `test_signin.py` refuses a
  cross-origin POST without the token.
- **Elasticsearch security on.** The platform's root entrypoint makes the
  `elastic` password once, 0600, in `/data/elastic` on `cr_platformdata`;
  Elasticsearch, Kibana and the collector mount that directory (Kibana only
  its `kibana/` part) by volume subpath, so none of them sees the store. For
  that, Elasticsearch now waits for the platform's health check (the file
  exists) instead of the platform waiting for Elasticsearch, and the
  platform's own registration retries for five minutes. `deploy/elastic/start.sh`
  hands the password through `ELASTIC_PASSWORD_FILE` and makes Kibana's
  service account token (`elastic/kibana/cr-kibana`) with
  `elasticsearch-service-tokens`, kept beside the password. No password or
  token is in `compose.yaml` or a container's configured environment. The
  entrypoint copies the password to `/data/elastic-password` (owner `cr`,
  0600), which the platform reads, so `manage.py` run by `docker exec`
  reaches Elasticsearch as the server does.
  Learners never sign in to Kibana: `register_pipeline.py` PUTs the role
  `cr_viewer` (read on `logs-*`, Discover) and the user `cr-viewer`, and
  nginx passes that user's `Authorization` from `/auth-check/kibana/` on each
  request. Kibana accepts Basic on that header because its basic provider is
  on (`autoSchemesEnabled`); checked live, `internal/security/me` answered
  `cr-viewer` through the `http` provider. `ingest/elastic.fetch` takes an
  `auth` argument: `core_loc` 584 -> 587 (+2 there, +1 for `harness.run`'s
  `http` argument, which `redteam/run.py` fills with its signed-in session).
- **Project password.** `/opt/cr/openstack-password`, 0600 and owned by uid
  10001 (the platform's `cr`), cloud-init makes it empty, the hand-over
  writes it in place over ssh stdin, compose mounts it as the secret
  `openstack_password`; it left `openstack.env` and the environment. The
  hand-over now recreates the platform, since a file written in place is no
  change compose sees.
- **Ingress.** `network.allowed` in `cloud.yaml` (a list of IPv4 networks,
  default `[0.0.0.0/0]`, written by `init`) becomes one rule per network for
  22, 8000 and 8002 (`repeat` in the Heat template).
- **Docker socket.** The live-map entry removed the platform's socket and
  GNS3; no compose service mounts it and `test_containment` keeps it out of
  every slot container.
- **Kernel sharing.** gVisor release 20261026.0 (gvisor.dev
  "Installation"; `gvisor.tar.bz2`, SHA-512 in `setup.sh`), registered as
  `runsc` with `--net-raw` and `--platform=kvm` beside `userns-remap`. Kali
  runs on it; the WAF and the four targets ran on it too and stay on runc
  for now (below); checked live on a slot: an nmap
  SYN scan, curl through the WAF (XSS refused 403), sqlmap, the WAF's
  `nginx -s reload`, MySQL, the WAF audit log reaching the host file, and
  `docker exec -t` into Kali. What it took:
  - gVisor copies a sandbox's interfaces into its own netstack at start and
    removes the addresses from the host namespace, so `nsenter` changes
    nothing it sees. `slot.sh` enters a sandbox with `docker exec
    --privileged` (that one process gets every capability inside gVisor),
    and gVisor refuses `ip addr flush` (`Operation not supported`), so Kali's
    addresses are deleted one by one. board and corp now carry `iproute2`
    for their route through the edge. The wiring read uses `docker exec`
    for a sandbox and `docker inspect` for one without `ip`.
  - Kali wears its origin by SNAT. In gVisor iptables-nft failed with
    `Protocol not supported`, so Kali uses legacy iptables; gVisor refuses a
    SNAT rule that names no protocol (`Invalid argument`), so `set-origin`
    writes one per TCP and UDP; gVisor takes the owner match but never
    applies it, so the customers' exemption by account no longer held, and
    the rewrite now matches only the address Kali sends from unbound to the
    target. gVisor picks that address by the longest prefix it shares with
    the target, not by the route's `src` (`ip route replace ... src` answers
    `Operation not supported`; `ip route get` named 73.0.0.10 while the box
    sent from 14.160.0.10), so `unbound-source` reads it with a connected UDP
    socket's `getsockname`, and `attacker.unbound_source` asks the same
    script.
    gVisor keeps an owner-match rule it cannot apply (`-m owner [unsupported
    revision]`), and with that rule in `POSTROUTING` no packet left Kali at
    all (the Website pane said `board.com did not answer`), so the
    customers' exemption by account is gone; the rewrite matching only the
    unbound source is what spares them.
  - Docker's embedded DNS at 127.0.0.11 is out of gVisor's reach: board
    first exited with `Unknown server host 'board-db' (-3)`. Each backend
    network now has a fixed /28 (10.40.N+1.0/28 for board, .16/28 for corp,
    kept off 10.40.0.0/24 where docker0 takes the pool's first /28), every
    service a fixed address, and the others' names in `extra_hosts`.
  - On runc stay the two sensors (af-packet on the host network reads the
    slot's bridges; gVisor's netstack has no view of them) and the edge
    (forwarding and filtering by the kernel's nftables and sysctls). No
    learner has a shell in either.
  - The default platform, systrap, did not carry eight slots: during the
    first full `bin/verify` the range host's load average reached 66 to
    131 on six vCPUs (47.9 % system time, about 1,000 `gvisor_sentry`
    threads) and one `docker exec` into a board took 35.5 s, so the
    platform's 16 waitress threads queued and every request timed out.
    The range host has `/dev/kvm`, and on `--platform=kvm` the eight idle
    slots left the CPU 67 % idle at load 5.
  - With all six learner-facing containers on runsc (KVM platform), the
    eight-slot acceptance suite still drove the range host to load 48 to 67:
    board and corp-wp each held about half a vCPU, slot resets took six to
    eight minutes (under one on runc), and a `docker exec` into the WAF
    died with `urpc method "containerManager.WaitPID" failed: EOF` while
    its slot reset. The four targets went back to runc; Kali and the WAF
    stayed on gVisor. Moving the targets needs a range host with more CPU,
    a decision about the flavor that is the user's (`docs/STATE.md`).
  - The WAF on gVisor then exited in the next run's lessons: the platform
    changes the WAF's defence with an nginx reload over `docker exec` and
    waits for the workers, and the sandbox ended mid-exec (`waiting on PID
    113 in sandbox ...: urpc method "containerManager.WaitPID" failed: EOF`,
    docker `task deleted` 17 s before the slot's reset), in s4, s6 and s8,
    and in the run before. The WAF went back to runc; Kali stays.
  - Measured on slot 8 of eight with Kali, the WAF and both databases on
    runsc: `slot.sh reset` 48.3 s on runc, 55.6 s on runsc; the range host's
    used memory 10,180 MB -> 10,841 MB (+661 MB, gVisor's guest memory shows
    as shared), the WAF 40 -> 297 MiB, each database about +30 MiB.

Not chosen: runsc `--network=host` (the container would share the range
host's network stack); a resolv.conf pointed at a resolver (gVisor's FAQ:
names of other containers still fail); a forced password change (the
user's ruling).

## 2026-11-15 — Detection results are labelled 정탐, 오탐, 미탐 and 정상 통과

Supersedes the label part of R1 (2026-10-11, "No TP/FP/FN/TN labels anywhere
a person reads") and KO-K1 (R1 read as covering the Korean words for TP, FN
and FP as score labels). The rest of R1 stands: the primary score leads, and a
case counts once however many alerts it drew.

The user, reading the labels, asked "명칭이 이게 하… 명칭뭐 다른거없어?" and then
accepted 정탐/오탐/미탐. The ruling: the detection result (탐지 결과) of a case reads 정탐 (TP), 오탐 (FP),
미탐 (FN) or 정상 통과 (TN). What the user objects to is the English
abbreviations, so those stay out of anything a person reads; the API keeps
`tp`/`fp`/`fn`/`tn` for agents.

`test_strings.py::test_no_shown_string_labels_a_detection_result_with_the_english_abbreviations`
fails on TP, FP, FN or TN as a word in any string-table value; the Korean
terms are allowed. The guard R1 named had been deleted on 2026-10-16
(58d151c) and nothing caught the labels after it.

## 2026-11-15 — The web services stand behind the WAF alone

The test audit found that `test/test_range_isolation.py` asserted, on
purpose, that Kali reaches the board on 8000 through the edge, past the WAF.
The user ruled: "칼리에서 와프 안거치고 바로 때릴 수 있으면 안되잖아. 그럼 와프
룰설정이 뭔의미야" (if Kali can hit the board without going through the WAF,
the WAF's rules mean nothing).

What changed:

| | before | now |
|---|---|---|
| `board`, `corp-wp` | on `sN_estate` (10.30.N.59, .60) beside the edge's `lan` | on `sN_web` (10.30.N+128.59, .60), which only the WAF shares; still on `<wargame>-default` with their database |
| WAF | `sN_estate` 10.30.N.247 | the same, plus `sN_web` 10.30.N+128.247; `extra_hosts` `board` and `corp-wp` point at the web network |
| edge | routes `sN_internet` and `sN_estate` | unchanged; it has no route to `sN_web`, so Kali reaches a target only through the WAF |
| estate sensor | `--af-packet=sN-estate`, bpf on the targets' addresses | `--af-packet=sN-web`, the same bpf on their new addresses: the WAF-to-target leg it watched before |
| target default route | via the edge (`slot.sh routed`) | none; a target answers only the WAF. `slot.sh` still turns its offloads off |
| slots per range host | 1 to 255 | 1 to 127: slot N's web /24 is 128 above its estate /24 in `network.estate` |

Kept: the edge's nftables have no DNAT and forward everything they route,
which no longer includes the targets. The loot path and the effect path read
inside the board and corp-db containers and do not cross a network. The
live map (drawn from `docker network inspect`) draws the web network as its
own zone.

Tests: `test_range_isolation.py::test_the_attacker_reaches_the_sites_only_through_the_waf`
reads the WAF's own upstream addresses and fails if Kali reaches either of
them, or resolves `board`, `corp-wp`, `board-db` or `corp-db`. It replaces
`test/test_attacker_reach.py`, whose claim held only because those names do
not resolve on Kali. `test_judge_isolation.py` probes a role's default
gateways if it has any, as a target has none now. `test_range_host.py`,
`test_containment.py` and `test_estate_sensor.py` pin the new addresses,
networks and bridge.

## 2026-11-15 — Test audit applied

An audit of every test module (37 findings in six categories) was applied to
`dev`. Each finding was checked against the code first.

| # | finding | action |
|---|---|---|
| 1.1 | `test_scoreboard` "undetected costs more" was relative to `DETECTED_WEIGHT` | asserts lost-and-undetected is exactly twice lost-and-seen |
| 1.2 | `test_api_attacker` stub gave `source_ip` = `direct_ip` | different stub addresses, each field asserted |
| 1.3 | `test_api_objectives` asserted the row it had just created | line deleted |
| 2.1 | exact course titles in `test_foundations` | line deleted |
| 2.2 | exact zone captions in `test_gns3_topology` | deleted (the live map replaces the file) |
| 2.3 | `cr/wsgi.py` source line grep | imports `cr.wsgi` with `Thread` patched |
| 2.4 | `data-t` count in `session.html` | both rendered pages show the same confirmation |
| 2.5 | `auditor.html` source line | deleted |
| 2.6 | Kali Dockerfile greps (3) | deleted; live tests cover them |
| 2.7 | `set-origin` COPY grep | deleted; live tests cover it |
| 2.8 | whole ttyd command line | asserts only `/vm-terminal/waf` runs `vm-terminal.sh cr-waf` |
| 2.9 | "badge" absent from template source | deleted |
| 2.10 | template id order | deleted |
| 2.11 | WAF conf regex for `/internal/` | kept as the cheap guard beside the live test |
| 2.12 | "openstack WAF VM" name | renamed `test_the_waf_blocks_rather_than_detects` |
| 3.1 | `test_corp_observe_live` = `test_corp_authz` | folded in with the exact credited sets |
| 3.2, 4.5 | three copies of "baseline read at open"; one with a refused stub shape | `test_loot_session_start.py` and the `test_session_stack` copy deleted |
| 3.3 | catalogue labels twice | `test_api_redteam` copy deleted |
| 3.4 | two `test_api_objectives` tests inside `test_loot_submit` | deleted |
| 3.5 | corp blind open twice | `test_corp_session_start` copy deleted |
| 3.6 | second open refused twice | `test_session_start` copy deleted |
| 3.7 | `test_lesson_flavors` :20 inside :24 | deleted; "WAF VM" message reworded |
| 3.8 | both engines present, inside `test_evasion` | acceptance copy deleted |
| 3.9 | six foundations once each, inside `test_foundations` | acceptance copy deleted |
| 3.10 | window case POST twice | `test_api_sessions` covers `window`; `test_api_attacker` copy deleted |
| 4.1, 5.4 | `test_attacker_reach` claimed nothing past the WAF was reachable | module deleted; the check is in `test_range_isolation`, and the wiring closed the bypass (entry above) |
| 4.2 | compose range always ready | deleted (substrate removed 2026-10-21) |
| 4.3 | shared range refuses a second open | deleted (same) |
| 4.4 | FreeBSD sh option terminator | deleted (OPNsense removed 2026-11-13); "OPNsense edge" message reworded |
| 5.1 | four sessions in `test_concurrent_sessions` | one pair |
| 5.2 | three corp sessions | two: the content overwrite runs in `rogue_admin_session` |
| 5.3 | two terminal-window sessions | one `terminal_windows` session; the strategy test reads the labelled case's verdict |
| 5.5 | `test_indiscriminate_defence` in its own session | third phase of `rules_session`, scoped to its case ids; criterion 4 reads the benign case's own `FP` |
| 6.1 | benign cases could be deleted with every test green | `test_harness` pins each case file's benign names |
| 6.2 | no test held the isolation seams | `test_isolation_seams.py`: a static scan per seam, owners plus the CLAUDE.md exceptions; a missing owner file is nothing to scan. It found the attacker's label path in `cr/settings.py` (moved to `attacker.py`) and a `suricatasc` fallback there (removed; the declaration's sensor hosts name their reload, now checked) |
| 6.3 | the R1 label guard was gone | ruling above; guard back for the English tokens |

The unit note (`test_range_host.py:161` waiting 10 s of real time) was not in
the categories applied.

## 2026-11-16 — Each slot's monitoring is real: sensors on the bridges they watch, a 관제망 and a log server

Approved by the user. The live map draws only real wiring, and the sensors
(host network, sniffing the bridge device) and the log path (the range host's
own rsyslog reading files and forwarding them) had no place on a believable
company network. Each slot now runs its monitoring as containers.

- **Sensors are slot containers on the bridge they watch.** The edge sensor
  joins `sN-inet`, the internal sensor `sN-web`, each through an interface
  named `sniff` that `slot.sh` strips of its address (`--af-packet=sniff`).
  Each also has a `mgmt` interface on the new `sN_mgmt` (bridge `sN-mgmt`,
  172.29.N.0/24), the 관제망. They left the host network and the host user
  namespace and run under `userns-remap` like every other container, with
  the same capabilities (NET_ADMIN, NET_RAW, SYS_NICE). The image's
  entrypoint chowns its config, rule and log paths, so `slot.sh` hands them
  to the remapped root (owner and group; with the group left as host root,
  the first live run failed with `chown ... Operation not permitted`).
- **SPAN by `tc mirred`, measured against hub mode.** Every other port of the
  watched bridge gets an ingress `matchall` with `mirred egress mirror` to the
  sensor's port; the sensor's port learns nothing, floods nothing and drops
  what the sensor sends, so it is a receive-only port and each frame reaches
  the sensor once, from the port it entered by. `slot.sh` applies it on `up`
  and again at the end of `reset` for the recreated containers' ports. Hub
  mode (`ageing_time 0`, sensor port flooding) was run on slot 1 with the same
  red-team file: the edge sensor saw 150,197 packets and 5,267 alerts against
  150,066 and 5,267 with mirroring, the internal sensor 827 and 812 packets,
  13,691 and 60 HTTP events on both, kernel_drops 0 on both. Equal capture,
  so `tc mirred` stays: hub mode floods every frame to every port, so corp
  would receive every frame meant for board and the edge every frame meant for
  Kali.
- **A log server on the 관제망.** `rsyslog/rsyslog-minimal` pinned by digest
  (`sN-log-server`, .10). A shipper per log runs the same image with
  `imfile`: the sensors' shippers share the sensor's network namespace
  (`network_mode: service:<sensor>`), so a sensor's log leaves from its own
  관제망 interface; the WAF's shipper is its own container on the 관제망 (.13)
  reading the WAF's audit log through a read-only mount. That is the simpler
  of the two options and keeps the WAF, a learner's root shell, off the
  관제망 (its namespace was also on gVisor when this was chosen). Shippers send
  over TCP 514 so the in-slot hop pushes back instead of dropping; the log
  server names each log by the address it came from (`$fromhost-ip`), with the
  host names and tags the range host used (`cr-edge-N`, `cr-range-N`,
  `cr-waf-N`; `suricata`, `modsecurity`), and forwards to the platform
  collector on 5140/udp as the range host did, so `ingest/` and the event
  shapes do not change. The range host's per-slot rsyslog forwarding and its
  `rsyslog` package are gone. Each of the four rsyslog containers takes about
  1 MiB (cgroup).
- **The 관제망 is the one slot network with a way out.** The log server reaches
  the collector through the range host's NAT. `slot.sh` installs the filter
  before compose creates the network: INPUT drops everything from `sN-mgmt`,
  DOCKER-USER passes `sN-mgmt` to itself and the log server to the
  collector's 5140/udp and drops the rest; `down` removes the rules.
  `test_range_isolation.py` now probes from a sensor and the log server too.
- **The map reads the new facts.** A sensor's other legs are links to their
  switches; the log server is a node on the 관제망 (role `log-server`),
  labelled with the port it listens on (514/tcp, read from its config); a
  sensor's own interfaces are no learner host's address. A log edge is drawn
  only for a device off the log server's network (the WAF), since a sensor's
  log goes over the 관제망 link already drawn. The 관제망 is a band under every
  zone holding the sensors (straight below the bridge each mirrors), its
  switch at the router's x and the log server below it; its caption sits at
  its left. The coach line for F1's log question follows.

- **The range host names itself in `/etc/hosts`.** The first full verify on
  the new range host hung: every acceptance group waited for a slot while
  waitress held 80-odd queued requests and about 150 ssh commands to the
  range host, each a readiness read (the board's ground truth, both sensors'
  rules). `sudo` looks up the host's own name; the range host has no DNS once
  its egress port is gone and no `/etc/hosts` line for `cr-range`, and
  systemd-resolved's synthesized answer (about 190 link-local addresses)
  took 21.8 s, so every `sudo docker exec` waited that long. With
  `127.0.1.1 cr-range` the lookup takes 0.2 s and `GET /api/range/ready/`
  4.5 s with eight idle slots. `slot.sh` adds the line first thing on every
  `up` and `reset`, so a standing host gets it at its next configure and no
  host replacement is needed.

Measured on the live range (eight slots, `dba.range`), the same
`redteam/cases/board.yaml` run before (session 2129, slot 3, d927d757) and
after (session 2130, slot 1): every case the same verdict and `corroborated`
(TP 12, FP 0, FN 0, TN 6); suricata detections 5,272 and 5,267, ModSecurity
45,989 and 45,974 (sqlmap's random agent and tamper vary run to run); edge
sensor 149,823 and 150,066 packets, 5,271 and 5,267 alerts, 13,695 and 13,691
HTTP events; internal sensor 825 and 812 packets, 60 and 60 HTTP events;
`capture.kernel_drops` 0 on every sensor of every slot. Range host memory
with eight idle slots: 10,724 MiB used before, 10,627 after; per slot (sum
of its containers' cgroups) 1,179 MiB before and 1,183 after.
Full `bin/verify` on the platform VM at the deployed commit: 553 s,
acceptance 95 passed, 0 failed, 1 skipped in 497 s across 12 processes, unit
and API 849 + 814, ratchet no regression; during it `GET /` p95 2.6 s and
`GET /api/range/ready/` p95 6.1 s with eight slots.

## 2026-11-16 — Sign-up waits for an admin's approval; sign-in, sign-up, the API and sessions are rate limited

The user: "회원가입을 해도, 관리자가 직접 승인해야 하는거로 해놔." and "진짜
보안 위협은 rate limit 같은걸 해야지".

- `POST /api/auth/signup/` (`username`, `password`, `password_confirm`) runs
  Django's `UserCreationForm` and the four default password validators,
  which `AUTH_PASSWORD_VALIDATORS` now lists (it was empty). The account is
  made with `is_active=False`, not staff. Refusals carry Django's error codes
  (`errors[].code`) and the page looks each up in the string table, so the
  learner reads Korean and an agent reads codes. The validators do not touch
  `admin` / `123456`: migration 0030 hashes it directly, and
  `changepassword` asks before it bypasses them.
- `ModelBackend` refuses an inactive user, so a pending account cannot sign
  in, and a session it holds is anonymous to `/auth-check/`. Sign-in tells a
  pending account apart (403 `{"pending": true}`) only when its password is
  right, so the answer names no account to a guesser.
- Staff get `/users/` (the account screen, linked in the header when `GET /api/auth/`
  says `staff`), backed by `GET /api/users/`, `POST /api/users/<id>/approve/`
  and `POST /api/users/<id>/reject/`. Reject deletes and takes only a pending
  account (409 otherwise), so no admin can remove themself. No roles beyond
  staff and learner, no email.
- Limits, with the reason for each number:
  - Sign-in, nginx: 5 POSTs a minute per address, burst 5. A person who
    mistypes a few times is never held; a guesser gets about 300 tries an hour.
  - Sign-in, Django: 10 wrong passwords for one username lock it for 15
    minutes (429, `locked_until`, `Retry-After`). Ten is past any honest typo
    streak; 15 minutes holds a guesser to about 40 tries an hour per
    username whatever addresses it uses, and a locked-out learner waits
    no longer than a break. The cost: anyone can lock `admin` for 15 minutes; acceptance runs on the VM
    and signs in with the right password, so it is held only if someone
    else locked the account.
  - Sign-up, nginx: 1 POST a minute per address, burst 3. nginx counts per
    second or per minute only, so an hourly cap lives in Django.
  - Sign-up, Django: 5 accounts an hour per address, and none while 50 wait
    for approval (503 `{"closed": true}`). Five covers a class signing up
    behind one NAT in turns; fifty is more than one admin reviews in a sitting
    and bounds what a spammer leaves in the table.
  - `/api/`, nginx: 20 requests a second per session cookie (burst 40) and
    100 per address (burst 200). The console's busiest page polls a handful
    of endpoints every few seconds; the per-cookie key keeps a classroom
    behind one NAT apart, the per-address key catches a client that rotates
    cookies.
  - Terminals and port 8002, nginx: 10 open connections per session cookie.
    A learner holds two terminal WebSockets and the site pane's few loads;
    ten keeps one client from tying up the front's connections and the 16
    waitress threads behind `/site/`.
  - Sessions: a learner holds one open session; a second
    `POST /api/sessions/` is 409 `{"open_session": <id>}` and the main page
    links to it. Staff are exempt, because acceptance opens one session per
    worker as `admin`. `Session.owner` (migration 0031) records who opened it.
- Exempt from nginx's limits: loopback, the Docker gateway `172.31.0.1`, and
  the IP literals in `DJANGO_ALLOWED_HOSTS`, which `entrypoint.sh` writes to
  `/tmp/nginx-platform-addresses.conf` before `nginx -t`. Measured on the VM
  (2026-11-16, `/proc/net/tcp` in `cr-platform`): a connection from the VM to
  its floating IP arrives from `192.168.2.247`, to its fixed IP from
  `10.20.0.61`, and the operator's machine over the VPN from `10.10.10.3`.
  `DJANGO_ALLOWED_HOSTS` already holds the floating IP (the only address
  `bin/verify` can use, since Django refuses the fixed one), so it names the
  platform's own address without a new setting.
- The counters are in Django's default local-memory cache: one waitress
  process, so its threads share them; a restart forgets them. No new
  dependency (django-axes and django-ratelimit were not added).

Not chosen: a CAPTCHA (no new dependency, and the approval already stops a
bot's account from doing anything); locking by address and username together
(an attacker with many addresses would never lock, and nginx already limits
per address); `select_for_update` for the one-session check (SQLite ignores
it). The check runs again inside `SLOT_CHOICE`, the in-process lock that
already serialises the slot choice, so parallel opens by one learner get one
session.

## 2026-11-16 — gVisor and Elasticsearch security removed: they answered a fake risk

The user: "보안과 성능에서 성능을 더 신경써", "커널 공유를 받아들인 위험
자체가 아니잖아. 의미가 없다니까", "성능 때문에 gVisor를 뺀게 아니잖아", and
"ai의 가짜 위험. slop 위험이라고 적어." The kernel-sharing and
container-escape threat that brought in gVisor on 2026-11-15 was raised by the
AI, not by anything in this product: AI slop. So was the Elasticsearch
authentication. Both are gone. What the product already is makes them
pointless: the range host is its own OpenStack VM, so the hypervisor is the
boundary; it holds only the slots; it is rebuilt from the stock Ubuntu image;
its only way toward the platform is the collector port (and NTP); and only
signed-in users an admin approved reach the range at all. Elasticsearch and
Kibana listen on the platform VM's loopback only, the range has no route to
them, and nginx already refuses Kibana's management and dev tools APIs.

- **gVisor.** No `runsc` install, SHA pin or `runtimes` entry in
  `daemon.json`; every slot container runs on Docker's default runtime.
  Undone with it, because they existed only for gVisor: `slot.sh` enters
  every container with `nsenter` again (no `docker exec --privileged`, Kali's
  addresses flushed in one step), the wiring read uses `nsenter` only, board
  and corp drop `iproute2`, the targets find each other by Docker's embedded
  DNS again (no fixed backend /28, no `extra_hosts` for neighbours), and Kali
  wears its origin as before 2026-11-15: nft iptables, one SNAT rule for all
  protocols, the unbound source read from `ip route get`, and the customers'
  `-m owner --uid-owner cr-users -j RETURN` exemption back in `POSTROUTING`.
  `test_containment` asserts that no slot container names a runtime and
  `daemon.json` registers none.
- **Elasticsearch security.** `xpack.security.enabled: "false"` again; gone
  are the `elastic` password and its cr-owned copy, `deploy/elastic/start.sh`,
  Kibana's service account token, the `cr_viewer` role and `cr-viewer` user,
  `/auth-check/kibana/` and nginx's `Authorization` injection, and the `auth`
  arguments in the collector, `register_pipeline.py`, `ingest/elastic.py`,
  the views and `test/conftest.py`. `core_loc` 587 -> 585. Sign-in on every
  surface, CSRF, the project password file, `network.allowed` and the
  removed Docker socket stay.
- **The session check is cached.** Every `/kibana/`, terminal and `/site/`
  request ran an `auth_request` subrequest into Django with no cache, and
  Kibana's Discover loads 322 requests. nginx now keeps the check's answer in
  `proxy_cache signed_in`, keyed by `$cookie_cr_session`, `proxy_cache_valid
  204 401 5s` (nginx docs, "ngx_http_proxy_module": `proxy_cache_key`,
  `proxy_cache_valid`), with `proxy_ignore_headers Vary` because Django's
  session middleware sends `Vary: Cookie`. Measured live 2026-11-16, three
  first loads of `/kibana/s/soc-logs-1/app/discover` in a fresh headless
  Chromium each, with a temporary subrequest log: without the cache 963
  checks reached Django, with it 16 (1 MISS, 15 EXPIRED, 958 HIT). The load
  time did not change (5.9-6.7 s without, 5.8-9.1 s with; 6.2-11.1 s on the
  old stack): Kibana's own assets dominate it, not the check. A sign-out
  stays honoured within five seconds, since Django gives the browser a new
  session key at sign-in and sign-out.
- **Measured on the range host** (eight slots, 13 containers each, the
  range host replaced by `bin/cloud up` because `setup.sh`, `daemon.json`
  and the images changed): `slot.sh reset 8` 41.9 s and 46.8 s on runc
  against 50.1 s with Kali on runsc the same night; available memory with
  eight idle slots 5,674 MB against 4,869 MB.

## 2026-11-16 — One sensor per slot on both legs of the WAF; the WAF on the 관제망; the log server's uplink drawn

The user rejected the first 관제망 ("관제망이 이상하잖아", "실무처럼 하라고"): a
dashed line ran from the WAF to the log server though the WAF had no
interface there, the logs stopped at the log server, and two sensors (one on
the Internet side) are not how a monitored network is built. The design
follows the practitioner sources:

- Security Onion 2.4, Hardware: a sensor has "one or more interfaces
  dedicated to sniffing (no IP address)" and "one wired network interface
  dedicated to management (preferably connected to a dedicated management
  network)", and should "collect from inside the NAT boundary so that you see
  the true internal IP addresses" (https://docs.securityonion.net/en/2.4/hardware.html).
  `so-monitor-add` adds further sniffing interfaces to the one sensor
  (https://docs.securityonion.net/en/2.4/so-monitor-add.html).
- NIST SP 800-94, §3.1 (a sensor's management interface), §4.2 (sensors at
  the divisions between networks and on key segments such as a DMZ) and
  §4.3.3.4 (watching traffic after TLS is terminated)
  (https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-94.pdf).

What changed:

- **One Suricata sensor per slot** (`sN-sensor`), two sniffing interfaces with
  no address: `dmz` on `sN-estate` (the edge router to the WAF, before the
  WAF) and `web` on `sN-web` (the WAF to the web servers, after it), each fed
  by `tc mirred`, and one management interface on `sN_mgmt` (.11). No sensor
  on `sN-inet` (outside the perimeter). One rule file, one reload: the
  `sensor` role is on `cr-range`, `cr-edge` names no rule file, the
  `estate-sensor` role is gone. The config is `deploy/suricata/suricata.yaml`,
  now the full Suricata configuration the edge sensor ran, with `HOME_NET` the
  private ranges, `EXTERNAL_NET any` (so the WAF's requests to the targets on
  the web leg match the `$EXTERNAL_NET -> $HOME_NET` rules, as the estate
  sensor's did) and `HTTP_PORTS` 80 and 8000; one `af-packet` entry per
  sniffing interface. Lessons tell the legs apart by destination, as before;
  Kibana's `sensor` field is now the leg an IDS event was seen on (`in_iface`,
  `dmz` or `web`), and `waf` for ModSecurity.
- **The WAF ships its own log**: a management interface on `sN_mgmt` (.12)
  and its shipper in the WAF's network namespace (`network_mode:
  service:waf`), like the sensor's; the standalone `waf-shipper` container and
  its address are gone. A reset recreates the shipper with the WAF. The WAF is
  the one learner-facing container on the 관제망: it has neither `NET_RAW` nor
  `NET_ADMIN`, so it sends from its own address only, and the log server names
  every log by the address it came from.
- **The edge router stays off the 관제망**: nothing reads its logs.
- **The map**: every edge is an interface link, a mirror or the log server's
  uplink. The sensor's legs are its interfaces with no address; the 관제망
  switch sits under the WAF's management link; the uplink goes out of the
  관제망 to a node showing the address and port the log server forwards to
  (`10.31.0.x:5140/udp`, Filebeat on the platform), read from the log server's
  configuration. No log edge remains, since every log source has its own
  management link.
- `slot.sh up` now removes containers the slot no longer declares and the
  mirror on `sN-inet`, so a slot re-renders in place.

Parity against the two-sensor slots (same red-team files): the board's
verdicts are the same, TP 12, FP 0, FN 0, TN 6, every TP corroborated;
Suricata alerts 5,268 before and 5,266 after (sid 9000001 5,255 -> 5,253,
9000002 1, 9000003 6, 9000004 6); HTTP events on the DMZ leg 13,692 (seen
on `sN-inet` before) and 13,691, on the web leg 60 and 60; corp TP 0, FP 0,
FN 3, TN 4 both times. No alert was seen only on `sN-inet` beyond run-to-run
variance. kernel_drops 0 (568,800 packets on `s1-sensor`). RAM per slot about
1,146 MiB before and 1,126 MiB after (host used 10,452 -> 10,076 MiB, eight
slots).

Two shipping faults were found on the way, both at reset, where the WAF and
its shipper are recreated: started at the top of `audit.log`, the new shipper
sent the closed session's ~9,400 WAF records a second time (session 2201), so
the shipper starts at the end of its file (`freshStartTail`); then, started
at the end of a full log that `slot.sh` emptied afterwards, it read nothing
the new WAF wrote (session 2222: Suricata's alerts and no ModSecurity record),
so `reset` now empties `audit.log` before it recreates the WAF and its
shipper. Full `bin/verify` on the VM after both: 550 s, acceptance 95 passed,
0 failed, 1 skipped in 488 s across 12 processes, unit and API 833 + 830,
`core_loc` 585, `dependencies` 6, `services` 4.

## 2026-11-16 — A learner sees only their own sessions; the cached session check is keyed on address and session too

A docs review of `dev` found that an approved learner could list and drive
any session (no owner check in `api/views.py`; the sign-up live check saw
another account's session 2207 on a learner's main page), and that the
front's five-second cache of `/signed-in`, keyed on the session cookie alone,
let a cached 204 skip Django's refusal of range-host addresses.

- `api.accounts.OwnSessionsOnly` (middleware, `process_view`): for a
  non-staff user, a view whose URL carries `session_id` or `detection_id`
  answers 404 unless the session (or the detection's session) is theirs;
  `/api/range/` writes answer 403. Staff pass. `GET /api/sessions/` lists a
  learner's own; `_asked_session` resolves a missing `session` to the
  learner's open session, else their newest, else 409, and a named one
  through the learner's own sessions. Every request that acts on "the newest
  session" goes through it, so a learner never falls through to another's.
- `/auth-check/` reads `X-Original-URI` (nginx sets it from `$request_uri` in
  the `/signed-in` subrequest). A learner gets 403 for `/site/<id>/` or a
  terminal `?arg=<id>` naming another's session, for a terminal with no
  `arg`, and for more than one `arg` (ttyd hands the first to
  `vm-terminal.sh`, a pattern would read the last). Other URLs (Kibana) pass
  on the session alone.
- The cache key is `$cookie_cr_session|$remote_addr|$session_asked`, where
  `$session_asked` maps the URL to `site:<id>`, `terminal:<query>` or `""`.
  A range address never reuses another address's 204, and one session's 204
  never opens another's. Still 5 s, still 204 and 401 only.
- Acceptance and agents sign in as `admin` (staff) and are unaffected.

Not chosen: an owner check in each of the ~40 session views (the middleware
covers every route with `session_id` in one place, and new routes inherit
it); moving the range-address refusal into nginx (the platform's list of
range addresses lives in Django and changes per slot). Left open: Kibana is
not split by session, so a learner reads every session's logs there.

## 2026-11-16 — `test_corp_authz` runs its two corp sessions side by side and batches range commands: 182 s to 67 s

Measured live on the platform VM (module alone, three tests). Opening a corp
session took 5–7 s: slots stand warm and `slot.sh` restores corp-db and
corp-wp from the pristine copy, so no WordPress install or healthcheck wait
is on the path. The time went to range commands: each `run()` is a
`manage.py run_on_role` process costing about 3.3 s (1.0 s Django system
checks, 1.8 s imports, 1.5 s OpenStack API reads to find the range host,
0.3 s ssh and `docker exec`), and the two sessions made about 30 of them in
series, plus the 2 s and 7 s sleeps and the case POSTs (4–9 s each, since
recording a case observes objectives from the binlog).

- `corp_sessions` opens both corp sessions at once (two threads) and returns
  `rogue_admin_session` and `option_flip_session`; `test_corp_authz` joins
  `TWO_SESSIONS` in `bin/acceptance`, so it takes two slots.
- A nonce is read and spent in one attacker call (`with_nonce`, `grep -oP`);
  the two option flips share that call. Reads that answer no later step run
  in one call (`run_side_by_side`), and each cleanup is one call per host
  (`run_in_turn`, new in `test/range.py`, sequential with the same part
  marks). In-window reads run beside the case POST.
- The 2 s settle and 7 s window gap are waited only for what the calls
  before them did not already take.

Kept: two sessions. One session would cost about 12 s more than two side by
side and would drop a check: objectives are unique per session and key, so
whichever breach goes second could not show it credits only its own
objective (the flip's `credited == {"corp-self-registration"}`, or the rogue
pair's exact set). Every assertion is unchanged. Left open: `run_on_role`'s
3.3 s floor is platform-side (`requires_system_checks`, the OpenStack lookup
per process) and would speed every acceptance module, but it needs a
platform image to measure.

## 2026-11-16 — The IDS stands behind the WAF; nginx's own refusals are WAF evidence; the live map redrawn

**The ruling.** The user: "waf 뒤 IDS가 맞잖아. 요청이 오지 않는거도 당연한거
아니야? waf 로그에 남겠지." The slot's one Suricata sensor sniffs only the
web servers' segment behind the WAF (`web` on `sN-web`); the DMZ leg added
earlier today is gone, after the user asked why every passed request was
logged twice ("로그 2배로 발생하는거 아니야?"). A request the WAF stops never
reaches the sensor; the WAF's own logs are its evidence.

**Measured before the change.** The two-leg one-sensor runs record each
Suricata event's leg (`in_iface`). Board session 2204: 5,266 Suricata
alerts, every one on the DMZ leg, 0 on the web leg, which carried 60 passed
requests (sqlmap's backtick and `/**/` probes; none matches the four
baseline rules on either leg). Re-scored with the platform's own
`correlate`/`score` without the web leg: unchanged (sessions 2203 and 2204,
TP 12 FP 0 FN 0 TN 6; corp 2202, TP 0 FP 0 FN 3 TN 4). Without the DMZ leg,
two board TPs fell to FN: `board-sqli-search`, which ModSecurity did block
but whose audit record the reset shipper fault of 9eed805 had dropped, and
`board-path-traversal-static`, which the WAF's nginx answers with 400 while
it parses the URI, before ModSecurity runs and before it reads any header,
so nothing but the DMZ leg had seen it.

**nginx's refusals.** The WAF's nginx now writes the requests it refuses
itself (status 400) as JSON to `/var/log/nginx/refused.log`, a host file
`/var/log/cr/sN/waf/refused.log` mounted into the WAF and read by the
waf-shipper under the tag `nginx`; the log server relays a sender's lines
only under the tags its own logs carry. Ingest turns a line into a WAF
detection (`source: nginx`). The error log could not hold it: nginx logs
"client sent invalid request" at `info`, below the WAF's `error` level, and
s7-waf's `error.log` was 0 bytes when the coordinator replayed the case. With
no header read there is no `X-Request-ID`, so `board-path-traversal-static`
is now correlated by `window` (the attacker's default-origin address, which
the cases API fills in, and the time). In board session 2274 it is TP,
`corroborated: false`; its record is `400 GET
/static/..%2F..%2F..%2F..%2Fetc/passwd HTTP/1.1`, which does not name the
mechanism its `expect: "traversal"` asks for. Its first score also credited
it with 214 ModSecurity records of the XSS and sqlmap cases the same address
had fired in the 2 s slack, so it would have been TP with no refused log; a
window case now leaves a record that another request's marker names to that
request (`scoring/correlate.py`), and re-scored, the case's evidence is its
one refused record.

**The attacker's address behind the WAF.** Suricata's EVE output reports the
X-Forwarded-For address as the docs describe it: "HTTP X-Forwarded-For
support by adding an extra field or overwriting the source or destination IP
address (depending on flow direction) with the one reported in the
X-Forwarded-For HTTP header" (Suricata 8.0 docs, Eve JSON Output). The sensor
runs `xff: {enabled: true, mode: extra-data, deployment: reverse, header:
X-Forwarded-For}`; `overwrite` would have put the client's address in
`src_ip` and taken away what F3 teaches (the server sees the proxy, the
client is in X-Forwarded-For). Measured: http records carry `xff`; URI alerts
do not, because Suricata raises them after the request line and before it
reads the headers. Ingest credits a Suricata alert to the `xff` of the http
record of the same transaction (`flow_id`, `tx_id`). Shown on slot 2,
session 2273: an alert with EVE `src_ip` 10.30.130.247 (the WAF) is credited
to 5.188.10.10. `core_loc` 585 -> 592: +4 for the nginx record, +3 for the
transaction's address.

**What else follows.** The readiness canary fires the blocked SQLi probe and
a passed `/search/?q=canary`: ready is ModSecurity's alert on the first and
Suricata's http record of the second, within the skew bound, with no
synthetic rule in the learners' rule set. Acceptance sessions that need both
engines put the WAF in the posture `tuned_session` already used (rule 949110
excluded on `/search/`, so ModSecurity logs the SQLi and lets it reach the
IDS); `full_run` requires ModSecurity only; the disabled-rule test disables
sid 9000001 and checks that the IDS goes silent on the attack the WAF still
logs; the acceptance check that a case drawing only noise is not corroborated
moved to the scoring unit tests, because behind the WAF every attack the IDS
sees is also on the WAF's record. `slot.sh up` recreates the sensor so Suricata reads a changed config
(the running sensor kept writing records without `xff` until restarted). F3's
count reads the one leg there is; F1's last map question asks for the log
server's IP address, since its label is now "로그 서버" and a Korean answer
cannot be checked outside the string table.

**Parity against the two-leg sensor, same red-team files:** board 2274, TP 12
FP 0 FN 0 TN 6 (every TP corroborated but the traversal case, above); corp
2275, TP 0 FP 0 FN 3 TN 4. Suricata alerts in the board run: 1 (the WAF
passes nothing the baseline rules match); ModSecurity 45,974; nginx 1.

**The map.** Drawn from the slot's real wiring only, as a practitioner draws
a logical diagram: each subnet a captioned box with its CIDR ("a Layer 3
diagram must show all of the important network segments and subnets";
security zones, "put a box around them, and label the box clearly" — Kevin
Dooley, Auvik, *The No-Sweat Guide to Network Topology*, pp. 17-19; "Inside
the network ovals put the full network and netmask (use /XX notation)" and
each link's address "near the interface" — FIU CGS4285, "Documenting
networks"). Our choices on top, by the user's rulings: a switch per subnet is
drawn although Dooley's Layer 3 guidance omits switches ("아니 스위치 그려");
each interface's full address stands beside its device on the side its link
leaves, or just inside the box its link enters when it leaves the device's
own box, never mid-line ("저 아이피는 양쪽으로"); the WAF stands inside the
DMZ, the web servers inside the 웹 서버 구간, the router on the boundary;
the slot's both wargames are drawn, each DB zone named after its wargame;
nothing outside the slot (no range host, platform VM or collector), no ports,
no legend, no parentheses; the IDS's link to the web switch is an ordinary
solid line, since no source gives a convention for a SPAN link. Names are
Korean role names (라우터, 로그 서버) and proper names (Kali, WAF, IDS).

## 2026-11-16 — `run_on_role` skips system checks and finds the range host from a 60 s record: 3.0 s to 1.3 s a call

Each acceptance range command is one `manage.py run_on_role` process. It ran
Django's system checks (about 1 s, the URL check importing every view) and
signed in to Keystone and read networks, servers and subnets to find one
management address (about 1.5 s). Now the command sets
`requires_system_checks = []`; the OpenStack adapter signs in only when it
first asks the cloud; every cloud read writes the range host's address and
host key alias to `CR_RANGE_HOST_SEEN` (`/data/range-host.json`, the
platform's data volume), and an adapter that has read nothing itself uses a
record younger than 60 s. A command that never reports finishing deletes
the record, so a range host rebuilt on another address is read again on
the next call. No new dependency; deployed by fast-forwarding `/opt/cr` and
recreating the platform container (the code is bind-mounted).

Measured on the platform VM, each module alone, no session open at start:

| | before | after |
|---|---|---|
| one `run_on_role` call | 2.7–3.5 s | 1.15–1.35 s |
| `test_corp_authz` | 78 s | 90 s, then 61 s |
| `test_acceptance` | 109 s | 123 s, then 97 s |
| `test_concurrent_sessions` | 63 s | 46 s |
| `test_lesson` | 97 s | 81 s |

The first run after the platform restart was slower than before for two
modules; the repeat was faster, so module times vary by about 15 s between
runs. Left in each call: about 0.4 s of `django.setup()`, 0.5 s of imports
(Django's management package, the adapter and `requests`), 0.2 s of ssh
and `docker exec` on the range host, 0.15 s of `docker exec` into the
platform. Under a second needs an entry point that does not boot Django.

## 2026-11-16 — A session's slot runs only that session's wargame

The user: "망은 시나리오 별로 달라야하지 왜 시나리오 2개가 같이있지?" The
ruling of 2026-10-15 ("The learner map is the company network the learner
defends, named by role, one map per wargame": "board and corp appeared
together though a session defends one wargame") had been met by hiding the
other wargame on a drawn template; the map now draws the slot's real wiring,
so the slot itself must run one wargame. Opening a session runs
`slot.sh play N <the wargame's services>`, which stops the other wargame's
containers (`compose stop -t 1`); the map, which reads only running
containers, then shows only the session's site and database. A reset starts
every wargame again (`targets_reset` as before), so an idle slot stands ready
for either and readiness still reads the ground truth.

Session open, POST `/api/sessions/` to 201 on warm slots, two runs each:
before board 15.0 s and 16.6 s, corp 8.1 s and 10.4 s; after board 12.0 s and
17.2 s, corp 16.5 s and 10.8 s. The stop adds at most a few seconds, within
run-to-run spread. A board session's map: Kali, 라우터, WAF, board.com,
board-db, IDS, 로그 서버; a corp session's the same with corp.com and corp-db.

## 2026-11-16 — A failed sign-in blocks the client, not the account; staff accounts after three

The user: "admin 은 3번 이상 IP 차단 및 가능하다면 핑거프린팅 기반 차단".

The per-username lock of the same day (10 failures lock the name for 15
minutes) let anyone lock `admin` out from anywhere. It is gone; `api/blocks.py`
counts failures per client instead.

- Against a staff account: 3 failures from one address within an hour block
  that address from signing in for an hour. Three is the user's number; an
  hour outlasts a scripted guesser's patience at nginx's 5 a minute and is
  short enough that a mistyping operator is not shut out for the day.
- Against any other name (a learner, or a name that does not exist): 10
  failures block the address for 15 minutes, the numbers the old lock used,
  because a per-name lock had the same abuse (anyone could lock a learner out).
- Fingerprint: a SHA-256 of the headers the browser sends with the sign-in
  (User-Agent, Accept, Accept-Language, Accept-Encoding, Sec-CH-UA,
  Sec-CH-UA-Mobile, Sec-CH-UA-Platform), counted with the same thresholds and
  blocked once it has failed from at least two addresses: the client that
  rotates addresses and keeps its browser. One address alone never blocks a
  fingerprint, so people sharing a browser build are not blocked by a single
  mistyping colleague.
- TLS fingerprints are not available: "JA4 looks at the TLS Client Hello
  packet" (FoxIO, JA4 technical details), and port 8000 is plain HTTP.
  Sec-CH-UA is "available only in secure contexts (HTTPS)" (MDN, Sec-CH-UA),
  so over http those three headers are usually empty. All of the fingerprint
  is chosen by the client: a script that changes its User-Agent with each
  address is held only by the per-address count.
- A blocked client is refused (429, `blocked_until`, `blocked_by`,
  `Retry-After`) even with the right password. Blocks are `SignInBlock` rows
  (migration 0032), listed by `GET /api/users/blocks/` and lifted by
  `POST /api/users/blocks/<id>/unblock/` (staff only) on the account screen.
  The failure counters stay in the local-memory cache.
- The platform host (loopback, 172.31.0.1, the IP literals of
  `DJANGO_ALLOWED_HOSTS`) is never counted or blocked, so acceptance and an
  admin on the VM always sign in.

Not chosen: locking the account after N failures (the abuse this replaces);
a JavaScript canvas or font fingerprint (more code in the page, and just as
client-chosen); JA4H, FoxIO's fingerprint of "the HTTP client based on each
HTTP request" (JA4H technical details), not implemented here: Django sees the
headers only after the WSGI server has parsed them into a dictionary, and a
JA4H value would be as client-chosen as the hash above.

## 2026-11-16 — F4 and 3.4 run the WAF in DetectionOnly mode; 3.1-3.3 attack with sqlmap's `--random-agent`

With the IDS behind the WAF (the entry above "The IDS stands behind the WAF"),
the IDS sees only what the WAF passes. Four exercises asked the IDS to catch
attacks the WAF blocks in full at paranoia 1, so they could not be completed.
The user ruled both kinds stay.

F4 and 3.4 (XSS, every request blocked at PL1): their defenses (`xss-gap`,
and `xss-watched` for 3.4) set the WAF posture's new `detection_only: true`,
which `rules/crs.py` writes as `ctl:ruleEngine=DetectionOnly` on the posture's
`SecAction` (ModSecurity's DetectionOnly: rules are processed, disruptive
actions are not). The WAF records the request and lets it through; the IDS
behind it must catch it. F4's text now says so; its `fired` step's
destination is board.com's address, no longer the WAF's. Live on 2026-11-16
(sessions 2368-2370): `<script>` and `<ScRiPt>` searches answered 200, the
audit log still carries 949110 "Inbound Anomaly Score Exceeded (Total Score:
20)", F4's `rule` and `ids_none` steps pass, and the learner's rule alerted
with `dest_ip` board.com's address on the `web` segment. `core_loc` 592 -> 597.

3.1-3.3 (sort-parameter sqlmap, "the attack slips past the WAF"): measured
first with the solution rules (an `http.uri` allow-list on `sort`), all three
failed with `board-sqli-orderby-sqlmap` undetected (sessions 2363, 2364,
2366): sqlmap's stock User-Agent draws 913100 "Found User-Agent associated
with security scanner" (5 points) on every request, so every request is
blocked at PL1 and none reaches board.com. Real attackers pass
`--random-agent`; the three scenarios now attack with
`board-sqli-orderby-sqlmap-random-agent`. Live with the solution rules
(sessions 2371-2373), each final check passed: about 2,350 requests blocked
by 949110 and 8 that reached board.com and drew the IDS alert per
random-agent case; in 3.3 the tamper case had about 2,400 blocked and 14
alerted. The 3.1/3.2 text no longer says the WAF blocks the attack in full.

The same rounds proved Suricata's alert `xff` live: an alert on slot 2 carries
`"alert":{..."xff":"175.192.0.10"}` beside `http.xff`.

## 2026-11-16 — Kibana keeps a learner to their open session's slot through a platform gate

Kibana was shared: from a session's space (`soc-logs-1`) a signed-in learner
could POST `/internal/search/es` with `"index": "logs-2-*"` and read slot 2's
logs (live: 10053 hits), or batch the same through `/internal/bsearch`.
Elasticsearch security stays off, and Kibana's own documentation says spaces
are no boundary then: "Controlling feature visibility is not a security
feature" (Kibana 8.15, Spaces). So the boundary is outside Kibana.

nginx hands every `/kibana/s/<space>/api/` and `/internal/` call (case
blind) to Django's `/kibana-gate/` with the raw `$request_uri`;
`kibana.refusal` allows a call only on a list of what Discover asks, only in
a space of a session the learner has open (staff: any), and only when every
index named is exactly that slot's pattern; no key `index`, `_index`,
`indices`, `namespace(s)` may appear in the body or query (terms lookup,
`more_like_this`, cross-space reads). `kibana.forward` sends the call on
with Kibana's own headers. The session spaces turn request batching off
(`bfetch:disable`, Kibana source `bfetch-plugin/server/ui_settings.js`:
"Disables requests batching"), so the search interceptor POSTs
`/internal/search/ese[/<id>]` (Kibana source
`data-plugin/public/search/search_interceptor/search_interceptor.js`) and
each body is checked whole.

Rejected: a denylist of administration routes (what nginx had: it let any
index through search, value suggestions and field lists); rewriting the
index in nginx (nginx cannot read a body before proxying; `auth_request`
drops it); per-slot Kibana instances (a service per slot); Elasticsearch
security (removed on purpose).

Left refused because Discover works without them: `resolve_index` (would
list every slot's index names), `internal/saved_query/_count` (its path
matches the Elasticsearch seam's `/_count` pattern; the saved query menu
shows nothing), and Discover's own `index: "*"` probe for the empty-result
hint. Staff keep the same call list but may name any index.

Live, as a learner with an open board session on slot 1: own-slot search
200; typed `logs-2-*`, `logs-*`, `.ds-logs-2-...`, `logs-1-*,logs-2-*`,
strategies `es`/`esql`/`sql`, `bsearch`, terms lookup into logs-2, Dev Tools
console proxy, the other slot's space, field list and value suggestions of
logs-2, `resolve_index`, a data view create, `_find?namespaces=*`, upper-case
and dot-segment paths and an advanced-settings write all 403; Discover's
data view editor cannot resolve `logs-2-*` and keeps "Use without saving"
off. Discover in the blue console showed the session's own alert after a
`board-sqli-search` run; staff read slot 2 from slot 1's space.

## 2026-11-17 — Staff delete an approved learner; their open sessions close through the close path

An answer-blind walk left an approved account (`walk23-697305`) that the
account screen could approve or reject but never remove. `POST
/api/users/<id>/delete/` (staff only, the approve/reject style) deletes a
non-staff account and answers 409 for any staff account and for the caller's
own. Before the delete it calls `close_session` for each of that learner's
open sessions, so the slot is rebuilt and released exactly as when the
learner closes it; deleting the user alone would leave the session open on
the books (owner set null by `on_delete=SET_NULL`), holding its slot with no
one to close it. Closed sessions stay with a null owner, as the foreign key
already allowed, so scores and detections are kept. The users page shows a
delete button on learner rows of the active table, behind a `confirm()`.

## 2026-11-17 — Answer-blind walk round 24: the learner's own XSS is a case, a scenario lists the objectives its attacks can take, 3.3's variant runs before the check

- **The XSS a learner sends from the website pane is an attack case.** The
  course 2 result listed four sqlmap runs and none of lesson F4's XSS requests,
  though the learner's rule 9100001 had alerted on them: browsing carries the
  session's browse marker and `/score/` drops it whole, so a learner's
  deliberate attack and an ordinary page view looked alike. A lesson check
  that names `case:` (F4's probe, upper, write, slipped and replay steps,
  `board-xss-script-tag-in-search`) now records, when the step passes, one
  case of the requests its pattern matched since the step was reached, with
  each request's time and URL in `meta.sent`. In `/score/` a browse-marker
  detection whose URL is one of those requests and whose time is within 5 s
  of it counts for that case; every other browsing detection is still left
  out. The case is judged like any other: TP if any detector alerted,
  `corroborated` against the case's `expect` ("XSS"). Rejected: one case per
  lesson (a probe the IDS missed and a replay it caught are two decisions),
  and a fresh marker per request (the proxy cannot tell an attack from a page
  view; the lesson's own pattern can).
- **A scenario lists the objectives its attacks can take.** 3.4 (comment XSS)
  showed the three account objectives as "지킴". The board's objectives are
  its account hashes, and only an attack that dumps them (`--dump`, the same
  test the debrief's `_taking_the_secret` already uses) can take them, so
  `GET /api/wargames/<id>/objectives/?scenario=` lists the tiers only when one
  of the scenario's attacks dumps (3.3, 1.x, 2.x, 4.1) and none for 3.1, 3.2
  and 3.4. Crediting is unchanged: the target's ground truth still decides,
  and a tier the target lost is listed and counted whatever the scenario
  staked. No new declaration was added to `scenario.yaml`; the case file
  already says what each attack does.
- **3.3's variant runs before a final check started at three minutes.** The
  brief says a second attacker is sending a differently shaped request; the
  walk started the check at 3:20 and the tamper run, due at 300 s, first ran
  inside the check. The plain run is now due at 45 s and the variant at
  120 s (each about 50 s), and the final check, which re-sends every case
  not already inside it, sends both again.

## 2026-11-17 — The edge router holds one public IP of its own and port-forwards to the WAF

The user's ruling: the router's WAN side holds one public IP, as a real
company's edge router does; that IP must look like a company's line, in a
block of its own (not in the attacker Kali's /24, not a `.1`); board.com and
corp.com resolve to it, and the router port-forwards the web port to the WAF.
Until now `sN-edge` held 31 addresses on `wan` (the `.1` of each of the 30
origin /24s, so replies to Kali's 100 addresses were on-link), and Kali's
`/etc/hosts` named both sites by the WAF's private estate address.

- **Address.** `rangehost.ROUTER_WAN` is 121.134.88.42/29: whois places
  121.128.0.0/11 with Korea Telecom (KORNET, KR), and a /29 is what an ISP
  gives a business line (.41 its gateway, .42 the customer's router). It
  overlaps none of the 30 origin /24s, which a unit test checks.
- **Reachability.** The two sides share the slot's `internet` bridge, so on-link
  routes are enough: Kali `default via 121.134.88.42 dev eth0 onlink`, the
  edge `default via 5.188.10.10 dev wan onlink` (Kali stands in for the
  Internet beyond the router). Kali's route names `src 5.188.10.10`: without
  it the kernel preferred the first address on eth0 (73.0.0.10), the origin
  SNAT rewrote nmap's raw SYN probes to the default origin's address, nmap's
  capture saw the replies addressed to that address and reported port 80
  filtered (the full live verify's SYN-scan test, reproduced on the range
  host). The old route via 5.188.10.1 gave 5.188.10.10 as the source
  implicitly; `attacker.unbound_source` reads the same address. Rejected: one
  route per origin /24 (30 routes saying what one default route says).
- **Port forwarding.** `rangehost.port_forwards` renders `edge-nat.nft` (since
  2026-11-17 `rangehost.edge_rules` and `edge.nft`, below), a
  `table ip nat` prerouting `dnat` of `wan` tcp 80 on the public IP to the
  WAF's estate address; `slot.sh` loads it with `nft -f` inside the edge
  after addressing `wan`. No SNAT, so the WAF and the sensor see each
  client's own address and X-Forwarded-For, customer attribution and scoring
  are unchanged. The edge's own `edge.nft` (image) is untouched.
- **Names.** `slot.yaml` gives Kali `board.com` and `corp.com` at `@router@`,
  filled from `ROUTER_WAN`. Each origin segment of the slot's shape names
  the public IP as its `gateway` and lists only Kali's addresses as nodes
  (`openstack._read`; the router's address is on none of the origin /24s,
  and the live acceptance test holds every drawn node to its segment's
  subnet). The Website pane connects to that gateway (`site.found_egress`),
  so its remote address reads 121.134.88.42:80 as a browser's would.
- **Map.** The map reads the live wiring, so the router's WAN label is
  "121.134.88.42" with no "외 N개"; Kali's eth0 keeps its count. The path
  lesson's coach and hint say the name points at the router's public IP and
  the router forwards to the WAF.
- **Left as is, then replaced the same day.** The edge forwarded anything
  from `wan` to the estate, so Kali could also reach the WAF's private address
  directly; the isolation acceptance test probed that way in. Replaced by the
  next entry.

## 2026-11-17 — The edge lets in from the Internet only replies and the forwarded port

Walk round 26 finding 4: the lessons teach that Kali reaches the WAF only
through the router's public IP, but from Kali `nmap` showed the WAF's DMZ
address 10.30.1.247:80 open and `curl` got 200, because the edge's forward
chain (`deploy/edge/edge.nft`) accepted everything. An edge router drops
unsolicited inbound traffic to the private addresses behind it.

- **Rule.** `rangehost.edge_rules` renders `edge.nft` (was `edge-nat.nft`):
  the `table ip nat` port forward as before and a `table ip inbound` forward
  chain: from `wan`, `ct state established,related accept`,
  `ct status dnat accept`, then `drop`. `slot.sh` loads it with `nft -f` in
  the edge after addressing `wan`, as before. A drop in any base chain on the
  hook is final, so the image's accept-all forward chain is left as it is and
  the range images (and the range host's tag) do not change.
- **Outbound.** Nothing from `lan` is filtered: the WAF's replies are
  conntrack-established and nothing in the slot opens a connection out
  through the edge (log shipping goes over `mgmt`, not the edge).
- **Who used the direct path.** Only the acceptance tests: the isolation
  test's "way in" probe and its SYN scan went to the WAF's estate address,
  and the exfil test named its address variable `waf` for what is the public
  IP. They now go to the address `board.com` names on Kali (the public IP),
  and the isolation test also probes the WAF's private address and requires
  it closed (`connect` fails, SYN scan `filtered`). The harness, the
  customers, the readiness canary and the Website pane already went by
  `board.com` or the public IP; the platform's ground-truth reads go into the
  target containers, not through the edge.
- Measured live (slot 8, rules loaded the way `slot.sh` loads them): from
  Kali `nmap -sS -p 22,80,443 10.30.8.247` all filtered, 121.134.88.42 80
  open; `curl http://board.com/` and `http://corp.com/` 200, from a
  non-default origin address 200; `curl` to 10.30.8.247 times out.

## 2026-11-17 — The comment cases post the comment form as a browser does

Walk round 26: in lesson 3.4 the WAF runs DetectionOnly, yet the attack
comment showed 403 in the WAF log and in the IDS http log, so board.com
itself refused it. Cause, in the case definition: `board-xss-img-onerror-in-comment`
(and the benign `board-normal-comment` in its shape) sent a JSON body with
no CSRF token. Django's `CsrfViewMiddleware` refused it 403, and even past it
`add_comment` reads `request.POST`, which a JSON body never fills. The
stored XSS never landed. Not a deliberate failure path.

- **Case.** Both cases now `prefetch` `/posts/1/`, read the `csrftoken`
  cookie from its `Set-Cookie` and the form's `csrfmiddlewaretoken`, and post
  the form urlencoded with that cookie, the token, `Origin` and `Referer`,
  as the browser sends the board's own comment form (the customers already
  post it this way, `traffic.py`).
- **Harness.** `tools.fetch_argv` reads the response with `curl -i`, so a
  pattern can match a header; `apply_prefetch` fills `{name}` for each named
  group of the pattern beside `{nonce}` for group 1, and leaves a header out
  of the prefetch GET while it still holds a placeholder.
- **Lesson 3.4.** The attack body is now what a browser sends:
  `body=%3Cimg+src%3Dx+onerror%3Dalert%281%29%3E`. Suricata's
  `http.request_body` is not URL-decoded: measured live, `pcre:"/on[a-z]+%3D/i"`
  and `content:"onerror"` on `http.request_body` alert, `pcre:"/on[a-z]+=/i"`
  does not. The `handler` hint now says the form arrives URL-encoded, `<` as
  `%3C` and `=` as `%3D`.
- Measured live (slot 1, WAF DetectionOnly): the attack comment answers 302
  and is stored (`Comment` 32, body `<img src=x onerror=alert(1)>`); the
  benign comment is stored too; with the WAF blocking (PL1) the attack is
  refused by the WAF, not the board.

## 2026-11-17 — A zone box is its subnet; the IDS stands in the mgmt box

The user's ruling: a zone box on the map is one subnet, and a device stands in
the box of the subnet it has an address in. The IDS's only address
(172.29.N.11) is on the mgmt network, so drawing it inside the web segment's
box (10.30.N.0/24) contradicted the box. The IDS now stands in the 관제망 box,
right under the web segment's switch; its mgmt link carries 172.29.N.11 beside
the IDS as every other link does, and its unaddressed mirror link leaves the
관제망 box straight up into the web switch. The two links part at a right angle
at the IDS so it does not read as an inline device between the two switches.
Rejected the same day: the IDS hanging inside the web box, and its address
written under its name with neither link labelled.

## 2026-11-17 — The range host's images are tagged by the last range-side change, so a platform-only replace keeps it

A live `uv run bin/cloud up --replace` took 26 min: the backup 29 s, the
stack, boot, cloud-init and hand-over 477 s, the API wait and converge 1055 s.
Most of the 1055 s was a new range host. The range host pulled its images at
`CR_IMAGE_TAG`, the platform's own commit, and carried it in `cr_tag`, so every
new platform commit made it stale (`_plan` in `platform/range/openstack.py`)
and `POST slot/` deleted it and booted another. Of the 249 commits on `dev`
since 2026-11-10, 9 changed a range image's build context. The recorded intent
was the other way: 2026-10-11 "so the range can stand through a replace", and
`docs/OPENSTACK.md` §5.3 "You do not need to tear the slot down". §3.6's "A
platform on a new commit … makes the range host stale" was a consequence of
reusing the platform's tag, not a goal.

- The range host's tag is `CR_RANGE_IMAGE_TAG`, written by the platform VM's
  first boot with `bin/range-image-tag` (`range_image_tag` in
  `bin/platform-rebuild`): in the `/opt/cr` clone, the last commit that changed
  the build contexts `images.yml` gives the six range images, the paths the
  sideload check (`refuse_unless_unchanged`) already compares. The platform's
  image keeps `CR_IMAGE_TAG`. The bundle digest is unchanged, so a change to a
  bundle file (setup, rendered pristine compose, `daemon.json`) still makes the
  range host stale.
- `images.yml` tags only the head commit of a push, so the last range-side
  commit may have no images: 089717e, today's, has none; the next commit,
  014bc78, has them. The tag is the first commit from the last range-side one
  to HEAD whose range contexts equal HEAD's and for which GHCR has all six range
  images. Later commits only add to the end of that list, so the choice holds
  while the contexts do. When none qualifies, or GHCR does not answer, it is
  HEAD, whose images `bin/platform-rebuild` checks before it deletes anything.
  Rejected: CI also pushing each range image under the range-side commit. It
  needs a YAML reader in the job (the runner's `python3` is not documented to
  have PyYAML) and would overwrite an old tag with a rebuild whose digest can
  differ.
- Kali's and the WAF's build context is all of `deploy/`, so a change to
  `deploy/openstack` or `deploy/range-host` would have moved the tag (66 of the
  249 commits). `images.yml` now gives them `sources` (`deploy/kali
  deploy/proxy`, `deploy/waf`), the files their Dockerfiles copy; a test holds
  each narrowed `sources` to its Dockerfile's `COPY` lines. The sideload check
  compares the same narrower paths.
- `bin/cloud` asks the API every 5 s instead of 30 s (`POLL`; `configure/`
  keeps its 300 s of 503 retries, 60 tries), and `bin/platform-rebuild` tries
  ssh and `/api/auth/` every 2 s instead of 10 s. Every line `bin/cloud` prints
  starts with `HH:MM:SS`, so the next run's log gives each step's time.
- Unverified until a live replace: that a platform-only `up --replace` leaves
  `cr-range` and its slots standing and converges with only `configure/` and
  `ready/`. The first replace after this change still boots a new range host
  once, because the standing one carries the old platform commit in `cr_tag`.

## 2026-11-17 — An apt try is decided by the install; the replace that boots a new range host takes 25 min

The first replace on the Kakao mirror (d761b9f7) failed the platform VM's
first boot: the mirror's `noble-security` `InRelease` (dated 02:02 UTC) listed
`main/dep11/Components-amd64.yml.xz` at 46,360 bytes while the file served was
46,388, so `apt-get update` exited 100 on all ten tries ("Mirror sync in
progress?"), although every `Packages` index downloaded and a simulated
install of the same packages on that VM succeeded. The archive and
`security.ubuntu.com` served the 46,360-byte file. Each try now runs the
install whatever `apt-get update` exits, and the install's exit decides the
try (`platform.yaml` runcmd; `setup.sh`, with `|| :` because it runs under
`set -e`). A failed `Release` download still fails the install on a new VM,
which holds no older lists, so the retry still covers the 404s of the
archive's servers. Rejected: taking `noble-security` from
`security.ubuntu.com`, the server pool whose 404s the mirror was chosen to
avoid; and turning off the DEP-11 index targets, which covers this file only.

Run 1, `uv run bin/cloud up --replace` at 655e331a from the half-built VM of
the interrupted 8bcbc9f9 replace (no store on it, so the newest backup with
rows, `db-20261117T042204Z.sqlite3` from the VM that ran 6ba70c0c, was
restored; 1 user, 608 rule sets and 162 disabled rules came back; its 2
sessions, closed more than 60 min before, were removed by retention at start):

| Step | Time |
|---|---|
| Checks (stack, `git ls-remote`, GHCR, keypair) | 19 s |
| Store probe (nothing to back up) | 2 s |
| Stack delete, create | 11 s, 30 s |
| Server created to ssh | 28 s |
| cloud-init and `cr-platform.service` | 6 min 24 s |
| Hand-over (key, store upload and restore, password, recreate) | 24 s |
| `/api/auth/` answers | 25 s |
| Converge: a new range host (`setup.sh` changed, so stale), 8 slots, `configure/`, `ready/` | 16 min 36 s |
| Total | 25 min 27 s |

The platform VM's first apt try succeeded; both hosts' sources point at
`http://mirror.kakao.com/ubuntu/`. The new range host is 10.31.0.242.

Run 2, `uv run bin/cloud up --replace` at 2f2f4783, a docs-only commit, from
run 1's VM (`CR_RANGE_IMAGE_TAG` 014bc78d on both, bundle unchanged):

| Step | Run 1 (655e331a) | Run 2 (2f2f4783) |
|---|---|---|
| Checks (stack, `git ls-remote`, GHCR, keypair) | 19 s | 19 s |
| Store probe and backup | 2 s (nothing to back up) | 5 s (1,646,592 bytes, integrity_check ok) |
| Floating IP, network, builders | 8 s | 8 s |
| Stack delete, create | 11 s, 30 s | 17 s, 24 s |
| Server created to ssh | 28 s | 32 s |
| cloud-init and `cr-platform.service` | 6 min 24 s | 6 min 29 s |
| Hand-over | 24 s | 23 s |
| `/api/auth/` answers | 25 s | 25 s |
| Converge | 16 min 36 s (new range host) | 1 min 12 s (`configure/`, `ready/`) |
| Total | 25 min 27 s | 10 min 14 s |

Run 2 kept the range host: the same server (`cr-range`, 10.31.0.242, one
Nova ID before and after) and every slot's board, board database, corp, corp
database, Kali, WAF and edge router containers (56 of 88, same IDs and
creation times). `configure/` recreated each slot's log server, sensor,
sensor shipper and WAF shipper (32 of 88): `up` in `deploy/range-host/slot.sh`
recreates the sensor and the logging containers on every run (`compose up
--force-recreate ... sensor $(logging)`), and the collector they forward to is
now the new platform VM's `mgmt` address (10.31.0.144 in run 1, 10.31.0.229
in run 2). A platform-only replace now spends most of its time in the
platform VM's first boot (6.5 min of 10).

## 2026-11-17 — Walk round 25: Kali's hosts file names its real address, the document JSON tab reads one document, a Kibana refusal is Korean, a session opens in about 10 s

**Kali's `/etc/hosts`.** `hostname -i` on Kali printed 172.30.N.10, the
address Docker gave the container on the `internet` network; `slot.sh`
flushes `eth0` and adds the origin addresses, so that address is in neither
`ip addr` nor the map. Docker writes the hosts file once, at create.
`address_kali`, `address_edge` and `spanned` in `deploy/range-host/slot.sh`
now note the Docker address before the flush and rewrite that line of the
container's `HostsPath` in place afterwards (`cat >`, so the bind mount keeps
its inode): Kali names its default source (5.188.10.10), the edge router its
`wan` public IP, and the sensor's sniffing leg loses its line. Checked on
slots 1 to 8 of the live range host: `hostname -i` on Kali is 5.188.10.10, on
the edge router 121.134.88.42 and 10.30.N.1.

**The JSON tab.** Expanding a log and opening the Document flyout's JSON tab
showed "An Error Occurred". The tab runs its own search, `params.index` the
slot pattern, filtered by `{"ids": …}` and `{"term": {"_index":
".ds-logs-1-sensors-…"}}`; the gate refused it because the body names
`_index`. `kibana.refusal` now lets that one clause through when it is a
whole filter clause of its own and its value is the slot pattern or one of its
backing indices; a term on another slot's index, a list, an object or a
wildcard is still refused. Opened as it was, the tab printed the raw
`_source`: the syslog line, `log.syslog.hostname: cr-waf`, filebeat's agent,
the request headers with `X-Request-ID`, all of which the data view hides from
the table and flyout (`HIDDEN_FIELDS`). `kibana.forward` therefore rewrites
that search (`shown_as_the_view_shows`): `_source` excludes the hidden fields
and `fields` asks for the data view's runtime fields alone, so the tab shows
`src_geo`, `@timestamp` and `source_ip`, `url`, `status`, `rule_id`, `rule`,
`request_header.*` and the rest the table shows.

**The refusal page.** Opening another slot's space showed Kibana's own English
error page with the gate's English reason. `/auth-check/` now answers 403 to a
learner for a `/kibana/s/<space>/…` document whose space is not one of their
open sessions' (staff pass), the nginx cache key carries the space, and nginx
turns that 403 and the other `/kibana/` refusals (Default space, `app/`
without a space) into the console page `/kibana-refused/`, written from
`kibana.refused.*` in the string table. The gate answers a call into another
space with the withheld line `kibana.refused.space` as Kibana's `message`.
Nothing that was refused is now let through.

**Opening a session.** POST `/api/sessions/` for scenario 1.1, profiled in the
platform (cProfile around the view), before: 18.8 s, of which `play` 6.6 s,
readiness 4.2 s (Nova server list 2.1 s, ground truth and sensor rules over
ssh), the WAF posture 2.3 s, the Kibana space 1.7 s, customers 1.6 s, the
attacker's origin 1.2 s, the baseline 0.7 s. `play` stopped the other wargame
with `compose stop -t 1`: WordPress and then its database each waited out the
second and were killed (exit 137), 4.5 s on the range host. Both are deleted
with their volumes at the next reset, so `play` now runs `compose kill` (1.7 s
on the range host). The Kibana space is made in a thread beside the range
work. After, three runs: 12.7 s, 10.6 s, 10.7 s (`play` 4.2, 1.7, 2.0 s); in
the browser the 201 came at 9.2 s against 13.2 s before. A lesson (f3): 14.4 s
while another slot was resetting. What remains is the readiness guard (3 to
4 s), the WAF posture (2.2 s: render and an nginx reload over ssh), customers
(1.5 s), the origin (1.1 s) and the baseline read (0.7 s); none has a cause to
cut without changing what is checked. Kibana's first open: 9.8 s in one run
with a cold browser (276 bundles to 3 s, `data_views/fields` 4.5 s), 3.7 s in
another cold run, 1.9 s warm.

`deploy/range-host/slot.sh` is in the slot bundle, so its digest changes and
the next replace boots a new range host.

## 2026-11-17 — Answer-blind walk round 25: a detection scenario counts its detector everywhere on the result page

- **One detection definition per scenario.** 3.3's tamper run read "경보 없음"
  on the timeline and "경보 6822건, 정탐" in the case table. In the store
  (session 2628) that run drew 6822 ModSecurity alerts and no Suricata alert:
  the timeline and the final check counted `completion.detected_by`
  (Suricata), the table counted every detector. `scenario_run.sensed` now
  scopes the detections a scenario with `detected_by` counts, and `/score/`
  (cases, objectives' detected flag, alerted customers), the window judgement
  and the debrief all read through it; `/score/` names the detector in
  `detected_by` and the table says so in one line. Rejected: counting the WAF
  on the timeline, because 3.1-3.4 are graded on the IDS rule the learner
  writes, and a WAF alert would mark a missed rule as caught.
- **A case is one row and one verdict.** The alert count is no longer a column
  that reads like the score; it is a muted "경보 N건" under the verdict.
- **The benign side of a detection scenario is shown.** 3.1, 3.2 and 3.4 grade
  "no alert on a customer request", yet the result listed no customer at all.
  The detection panel now says how many customer requests passed without an
  alert and lists those that drew one (`customers.alerted_requests`, at most
  20); the case table ends with one customer row, 통과 or 오탐.
- **A scenario without objectives shows no objectives card.**
- **One time format.** The timeline showed elapsed time (2:01) and the table
  wall-clock (17:17); both now show wall-clock HH:MM (`at.opened` plus the
  entry's offset), the format of the session header.
- **적용 전·후 shows detection.** `cases[]` carries `alerted_before` and
  `alerted_after`, and each cell shows the alert beside the hash outcome, so
  3.3 reads 경보 없음 → 경보 발생 instead of the same "no hash taken" twice.
- **A lesson result shows the change applied.** The closed lesson session's
  detail carries `change` (`views.applied`, the same diff the scenario
  debrief shows: IDS rule lines and the WAF exclusion removed), rendered under
  the lesson card for a scored course.

## 2026-11-17 — The learner map is drawn as practitioners draw it: what the 2026-11-16 rules left out

The 2026-11-16 entry ("The IDS stands behind the WAF", "The map") records
switches per subnet, addresses beside their device on the side the link
leaves, nothing outside the slot, no legend and no parentheses. The user's
rulings since add the following; the map is read by a learner who has never
seen the range, so a mark that is not a device, a link or an address is
noise, and text too small to read at the console's frame defeats the map.

- **Full IPs, never under the name**: every address is the whole IP (no
  shortened `.N`), and none stands under its device's name or at the switch
  end of its link (`test_live_map.py` holds both).
- **No dashed lines**: every edge is a solid interface link, the mirror and
  management links included; the dashed 미러링 and log edges of 2026-11-15 are
  gone.
- **Korean names**: role names come from the string table
  (`topology.name.*`); Kali, WAF and IDS keep their proper names.
- **Size**: three rows (internet, router and DMZ; 관제망 and web segment; the
  DB zone) so the drawing fills the frame and its text renders at 13 px or
  more in the console's 1040 px pane (13.3 px measured).

## 2026-11-17 — The 관제망 keeps its switch; the router stands free between the zones

Completes "A zone box is its subnet; the IDS stands in the mgmt box". The
관제망 switch stays: `sN_mgmt` is a real bridge, and every bridge is drawn as
a switch (2026-11-15); the IDS's and the WAF's management links and the log
server meet on it. The router has an address in two subnets (its `wan` public
IP and its `lan` on the DMZ), so it belongs to neither box: it stands between
the internet and DMZ boxes with both addresses outside them. This
replaces the 2026-11-16 placement "the router on the boundary".

## 2026-11-17 — Kali lists its default source first

Kali's default route names `src 5.188.10.10` (recorded in "The edge router
holds one public IP of its own"), and `hostname -i` and the map name the same
address, but `ip addr` on Kali listed 73.0.0.10 first, because the kernel
lists an interface's addresses in the order they are added and `kali.ip`
added the origins in declaration order. A learner who reads `ip addr` saw a
different address from the one their traffic leaves from. `rangehost` now
writes the default origin's addresses first (tested in
`test_range_host.py`); the address set and the route are unchanged.

## 2026-11-17 — Both hosts install from mirror.kakao.com

Two Ubuntu archive servers answered 404 for noble's `Release` for over half
an hour and failed three platform VM boots in a row; ten tries 15 s apart did
not outlast it. The platform VM (`platform.yaml`, `apt`
primary and security) and the range host (`setup.sh`) now install from
`http://mirror.kakao.com/ubuntu/`. The same mirror's lag between
`InRelease` and a DEP-11 file then made `apt-get update` exit 100 while every
package index had downloaded, so a try is judged by the install, not by
`apt-get update` ("An apt try is decided by the install"). Rejected: keeping
the default archive with longer retries, since the outage outran the
retries.

## 2026-11-18 — Answer-blind walks: interim rounds re-check only what was fixed; the walk runs per course in parallel

The user's ruling, from round 29 on. A full walk of both courses on one slot
runs every lesson and scenario in series, and a screenshot of a step that
passes carries no finding; an interim round exists to confirm that the last
round's findings are fixed.

- **Interim rounds re-check only the fixed items**: each finding of the last
  round is walked again on the deployed code, not the whole course.
- **One agent per course, each on its own slot**, run side by side; the slots
  are session-isolated, so the walks do not see each other.
- **Screenshots only of findings and result pages**; a passing step is
  recorded in text.
- **The last round before `main` stays a full walk** of every course, so a
  regression outside the fixed items is still caught before gate 2.

## 2026-11-18 — core_loc rises by 7 for the F6 reload check

F6 step 7 passed when nano saved the exclusion file, before `nginx -t` and
the reload, so a file nginx refuses passed too (walk round 28). The check now
asks whether an nginx worker started after the file was last written
(`crs.reloaded_since_written`). It runs a command on the WAF's nginx
processes, and `rules/crs.py` is the only file allowed to know the nginx
reload, so the 7 lines go into core and core_loc goes from 597 to 604.
Rejected: passing on the file alone (the walk's finding); a probe request
through the WAF (it would add traffic to the learner's logs and score); a
worker-PID set remembered in the view (it would put nginx process knowledge
outside `crs.py`); joining lines elsewhere in core to keep the number flat
(that hides the growth instead of recording it).

## 2026-11-18 — The WAF records the request body; the session view shows it as `request_body`

Scenario 3.4 asks for an IDS rule on a URL-encoded comment body, and no log a
learner can read held one: the audit log parts `ABIJDEFHZ` came from
ModSecurity v2, and v3 writes the request body only for part C and has no D,
I or K (ModSecurity Reference Manual v3.x, `SecAuditLogParts`, default
`ABCFHZ`). The WAF now logs `ABCEFHJZ` (`SecRequestBodyAccess On` already),
and the session data view adds one runtime field, `request_body`, the body as
sent (`transaction.request.body`); `transaction.*` stays hidden. 3.4's hint
names the field, not the value.

Rejected: Suricata's `http-body-printable` on alerts, which shows a body only
once a rule already fires; CRS's matched data (`transaction.messages.details.data`),
which is the decoded fragment, not what the IDS inspects; leaving the learner
to reproduce the comment in the developer tools, which shows their own
request, not the attacker's. The audit record now also carries bodies of
other logged requests (4xx-5xx or a CRS match), such as a refused login's
form; the range's accounts are seeded test accounts.

## 2026-11-18 — The Heat range comes up from cloud.yaml: the pool, the role images, the boot contract

Decided while the user was away, to have the range of
`docs/superpowers/specs/2026-11-18-heat-range-design.md` deployable with
`uv run bin/cloud up --replace`.

- **Pool `{board: 3, corp: 1}`** (`compute.pool`). Today's quota is about
  24 vCPU, 56 GB and 17 instances; the platform VM (`m1.large`) takes 2 vCPU
  and 8 GB; a slot is four VMs. Four slots are 16 VMs, with the platform 17
  instances. Board gets three because the lessons and most acceptance modules
  open board sessions; corp keeps one. The number is the cloud's capacity, set
  in `cloud.yaml`, not a property of the design (KYPO pre-allocates pools sized
  by operations).
- **Flavors and images per role.** `compute.flavors.<role>` defaults to
  `dba.small` for kali, waf, infra and target, the WAF included: nothing
  measured says the WAF needs more than the others. `compute.images.<role>`
  defaults to `cr-<role>-bake1`, the images baked from `deploy/roles/`. Both
  reach the platform as `CR_OPENSTACK_FLAVORS` and `CR_OPENSTACK_IMAGES`, the
  pool as `CR_OPENSTACK_POOL` (`board=3 corp=1`), through `platform.yaml`.
- **A `cloud.yaml` written for the range host still parses.** `network.estate`,
  `network.mtu`, `compute.slots` and `compute.flavors.range` are read and
  ignored. `cloud.yaml` is per checkout and not in git; refusing it would stop
  `bin/cloud up --replace` before anything runs, as with `backups.keep`.
- **`bin/cloud up` removes what the range host left before it fills the pool**,
  not after the range is ready: the old `cr-range` VM (6 vCPU, 16 GB) holds the
  quota the slot VMs need. `DELETE /api/range/leftovers/` already lists it (its
  `cr_host` metadata). `down` deletes the slot stacks through the API and waits
  until none stands before it removes the fabric, because each slot VM's control
  port holds `cr-mgmt`; with no platform to ask it deletes the stacks tagged
  `cr-range` with the CLI.
- **Ready and failed are written by cloud-init, not by `slot-boot`.** Each
  node's user data ends with `systemctl start <its role's boot units>`, then
  `touch /var/lib/cr/ready`, or writes the units' status into
  `/var/lib/cr/failed`. The units are kali `slot-boot`, waf `slot-boot` and
  `nginx`, infra `slot-boot` and `sensor`, target `wargames`. `systemctl start`
  of a oneshot returns when it has run and says whether it failed. Why here: the
  images baked now (`bake1`) work as they are, a re-bake needs no change, and one
  place covers the target, whose boot is `wargames.service`, not `slot-boot`.
- **One management user on every node.** The user data creates
  `CR_OPENSTACK_SSH_USER` (default `ubuntu`) with the platform's public key and
  passwordless sudo, after cloud-init's `default` user. On Ubuntu that is the same
  user; on Kali the default user `kali` stays for learner ssh (P6). The key is in
  the template, so a new platform key makes every slot stale and it is replaced.
- **Node addresses are held per stack.** The readiness check already lists the
  Nova servers; once every node of a `CREATE_COMPLETE` stack is ready, their
  `cr-mgmt` addresses and host-key aliases are kept for that stack id. A command
  then asks the cloud nothing (before, every command read networks, servers and
  subnets, about 1.5 s in acceptance). Creating or deleting the slot's stack, or
  a plan that finds the stack not complete, drops them. Kept in the API server's
  memory; `vm-terminal.sh` runs its own process and looks up once per terminal
  open. Rejected: fixed control addresses per slot (the `cr-mgmt` /24 would cap
  the slot count and per-slot address arithmetic would come back); Heat stack
  outputs (another call per plan).
- **The DB zone is the target's Docker network.** The learner map draws what is
  wired, so the database and its network come from the target VM: one
  `docker network inspect` over ssh when the stack is first held, kept with the
  addresses. Only internal networks are drawn (`<wargame>_backend`, rendered
  `internal: true`), as zone `<wargame>-backend` with caption database; the
  `<wargame>_front` bridge and `docker0` carry only the host's port publish, the
  WAF reaches the target's Neutron port. Rejected: the database on its own
  Neutron LAN, which needs a macvlan or another VM for the database container and
  a change to every wargame's compose file, and would still need the container's
  address.
- **Gone with the range host:** `bin/range-image-tag`, `CR_RANGE_IMAGE_TAG`, the
  `range_flavor`, `range_mtu` and `slots` parameters of `platform.yaml`,
  `CR_OPENSTACK_FLAVOR` and `CR_OPENSTACK_SLOTS`. Slot VMs boot from Glance
  images; nothing pulls from GHCR when a slot boots.
- **Isolation, as acceptance checks it now.** From Kali: ping and traceroute to
  121.134.88.42 answer; the WAF's private address is filtered; nothing on
  `cr-mgmt` (every slot VM's control port and the platform's) takes a
  connection; the internet and the metadata address are unreachable; a frame
  from a MAC Neutron did not give Kali's port is dropped (the pair `0.0.0.0/0`
  admits any source address, port security still binds the MAC). After a close,
  the slot's WAF is a new VM (another boot id) without the file the last learner
  wrote. Dropped with the host: the probes of the range host itself and the
  planted links into its log files.

## 2026-11-18 — The baked images as they are: the wargame tag, Suricata in its container, a slot rebuilt in one call

Found while the role images were baked and the docs were made true for the
Heat range.

- **The target image's wargame tag is explicit.** `cr-target-bake1` holds board
  and corp pulled at one `CR_IMAGE_TAG`, and a slot has no egress, so it runs
  only those. `compute.target_tag` in `cloud.yaml` (the full commit; the
  default is the tag `cr-target-bake1` was baked at) reaches the platform as
  `CR_OPENSTACK_TARGET_TAG`. The target's boot refuses to report ready when an
  image line in `/opt/wargames/*/compose.yaml` carries another tag, and writes
  the lines it found into `/var/lib/cr/failed`. A new bake at another tag is a
  new image name and a new `target_tag`; both are in the stack's digest, so
  every slot is replaced. Rejected: pulling at boot (no egress), and following
  the platform's own commit (a platform-only commit would fail every slot).
- **Flavors.** Kali's image has `min_disk` 25 GB; `dba.small` has 30 GB, so
  `dba.small` stays the default for every role.
- **Suricata's commands run in its container.** The infra installs only the
  `suricatasc` wrapper; `suricata -T` (rule validation) exists only in the
  `sensor` container. The topology's `cr-ids` device names `container: sensor`,
  so validate, read, write and reload all run through `docker exec sensor`, as
  in the container range. The infra reports ready only once
  `suricatasc -c uptime` answers (node `answers:` in `topology.yaml`, up to
  300 s), because configure loads the baseline rules through that socket next.
- **A slot the ensure deletes is created again by the refill.** `ensure_slot`
  returns the deleted stack in `rebuilt`, which starts the refill thread that
  creates it and configures it; before, a stale or failed slot stayed
  `NOT_STANDING` until another call. The pool's assignment now wins over the
  stack's tag, so a changed `compute.pool` retargets a free slot.
- **An open session holds its own slot only.** `POST /api/range/slot/` treated
  every slot as held while any session was open, a rule from the one range host.
- **The platform keeps its `cr-mgmt` address across `--replace`.** The fabric
  attaches the detached `cr-platform.mgmt` port to the new platform VM instead
  of making another; every slot's user data names that address as its
  collector and NTP server, so a new address would have made every slot stale.
- **A missing role image blocks the slot before Heat is asked.** A slot with
  no stack is `NOT_STANDING` with the reason "no active image ... in Glance".

## 2026-11-18 — The first live pool fill: shared LAN security groups, the WAF re-baked on a 30 GB builder, digest-pinned images pass the tag check

Found on the first `POST /api/range/slot/` against this cloud, which created
the four stacks of the pool `{board: 3, corp: 1}` at once. Decided while the
user was away.

- **The slots share one security group per LAN rule set.** Every stack failed
  with `OverQuotaClient: Quota exceeded for resources: ['security_group']`.
  The project's `security_groups` quota is 10 (`openstack quota show`);
  `default`, `cr-platform`, `cr-reach`, `cr-mgmt`, `cr-senders` and
  `cr-egress` hold 6, and five groups per stack put a pool of four at 26. Every
  slot uses the same addresses, so every slot has the same rules, and two
  pairs of LANs are equal: `internet` and `dmz` admit everything (Kali's and
  the router's ports carry the pair `0.0.0.0/0`), both web legs admit
  10.30.128.0/24. The adapter now makes each distinct rule set once as
  `cr-lan-<first 12 hex of the rules' SHA-256>`, under a lock, before it
  creates a stack, and hands the ids to the stack as `group_<lan>`; board and
  corp take the same three, so the range holds 9 of 10 for any pool size. The
  rules are unchanged, and they name CIDRs, not groups, so a shared group
  opens nothing between slots. `fabric.teardown` deletes the `cr-lan-` groups
  after the slots. Rejected: merging the equal groups within each stack (still
  3 per stack, 12 + 6 > 10); port security off on the slot LANs (loses the
  anti-spoofing on the WAF's ports, where the learner has root); asking for a
  quota raise (admin only, and the user was away).
- **The WAF image is re-baked on a builder with a 30 GB disk.** Heat refused
  every stack with `StackValidationFailed: Image cr-waf-bake1 requires 40 GB
  minimum disk space. Flavor dba.small has only 30 GB.` A Nova snapshot takes
  the builder's root disk as its virtual size and `min_disk`, and
  `cr-waf-bake1` was baked on a 40 GB builder. `cr-waf-bake2` was baked
  unchanged from `deploy/roles/waf/` on an `m1.medium` builder (2 vCPU, 4 GB,
  30 GB) on `cr-platform`, reached over ssh through the platform VM with no
  floating IP: `install.sh` took 12 min 53 s (ModSecurity built from source),
  the snapshot 2 min 30 s, and the image has virtual size 30 GB and `min_disk`
  30 GB. This cloud's `cloud.yaml` names `compute.images.waf: cr-waf-bake2`;
  `cloud.example.yaml` and the code default stay `cr-<role>-bake1`, and
  `cr-waf-bake1` stays in Glance, unused. The rule: bake on a flavor whose
  disk is no larger than the slot flavor's. The Kali image's `min_disk` is
  30 GB, not 25 GB as recorded above; infra and target are 30 GB too.
  Rejected: a 40 GB flavor for the WAF (`dba.medium`, 4 vCPU: the pool of four
  would need 30 vCPU against the quota of 24).
- **Digest-pinned images pass the target's tag check.** The baked compose files
  pin MySQL by digest (`mysql@sha256:...`), which has no tag, so every target
  wrote `/var/lib/cr/failed` and all four slots stood `SETUP_FAILED`. `booted`
  in `platform/range/sandbox.py` now also passes an `image:` line ending in
  `@sha256:<hex>`; a line with another tag still fails.
- **A refused OpenStack call names the service's own message.** The 503 of
  `POST /api/range/slot/` carried the first 200 characters of the body, which
  for Heat's `StackValidationFailed` cut the reason off. It now gives the
  `message` Heat (`error`), Nova (`badRequest`) and Neutron (`NeutronError`)
  wrap their reason in, and the first 200 characters only when the body has
  none.
- **Measured on this fill.** With no image cached on com01, the 14 GB Kali
  image was copied there first; the other VMs were `ACTIVE` after about 4 to
  5 min and the stacks reached `CREATE_COMPLETE` after about 12 to 13 min. The
  infra wrote ready about 3 min after its boot, the target about 2.5 min
  (cloud-init finished at 151 s).
- **A slot's readiness reads its own wargame's ground truth.** Readiness read
  board's loot on every slot, a rule from the range host where every slot ran
  both targets. A Heat slot runs only its wargame, so the corp slot stood
  `CHECKING` ("the target's ground truth could not be read"), and every corp
  session open in the acceptance suite retargeted a free board slot to corp
  (409 "no slot runs corp, so slot 2 is being built again for it"), which the
  suite took for a failure. Readiness now reads the slot's wargame through the
  baseline a session open reads (board's loot, corp-db's state), and the
  acceptance suite waits on that 409 as on a reset. Rejected: skipping the
  check on corp slots (a corp slot whose database is down would read READY).
- **Measured on the second fill**, with every image cached on com01: the four
  stacks reached `CREATE_COMPLETE` in under 2 min, and three slots were
  `READY` 8 min 50 s after the stack create (sixteen VMs booting at once; a
  target's cloud-init still running at 4 min). A session open took 8.2 s. A
  closed session's stack is deleted and created again; how long until that
  slot is `READY` again is **[unverified]**. A target VM showed 0.8-0.9 GB of
  its 2 GB in use with board or corp running (1.1 GB available).
- **The platform's `up` and a verify run do not overlap.** A full `bin/verify`
  restarts the platform; started while `bin/cloud up` still polled
  `GET /api/range/ready/`, it cut that poll off (`RemoteDisconnected`) and
  `up` exited 1 with the pool standing. Start the verify after `up` returns.

## 2026-11-18 — A slot is retargeted or opened on only while no session holds it and no reset runs on it

Both full verify runs of the day failed `test_concurrent_sessions.py` with a
503 on the second session's `PUT .../waf/` (run 2: "cr-waf stands on no mgmt
address this platform can reach"; run 1: the SSH control master to cr-waf
broke). Run 2's record: session 2788 opened on slot 3 at 23:06:22Z; a corp
session open answered 409 at 23:06:24Z; slot 3's board stack (created
22:49:42Z) was gone by 23:06:38Z and a corp stack was created on slot 3 at
23:06:44Z. The corp open read the readiness before session 2788 existed, saw
slot 3 `READY` and free, and its retarget deleted the stack session 2788 then
held. The readiness read is slow and runs outside the slot-choice lock, so
neither the retarget nor a session open may trust it alone: the retarget now
claims the slot under that lock and only when no open session holds it, and a
session open under the same lock refuses a slot whose reset is running.
Rejected: holding the lock across the readiness read (every open would wait
on the cloud and on SSH for every slot).

## 2026-11-18 — A slot node's control port starts nothing but DHCP and traffic to the platform

Run 2 of the full verify on the Heat range: Kali, the WAF and board reached
169.254.169.254:80. Read live: each slot VM routes it `via 10.31.0.1 dev ens3
proto dhcp`, and 10.31.0.1 is the `network:distributed` port on `cr-mgmt`, the
OVN metadata port; `cr-mgmt` and `cr-senders` held only Neutron's default
egress (IPv4 and IPv6, anywhere). The slot VMs boot from config drive, so
nothing in a slot needs the metadata service. `range/fabric.py` now wants two
egress rules on each of those groups, IPv4 to the `cr-reach` group (NTP, and
syslog from the infra) and udp 67 (DHCP on the control port), and the fabric
bring-up deletes every other egress rule on them, on new groups and on the
groups already standing (`Plan.confine`, so `POST /api/range/fabric/` fixes
the live cloud at the next `bin/cloud up`). Board's container leaves through
the target VM's control port, so the same rule closes it. Rejected: a route
or firewall rule in each role image (a re-bake, and a learner with root on
Kali removes it); disabling DHCP on `cr-mgmt` (the platform VM's port is on
it too). That OVN applies the port's egress rules to traffic for its metadata
port is the Neutron security-group model, **[unverified]** on this cloud until
the next bring-up and `test_range_isolation.py`.

## 2026-11-18 — Documents call the range unit the session's stack, not a slot

The user's ruling: a slot is in effect the session, so the documents people
read say so. `README.md` and `docs/ARCHITECTURE.md` describe the range as one
Heat stack per session, kept ready in a pool, given to a session when it opens
and deleted and built again when it closes; the English documents
(`docs/OPENSTACK.md`, `docs/THREAT-MODEL.md`, `docs/TROUBLESHOOTING.md`,
`CLAUDE.md`, the `orchestrate` skill) say "the session's stack", "range stack"
and "range VM" where they meant the concept. Code identifiers keep the word
(`cr-slot-<n>`, `Session.slot`, `/api/range/slot/`, `?slot=N`,
`compute.pool`, `/etc/slot.env`, `slot-boot`); a document that names one quotes
it as code. `docs/ARCHITECTURE.md`'s glossary says once what the number in
those names is: the reused stack number that fixes the stack's name and
Neutron tag `cr.slot=N`, its Kibana space `soc-logs-N` and its log index
`logs-N-*`, which a session borrows for its lifetime. Earlier entries in this
file keep the word they were written with. Rejected: renaming the code
identifiers (a migration, an API change and new stack names for wording only).

## 2026-11-18 — An IDS alert is credited to its X-Forwarded-For client when its http record arrives after it

The third full verify on the Heat range failed `test_map.py`'s check that
every IDS alert behind the WAF is credited to the client X-Forwarded-For
names: Suricata alert `t6u77KEBttGyDep4igCN` (flow 378853086090056, tx 0,
03:37:37.767Z, `logs-3-sensors`) was stored with the WAF's 10.30.128.247,
while its transaction's http record carries `xff` 5.188.10.10. Both are in
Elasticsearch with the same `@timestamp`, but the alert's generated id is one
step before the http record's and the ModSecurity record's (the two
transactions either side have the alert and its http record under one id
step), so they were indexed apart; an ingest that read the index between the
two refreshes stored the alert uncredited **[unverified]**: the platform does
not log its ingest calls. Ingest skipped every detection it already held, so
the credit was never made. `_ingest` now moves a held detection's `src_ip` and
`src_host` to the client a later fetch credits from the transaction's http
record, only when the credited address differs from both the stored one and
the alert's own `src_ip`, so an alert seen again without its http record keeps
the client. Rejected: reading `alert.xff` in `ingest/elastic.py` (Suricata
raises a URI alert before it reads the headers, so it is not always there,
and `core_loc` is at its ceiling); waiting before the first ingest of an
alert (every score read would wait).

The same run confirms the control-port egress entry above: Kali, the WAF and
board each time out on 169.254.169.254:80 (`bash -c 'exec
3<>/dev/tcp/169.254.169.254/80'`, exit 124, on `cr-slot-3`) and
`test_range_isolation.py` passed; `cr-mgmt` and `cr-senders` hold only the
two egress rules (IPv4 to `cr-reach`, udp 67).

## 2026-11-18 — The platform store runs in WAL mode with `synchronous=NORMAL`

The final full verify on the Heat range lost its red team fixture to a 30 s
sign-in timeout at about 04:35:20Z while SQLite refused the store: the
scenario tick's `SELECT` on `api_session` failed with `database is locked` at
04:35:22Z and two `/api/range/ready/` reads of `django_session` at 04:35:45Z.
Those were reads. Under the rollback journal (`journal_mode` was `delete`) and
`transaction_mode: IMMEDIATE`, a transaction held open only holds RESERVED,
which readers pass; readers wait only while a writer holds PENDING or
EXCLUSIVE, that is while it writes its pages into the file and syncs them. So
no transaction held across a slow call (every `transaction.atomic` and
`select_for_update` in `api/` was read for one; none spans an ssh, Heat or
Elasticsearch call) explains it: a writer was in its commit for 30 s and more.
The disk was stalling then: `sar` on the platform VM for 04:30-04:40 has the
day's worst interval on `vda` (await 559 ms, queue 15.6, iowait 40 % at 27
tps), Elasticsearch's data-path health check took 7609 ms at 04:36:03Z, and
Kibana's requests to Elasticsearch timed out from 04:35:04Z to 04:36:32Z;
earlier the same day Elasticsearch logged cluster-state writes of up to 29 s.
Which request was the committing writer is **[unverified]**: the platform logs
no access and no lock holder. The two resets running then build eight VMs on
the cloud and are the likely load **[unverified]**.

SQLite's documentation: in WAL mode "readers do not block writers and a writer
does not block readers", and with `synchronous` NORMAL "the checkpoint is the
only operation to issue an I/O barrier or sync operation"
(https://www.sqlite.org/wal.html); "WAL mode is always consistent with
synchronous=NORMAL, but WAL mode does lose durability"
(https://www.sqlite.org/pragma.html#pragma_synchronous). The store's
`OPTIONS` now carry `init_command: PRAGMA journal_mode=WAL; PRAGMA
synchronous=NORMAL` (Django 5.1+). A commit no longer syncs, and a writer
waiting on the disk no longer locks readers out. The cost: a power loss or
crash of the platform VM may roll back its last transactions; the file stays
consistent. WAL needs every process on one host, which the store has (one
volume on the platform VM). The two restores that copy a backup over the
store (`bin/platform-rebuild`, the README's) now delete `-wal` and `-shm` with
`-journal`, because a WAL file left beside a replaced store is replayed into
it. `bin/backup` takes its snapshot with `VACUUM INTO`, which reads the WAL.
Rejected: raising the busy timeout (the client's 30 s sign-in timeout would
still lapse); logging the lock holder first (the cause is visible without it,
and a reader cannot be blocked by a writer in WAL mode whichever writer it is).


## 2026-11-18 — The home page drops the Kali trademark line; debrief labels lose their prefixes

- **The trademark footer goes, by the user's ruling.** The user asked for "KALI LINUX™는 OffSec의 상표입니다." to be removed from the console. The footer in `main.html`, the `topology.trademark` string and the test that pinned the footer are gone. The dragon's source record stays in `symbols/host-kali.txt`. This sets aside the 2026-10-15 entry's reading of OffSec's policy ("When using an OffSec trademark in written materials, you should include ... a trademark of OffSec") for the console page; the map still uses the unmodified press-pack logo.
- **Debrief labels say the thing, not a frame around it.** "내 정·오탐 판단" is "정·오탐 판단"; "근거: 이 세션에서 실행된 공격의 로그" is "공격 로그"; the five `lesson.fix.*` lines drop "적용한 조치:" and say what was changed. The user called the old wording slop.


## 2026-11-18 — Triage groups on a stored rule column, the console never re-asks a read still out, ingest commits in batches of 500, and readiness is answered from a kept verdict

Scenario 1.3 (session 2851) stalled the platform from 06:49 to 07:04Z: waitress
"Task queue depth is" rose from 13 at 06:49 to 83 at 07:02-07:04, the
connection limit was reached from 07:02:40Z, scheduled attacks 6 and 7 failed
at 06:50:33Z with `database is locked` on `_fire`'s `Session...update(ended_at=...)`
after the 30 s busy timeout, and at 06:59:30Z a plain read (`GET
/api/sessions/`, `session.cases.aggregate`) and the engine's ingest
(`bulk_create`) failed the same way. The deployed store was still
`journal_mode=delete` (WAL is on `dev` only). Measured afterwards, read-only
on the live store (2 vCPU, 98,995 alerts in session 2851, 2.5 KB of raw JSON
each, 217,557 in all, 961 MB): triage's `GROUP BY marker, source, signature,
ruleId, signature_id` took 3.43 s on the idle VM, the same grouping without the
two JSON paths 0.65 s, its other two reads 0.39 s and 0.36 s. Every open blue
console asked `GET triage/` every 15 s and `GET scenario/` every 5 s whether or
not its earlier read had come back, so once a read took longer than its poll,
requests arrived faster than 16 threads on two cores could answer them. Under
the rollback journal a writer's commit waits for every reader to finish and
locks new readers out meanwhile, so multi-second triage reads stretched each
commit, and a 13,000-alert-a-minute ingest held the write lock for its whole
`bulk_create` while other writers queued **[the writer holding the lock at
06:50:03-06:50:33Z is inferred, not logged]**. No `transaction.atomic` or
`select_for_update` spans an ssh, Heat or Elasticsearch call (each was read
again); the waits were on the lock, not inside it.

- `Detection.rule` is a stored `GeneratedField`: `Coalesce` of
  `raw.details.ruleId` and `raw.alert.signature_id`, computed by SQLite at
  insert. Triage groups on it and parses no JSON per poll. Migration 0033
  rebuilds `api_detection` once (Django remakes the table for a stored
  generated column on SQLite); 217,557 such rows took 2.3 s on a laptop SSD,
  the platform VM's time **[unverified]**.
- The blue console's scenario and triage polls skip a turn while their last
  read is still out.
- `_ingest` stores new alerts in `bulk_create` calls of `INGEST_BATCH` (500)
  rows, each its own transaction, so no insert holds the write lock for more
  than one batch.
- `GET /api/range/ready/` answers from a kept verdict while the sessions'
  slots and the slots' reset states are unchanged; a verdict older than
  `READY_FRESH` (15 s) is still answered while one background thread reads
  again; a change of those inputs (an open, a close, a reset) reads again in
  that request, one at a time. A read that raised is kept too and answered as
  that error (503 for `RangeUnavailable`), never as the last ready verdict.
  It took 13-26 s a call, each holding a request thread. The session open
  still reads readiness itself: it must not hand out a slot on a verdict up
  to 15 s old.

Rejected: more waitress threads (two cores; more threads run more of the same
reads at once); a covering index on `api_detection` (the JSON parse was the
cost: 3.43 s against 0.65 s); a plain `rule` column filled by ingest (old rows
would need the same backfill and `ingest/elastic.py` a new field). Open: a
session open still takes 21-52 s (readiness, the attacker's aim, the
baseline, the defence and the Kibana space). The lesson console's step poll
already skips while a check is out; the session page's 10 s activity poll does
not, and is left as it is.


## 2026-11-18 — The first Heat walk's findings: what a count counts, the final check apart, Start per wargame

The answer-blind walk of the Heat range (lessons c1, c2; scenarios 3.1-3.4,
1.1, 1.2) reported the following; each is fixed at its cause.

- **A result row counts alert records, not matched rules.** One XSS request
  with one WAF record read 경보 5건 (five CRS rules on the record) and a
  sqlmap run of 2,065 records read 8,581. The lessons teach the learner to
  count Kibana records, so `per_case[].alerts` is the number of distinct log
  records among the case's detections (a WAF detection id is the record id
  and its message position), shown as 경보 기록 N건; `detections` keeps the
  rule-match count for the API. The customer row's number is alerted
  requests and says so (경보가 난 요청 N건).
- **The final check is reported apart from what came before it.** 3.1, 3.3
  and 3.4 are built so the first run is missed before the learner's change;
  the result page read 공격 2건 중 1건 정탐 with that miss in red. The score
  gives `per_case[].in_window` (the case's schedule entry falls in a judged
  final check, the debrief's own rule), `final_checks` and
  `customers.final_check`; the page writes the final check and the time
  before it as two sentences and greys a miss or a customer alert before the
  check. TP/FP/FN/TN are unchanged: the early miss is still FN.
- **Benign rows on every scenario, and the debrief counts alerts too.** 3.2's
  debrief said 0건 차단 while its result page listed 42 customer requests the
  IDS alerted on (all while the learner was writing the rule, none in the
  final check); 1.1 and 1.2 showed no customer row though the WAF blocked
  customer requests. The debrief now counts the customer requests that drew
  an alert, per final check, with a customer row in its before-and-after
  table, and every scenario's result table carries the customer rows.
- **Start says why at once and follows the pressed wargame's stack.** The
  readiness verdict names any free ready stack; with a corp stack ready, a
  board open refused for a reset said only 시작을 다시 누르세요 and the reset
  notice came about 90 s later, after the 13-26 s readiness reads. A 409 for
  a stack being reset or rebuilt carries `settling: true`, and the home page
  enables each Start from the verdict's `slots` for its own wargame.
- **3.3's second attacker has its own address.** The brief and card name a
  second attacker; both runs wore `ru` (5.188.10.10). The tamper run now
  comes from `us`.
- **The map stays the defended network.** Every slot VM has a control port on
  `cr-mgmt` (10.31.0.0/24) that `hostname -I` lists first. It is the
  platform's network, not the company's, so the map does not draw it (the
  2026-10-14 ruling: only the defended network); the lesson reference says
  that Kali's and the WAF's shells show one address the map leaves out and
  what it is. Neutron confirms the IDS has no 관제망 port: its two legs bridge
  the WAF to the web segment, and its logs reach the log server on the same
  VM, which is what F1's step 5 now says.
- Also: F3's first step asks for a word not yet searched in this session;
  the strip hides 탈취된 목표 where nothing is at stake (3.2, 3.4); 1.3's alert
  list header asks for the attack type; two particle typos.

## 2026-11-18 — The Kali image masks sslh's generator and wants cloud-init.target itself

Two of four Kali VMs from `cr-kali-bake1` booted with no cloud-init unit and
stayed SETTING_UP; a rebuild of the same server booted fine. The stuck
boot's console shows `systemd-sslh-generator` "terminated by signal ABRT"
while the generators ran, and systemd stops waiting for the other parallel
generators when one dies by a signal, SIGTERMing those still running, so
`cloud-init-generator` never linked `cloud-init.target` into
`multi-user.target` (`docs/TROUBLESHOOTING.md` "A Kali VM booted without
cloud-init" has the console lines and the systemd source). sslh comes with
`kali-linux-headless` and the range never runs it. `install.sh` now links
`/etc/systemd/system-generators/systemd-sslh-generator` to `/dev/null` and
`cloud-init.target` into `/etc/systemd/system/multi-user.target.wants/`;
the second link keeps cloud-init on even when some other generator dies,
at the cost of bypassing `ds-identify`'s "no datasource, disable" verdict,
which a VM that boots only on Nova with a config drive does not need.
Rejected: purging `sslh` (`kali-linux-headless` depends on it, so the
metapackage would go with it); a boot unit that runs
`cloud-init` by hand (a second way to start it, beside systemd's); a retry
on the platform side (the reset already waits 1800 s; a rebuild costs a
stack). Needs a re-bake as `cr-kali-bake2` and `compute.images.kali` naming
it; the image name is in the stack digest, so every stack is replaced.

## 2026-11-18 — The second Heat walk's findings

An answer-blind walk of courses c1 and c2 on the live Heat range
(screenshots in `~/.cache/fsl-work/walk-heat2/c/`).

- **세션 종료 on every lesson screen.** The note's close section hid once a
  lesson finished, so the end card of F1, F2, F4 and F5 had none and the
  learner went home to close. It now stays on the end card; only the course
  summary, which has its own close button, hides it.
- **The coach rings at most the tool or tab, never the answer.** The
  earlier ruling (DevTools rings the tab, not the line) now holds for every
  locator. DevTools: while a request row has to be picked, the ring sits on
  the Network panel tab, not on the row (F2 step 6's `?sort=title`, F5 step
  2's 500). Kibana: `doc` rings the flyout's field filter, not the value;
  `hits` rings nothing once the query is new (the count and "no results"
  are the answer; a panel over the count still rings its close button);
  `sidebar` rings the field in the list, not Top values or the record-count
  line (this reverses F12). Terminal: lessons ring only the prompt; F5's
  verdict and F6's account table open the pane only, F6's exception step
  rings the WAF prompt. F6's cost step rings the objectives card, not the
  admin row. The map's node rings stay: the address label lies outside the
  ring. Rejected: ringing the whole request list (it holds the row and its
  status). Eight tests that asserted the old rings were removed or
  rewritten; `test_no_lesson_step_rings_a_line_of_terminal_output_...`
  guards the lesson file.
- **No "label: value" strings.** `CRS 설정: <path>`, the reference's
  `nano: Ctrl+K` rows, the replay lines (`공격 요청 차단: 대기 중`), the
  report's `<case>: 경보 없음` / `경보 기록 N건`, `차단된 고객 요청: …`,
  `검증 완료: …`, `시나리오 1.1: …`, `출발지: …`, `탐지 근거 부족: …`,
  `남은 시간: …`, `고객 동작별 차단: …` and `다음 레슨: <제목>` are
  sentences, a heading or a table column now. The next lesson is named in
  the end line (`lesson.next.named`); its button says 다음 레슨 시작, so it
  no longer overflows the note by the title's length. `test_strings.py`
  refuses a value opening with a short Korean label and a colon. The
  DevTools imitation keeps Chrome's own wording (`적용 범위: N/A`).
- **The reset notice shows once.** A refused open says 초기화하는 중 beside the
  pressed Start; the home page's banner hides while its reasons are all
  told there.
- **The learner VMs carry their role as hostname.** The WAF prompt read
  `root@cr-slot-1-waf` (cloud-init took Nova's server name) while Kali's
  read `kali`. Each node's cloud-config sets `hostname` to its role
  (`kali`, `waf`, `infra`, `target`); the Nova names and every lookup by
  tag or metadata are unchanged; syslog sender names are fixed in the log
  server's template, not taken from the hostname. The user data is in the
  stack digest, so every stack is replaced once.
- **A lesson's minutes add up to the session's.** The first lesson's
  `started_at` was stamped before the slot was chosen (23 s on the walk), so
  c1's lessons summed to 6 min against 5. It is now the session's
  `started_at`.
- **The close-time ingest leaves out Filebeat's raw line.** Closing c2 took
  14.1 s (c1 6.0 s). The ingest before `close/` reads the whole session
  again: re-run read-only on session 2852, 10,818 documents, 9.24 s to
  fetch, of about 80 MB 38 MB was the top-level `message` field, which no
  detection reads; `close/` itself about 3.5 s. `elastic.fetch` now asks
  for `_source` without `message` (`core_loc` 601 -> 602). Expected about
  4 s less on c2 **[unverified]**. Rejected for now: an incremental
  close-time read (the re-read is what credits late markers and
  X-Forwarded-For to stored alerts).
- **The 8-minute refusal was not the reset.** The c2 close's new stack and
  the board slot retargeted for the next open both got Kalis that booted
  without cloud-init (sslh's generator, "The Kali image masks sslh's
  generator" above), so no board slot was READY until another session's
  slot was rebuilt. A healthy reset measured on slot 2: delete 28 s, Heat
  create 43 s, boot to the readiness file 114 s, platform poll and
  baseline at most 80 s, 3-4.4 min in all. No platform change: the fix is
  the `cr-kali-bake2` bake.

## 2026-11-18 — The second Heat walk's scenario findings (1.1 to 2.1)

An answer-blind walk of scenarios 1.1 to 2.1 on the Heat range.

- **Start waits for readiness and says why it is off.** The home page enabled
  시작 for 0.5-2.5 s after load, before `GET /api/range/ready/` answered; the
  buttons now render disabled until it does. With every board stack held and
  only corp READY, each board 시작 was greyed with no reason; the card now
  says why (`main.wargame_busy`, `range.resetting` or `range.blocked`).
- **An open with nothing ready is refused at once.** Clicking 시작 with no
  free READY stack spun 30-45 s, then said 초기화하는 중: the open re-checked
  every stack in turn (plan, ground truth and rules baseline over SSH) only
  to refuse. When the kept readiness verdict (its inputs, the holders and
  reset states, unchanged) has no READY free slot, the open is refused with
  409 straight away, `settling` when a slot is resetting. A READY slot of
  another wargame still goes the retarget path.
- **세션 종료 on the briefing.** The briefing covers the console, so the
  session could not be ended before 시작. It has its own 세션 종료, which
  shows the console's close confirm; keeping the session reopens the
  briefing, and the clock does not start.
- **The judged count names its items.** The console counted every item
  (1.1: 31개 중 30개) while the result counted the items listed when the
  final check started (24/24), which is what the completion grades. Once a
  final check has started, `GET triage/`, `right_so_far` and the result all
  count those listed items; the console says 최종 점검 시작 전 항목 and the
  result line says 최종 점검 시작 전에 경보가 난 항목. Before a check, both
  count every item.
- **The list keeps refreshing with a question open.** The 15 s poll skipped
  while an attack's follow-up (type, 탈취) was open, so the list sat at 35
  items for about 2.5 min while the API had 43. It now always refreshes and
  restores the open question, the chosen type and the scroll position.
- **One alert count, records.** The triage card summed rule matches (search
  SQLi 경보 6건; sqlmap 20,050) while the result counts log records (경보
  기록 2건; 2,065). The card now counts records the same way (a WAF record id
  before its `:position`) and says 경보 기록 N건.
- **The level shows its value.** A WAF file with no paranoia line runs at
  CRS's default 1; the result read Paranoia Level 3 → —. `change.before` and
  `.after` now carry `lesson.CRS_DEFAULT_LEVEL` when the line is absent.
- **Label slop.** 고객 동작별 차단:, `<case>: 경보 없음`, 출발지:, CRS 설정: were
  the deployed build, which predated the previous batch; dev already writes
  them as sentences and `test_strings.py` already refuses the form. A test
  now pins that the regex catches these four walk lines.
- **The final check's 81 s wait.** From code: `ready_to_judge` waits until
  every attack inside the window has settled, and `window_attacks` placed
  the missing cases at even gaps with the first one gap in, so 1.1's sqlmap
  started 90 s into a 3-minute check; the dump runs about 166 s
  (`redteam/cases/board.yaml`), so judging waited about 76 s past the end
  plus the tick and the 1 s console poll: the 81 s seen. Tool-run cases now
  go first and the first starts with the window. Not verified live: a
  sqlmap slower than the window (1.2's run drew 20,050 alerts) still
  delays the judgement. The triage click (3.5-5.2 s) built every item
  (grouped rules, first-request JSON fields over up to 20,000 detections;
  the probe's `GET triage/` took 1-3.3 s during sqlmap) just to check the
  item id; it now reads only the alerted markers **[unverified live]**.

## 2026-11-19 — Rebuild as a side split: attack, defence, referee around a round

The mentor review of 2026-11-18 found most lessons and scenarios to be slop. The user ruled:
scenarios are removed; the path is guided lessons then live rounds; rounds are PvP on one stack,
a human defender against an attack bot, or a human attacker against a defence bot; attack and
defence each have one API that a human console and a bot use alike, bots model-agnostic and first
driven by Claude Code; source IPs carry hit points so pointless scans spend themselves, and the
bot is told the rule; a WAF/IDS rule is tested where it is written, with syntax errors and per-case
TP/FN/FP/TN at once, before it is applied; problems live in the database and are edited on a staff
page. Time and dependency counts are not criteria; the ratchet is removed. The code is rebuilt for
maintainability rather than migrated: the current code is reference, and only its good modules
(isolation seams, scoring core, range adapter, cases) are carried over.

Seven whole-repo structures were proposed, each checked by a skeptic against the repo and scored
by four judges (maintainability, product fit, operational risk, project invariants). The user chose
the side split and asked for the others' strengths to be fused in. The fused design, with each
graft and its source option, is `docs/superpowers/specs/2026-11-19-side-split-design.md`.

## 2026-11-20 — What the side-split build decided beside the spec

These came up while building `side-split` against the design; the design
spec is updated where it named the old placement.

- **Jump grants live in `range/jump.py`, not under `attack/`.** The defence
  terminal needs the same grant as the attack terminal: an SSH key on the
  platform sshd that forwards only to one box, plus the seat's key in that
  box account's `authorized_keys` (kali for the attack seat, `analyst` on
  cr-waf's management address for the defence seat). `attack` and `defence`
  may not import each other (import rule 3), so the grant module sits in L1
  under `range/`, takes the address, runner and account from its caller, and
  imports no Django and no app. `attack/box.py` no longer edits
  `authorized_keys`; a seam pattern (`authorized_keys`, `cr-session-`) keeps
  `range/jump.py` its only owner beside `entrypoint.sh`, which creates the
  jump host's empty file. `match.service.end_round` revokes both sides'
  grants under `guarded`: a box that cannot be reached raises
  `RangeUnavailable`, a domain error, so it never stops the settling or the
  `round.ended` event. If the box refuses the seat key, the platform grant
  stays until the round ends; without the box key it opens nothing.
- **A fired case and a sent request answer with their own marker.**
  `POST attack/requests/` and `POST attack/cases/` return the marker the
  platform set as `X-Request-ID`, so a seat (a bot, the acceptance suite) can
  tie the alerts its action drew to it from `GET defence/alerts/`
  (`request_id`) without reading the event log. The marker carries no
  verdict; free actions still never enter TP/FP/FN/TN.
- **Defence writes are phase-checked in the permission class.**
  `match.auth.SidePermission` refuses every non-GET on either side with
  `round_not_started` before `running` and `round_closed` after the end;
  the terminal route is a GET and checks the phase itself.
- **A lease expires without a heartbeat.** After `CR_LEASE_IDLE_MINUTES`
  (default 30) with no heartbeat from the operator or a seat, the follower
  closes the lease with `lease_expired`; the acceptance suite's shared leases
  send one every minute. An ended round's seat token keeps no lease alive.
- **A RuleSet records the seat that applied it**, so the start posture the
  platform applies at round start is not taken for the learner's apply by
  the `rule_applied` check.
- **Three live acceptance modules are dropped, not ported.**
  `test/test_lesson.py` walked the lessons F1-F6 and courses c1 and c2,
  which are deleted with no replacement content; lesson rounds are covered by
  `platform/tests/lessons/` until staff author problems. `test/test_ready.py`
  read the canary of the old readiness route (`/api/range/ready/`), which the
  new API does not serve; a round's sensors check `local.rules` before the
  acceptance suite instead. `test/test_map.py` checked the attacker world-map
  points of the old session map route, which is gone; the learner map stays
  covered by `test/test_topology.py`, and the geoip pipeline behind the
  origins by `test/test_geoip_durable.py`. A check
  comes back with its route if one is built.
- **`docs/ARCHITECTURE.md` and `docs/STATE.md` are written anew** for the new
  layout rather than edited: the old texts described `platform/api/`, the
  console templates and the scenario engine on almost every line. The old
  texts stay in git. `docs/DECISIONS.md` keeps its Korean quotes of the
  user's rulings for now; `test_no_hangul.py` allows it by name until they
  are translated.
- **Grafts from the other restructure options**, as the spec's Appendix B
  records them (the base is `by-side`):
  - hexagonal: the pure `domain/` core; the AST import test; the nftables
    `spent` set at the infra edge; HP from two sources deduplicated by
    marker; async tool runs; terminal access per seat; per-engine defence
    resources; one error shape; a pure problem validator and a learner read
    API without answers; progress by user and problem; panes shared by
    lessons and rounds; the layered test split; folding `register_pipeline`,
    `operator_log` and the tool image into their owners; explicit end
    conditions; the geoip tools kept.
  - django-apps: `corroborated` and the tally below the apps; the scratch
    CRS instance with a stub upstream and the IDS read from a scratch
    `eve.json`; non-destructive syntax checks; the HP block on every attack
    response; a lessons app with a check registry; the content snapshot at
    round start; seat-scoped tokens; `search_after` cursor ingest; one
    exception handler; explicit deletions and backup re-pointing;
    `browse_marker` and `CustomerRequest` kept.
  - django-drf: lease apart from round with the baseline per round;
    seat-token permission classes; per-side schemas and a completeness test;
    the stale-apply 409; Posture rows; the lesson rule check reusing the
    rule-test verdict; APIClient-only tests with English placeholders; no
    Django admin; ops scripts re-pointed; Django-free seams with config
    dataclasses.
  - thin-api: the committed OpenAPI contract with a staleness test; a
    generated client for bots and `test/`; the typed front end; the
    normalised alert shape and `traffic/`; `against_applied`; the seam scan
    over clients; the pane enum.
  - event-sourced: the events app as a leaf feed with `visible_to` per kind;
    the follower service; recorded responses for the CRS stub; probes stored
    with the target app; only the referee appends `objective.lost`; the
    score as separate objects; pure fixture tests.
  - minimal-cut: the nested problem document saved atomically; checks as a
    registry of pure judges; hashed seat tokens; one refusal path; the
    request count from WAF-edge nginx records; a machine-readable HP rule and
    the all-spent end state; the separate scratch nginx master with its own
    audit log; every benign case always probed with `untested` reasons;
    probe recording with CRS detection-only; no KQL in the bot API.

## 2026-11-20 — The first account, the widened seam scan and the comment scan

- **`admin` / `123456` exists on every store again.** The 2026-11-15 ruling
  ("초기 비밀번호는 admin/123456 무조건") was lost with the old migrations.
  `accounts.0002_first_account` makes `admin` with `123456` as active staff
  (and superuser, as the old migration did) when no `admin` exists; nothing
  asks for a change. `bin/carry-users` carries rows without their primary
  keys: when the old store has `admin`, the migrated one is deleted first so
  the old hash wins; when it has none, the migrated `admin` stays. A store
  holding any user but `admin` is still refused.
- **The seam scan moved to `platform/tests/seams/` and widened to the spec.**
  It scans `platform/`, `front/src`, `bots/`, `test/` and `bin/` (the
  generated `bots/client/` and `front/src/api/schema.d.ts`, and the
  platform's own tests and fakes, excluded), and adds packet capture
  (`rules/suricata.py`), the infra nftables sets and conntrack
  (`range/edge.py`), the node names, the log index patterns and
  `/kibana/api|internal`. Its exceptions are a closed map from file to the
  seams it may know; a test reads the "Known exceptions" paragraph of
  CLAUDE.md and fails when the two lists differ, another when an exception
  no longer knows what it is allowed to. The spec's own list
  (`bin/cloud`, `bin/platform-rebuild`, `test/range.py`,
  `test/test_range_isolation.py`) matches none of the patterns, so those
  files are not listed. Four acceptance checks of Elasticsearch's own set-up
  (`test/test_event_time.py`, `test_geoip_durable.py`,
  `test_origin_placement.py`, `test_waf_geolocation.py`) query it directly
  and are named exceptions until they move behind `/api/`; the corp test's
  message no longer names the binlog.
- **`platform/tests/seams/test_no_comments.py`** scans Python (comment
  tokens and docstrings), shell (outside heredocs) and TS/TSX/JS under
  `platform/`, `front/src`, `bots/`, `bin/`, `test/`, `deploy/`, `wargames/`
  and `redteam/`, allowing only shebangs, Django's migration header (in a
  migration) and `deploy/suricata/rules/`. It found one: a `# noqa` on the
  PyYAML probe in `bin/platform-rebuild`, now `importlib.util.find_spec`.
- **Review of the scans.** The shell scan took any `<<` followed by a word
  for a heredoc, so a here-string such as `<<< word` hid the rest of the
  file from it, and it saw only lines that start with `#`. It now skips
  here-strings and arithmetic shifts, reads `<<\EOF`, finds a trailing
  `cmd # note` outside quotes, and scans the body of a heredoc fed to
  `python` as Python. The seam scan also reads `.md` and `.json`, so the
  bots' prompts are held to the same seams as their code.

## 2026-11-20 — nginx.conf and vm-terminal.sh for the side-split layout

- **Per-seat terminals.** `/vm-terminal/attack/<round>/` and
  `/vm-terminal/defence/<round>/` each go to their side's ttyd (7691, 7692;
  `-b /vm-terminal/<side>`, `-a`). nginx drops the client's query and passes
  `?arg=<round>` itself, so the round ttyd hands `vm-terminal.sh` is the one
  in the path the seat check approved. The check is an `auth_request` to
  `/api/rounds/<round>/terminal-auth/<side>/`, found from `$request_uri`
  through a map so the subrequest needs no variable of the parent location,
  and it is not cached: a yes must not outlive the seat or the round.
  Any other `/vm-terminal/` path is 404.
- **`vm-terminal.sh <host> <side> <round>`** asks `manage.py terminal_shell`
  (`match.service.terminal_shell`) for the address, host key alias and
  account. It refuses unless the round is running and the side's seat holds
  a jump grant (`range.jump.granted`), which `GET terminal/` issues and the
  round's end revokes; the address is the grant's. The attack seat gets
  `sudo -i -u kali`, the defence seat `sudo -i -u analyst`, never a root
  shell. The platform's management key still makes the ssh hop; the seat's
  own jump key is for the seat's client, which the platform never keeps.
  `entrypoint.sh` passes the side after the host, so neither the script nor
  Python names a node.
- **No `/auth-check/` view exists in the new tree**, so `/signed-in` asks
  `/api/me/` (200 signed in, 401 not), cached 5 s per session cookie and
  address. Kibana pages and the site pane need only a signed-in session;
  every Kibana API call in a space still goes to the gate, which checks the
  space against the user's defence seats. `/kibana-refused/` and
  `/static/map/` are gone: every refused Kibana route goes to the gate,
  which answers in Korean from `strings/server.json`, and the map ships with
  the front build.
- **The site listener** passes Django only `cr_session` (the site proxy
  authenticates the seat with it); `match/site.py` keeps the target's
  cookies in its own jar and never forwards the browser's. The proxied path
  is the raw rest of `$request_uri`, so percent-encoding reaches the target
  unchanged.
- **The console** is `root /app/front/dist` with `try_files $uri $uri/
  /index.html`, the last location of the 8000 server; nothing else on 8000
  reaches Django except `/api/` and the Kibana gate. `@too-many` answers in
  the API's one error shape with code `too_many`.
- **Verified offline only.** `platform/tests/test_front.py` parses the file
  (braces and semicolons) and checks each location against the Django routes
  it names; `test_vm_terminal.py` runs the script against fake `python`,
  `ssh` and `tmux`. Docker was not running on the development machine, so
  `nginx -t` was not run; nothing has run on a range.

## 2026-11-20 — Terminal review: the seat nginx checks is the seat it opens, and a shell ends with its grant

- **The raw path and the routed path must name one seat.** The seat check
  is found from `$request_uri` (raw), but the location matches the
  normalized `$uri`, so `/vm-terminal/defence/7/../../attack/5/ws` checked
  the caller's defence seat in round 7 and handed the attack ttyd round 5:
  someone else's kali shell, attached to that seat's tmux session. Each
  terminal location now returns 404 unless the raw path's seat equals
  `$terminal_round/terminal-auth/<side>` from its own captures; a dot
  segment, an escape or a doubled slash that changes the seat is refused
  before the check. `tests/test_front.py` replays nginx's normalization
  over such paths.
- **An open shell closes when its grant goes.** `vm-terminal.sh` runs ssh
  beside a loop that asks `manage.py terminal_shell` again every
  `TERMINAL_RECHECK` seconds (15) and kills ssh once the round has ended or
  the seat's jump grant is gone. The check runs in the terminal's own
  process, so it holds whichever container ends the round (the follower
  ends timed-out rounds and has no tmux). Revoking the grant used to leave
  the kept tmux session, and with it a shell on the slot's kali, open into
  the next round on that slot.

## 2026-11-20 — Spec step 5, the repo side: edge sets, the access log, the scratch CRS test, analyst

The deploy files of build step 5 are written to match what `range/edge.py`,
`rules/crs.py`, `rules/suricata.py` and `ingest/elastic.py` already call.
Nothing is baked or run on a range; `docs/OPENSTACK.md` §3.7 holds the rebake
and its checks.

- **Only `spent` is enforced at the edge.** `edge.nft` declares `pool` and
  `spent` and drops `ip saddr @spent` from `wan` before the established
  accept. The spec also drops `ip saddr != @pool`; the code fills `pool`
  only in `attack.service.refill_edge`, which returns when a round has no
  origin budgets, and a probe lease has no round. That drop would cut probe
  recording and every round without attack origins, customers included, so
  it waits until those fill `pool` too (`docs/STATE.md`).
- **The access log is `/var/log/nginx/access.json`, not `access.log`.**
  Ubuntu's `nginx.conf` already writes the combined format to
  `/var/log/nginx/access.log`; a second format into the same file would mix
  the two. The JSON line carries the fields `elastic.access_record` reads
  (`time`, `client_ip`, `status`, `request_id`) plus `request`, `vhost` and
  `refused` from the one `$refused` map; `host` is avoided because the
  template maps it as an object. Filebeat keeps renaming `status` to
  `http.status`, which `access_record` reads, so no field collides with a
  Kibana runtime field.
- **The relay and Kibana follow the new tag.** `log-relay.conf` on the infra
  forwards programname `nginx-access` (the old `nginx` branch read the
  removed `refused.log`), and the Kibana alert search and its three
  visualizations show `event.module : "nginx_access" and refused : true`
  instead of module `nginx`, so a 200 is traffic, not an alert.
- **tcpdump keeps root.** Ubuntu's tcpdump drops to the user `tcpdump` before
  it opens the `-w` file, and `rules.suricata.capture` writes into a folder
  root just made; the capture now passes `-Z root`. The infra installs
  `tcpdump` and `conntrack` (for `edge.spend`), which it lacked.
- **The scratch CRS instance needs no worker writes under its prefix.**
  `probe.conf` runs `user www-data` like the live master, keeps request
  bodies in memory (`client_body_buffer_size 16m`) and buffers no upstream
  response to disk (`proxy_max_temp_file_size 0`), so `/var/lib/cr-crstest`
  stays 0700. The error log and the audit log are opened by the root master.
  `probe-upstream.py` answers with `text/html` so ModSecurity inspects the
  recorded body as it would the live one.
- **analyst.** A bash login by the jump grant's key (password field `*`,
  which OpenSSH does not treat as locked), group `adm` for the nginx and
  ModSecurity logs, sudo for `nginx -t` and `nginx -T` only, no ssh
  forwarding, and an nftables output rule that drops every packet its
  processes send, so the defence seat cannot reach the target or the live
  WAF on loopback from its shell. The exclusion file is created 0644 (the
  platform writes it as root through sudo) instead of 0664 group `adm`,
  which analyst would have been able to write.
- **`bin/record-probes` is a thin client.** It starts the recording, follows
  the progress through the generated client and exits non-zero when a case
  was not recorded. The platform writes the recordings to its
  `CR_PROBES_OUT`; no route serves them, so they are copied off the platform
  VM by hand before they are committed.
- **Unverified.** Docker was not running on the development machine, so
  `nft -c` and `nginx -t` were not run on these files; the tests check them
  structurally, run `probe-upstream.py` on loopback and push an access line
  through the Filebeat steps into `ingest.elastic`. Whether
  `jasonish/suricata`'s entrypoint lets the offline `-r` run write to a
  root-owned scratch log folder mounted at `/scratch` is not known.

## 2026-11-20 — Step 5 review: a round starts with empty edge sets; what the missing `pool` drop leaves open

- **Each round start empties `pool` and `spent`.** A lease holds rounds one
  after another and its slot is rebuilt only when the lease is released, so
  the spec's "the `spent` set needs no flush at round end" does not hold:
  with `edge.nft` now dropping `@spent`, an origin spent in one round stayed
  dropped in the next, whose fresh budget for it showed it unspent and whose
  box could be told to wear it. `attack.fill_pool` (round start) now loads
  the edge through `range.edge.restart`, which flushes both sets and adds the
  round's addresses in one `nft -f` transaction. The tick's
  `attack.refill_edge` still only adds, so a spend that lands between its
  read and its load is never undone.
- **Why `ip saddr != @pool drop` is still missing, corrected.** The step-5
  entry gave two reasons; only one holds. Every started round has budgets
  (`match.service.start_round` calls `attack.fill_pool`, which refuses a box
  with no origin). The probe lease is the case left: it has no round and
  fills nothing. What the gap leaves open is stated in `docs/STATE.md`:
  kali's internet port allows every address, so a learner with sudo can send
  from an unused address in an origin subnet that neither set holds, and the
  HP rule does not reach it.

## 2026-11-20 — Docs brought in step with the side-split code after step 5 and the terminals

- **The spec says what was built where the build departed.** Its status line
  now says it was approved on 2026-11-19 and is being built; the text for
  the first account, the seam scan's exception map (the spec's own list
  matched nothing the scan finds), the comment scan's reach, the per-seat
  terminals and their raw-path guard, `/signed-in` on `/api/me/` (no
  `/auth-check/` or `/kibana-refused/` view, `/static/map/` dropped), the
  access log's path (`access.json`), the `spent`-only edge drop, the round
  start that empties both edge sets and `deploy/proxy/stamp.py` is changed
  to match the code. The reasons stay in the entries above.
- **`deploy/proxy/stamp.py` stays.** The spec listed it for deletion as a
  duplicate of `deploy/roles/kali/stamp.py`, but the role's file is a git
  link to it, so the repo holds one copy; there is nothing to delete.
- **OPENSTACK.md names the side split's staff range API.** Its procedures
  used the old tree's `/api/range/slot/`, `ready/`, `configure/`,
  `/api/sessions/<id>/ssh/`, `/auth-check/`, the session reset with its
  retarget and `reset-owed` files, and root shells for both terminals. They
  now follow `bin/cloud` and `match.service`: `POST fabric/`, `DELETE
  leftovers/`, `POST pool/` (a refill owed to every slot no lease holds,
  carried out by the follower, state in `CR_REFILL_DIR`), `GET
  /api/staff/range/` until every refill is `idle`; a lease gets only a free
  slot of its own wargame or `503 range_unavailable`, with no retarget; the
  terminals open as `kali` and `analyst`. Runs and measurements dated before
  2026-11-19 keep the old names as the record, which a note at the top says.
- **CLAUDE.md names `docs/DECISIONS.md` among the Korean places** for as long
  as `test_no_hangul.py` allows it by name, and no longer says the platform
  Dockerfile and `images.yml` generate the clients: only `bin/verify` does
  until the `front/` node stage exists.

## 2026-11-20 — Three open points closed: the `pool` drop, a refused terminal's answer, what `analyst` leaves

- **The edge drops every address outside `pool`.** `edge.nft` now has
  `iifname @wan@ ip saddr != @pool drop` right after the `spent` drop, both
  before the established accept. The probe lease was the one sender with no
  `pool`; `attack.fire_probe` now admits the origin it wears through
  `range.edge.admit` before each case (per case, not once, so a `slot-boot`
  reload mid-recording is refilled the way the tick refills a round). The
  other senders from the origin subnets already go through `pool`: case
  firing, free tools, requests and the attack-seat site pane wear an origin
  through `attack.wearing`, which fills the pool when the round has none;
  customers and the defence seat's site pane send from customer addresses,
  which `refill_edge` puts in `pool`. The attack terminal only checked the
  phase, so it now fills the pool the same way before it grants a shell.
  A learner with sudo on kali who adds an unused origin-subnet address now
  reaches nothing; sending from a customer address stays open (spec §17
  risk 7).
- **A refused terminal answers the API's status and code.** nginx's
  `auth_request` passes on only 2xx, 401 and 403 and makes everything else a
  500 with no body. Rather than change `terminal-auth`'s statuses (it is an
  API route with the contract's `409 round_closed`), its view adds the
  refusal code as `X-Error-Code`; each terminal location keeps it with
  `auth_request_set $terminal_refusal $upstream_http_x_error_code` (the
  module sets these variables before it checks the status, so they survive
  the redirect) and sends `403` and `500` to `@terminal-refused`, which
  returns `409 round_closed`, `409 round_not_started`, `404 unknown_round` or
  `403 not_seated` in the one error shape, and `503 unavailable` when the
  check named nothing it knows. A 401 still goes to `@sign-in`. An
  `error_page` in a location drops the server's, so the terminal locations
  also carry `error_page 429 = @too-many` for their `limit_conn`.
- **What `analyst` starts ends with the round.** When the round's defence
  grant is revoked, `defence.revoke_terminal` runs `range.jump.end_account`
  on cr-waf as root: `crontab -r`, `atrm` of the account's `atq` jobs,
  `loginctl disable-linger` and `terminate-user` (which stops its
  `systemd --user` manager and units), then `pkill -KILL -u` up to three
  times until none is left; a process that survives makes it
  `RangeUnavailable`. It runs after the key is dropped, so no new shell can
  start between the two, and only when a grant was revoked, so a round whose
  defender never opened the terminal makes no WAF call. It lives in
  `range/jump.py` beside the key handling because it is account knowledge,
  not CRS or nginx knowledge; kali's `kali` account is not ended the same way,
  since its tool runs and the box's own services are stopped by
  `attack.stop_runs` and a root learner could escape it anyway.
- **Verified offline only.** `tests/test_edge_sets.py` and `test_roles.py`
  check the rule's place; the probe recording test checks the admitted
  origin; `tests/test_front.py` replays `auth_request`'s status rule over the
  parsed config for every refusal; `tests/seams/test_jump.py` runs the end
  script against fake `crontab`, `atq`, `atrm`, `loginctl`, `pkill` and
  `pgrep` with a respawning process. No `nft -c`, `nginx -t` or range run;
  `docs/OPENSTACK.md` §3.7 lists the checks for the slot.

## 2026-11-20 — HP review from kali: one excuse per API charge, an empty edge between rounds, a bounded access line

A review of the `pool` drop from the learner's seat on kali (sudo, raw
sockets, other subnets, IPv6, the control NIC, the proxy on 127.0.0.1:8081)
and of the terminal's refusal answer.

- **An API charge excused every access event with its marker.**
  `domain.ledger.debit` skipped any asynchronous event whose marker belonged
  to an Action charged on the spot, and `stamp.py` keeps an `X-Request-ID`
  the request already carries. So a learner who read one marker from a
  `POST requests/` answer could send any number of requests from kali's
  terminal with that header and pay nothing, no sudo needed. Now a
  synchronous charge excuses exactly one event: `debit` drops the marker from
  the owed set once it skips an event, and `charge_access_page` marks the
  Action `access_seen` (migration `attack.0002_action_access_seen`) so a
  later page or tick charges the next one. Each charged Action sends one
  request (the prefetch of a case carries no action marker), so the API's own
  request is still charged once.
- **The edge stayed open after a round.** `pool` kept the round's origins
  and customer addresses until the next round start, and the HP rule charges
  only running rounds, so a process the learner left on kali (a `nohup`
  sqlmap, a root cron job) reached the target uncharged between rounds.
  `attack.close` now empties `pool` and `spent` (`range.edge.restart` with
  no addresses) when the round had filled them, and `refill_edge` adds
  nothing once the round has ended, so a tick that finishes after the end
  cannot fill it again. One open round per lease (`round_open`) makes this
  safe for the lease's next round, which fills the sets at its start.
- **A padded marker could lose the access line.** nginx 1.24 joins repeated
  headers into `$http_x_request_id` and passes control bytes in header
  values, which `escape=json` writes as six bytes each, so four 8 KiB
  `X-Request-ID` lines make an access line far past the 64 KiB rsyslog and
  filebeat carry; the cut JSON has no `client_ip` and charges no origin.
  `board.com.conf` now logs `$logged_marker`, which is `$http_x_request_id`
  only when it matches `^[A-Za-z0-9._:-]{1,128}$` (uuid hex and hyphenated,
  case names) and empty otherwise; such a request is charged as unmarked.
  The line is bounded by `$request` (one 8 KiB buffer, at most doubled).
- **Not defects.** IPv6: the infra does not forward it and the LAN groups
  admit IPv4 only. Other subnets and unused origin addresses: dropped by
  `!= @pool`. Raw sockets: a spoofed source is either a pool origin, charged
  to that origin, or a customer address (spec §17 risk 7, unchanged). The
  control NIC: `cr-mgmt` lets kali send only to `cr-reach`, which takes
  udp 123 only from it. The proxy listens on every interface, but only the
  infra and the platform can reach kali, and `analyst` on cr-waf sends
  nothing (`meta skuid analyst drop`), so it is left as is rather than
  rebaking kali. The terminal's `@terminal-refused` maps every code
  `terminal-auth` can raise; variables set by `auth_request_set` survive the
  `error_page` redirect.
- **Verified offline only.** `tests/domain/test_ledger.py` and
  `tests/attack/test_charge_from_access.py` (a reused marker charged across
  ticks), `tests/attack/test_spend.py` (the end empties the edge, a late tick
  adds nothing), `tests/test_access_log.py` (the marker map). No
  `nginx -t` or range run; `docs/OPENSTACK.md` §3.7 lists the slot checks.

## 2026-11-20 — The Hangul scan and the vocabulary file are gone

The user ruled both out as meaningless. `platform/tests/seams/test_no_hangul.py`
(the repo-wide scan that allowed Korean only in a closed list of files) and
`docs/vocabulary.md` (term translations and their sources) are deleted, and
CLAUDE.md no longer lists the places Korean may appear. Repo files are still
written in English for token cost and the product stays Korean-only; neither
is enforced by a test. A practitioner term is still taken from a primary
source when one is asked for, without a file to hold it.

## 2026-11-20 — Korean is allowed in repo files

Asked whether repo files stay English-only now that the Hangul scan is gone,
the user chose to allow Korean. CLAUDE.md drops the English-only rule for
code, commits and documents; the 2026-11-15 ruling that README.md and
docs/ARCHITECTURE.md are Korean-only stands.

## 2026-11-20 — Seats are named by username; the user pk leaves the API

The user ruled that an account is identified by its username (login ID) and
that the database id must not appear in the API. `SeatLine` carries
`username` (null for a bot or open seat) in place of `user`, and the seat ask
of `POST /api/leases/<lease>/rounds/` takes `{username}`; an unknown or
inactive account is `400 unknown_account` on `seats.<side>.username`. The lobby
asks for the username instead of a number, and the round bar shows who holds
each seat (the username, or the bot's name). `test/plays.py` seats the
operator by the username it signs in with instead of looking up its id. The
staff accounts API follows: `Account` drops `id`, and approving or disabling
is `POST /api/staff/users/<username>/approve/` and `/disable/`. An unknown
username there stays `404 unknown_user`, because `unknown_account` is already
the 400 field code of the seat ask and a code belongs to exactly one status.
The staff accounts page shows the username alone, without the `#id` line.

## 2026-11-21 — The platform is restructured into five units, KYPO-style

The owner reviewed the current `side-split` layout against cyber ranges (KYPO,
Crucible, Locked Shields), attack/defence game servers (FAUST, ENOWARS, iCTF),
agent environments (CybORG, Caldera, Inspect) and detection test tools
(go-ftw, suricata-verify, VECTR), and chose the range-service split because
its top level is the easiest to read.

- **Top level:** `users/` (accounts, sign-in, seat tokens), `sandbox/` (the
  range: pool, Heat, edge, access, and every file that knows an outside
  device: OpenStack, Suricata, CRS/nginx, Kibana, the attacker box),
  `telemetry/` (Elasticsearch, events, alerts, access and command logs),
  `training/` (content, round, traffic, attack, defence, lessons) and
  `scoring/` (the only reader of the target's ground truth). `cr/` and
  `domain/` stay shared. "training" follows KYPO's Training Service;
  "exercise" was rejected because the field uses it for a whole multi-day
  event (Locked Shields).
- **Names:** Seat becomes `Player` (a human or a bot on one side of a round;
  the owner's "Player vs AI"). Lease becomes `Allocation` (KYPO's sandbox
  allocation).
- **Fresh database.** Everything so far is test data; no migration carries
  data over. Stacks are rebuilt per allocation too, so no rule file still
  carries the `# fsl-disabled` or `# fsl-suppressed` marker: enabling a rule
  reads only `# cr-disabled`.
- **No periodic tick.** Reads of alerts, the WAF access and error logs, the
  corp DB log and the attacker command log happen when an API request for
  the round comes in, one reader per round at a time; scoring counts only
  what happened up to the round's end time. A round past its time limit is
  ended by the next request. An allocation left open is cleaned up when the
  next learner asks for a slot. Rebuilding a stack is a background job
  started when the allocation closes. KYPO has no tick either (its training
  service is driven by REST calls and its sandbox work runs as RQ jobs);
  RQ/Redis is not adopted because it adds a service.
- **OpenStack does not replace any of this.** The cloud is ML2/OVN.
  RabbitMQ is the control-plane bus (security guide: no further authorization
  once queue access is granted); security groups are allow-only; FWaaS on OVN
  is L3 at router gateways; QoS limits are per port and admin-only; OVN ACL
  logs stay on compute nodes. None sees HTTP.
- **Origin loss replaces HP.** An origin is spent when the WAF's nginx error
  log shows `access forbidden by rule` (a `deny`) or `limiting requests`
  (`limit_req`) for it. A CRS rule's 403 does not spend it; `geo` with
  `return 403` leaves no error-log line and does not count. The floor is
  twice the busiest benign customer's per-origin rate in `traffic.yaml`,
  computed into the round setup; a limit below it spends nothing and the
  defender is warned.
- **The WAF is real files.** The defender edits `crs-setup.conf`,
  REQUEST-900/RESPONSE-999 exclusions and nginx config in a terminal;
  `nginx -t`, reload and rollback. The JSON tuning object and `drift.py` go.
  The console shows the current files, their change history and the
  recorded-request test results instead of forms. Applying from the console
  checks, reloads and records; a reload done in the terminal is recorded the
  next time the files are read. `SecRuleEngine Off` and `DetectionOnly` are
  allowed: the score shows the result. curl from the defender's box is
  allowed (practitioners test rules with live requests; such requests carry
  no marker). Logging config (`log_format`, `access_log`, the request
  marker, Suricata `eve-log`) is read-only for `analyst`, because it is the
  platform's measurement, not defence.
- **Benign traffic moves from kali to the infra VM**, keeping its marker:
  running it on the attacker's box let the attacker see it and tied it to
  attacker origins.
- **The board secret is random per round** (KYPO generates answers per
  sandbox); the seeded password made the hash the same every round.
- **PvP stays.** A bot is a Player that uses the same API and the same shell,
  so PvP covers Player vs AI.
- **Bots:** the defence bot gets the same shell as a human; the form-API
  tools go. The generated client goes; `bots/` builds its tool list from
  `openapi/schema.yaml`.
- **Lessons:** the current lesson content goes; `training/lessons/` keeps its
  place for the rewrite from both sides.
- **Addendum (docs stage):** `core_loc` is not repointed at the new paths.
  The ratchet (`bin/measure`, `metrics.json`) was removed on 2026-11-19, so
  there is no measure to rerun and no record to update.

## 2026-11-21 — The tick is gone: round reads run on the round's requests

How the "no periodic tick" ruling above is carried out.

- **Where the reads run.** Every API view on a round or an allocation
  (events, state, score, the attack and defence actions, the site pane, the
  terminal checks) derives from `CatchingUpView`
  (`training/round/views_catch_up.py`). After authentication and permissions
  it closes the allocation if it is past `expires_at`, then calls
  `lifecycle.catch_up` for the round: alerts, the WAF access log (HP), corp
  effects, the attacker's command log, WAF drift, expired rule disables, the
  customers' records and the benign pass, then the end conditions.
- **One reader at a time.** `catch_up` claims the round with one conditional
  `UPDATE` on `Round.reading_since` (a compare-and-set; a claim older than
  five minutes counts as abandoned) and releases it with `read_at`. A round
  is read again only `CR_READ_EVERY_SECONDS` (default 5) after the last read,
  and first one interval after its start, so a console polling several panes
  does not read the range once per pane. A round past its time limit is read
  at once. The reads were already idempotent (cursors, unique detections,
  `access_seen`).
- **The end time.** A round ended late keeps `min(now, ends_at)` as its
  `ended`; the score counts actions that started, alerts stamped and
  objectives lost up to `ended`, and corp effects after `ends_at` do not
  mark an objective.
- **Allocations.** Opening an allocation first closes the expired ones and
  prunes the closed ones past `CR_RETAIN_CLOSED_MINUTES`.
- **The rebuild job.** The `follow` compose service is now `rebuild`
  (`manage.py rebuild_slots`, `CR_REBUILD_EVERY_SECONDS`); it only advances
  the slot rebuilds the pool owes.
- **The edge is not refilled mid-round.** `refill_edge` went with the tick.
  The round start loads the sets (`attack.load_edge`, flush and add); if
  `slot-boot` reloads the table mid-round the sets stay empty until the next
  round starts.
- **What changes for a learner.** Nothing happens in a round no one is
  looking at: the benign pass and HP charges from the access log wait for
  the next request. A bot or console that polls events keeps them moving.
  `check_drift` stays in the reads until the WAF-as-files stage removes it.

## 2026-11-21 — Origin loss replaces HP: how it is read

How the "origin loss replaces HP" ruling above is carried out.

- **What went.** `domain/ledger.py`, `HpRule`, `Charge`, `OriginState`,
  `RoundSetup.hp` and the `round.hp` problem field (a document that still
  names it is refused with `unknown_field`), `OriginBudget` (now `Origin`,
  with `spent_at` and `spent_by`), `Action.charged` and `access_seen`, the
  `origin.charged` event, the `hp` block on attack answers and errors, the
  `X-Origin-HP` header, the console's HP pane and the staff HP fields.
- **What the attacker sees.** A successful attack answer carries
  `remaining: {origin, left, total, spent}`; every attack answer carries
  `X-Origin` and `X-Origins-Left`. The console pane is "출발지 IP" and shows
  남은 IP. A refusal is `{errors}` only.
- **The log.** The WAF writes `error_log /var/log/nginx/error.log warn;`
  (in `board.com.conf`, beside the access log); `log-shipper.conf` ships it
  as `nginx-error`, the infra relays it, filebeat keeps the text line as
  `error.message` under module `nginx_error`. `telemetry/elastic.py` reads
  it (`error_events`), `telemetry/access.py` picks the two lines that spend:
  `access forbidden by rule, client: <ip>` and `limiting requests, excess:
  ... by zone "<zone>", client: <ip>`. A dry run line, `delaying request`
  and ModSecurity's own 403 line do not match. `warn` rather than the
  default `error` keeps a `limit_req_log_level warn` visible.
- **The floor.** `domain/traffic.py` computes it from `traffic.yaml`: the
  customers' `rate` (default one request a second across all customers,
  the rate `users.py` already paced at) times the largest share of `users`
  one origin gets, in requests per minute, doubled and rounded up (board:
  90 r/m). `content.snapshot` stores it as `round.limit_floor_rpm`. A
  `limiting requests` line is judged by its zone: `sandbox/crs.py` reads
  the zone rates from `nginx -T` (only when such a line appears), and a
  zone below the floor spends nothing and leaves one `limit.below_floor`
  event per zone and rate on the defence side; a zone the running
  configuration no longer declares spends nothing either. A wargame with no
  `traffic.yaml` has no floor, and any limit spends.
- **When.** The error log is one of the round's reads
  (`attack.spend_from_log`, cursor `errors` on the allocation's
  `AccessCursor`); only lines stamped between the round's start and its
  end time count. The spend itself is unchanged: the edge drops the
  address, tool runs stop, the box wears the next origin, and the round
  ends `origins_spent` once all are gone.
- **Not measured.** None of this has run on a range: the WAF image must be
  rebaked with the error log shipped, and the acceptance tests
  `test/test_origin_spend.py` and `test/test_block_everything.py` were
  rewritten without being run.

## 2026-11-21 — The WAF is real files: how it is read, applied and recorded

How the "WAF is real files" ruling above is carried out.

- **The files.** The defence edits six files on cr-waf, named by the WAF
  device's `files:` in each `topology.yaml` and by `WafConfig.files`:
  `crs-setup.conf`, the REQUEST-900 and RESPONSE-999 exclusion files, and
  `/etc/nginx/defence/http.conf` (http level), `board.com.conf` and
  `corp.com.conf` (each site's server level), where `deny`, `limit_req` and
  `limit_req_zone` go. `conf.d/board.com.conf` keeps the maps, `log_format`,
  `access_log` and `error_log` and includes the three nginx files; it and
  `modsecurity.conf` stay read-only.
- **One flow for IDS and WAF** (`training/defence/rules.py`): read, check
  (`suricata -T`, or `nginx -t` on a scratch copy), test against the
  recorded probes, write, reload, record. A version (`RuleSet`) stores every
  file's text (`files`), their hash (`sha`) and where it came from
  (`source`: setup, console or terminal). A test (`RuleTest`) stores the set
  it ran: the given files over the live ones. `same_as_tested` compares the
  hashes. `sandbox/crs.py` writes only the changed files, reloads, waits for
  a new worker, and writes the previous text back if nginx refuses or starts
  no worker. Errors name the file and line, ModSecurity's `File: ... Line:`
  included, mapped back from the scratch paths.
- **What is refused.** A file outside the six, and in a given file the
  platform's logging: `access_log`, `log_format`, `error_log`,
  `open_log_file_cache`, `SecAudit*`, `SecDebugLog*`, `ctl:audit*`.
  `SecRuleEngine Off` and `DetectionOnly` pass. This check runs on what the
  console and the API send; a file written in the terminal is not checked,
  so a logging directive added there and reloaded is recorded like any
  other version.
- **A reload done in the terminal.** The round's reads (the step that
  replaced `check_drift`) compare the live files' hash with the last
  version's; when they differ and an nginx worker started after the newest
  file was written, the live files become the next version, `source:
  terminal`, by the defence player. Files edited and not reloaded are not
  running and are not recorded; `GET waf/` says so with `recorded: false`.
  A round whose posture names no WAF files records the live files as
  version 1 at its start, so a later reload has something to differ from.
- **What went.** The JSON tuning object (`crs.checked`, `rendered`,
  `parsed`, the paranoia, exclusion and threshold fields), `defence/drift.py`,
  `RuleSet.drifted_at`, the `rule.drifted` event and the score's
  `posture_drift`. `Posture.crs_tuning` is now `Posture.waf_files`
  (path to text); a document that still names `crs_tuning` is refused with
  `unknown_field`. The probe recorder's detection-only WAF appends
  `SecRuleEngine DetectionOnly` to `crs-setup.conf`.
- **The analyst account.** The six files are `root:analyst 0664`; their
  directories, the site config, `modsecurity.conf`, the log shipper and the
  logs stay unwritable. `sudo` allows `nginx -t`, `nginx -T`,
  `nginx -s reload` and `systemctl reload nginx`. The nft fence that dropped
  everything the account sent now accepts loopback, so `curl` reaches the
  sites through the WAF itself. Such a curl may carry any `X-Request-ID`,
  so a detection counts for a marker case only when its source address is
  the one the case was sent from (`correlate._sent_from`); the curl's
  source is the WAF's own, and it counts for no case. The sensor gets no analyst account, so nothing changes there.
- **The scratch test** copies the CRS tree and `/etc/nginx/defence`, points
  every `proxy_pass` in the copied site files at the probe stub, and loads
  the copies where the live config loads them (`probe.conf` now has a
  server per site).
- **Console.** The WAF pane shows each file's current text in an editor,
  sends only the changed files, and lists the versions with source and hash;
  a version opens with its files' text. The staff posture editor edits file
  text instead of a form.
- **Not measured.** The WAF image must be rebaked for the split site config
  and the writable files; no live round has run on it.

## 2026-11-21 — Benign traffic runs on the infra VM

The restructure ruled that benign traffic leaves kali. How it is done:

- **Where it sends from.** Each origin's first address stays on kali as the
  attack origin; the origin's other addresses go to the infra
  (`CUSTOMERS` in its `/etc/slot.env`, from `stack_plan.customer_addresses`),
  never the default origin's. `slot-boot` puts them on a dummy link
  `customers` as /32s: a /24 there would route the attackers' replies into
  the dummy link. The sites resolve to the WAF's front in `/etc/hosts`
  (`SITES`, the gateway's names).
- **The path.** The infra sends out of its DMZ port straight to the WAF.
  That port already allows every source address because it routes, so no
  Heat change was needed. The customers do not cross the edge, so the edge's
  `pool` holds only attack origins; kali sending from a customer address is
  dropped at the edge as an address outside `pool`.
- **What runs.** `deploy/traffic/users.py` is baked into the infra image
  with the unit `cr-customers.service` (account `cr-users`, not enabled).
  `sandbox/customers.py`, the only file that knows that box, writes the
  round's plan, starts and stops the unit and reads the records. The
  benign cases and the defence player's site pane run `curl` there as
  `cr-users` with `--interface` set to a customer address. The
  `X-Request-ID` marker is unchanged, so benign requests are scored as
  before.
- **Kali.** It holds one address per origin; the customers' account, the
  owner-match NAT exception and the pushed program are gone from
  `sandbox/attacker.py`. The map's unused "customers on the attacker box"
  placement went with them.
- **Not measured.** `cr-infra` has to be rebaked (and `cr-kali` with it)
  before a range has customers; nothing has run on a slot
  (`docs/OPENSTACK.md` §3.8).

## 2026-11-21 — The board secret is set at random at each round's start

How the "board secret is random per round" ruling is carried out.

- **Where it is set.** The board's own management command
  `posts/management/commands/set_passwords.py` reads a JSON map of username
  to password on stdin and sets every account's password: the named ones to
  the given password, every other one to `secrets.token_urlsafe(24)`. The
  board's secret in `objectives.yaml` names it as `rotate`, so the platform
  holds no board-specific command.
- **When.** `lifecycle.start_round` hands the round's passwords to
  `scoring.baseline.take_baseline`, which runs `loot.rotate` through the
  same runner into the board container and then reads the baseline, so the
  baseline is that round's hashes. A board that cannot set its passwords
  refuses the baseline (`ground_truth_unavailable`) and the round stays
  created. The probe recorder reads the truth without setting it.
- **The customers still sign in.** `traffic.yaml`'s `accounts` lists only
  usernames now. `customers.fresh_passwords` makes a random password per
  account per round; the same map goes to `set_passwords` and into the
  customers' plan (written `umask 077` on the infra). It is not stored in
  the database. `admin` is not a customer account, so its password is known
  to no one.
- **The image default.** `seed.py` keeps its fixed passwords: a board that
  is not in a round, and the tests that check the seed, still have them.
- **Not measured.** The `cr-board` image the target bakes must carry the
  command (`docs/OPENSTACK.md` §3.9); until then every round start fails.

## 2026-11-21 — Verdicts reach the defence as they are decided

The 11-20 direction asks for live verdicts; the score stays closed to players
until the round ends. Each round read now judges the cases it can decide and
tells the defence at once.

- **When a case is decided** (`domain.scoring.metrics.decided`): an ended case
  with a matching alert is judged at the next read (TP or FP); an ended case
  with none is judged once `CR_JUDGE_AFTER_SECONDS` (default 30) passed since
  it ended (FN or TN), so the alert pipeline's delay is not read as a miss; a
  tool case still running waits for its run to end; the round's end judges
  every case left, before `round.ended` is written, so a follower that stops on
  `round.ended` has them all.
- **Same rules as the score.** `scoring.score.judge` uses the score's own
  correlation, its end-time cut and `corroborated`; free actions are never
  judged.
- **One case, one decision.** A verdict is a `scoring.Verdict` row, unique per
  round and action; only a row this read created becomes a `case.judged` event
  `{action, case, verdict, alerts, corroborated}`. Alerts that arrive later do
  not change it, so a notice can differ from the final score when an alert
  comes in after the wait. The final score is still computed from the rows.
- **Who sees it.** `case.judged` is a defence-and-staff kind: it measures the
  defence, and telling the attacker which cases were seen would hand them the
  defender's coverage. The defence console shows it as 판정 알림 in the lower
  right corner, the newest three, each closable.
- The judge step is the last of the round reads, after alerts are ingested and
  the customers' benign pass is fired.

## 2026-11-21 — Bots: the same shell as a human, no generated client

How the "Bots" ruling above is carried out.

- **No generated client.** `bin/gen-clients`, `openapi/python-client.yaml`
  and the `openapi-python-client` dev dependency (and with it `httpx2`) are
  gone. `bots/rest.py` sends an operation by its `operationId`: it reads the
  method, the path and which parameters go in the path or the query from
  `openapi/schema.yaml`, and sends the body as JSON. `bots/signin.py` returns
  `requests` sessions (`signin.Platform`: base URL, timeout, the CSRF header
  from the `cr_csrf` cookie, the player token as `Bearer`). `bots/`, `test/`,
  `bin/acceptance`, `bin/cloud`, `bin/record-probes` and `bin/verify` all call
  through it. An operation gone from the schema now fails at its first call
  instead of at import. `bin/verify` exports the schema itself
  (`manage.py spectacular`). `front/` keeps its hand-written
  `src/api/client.ts` over the types `npm run types` generates.
- **Arguments are checked against the tool spec.** The generated models used
  to refuse a value outside an enum; `bots/calls.py` now checks each
  argument's type and enum against its input schema and refuses it locally
  (`"local": true`, code `invalid`) before anything is sent.
- **The shell.** Each side has a `shell` tool while the schema has its
  terminal operation. Its first call asks `attack_terminal` or
  `defence_terminal` for the SSH grant a human's terminal uses, writes the key
  to a private temporary directory and runs each command as `ssh` through the
  jump host (`ProxyCommand ssh -W`) to the learner account on the attacker box
  or `analyst` on the WAF. The grant is kept for a `run` and dropped when ssh
  itself fails (exit 255); `call` and the one-line form are one process each
  and ask for a new grant each time, which replaces the one before. A reload
  made through it is recorded like a human's terminal reload.
- **Form tools.** The tool list was already built from the schema, so no tool
  outlived its endpoint; the WAF form tuning went with its API in the WAF
  files ruling. The defence keeps the IDS and WAF file tools, which are the
  API the console uses, beside the shell.

## 2026-11-22 — Terminal text stays English, IDS rules are edited on the sensor, no version author

- The line `vm-terminal.sh` prints when a terminal fails stays English, as ssh, nginx and every other tool on a terminal print English. The Korean-only rule covers the console, not terminal output.
- The defence player edits Suricata rules on the sensor itself, as the Suricata documentation describes for a standalone sensor (edit `local.rules`, reload), not through a platform form or API. The sensor runs on the infra VM beside the customers program and the edge router's nftables sets, so the defence gets an `analyst` account there, as on the WAF: it may write the rule file and run `suricata -T` and the rule reload under sudo; it may only read `suricata.yaml`'s outputs (eve-log), and has no access to `nft`, `edge.nft`, the customers program or the `cr-users` account. A terminal reload is recorded as a version on the next read, and one that touches the logging configuration is put back, as on the WAF. The IDS rule API and its console form are removed; the bots use the same shell. Rejected: keeping the API, which imitates a central SOC rule manager the range does not have.
- WAF and IDS versions carry no author field: a round has one defence player, so the round already names who made each version.

## 2026-11-22 — IDS rules on the sensor: how it is carried out

How the "IDS rules are edited on the sensor" ruling above is carried out.

- **The account.** `deploy/roles/infra/analyst.sh` makes `analyst` on the
  infra like the WAF's: key login only, group `adm` (reads
  `/var/log/suricata`), the same ssh `Match` block, and an nft fence that
  accepts its packets on `lo` only to `127.0.0.0/8` and `::1`. The WAF's
  fence accepts anything on `lo`; on the infra that would reach the log
  relay, which listens on the host's own address (`imtcp` 514, a packet to
  which also leaves on `lo`) and forwards a `modsecurity` message as a WAF
  log, so the account could have written a WAF detection.
  It writes `/var/lib/suricata/rules/local.rules` through an ACL
  (`u:analyst:rw`): the `jasonish/suricata` entrypoint runs `chown -R
  suricata:suricata /var/lib/suricata` (and `/etc/suricata`,
  `/var/log/suricata`) when the container starts with its capabilities, so
  a group grant would not survive a sensor start; an ACL does. `sudo`
  allows only `/usr/local/bin/suricata -T` (a wrapper that runs `suricata
  -T -c /etc/suricata/suricata.yaml` in the `sensor` container) and
  `/usr/local/bin/suricatasc -c reload-rules`, the topology's reload
  command. `/usr/local/share/slot` (the edge table, the log relay) and the
  rule test scratch are root 0700, the customers' home and program folder
  `cr-users` 0750; the account is in no `docker` group. The infra's
  `/etc/nftables.conf` holds only the fence table, so `nftables.service`
  is enabled and the edge table `slot-boot` loads stays.
- **The terminal.** `GET defence/ids/terminal/` grants a second jump key per
  defence player, named `cr-session-<player>-ids` beside the WAF's
  `cr-session-<player>` (`sandbox/access.py` keys a grant by player and
  box), to `analyst` on the first sensor's node. The platform runs a third
  ttyd, `vm-terminal.sh cr-infra ids` on `/vm-terminal/ids/<round>/`,
  checked by `terminal-auth/ids/` (the defence player). The console's
  defence terminal pane switches between WAF and IDS. The round's end
  revokes both grants and ends `analyst` on both boxes.
- **What is recorded.** Suricata runs what it read at its last reload,
  not the file, and a player may edit the file again before the next read,
  so the reload records what it loads. The host's `suricatasc` wrapper,
  given `-c reload-rules`, copies the rule file into
  `/var/lib/cr-reloaded/ids` (root 0700; the analyst cannot write it),
  installs that copy over the live path as a new root-only file, reloads in
  the container (`reload-rules` blocks until the reload is done), and on a
  `"return": "OK"` reply writes the reload time beside it (`at`); only then
  does it give the analyst's ACL back. Suricata therefore reads exactly the
  snapshot: a write during the reload is refused, and one through a
  descriptor opened before it lands on the replaced file. The wrapper
  ignores INT, TERM and HUP, holds a lock (`flock` on
  `/var/lib/cr-reloaded/ids.lock`) and stages in its own `mktemp -d`
  directory, so two reloads never mix; the platform's read takes the same
  lock shared and fails when a file is missing. The round's reads (through the sensor's
  node) compare that snapshot with the head IDS version: when its time is
  not the one the head keeps (`RuleSet.reloaded`, set to the snapshot time
  current whenever a version is recorded, so a platform reload, which runs
  inside the container and leaves no snapshot, consumes the older one) and
  its text differs, it is the next version, `source: terminal`, with no
  test attached. The live file is never put back for being edited. A
  reloaded rule with the `config: logging` keyword (Suricata's per-transaction or per-flow logging
  disable, which stops the eve records the platform measures) is written
  back to the head version and reloaded, with `rule.refused`; a rule
  continued over lines with a trailing backslash (Suricata's loader joins
  them, `src/detect-engine-loader.c`) is matched as one rule. A round
  whose posture has no Suricata rules records the live file as IDS
  version 1. `GET ids/rules/` reads the live file and says `recorded`.
- **What went.** `POST ids/rules/check/`, `POST ids/rules/apply/`,
  `ids/disabled/` and `ids/disabled/<sid>/`, `DisabledRule` (training's
  `0001` is generated again without it), `defence/disable.py`, the `rule.disabled` event, the
  `unread_sid` code, the expired-rule read, and the console's IDS editor
  and disabled-rule form. Kept: `GET ids/rules/`, the versions, the rule
  test and its results; the posture still writes the sensors at the round
  start. The defence bot has `ids_shell` over the new grant.
- **The WAF the same way.** `deploy/roles/waf/nginx`, installed as
  `/usr/local/sbin/nginx` (first on sudo's `secure_path`, so `sudo nginx
  -s reload` finds it; sudoers names it for `-t`, `-T` and `-s reload`),
  passes every other call to `/usr/sbin/nginx`; given `-s reload` it copies
  the six files into `/var/lib/cr-reloaded/waf`, installs each copy over
  its live path as a root-only file, runs `nginx -t` (nginx's reload signal
  returns 0 even when the master then refuses the files), reloads, waits
  for a new worker of the master (`/run/nginx.pid`; ten seconds, else it
  fails), writes `at`, and only then gives the six files back to
  `root:analyst 0664`. nginx tests and loads the snapshot, not a file the
  analyst can change under it; the lock, the private staging directory and
  the ignored signals are the IDS wrapper's. A drop-in points `systemctl reload nginx` at the
  wrapper. The reads record the snapshot, and only a refused snapshot is
  put back (head written and reloaded, `rule.refused`). The worker-start
  check (`crs.reloaded_since_written`) and the IDS reload-time read
  (`suricata.reload_times`) are gone with the put-back of rules whose
  running state was unknown.
- **Not measured.** The infra and the WAF must be rebaked
  (`docs/OPENSTACK.md` §3.7, §3.10). While a reload runs (on the WAF the
  whole `nginx -t` and the worker start, seconds) the analyst's writes to
  those files are refused; a descriptor held open across a reload writes
  to the replaced file, which nothing loads. The acceptance tests
  that changed IDS rules (`test/shared_sessions.py`,
  `test/test_apply_after_test.py`, `test/test_concurrent_sessions.py`,
  `test/test_rule_changes.py`) now write and reload through the IDS shell
  and were not run; `test/test_disabled_rule.py` went with the feature.

## 2026-11-22 — Whole-branch review: what was fixed and what stays open

- **A marker counts only from its own address.** Any client can send an
  `X-Request-ID`, and the WAF's analyst can curl the sites through the WAF.
  Under marker correlation a detection now counts for a case only when its
  source is the address the case was sent from (an attack origin, or the
  customer address of a benign case); a detection with no source still
  counts. The IDS sees the WAF-to-site leg, so its source is the last
  `X-Forwarded-For` entry, which nginx sets to the client it saw.
  **[unverified on a range]** an IDS alert that reaches the platform with no
  `X-Forwarded-For` join keeps the WAF's address and no longer counts for a
  marker case; the acceptance run must show TP > 0 still.
- **The WAF reload refuses before it loads.** `deploy/roles/waf/nginx` runs
  the platform's measurement check (the logging directives, real IP and, new,
  nginx `include` and ModSecurity `Include`/`IncludeOptional`) on the
  snapshot before `nginx -t` and the reload, and on the live files for a bare
  `-t` or `-T`; the console applies and the scratch test check the live files
  they load beside the given ones. A test holds the shell check to
  `crs.measurement_in` line by line. The WAF must be rebaked.
- **The round's end waits for late alerts.** `finish` waits until
  `CR_JUDGE_AFTER_SECONDS` past `ended`, ingests once more, then settles and
  judges; the request that ends a round can take that long. The final reads
  fire no benign pass.
- **Smaller fixes.** A `limit_req_zone` whose key has no `$remote_addr` or
  `$binary_remote_addr` spends nothing (silently, as an undeclared zone). A
  closing allocation holds its slot `resetting` before it is marked closed,
  so the slot is not offered during the teardown. A rebuild step drops its
  result when the refill changed while it ran. An operator who holds a seat
  reads the score only after the end. A read ends a tool run the box reports
  finished. `RuleSet.player` is gone and training has one `0001` again.
- **Open.** Whether a lost objective counts as seen from any detected attempt
  in its window or only the latest (free actions now qualify and the
  attacker can pick the credited one); judging a `limit_req` refusal by the
  zone rate live when it was written, which needs every reload kept, not
  only the last; a warning text for a shared-key zone; the IDS reload
  wrapper checks nothing before it loads; whether the topology should name
  the sensor's `suricata -T` check the way it names the reload.

## 2026-11-22 — A lost objective is scored by detection and response, each O or X

The objective score used to ask one question of a lost objective: was the attack seen, meaning an alert fired on the latest attack action in the two minutes before the theft. An alert firing measures the sensor, not the defender, and the latest-action rule let an attacker turn a detected theft into an undetected one by sending one plain request after the attack.

Each lost objective now carries two marks:
- **탐지 (detection) O/X**: O when any attack action (`malicious is not False`, benign never) in the attribution window drew an alert that survives `expect`. Not only the latest action, so a noise request after the attack changes nothing.
- **대응 (response) O/X**: O when the defender acted against that attack before the objective fell: an origin used by an attack action in the window was spent (deny or limit_req in the nginx error log, the origin-loss path), or a WAF or IDS version was applied (console or terminal reload snapshot) after the first alert of those actions, or after the first of those actions when none alerted. Viewing Kibana does not count; only actions recorded in logs do.

Weight of a lost objective in the primary score: 대응 O counts half (the old detected weight), 대응 X counts full, whatever 탐지 says. 탐지 is reported beside it, and so is the time from the first alert to the first response; neither is folded into the number. corp's effect path uses the same two marks. Rejected: crediting an alert alone (it rewards an ignored alarm) and counting Kibana views (a view is not a decision).

## 2026-11-22 — A rule goes live only after a test with no false positive; a response counts only when a replay proved it

Amends the entry above on what counts as 대응 O, and changes how a rule reaches a sensor.

- **Test required.** No WAF or IDS change goes live untested, from the console or from the terminal. A test replays the round's benign cases and the attack cases against the candidate files on the scratch instance (WAF) or the offline `-r` run (IDS). It passes only when no benign case is refused (WAF) or alerted (IDS) and the engine check passes. The console apply accepts only files whose hash equals a passed test of that round and engine. On the box, the reload wrapper refuses to load a snapshot whose hash is not in the list of passed tests the platform writes there (root-owned, read-only to the analyst). The aim is that a false positive cannot reach the live sensor at all.
- **대응 O** needs proof in logs, not just a new version: (a) an origin used by the attack was spent, shown by deny or limit_req lines in the nginx error log; or (b) a WAF version went live after the attack's first alert (or its first action when none alerted) and before the objective fell, and its required test replayed that attack's own requests (built from what the platform sent for that action: a case recording, or the logged request of a free request action) and the WAF refused them. An IDS change cannot be a response: the IDS only alerts. Rejected: counting any applied version (a no-op or unrelated rule would earn 대응 O).

## 2026-11-22 — Test required and response proof: how it is carried out

How the two rulings above are carried out, and two open points of the
whole-branch review closed.

- **The gate.** A rule test passes (`passed`) when the engine check passes
  and no tested benign case was refused with 400 or 403 (WAF) or drew an
  alert (IDS); the failing cases are `failed_benign`. On a pass the platform
  appends the box's hash of the tested files to a root-only list,
  `/var/lib/cr-reloaded/waf.passed` on cr-waf and `ids.passed` on the
  sensor's node, through `sandbox.crs.permit` and `sandbox.suricata.permit`
  only; the posture step of a round's setup empties both. The WAF hash is
  the sha256 of the six defence files' `sha256  path` lines in their fixed
  order, the IDS hash the rule file's sha256, so the wrappers compute it
  with `sha256sum`. `deploy/roles/waf/nginx` and
  `deploy/roles/infra/suricatasc` refuse a snapshot whose hash is not listed,
  before it loads, and print why. The platform's own loads through the
  wrapper (posture, put-back, DetectionOnly for a probe recording) list
  their hash first in `crs.apply`. The console WAF apply merges the live
  files with the given ones, refuses the result unless a passed test of the
  round has its hash (`409 not_tested`), and writes that whole set. A
  terminal version is tied to the passed test of its files.
- **The proof.** A WAF test also replays the round's attack actions so far
  (`rules.attack_requests`: a fired case by its recording, a free or
  site-pane request by the method, host, path, query, headers and body the
  platform now logs in `Action.meta`), each under its own marker, and keeps
  per action whether the scratch WAF refused it in the stored result. That
  list is not served to the defender: it would show attacks no alert saw.
  A version is a response for a lost objective when it is a WAF version
  with a passed test of the same files, live after the window's first alert
  (first action when none alerted) and before the loss, and its test
  replayed at least one of the window's actions and refused every one it
  replayed. Tool runs and commands cannot be replayed and are proved only
  by a spent origin.
- **Closed from the review.** The IDS reload wrapper runs the
  `config: logging` check before it loads. A `limit_req_zone` keyed by
  anything but the client address spends nothing, with or without a floor,
  and leaves one `limit.shared_key` event for the defence. The request that
  ends a round no longer sleeps out `CR_JUDGE_AFTER_SECONDS`; the first read
  after it runs the last ingest, settle and judge, sets `Round.judged_at`
  and logs `round.judged`, and the score carries `pending` until then.
- **Open.** With no probe recordings committed no benign case is tested and
  every rule passes; whether a pass should need a tested benign case is for
  the user. Acceptance plays that applied a rule expected to refuse
  customers on the live range now meet the gate and were not run. A replayed
  case whose recorded response is a 400 or 403 reads as refused by the WAF.
  The boxes must be rebaked for the wrappers.

## 2026-11-22 — Test required: the review's fixes

Four points of the review of the entry above, fixed.

- **A pass needs every benign case tested.** A rule test passes only when
  every benign case of the round was replayed (WAF) or run (IDS), at least one
  was, and none was refused or alerted on. A benign case with no recording
  lists in `untested_benign` and fails the test, so nothing is permitted. This
  closes the open point above: with no probe recordings a rule that refuses
  every request used to pass. Until `bin/record-probes` has recorded a
  wargame's probes, no WAF or IDS change can go live on its range.
- **The response is judged on the attack's requests.** A WAF version answers
  a loss when its test refused every replayed window action that drew an
  alert; when none drew one, every replayed case attack; when only free
  requests were replayed, any one of them. Rejected: "every replayed action
  refused", which let one plain request in the window cancel any response,
  the same noise the detection ruling closed.
- **Replays carry fresh markers.** Each replayed attack action goes to the
  scratch WAF under `replay-<test>-<random>` and is mapped back to its own
  marker in `actions`. A rule keyed on the `X-Request-ID` the analyst can read
  in the access log refuses none of the replays.
- **Acceptance proves the halved weight.** `board_session` applies a tested
  WAF rule refusing the SQLi search after its alert and before the loot, and
  `test_score_reveal` needs a responded loss on the board and an unanswered
  one on corp; the detection mark is a separate test.

## 2026-11-23 — The response replay sends the attack's own logged requests, against the live version and the candidate

Corrects the 2026-11-22 entry, which wrote the user's ruling ("send the log mock-up for real and count what the logs prove") down as a case recording or the logged request of a free request. That replayed one pre-recorded sample per case, not what the attack sent in the round: sqlmap sends about 2,000 requests a run, and the sample says nothing about the ones that got through.

- The requests replayed for an attack are the requests that attack sent in this round, taken from the logs by its marker: the WAF access log's request lines (method, URI, Host), and the ModSecurity audit log for headers and body where it holds the transaction. A request whose body the logs do not hold (a POST that drew no rule, so the audit log kept nothing) takes the body the platform sent for that action; if none is known it is replayed without one and marked so.
- Each replayed set is sent twice to the scratch instance: once with the files live when the candidate was tested, once with the candidate. 대응 O needs at least one of the attack's requests that the live files let through and the candidate refuses. A version that refuses only what was already refused, or nothing, is 대응 X.
- Identical request lines are sent once; above a cap per action the replay takes an even sample and says how many it sent of how many logged.

## 2026-11-22 — Attack origins, benign traffic kinds, Internet scanners, board attack paths

The user's rulings of 2026-11-22, recorded on 2026-11-23. None is built yet.

- **Five attack origins per attacker** for now, in place of about thirty, and settable per wargame. With fewer origins each spent origin costs the attacker more.
- **More benign traffic kinds.** The customers' program gains search crawlers (Googlebot, Bingbot, Naver Yeti, Daum), uptime monitors, RSS/feed readers and similar bots, and ordinary users who at random read posts, upload new posts and comment.
- **Internet scanners as noise.** Probes for `wp-login.php`, `.env`, `phpmyadmin` and Shodan/Censys-like user agents run as background noise. They are neither benign nor attack: they enter no TP/FP/FN/TN, and the zero-FP rule test does not replay them.
- **Board attack paths.** Only realistic old CVEs and configuration mistakes; each round picks one or two:
  - SQLi: `order_by` CVE-2021-35042 (today's `?sort=`), Trunc/Extract CVE-2022-34265 (month/week archive).
  - RCE: reportlab CVE-2023-33733 (save a post as PDF), with a new objective: the `SECRET_KEY`.
  - `/admin/` access-control bypass: gunicorn request smuggling CVE-2024-1135 (< 22.0.0) or the trailing-newline CVE-2021-44420, combined with `/admin/` password guessing with no login rate limit.
  - Information disclosure: `.env` served by an nginx static misconfiguration; `dictsort` CVE-2021-45116 (member list `?order=`).
  - Deferred: SSRF, XXE, XSS (XSS needs a moderator browser bot). Rejected: `DEBUG=True`, as unrealistic for a production board; this also drops django-debug-toolbar, whose default show-toolbar check needs `DEBUG`.
  - Before building a path, check from the CRS rule files which rules cover it.

## 2026-11-23 — The first cloud check of `restructure`: what it changed in the product

The first range built from `restructure` (rebaked images, the platform VM
replaced, the pool converged, `docs/OPENSTACK.md` §3.7-§3.10 checked, probes
recorded, the full `bin/verify` with acceptance) found these, fixed on the
branch.

- **The attack API returns bodies up to 256 KiB, not 64 KiB.** corp's
  WordPress pages are 70-94 KB and their nonces sit a few hundred bytes from
  the end (the home page's probe response is 93,755 bytes, its nonce at
  93,421). `POST requests/` cut bodies at 64 KiB, so a bot player could not
  read a nonce the human reads in the site pane. A bot must reach what a
  human reaches (CLAUDE.md), so the limit follows the largest page the
  wargames serve.
- **`board-path-traversal-static` climbs from `/static/admin/`.** The case sent
  `/static/` followed by four encoded `../`, which climbs above nginx's root:
  the WAF's nginx answered 400 in its URI parser, before ModSecurity and
  before anything reached the sensor, so its probe recording was an empty
  capture and the case drew no alert of its own. The path is now
  `/static/admin/%2e%2e%2f%2e%2e%2fetc/passwd`, which stays inside the root and
  reaches CRS and the sensor; its probe was recorded again.
- **The offline IDS rule test runs Suricata with `--runmode single`.**
  `sandbox.suricata.offline_test` ran the sensor's `suricata.yaml`, whose
  `runmode: workers` Suricata 8.0.7 refuses for `-r` ("The custom type
  "workers" doesn't exist for this runmode type PCAP_FILE"), and stderr was
  discarded. Every replay was empty, so every IDS rule test passed with no
  alert and no benign case could fail it. With `--runmode single` the replay
  of `board-sqli-search.pcap` gives its alert, and the zero-FP gate now holds
  for IDS rules.
- **A terminal grant names the jump host.** With no `CR_JUMP_HOST` set, every
  grant (attack, WAF and IDS terminals) answered an empty `ssh.host`, so no
  client could reach the jump sshd. The views fall back to the request's host,
  as the old tree did (`training.round.access.with_jump_host`).
- **The declaration file is read beside the code.** `cr/config.py` built the
  declaration's path from `CR_SOURCE`, but the platform container mounts only
  `deploy/`, `wargames/` and `redteam/cases` there, so `POST
  /api/staff/range/fabric/` answered 500. The path falls back to the file
  beside the code when `CR_SOURCE` does not hold it.
- **Acceptance plays that changed the posture past the gate start from it.**
  With the rule-test gate working, a live change that refuses or alerts on a
  benign case cannot go live, so the block-everything WAF and the noisy and
  catch-all IDS rule sets are now the start postures of their own rounds
  (staff write those, no rule test gates them), and the round isolation plays
  use rules that touch only a path no benign case uses.
- **Open, for the user.** A benign case is fired on every pass of the
  customers, so one round holds many firings of it, and the score lists one
  line per firing. CLAUDE.md says one case is one decision however many
  alerts it drew. The acceptance harness now reads a case as detected when any
  of its firings drew an alert (the newest firing's alert may not be ingested
  yet when the score is read). Whether the score should fold a benign case's
  firings into one decision, and how, is not ruled.
