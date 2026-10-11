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
  pfSense/Suricata and carries the origin country from `fsl-origin` SNAT. A
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
  which broke tool cases there too. Set in the VM's openstack.env. Whether the
  attacker image should resolve from the substrate in code rather than from an
  env var is left open (STATE backlog 0).

## 2026-10-09 — /attacks/ wears the origin; sqlmap `?sort=` extraction verified negative

`POST /sessions/<id>/attacks/` recorded the requested origin in the case meta
and picked the launcher segment, but never applied the SNAT. On OpenStack the
source country is set only by `fsl-origin`, so an API-only caller fired from
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
- Verified live in a guided board session (session 195, opened from "레슨으로
  시작"): boxes over the alert table, a row's expand toggle and the panel's
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
product terms as CRS and ModSecurity write them instead of translations:

| old | new | source |
|---|---|---|
| 편집증 수준 | Paranoia Level (PL) | https://coreruleset.org/docs/2-how-crs-works/2-2-paranoia_levels/ ("The paranoia level (PL)") |
| anomaly scoring (lowercase title) | Anomaly Scoring, inbound anomaly score | https://coreruleset.org/docs/2-how-crs-works/2-1-anomaly_scoring/ |
| 임계값 | inbound anomaly score threshold | same page ("inbound anomaly score threshold of 5") |
| 규칙 제외, 제외 | rule exclusion | https://coreruleset.org/docs/2-how-crs-works/2-3-false-positives-and-tuning/ ("rule exclusions") |
| 오탐 (in the CRS cards) | false positive | same page ("it is described as a false positive") |
| 감사 로그, audit 기록 | audit log | https://github.com/owasp-modsecurity/ModSecurity/wiki/Reference-Manual-(v3.x) (`SecAuditLog`) |
| 규칙 ID | rule ID | same reference (`id` action) |
| CRS 규칙 | CRS 룰 (the console's existing loanword for a rule) | — |
| 참음성(TN) | TN | the en table already says TN; no translated term |

The scoreboard's 정탐/미탐/오탐 tiles stay: they label the platform's own TP/FN/FP
counts, not a CRS term.

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
| arrow / 화살표 | expand icon / expand 아이콘 | as above |
| Kibana query / Kibana 검색어 | KQL query / KQL 쿼리 | https://www.elastic.co/guide/en/kibana/8.15/kuery-query.html |
| false positive (Korean theory) | 오탐(false positive) first, then 오탐; 놓침(미탐), 잘못 막음(오탐) | Cisco Korean documentation's 오탐 for false positive |
| 룰 | 규칙 | AWS WAF Korean developer guide (규칙, 규칙 그룹) |
| rule exclusion | rule exclusion(규칙 제외) on first mention | AWS WAF Korean developer guide |
| objective {1}개 인정 | 목표 {1}개 인정 | the console's own 목표 elsewhere |
| Open ELK / ELK에서 | Kibana | the pane is Kibana |
| 주의 요함, 개발자 도구, 소스 보기 | kept | Chromium `components_strings_ko.xtb` |
| WAF 실습 (ARCHITECTURE.ko) / 라운드 진행 (README.ko) | WAF 레슨 / 세션 진행 (README's "Running a round" → "Running a session") | the console's own words |

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
