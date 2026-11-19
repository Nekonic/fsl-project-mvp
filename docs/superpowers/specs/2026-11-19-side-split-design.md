# Side split: attack, defence, referee around a round

Status: approved at gate 1 on 2026-11-19 and being built on `side-split`. Where the build departed from this text for a reason, the text says what the code does and `docs/DECISIONS.md` (2026-11-20) says why; `docs/STATE.md` says which steps are built. The base is option `by-side` from the restructure survey, with grafts from the other six options (Appendix B lists them by source). Every skeptic finding against `by-side` is resolved (Appendix A). Every review issue of this round was checked against the repo; the ones that hold are fixed in place, and the ones that do not are listed at the end under "Review notes rejected".

User ruling: we do not keep or migrate the current code. The goal is code that stays maintainable. The current code is a reference for behaviour and for the parts that are good: the isolation seams, the scoring core, the range adapter and the cases. Everything else is written again. The build is a fresh build that carries those modules over. It is not an in-place refactor of `api/views.py`, and it keeps no compatibility with old URLs, models or migrations.

---

## 1. Goal and decided product rules

### Goal

The product is a cyber attack and defence range. Two clients drive it: human consoles and bots. Both go through **one attack API and one defence API**. Every package has one owner, and the dependency graph (imports, model FKs and migration dependencies) is enforced by a test. Game rules are pure functions that can be tested without a database or a cloud.

### Decided product rules (fixed for this build)

1. **No scenarios.** The scenario engine, triage and debrief are removed. There are two kinds of play: a **guided lesson** (steps, server-judged checks) and a **live round**. A lesson is a round of kind `lesson`.
2. **Matchups on one stack:** PvP (human attacker and human defender), human defender vs attack bot, and human attacker vs defence bot. Each one is a round with two seats on one leased `cr-slot-<n>` stack.
3. **Bots are model-agnostic.** Claude Code drives them first. A bot reaches exactly what a human console reaches, because both call the same endpoints under the same permission class, terminals included (§7, §8).
4. **Source-IP hit points (HP) stop pointless scans.** Each attack origin has a budget. Every request drains it. A request the WAF refuses, or a burst, drains it faster. A spent origin is dropped at the infra edge, and the attacker moves to the next origin. The bot is told the rule and its HP on every response, errors included.
5. **The WAF/IDS rule test** runs where the rule is written, before apply. It returns syntax errors, or a per-case TP/FN/FP/TN table. The live target, the live sensors and the round's alerts are never touched.
6. **Problems live in the database** and staff edit them on a staff page. That page is a client of the REST API.
7. **The target decides objectives** from its own stored data (board loot against the round-start snapshot; corp effects). That number stays apart from TP/FP/FN/TN, which is reported beside it and never folded in. One declared case is one decision however many alerts it draws; free actions never enter TP/FP/FN/TN (§9).
8. **Fixed technology:** OpenStack, Docker, Suricata, nginx, Elasticsearch. The ratchet is removed. Time, effort and dependency counts are not criteria.
9. **The product is Korean-only.** Every string a learner or operator sees comes from the Korean string tables (§13). The API carries stable English codes, and the front end maps them to Korean.

---

## 2. Principles and dependency rules

### Principles

- **A side is what it may touch.** Attack touches the attacker box, its origins, its terminal and the HP ledger. Defence touches the Suricata rules, the CRS posture, the WAF terminal (read-only) and alerts. Neither side decides the objective score.
- **There is one pure core, `platform/domain/`.** It holds the game rules as plain functions over frozen dataclasses: correlation, one-case-one-decision metrics, corroboration, objective attribution and tally, the HP ledger, rule-test verdicts, step-check judges, the problem validator and the round rules (end conditions, scored-start). It imports only the standard library.
- **Seam modules are Django-free.** Each one takes its settings as a frozen dataclass that `cr/config.py` builds. It imports nothing from Django and nothing from any app, and its runner is injected (`range/runner.py` `Runner`, `Launcher`, `Substrate`). No extra `Protocol` layer is added: each system has one implementation, and runner injection plus the import test already give the fakes.
- **Apps call each other through `service.py` only.** Across an app boundary only `<app>.service` may be imported; `<app>.models` only as an FK target, and only downward.
- **Services raise domain errors and never build responses.** One DRF exception handler maps the errors to status codes and to the one error shape.
- **Every UI action is a REST call first.** The front end, the bots, `test/` and the operator scripts in `bin/` that act on a round are clients of `/api/` only.
- **The event log is the feed, not the store.** Scores and step judges read rows (`Action`, `Detection`, `Objective`, `RuleTest`, `RuleSet`) through the side services. Events carry only what clients poll for.

### Layers (a module may import only from its own layer or lower)

| Layer | Modules |
|---|---|
| L0 pure | `domain/**` |
| L1 seams and libraries | `cr/config.py`, `cr/errors.py`, `ingest/elastic.py`, `rules/suricata.py`, `rules/crs.py`, `range/**` (including `range/jump.py`), `attack/box.py`, `attack/firing.py`, `attack/tools.py`, `defence/kibana.py`, `referee/loot.py`, `referee/effect.py`, `platform/testing/**` |
| L2 base apps | `accounts/models.py`, `accounts/service.py`, `accounts/signin.py`, `accounts/blocks.py`, `events/**` (except HTTP), `content/**` (except HTTP) |
| L3 round records | `match/models.py`, `match/auth.py` |
| L4 | `referee/models.py`, `referee/service.py` |
| L5 sides | `attack/models.py`, `attack/service.py`, `defence/**` (except `kibana.py` and HTTP) |
| L6 | `match/service.py`, `match/follow.py`, `match/customers.py`, `match/site.py`, `match/retention.py`, `match/probes.py` |
| L7 | `lessons/models.py`, `lessons/facts.py`, `lessons/service.py` |
| L8 HTTP | every `views*.py`, `serializers.py`, `urls.py`; `cr/urls.py`, `cr/handler.py`, `cr/settings.py`, `cr/strings.py`, `management/commands/*` |

### Import rules, enforced by `tests/seams/test_imports.py` (AST, not text)

1. `domain/**` imports only the standard library and `domain`.
2. L1 modules import no `django`, no `rest_framework` and no app.
3. `attack` and `defence` never import each other.
4. Only `referee/` imports `referee.loot` or `referee.effect`. Other apps import only `referee.service`.
5. `referee` never imports `attack`, `defence`, `lessons` or `match.service`. It receives actions and detections as `domain.types` records from its caller.
6. `lessons` imports only the `service.py` of `match`, `attack`, `defence`, `referee` and `content`. Nothing imports `lessons` except its own HTTP layer.
7. Only the L6 `match` modules and `lessons.service` import more than one side service.
8. `events` imports no other app, and its model has no FK to any other app. Every app may import `events.log`.
9. Across an app boundary, only `<app>.service` is imported; `<app>.models` only for an FK, and only to a lower layer.
10. Every `views*.py` and `serializers.py` imports only its own app's `service.py`, its own `models` (for typing), DRF, `cr.errors`, `match.auth` and `accounts.service`. It never imports an L1 seam.
11. `objective.lost` is passed to `events.log.append` only under `platform/referee/`.
12. `front/`, `bots/`, `test/` and `bin/` never import `platform/`. Reading `range/declaration.yaml` and `redteam/cases/*.yaml` as data stays allowed.
13. No test imports a name that starts with `_` from another module.
14. Every module under `platform/` is assigned to a layer; an unassigned module fails the test.
15. The same layer order holds for model graphs: every `ForeignKey`/`OneToOneField` target and every migration `dependencies` entry points to the same app or a lower layer.

---

## 3. Directory tree (file level)

```
fsl-project-mvp/
  CLAUDE.md                         ratchet removed; seam table re-pathed; Korean places and generated-code rule updated (§13)
  pyproject.toml  uv.lock           + djangorestframework, drf-spectacular, openapi-python-client (dev)
  compose.yaml                      elasticsearch, collector, kibana, platform, follow (same image, `manage.py follow`)
  openapi/
    schema.yaml                     the committed contract (the only committed generated file)
  strings/
    console.json                    Korean shown in the console (bundled into front/)
    server.json                     Korean the server renders itself (Kibana gate page); never bundled
  bin/
    cloud  platform-rebuild  acceptance  select-tests  backup  prune  build-css
    verify                          no ratchet step; runs tests/domain first; regenerates clients before tests
    gen-clients                     exports openapi/schema.yaml; generates bots/client/ and front/src/api/schema.d.ts (not committed)
    carry-users                     one-off: dumps auth.User from the old store, loads it into the new one
    record-probes                   HTTP client of POST /api/staff/wargames/<id>/probes/record/
    fetch-geoip  pick-origins  worldmap   kept: the ingest pipeline is the geoip pipeline
  platform/                         not a package; cwd for manage.py and pytest
    manage.py  pytest.ini  Dockerfile (node stage builds front/)  entrypoint.sh  nginx.conf
    vm-terminal.sh  tmux.conf
    cr/
      __init__.py  settings.py (LANGUAGE_CODE='ko', REST_FRAMEWORK, SPECTACULAR)  urls.py  wsgi.py
      errors.py                     DomainError + subclasses with their codes (Django-free)
      handler.py                    the DRF EXCEPTION_HANDLER
      strings.py                    line(key) over strings/server.json
      config.py                     builds the frozen config dataclasses each seam takes (incl. the sensor list from topology watches)
    domain/
      __init__.py
      types.py                      CaseRecord, DetectionRecord, ActionRecord, Charge, OriginState, FieldError ...
      scoring/
        __init__.py
        correlate.py                from scoring/correlate.py (marker from Action.marker)
        metrics.py                  from scoring/metrics.py (one declared case one decision)
        corroborate.py              corroborated(expect, signatures, indiscriminate)
        objectives.py               attribute, tally, DETECTED_WEIGHT; tier difficulty is the weight
      ledger.py                     HP ledger: debit(state, charges, rule) -> (state, spent)
      verdicts.py                   rule-test verdict table from correlated probe alerts
      checks.py                     CHECK_SCHEMAS, JUDGES {kind: judge(spec, answer, facts) -> Verdict}
      problems.py                   validate_problem(doc, catalog) -> [FieldError]
      round_rules.py                Matchup, Phase, ended(state) -> reason | None, may_end(state), may_start_scored(lease_state)
    ingest/
      __init__.py
      elastic.py                    SEAM: fetch_after (search_after cursor), access_events, normalize, register_pipeline
    rules/
      __init__.py
      suricata.py                   SEAM: current, checked, apply (one sensor), seed, offline_test, capture
      crs.py                        SEAM: checked, rendered, read, apply, scratch_check, scratch_test
    range/
      __init__.py                   empty
      openstack.py                  SEAM: Keystone/Heat/Neutron over REST, live wiring read, refill seed via rules.suricata.seed
      cloud_config.py               clouds.yaml identity and cloud.yaml values (was cloud.py)
      stack_plan.py                 topology.yaml devices, LANs, ports -> the Heat plan (was sandbox.py + clock.py)
      declaration.py  declaration.yaml   sites, origins, segments (was declared.py)
      networks.py                   Neutron network naming and subnet plan (was fabric.py)
      wiring.py                     parse of the live wiring
      topology.py                   learner names for the wiring, filtered by side
      pool.py                       pool phase per slot
      refill.py                     Django-free slot refill state machine over an injected store and clock (rewrite of api/reset.py)
      reachability.py               from api/reachability.py
      runner.py                     Runner, Launcher, Substrate, Ran, RangeUnavailable, Drifted (was ports.py)
      substrate.py                  substrate(config) (was range/__init__.py)
      edge.py                       SEAM (new): infra nftables `pool` and `spent` set elements and conntrack flush
      jump.py                       SEAM: platform sshd jump grants, key generation, the grants file and the box account's
                                    authorized_keys (address and account passed in); both sides import it
    accounts/
      apps.py  models.py (SignInBlock)  signin.py  blocks.py  service.py
      serializers.py  views.py  urls.py  migrations/0001_initial.py  0002_first_account.py (admin / 123456)
    events/
      apps.py  models.py (Event, no FKs)  kinds.py (schema + visible_to per kind)  log.py (append, after)
      serializers.py  views.py  urls.py  migrations/0001_initial.py
    content/
      apps.py  models.py (Wargame, Posture, Problem, Step, RoundSetup, ProbeSet)
      catalog.py                    reads wargames/<id>/wargame.yaml, topology.yaml, objectives.yaml, traffic.yaml, redteam/cases
      service.py                    published(), snapshot(problem), save_document(doc, base_revision), export(problem)
      serializers.py  views.py  urls.py  migrations/0001_initial.py
    match/
      apps.py  models.py (Lease, Round, Seat, CustomerRequest)
      auth.py                       SeatTokenAuthentication, HasSeat(side), IsOperator
      service.py                    open_lease, heartbeat, close_lease, create_round, join, start_round, end_round, forfeit, tick, score
      follow.py                     loop over open leases and rounds: refill, tick, idle expiry
      customers.py                  benign schedule and customer traffic, through attack.service
      site.py                       site pane proxy target (/site-proxy/<round>/<host>/)
      probes.py                     probe-lease recording, through the side services
      retention.py
      serializers.py  views.py  urls.py
      management/commands/follow.py  register_pipeline.py  prune.py  run_on_role.py
      migrations/0001_initial.py
    referee/
      apps.py  models.py (Objective)
      loot.py                       SEAM: board ground truth (urllib HTTP to the target's read path)
      effect.py                     SEAM: corp ground truth
      service.py                    take_baseline, submit_loot, observe_effects, objectives, redact, score(round, actions, detections)
      migrations/0001_initial.py
    attack/
      apps.py  models.py (Action, ToolRun, OriginBudget, AccessCursor)
      box.py                        SEAM: attacker box (origins, set-origin, command log, tool image, customer origins, stop runs, kali address)
      firing.py                     load_cases, build_request, fire, fire_http, fire_tool (was redteam/harness.py; launch injected)
      tools.py                      tool argv per case and per free tool (was redteam/tools.py)
      service.py                    state, send, catalog, start_tool, tool_output, stop_tool, fire_case, fire_benign, submit_loot,
                                    next_origin, charge, terminal, customer_origins, send_as_customer
      serializers.py  views.py  urls.py  migrations/0001_initial.py
    defence/
      apps.py  models.py (Detection, RuleSet, RuleTest, DisabledRule, AlertCursor)
      kibana.py                     SEAM: Kibana API, space_of, refusal, presets
      disable.py                    temporary rule disable, unread check
      alerts.py                     ingest with AlertCursor through ingest/elastic.fetch_after
      ruletest.py                   check -> probe set -> offline run -> domain.verdicts
      drift.py                      compares the live CRS files with the head RuleSet
      service.py  serializers.py  views.py  views_kibana.py  urls.py  migrations/0001_initial.py
    lessons/
      apps.py  models.py (StepResult, Progress)
      facts.py                      gathers the rows a check kind needs through side services
      service.py  serializers.py  views.py  urls.py  migrations/0001_initial.py
    testing/
      fakecloud.py  standin.py  fakes.py (fake runners, fake ES)  factories.py (English placeholder problems)
      fakerange.py                  fake substrates: the defence range, the attack range, a slot and a cloud of slots
    tests/
      domain/   conftest.py (no Django)  test_correlate.py test_metrics.py test_corroborate.py
                test_objectives.py test_ledger.py test_verdicts.py test_checks.py test_problems.py test_round_rules.py
      seams/    test_imports.py test_isolation_seams.py test_no_hangul.py test_no_comments.py test_elastic.py
                test_suricata.py test_crs.py test_edge.py test_box.py test_jump.py test_openstack.py test_wiring.py
                test_loot.py test_effect.py
      accounts/ events/ content/ match/ lessons/ attack/ defence/ referee/
      contract/ test_schema_fresh.py test_schema_complete.py test_error_shape.py test_error_codes.py
                test_no_admin.py test_backup_tables.py test_opposite_seat.py
      conftest.py
  front/                            typed console
    package.json  package-lock.json  vite.config.ts  tsconfig.json  vitest.config.ts  index.html
    src/
      main.tsx  router.tsx
      api/ schema.d.ts (generated at build, not committed)  client.ts  follow.ts
      t.ts                          reads strings/console.json
      panes/ Kibana.tsx Terminal.tsx Site.tsx Map.tsx IdsRules.tsx Waf.tsx Alerts.tsx
             Objectives.tsx Hp.tsx Score.tsx RuleTestTable.tsx StepCard.tsx
      pages/ Login.tsx Signup.tsx Home.tsx Lesson.tsx RoundAttack.tsx RoundDefence.tsx RoundLobby.tsx
             Result.tsx staff/Problems.tsx staff/Postures.tsx staff/Users.tsx staff/Range.tsx
      test/ *.test.ts(x)
  bots/
    README.md                       rules of play, HP rule, error codes (English)
    cli.py                          `python -m bots.cli <operation> --json '{...}'`, plus `tools`, `prompt`, `call` and `run`
    tools.py                        tagged operations of the committed schema -> JSON Schema tool specs per side
    calls.py                        one tool call through the generated client with the seat token
    play.py  provider.py            the turn loop and the provider interface `turn(system, tools, transcript)`
    signin.py                       signed-in and seated clients, shared with `test/` and `bin/`
    prompts/ attacker.md defender.md claude_code.md
    client/                         generated from openapi/schema.yaml (not committed)
  redteam/
    cases/board.yaml  cases/corp.yaml   attack and benign cases (data only)
  wargames/<board|corp>/
    app/  compose.yaml  topology.yaml  objectives.yaml  traffic.yaml (optional customer profile)
    wargame.yaml                    id, title, image, public_url, hosts, objective_model, case_file, default_traffic
    probes/manifest.json (image digest, markers)  probes/<case>.request.json  probes/<case>.response.json  probes/<case>.pcap
  deploy/
    roles/infra/edge.nft            + sets `pool` and `spent`; `@spent` dropped before the established accept (§11)
    roles/infra/slot-boot           unchanged loader; edge.py refills the sets after it
    roles/infra/log-relay.conf      relays the WAF's `nginx-access` lines (replaces `nginx`)
    roles/infra/install.sh          + conntrack, tcpdump, /var/lib/cr-ruletest
    roles/waf/board.com.conf        both vhosts (board.com, corp.com); one `$refused` map (400, 403); JSON access log of every request
    roles/waf/log-shipper.conf      ships /var/log/nginx/access.json under Tag "nginx-access" (replaces refused.log)
    roles/waf/probe.conf            scratch nginx+ModSecurity template for the CRS test
    roles/waf/probe-upstream.py     loopback stub serving each probe's recorded response
    roles/waf/analyst.sh            read-only shell account for the defence terminal
    roles/kali/stamp.py             a link to deploy/proxy/stamp.py, the one copy of the proxy
    roles/kali/  roles/target/  openstack/  suricata/ (local.rules only)
    filebeat/filebeat.yml           + route appname nginx-access -> module nginx_access
    elastic/ingest-pipeline.json    + nginx_access branch
    traffic/  kibana/
  test/                             live acceptance; HTTP clients of the generated client only
  docs/  ARCHITECTURE.md DECISIONS.md STATE.md OPENSTACK.md TROUBLESHOOTING.md THREAT-MODEL.md
         vocabulary.md state/now.md superpowers/specs/
```

`platform/scoring/`, `platform/scoreboard.py`, `platform/lesson.py`, `platform/api/`, `platform/console/`, `platform/wargames.py`, `platform/lifecycle.py`, `platform/register_pipeline.py`, `platform/operator_log.py`, `redteam/*.py` and `deploy/proxy/stamp.py` no longer exist (§15).

---

## 4. Module ownership

| Path | Owns | May import |
|---|---|---|
| `domain/` | All game rules as pure functions | stdlib |
| `cr/config.py` | Frozen config dataclasses for every seam, the sensor list from topology watches | stdlib, `yaml` |
| `cr/errors.py` | Error classes and their codes | stdlib |
| `ingest/elastic.py` | Elasticsearch: reads, normalisation, the ingest pipeline | `requests`, `domain.types` |
| `rules/suricata.py` | The Suricata process on one sensor: rule file, `-T`, offline `-r` run in the pinned image, reload, packet capture | runner |
| `rules/crs.py` | CRS/ModSecurity config, the nginx reload, the scratch test instance | runner |
| `range/openstack.py` | The OpenStack API, live wiring read, the baseline rule seed on refill | `requests`, `rules.suricata.seed` |
| `range/edge.py` | Infra nftables set elements `pool` and `spent`, conntrack flush per address | runner |
| `range/cloud_config.py` | clouds.yaml sign-in and `deploy/openstack/cloud.yaml` values | `yaml` |
| `range/stack_plan.py` | The Heat plan rendered from `topology.yaml` | `yaml` |
| `range/declaration.py` | Sites, origins and segments from `declaration.yaml` | `yaml` |
| `range/networks.py` | Neutron network names, tags and subnets per slot | stdlib |
| `range/wiring.py`, `range/topology.py` | Live wiring parse; learner names, filtered by side | stdlib |
| `range/pool.py`, `range/refill.py` | Slot phase; the refill state machine (store and clock injected) | stdlib |
| `range/reachability.py`, `range/substrate.py`, `range/runner.py` | Reachability probe; substrate choice; runner contracts | stdlib |
| `attack/box.py` | The attacker box: origins, `set-origin`, command log, tool image, customer origins, stopping runs, the kali address | runner |
| `range/jump.py` | The platform sshd's jump grants and keys, and the per-seat key in the box account's `authorized_keys` (box address, runner and account passed in) | stdlib, runner |
| `attack/firing.py`, `attack/tools.py` | Building and firing cases with the `X-Request-ID` marker; tool argv | `requests`, `yaml` |
| `defence/kibana.py` | The Kibana API, every Kibana route and space rule | `urllib` |
| `referee/loot.py`, `referee/effect.py` | The target's ground truth | `urllib` |
| `accounts` | Users, approval, sign-in, sign-in blocks | Django, DRF |
| `events` | The append-only typed log per round, the cursor feed | Django |
| `content` | Wargame catalog, postures, problems, steps, round setups, probe sets, staff API | `domain.problems`, `rules.crs.checked`, `attack.firing.load_cases` |
| `match` | Lease, Round, Seat (with its token), auth classes, lifecycle, tick, customers, site pane, probe recording, the one score | every service |
| `referee` | Objectives, baseline, loot, effects, attribution, redaction of the secret | `domain.scoring`, its seams, `events` |
| `attack` | The one attack API: actions, tool runs, HP, origins, terminal, customer sends | `domain.ledger`, `attack/*` seams, `range.edge`, `range.jump`, `ingest`, `referee.service`, `match.models` |
| `defence` | The one defence API: rules, posture, tests, apply, disable, drift, alerts, traffic, terminal, Kibana | `rules/*`, `range.jump`, `ingest`, `domain.verdicts`, `referee.service`, `match.models` |
| `lessons` | Step results, judging, progress | `domain.checks`, side services, `match.service`, `content.service` |
| `strings/` | The two Korean tables | data |
| `front/` | Pages and panes | HTTP `/api/` only, `strings/console.json` |
| `bots/` | CLI, tool specs, prompts | HTTP `/api/` only |

There is one score function: `match.service.score(round)` gathers the records from the sides and calls `referee.service.score(...)`. The score endpoint calls only the match one.

---

## 5. Isolation seams (each with a single owner)

| Knows | Sole owner (new path) | Change |
|---|---|---|
| Elasticsearch | `ingest/elastic.py` | + `fetch_after` with a `search_after` cursor, + `access_events` (reads only module `nginx_access`), + `register_pipeline()` folded in (removes the `register_pipeline.py` exception) |
| Suricata process | `rules/suricata.py` | + `checked()` returns `[{line, message}]` (`RULE_ERROR` moves here), + `offline_test`, + `capture`. Each call takes one sensor; the fan-out over sensors is `defence.service` (§8) |
| CRS/ModSecurity config and nginx reload | `rules/crs.py` | + `scratch_check`, + `scratch_test` (§8) |
| OpenStack API and live wiring | `range/openstack.py` (parse: `range/wiring.py`, names: `range/topology.py`) | config injected; `substrate()` moves to `range/substrate.py`; calls `rules.suricata.seed` with the baseline file on refill (recorded dependency, see below) |
| Infra edge set elements | `range/edge.py` (new) | `pool` and `spent` sets, conntrack flush. `slot-boot` stays the only loader of the table; `edge.py` adds, lists and refills elements, and at round start empties both sets and adds the round's addresses in one load (`restart`) |
| Kibana API | `defence/kibana.py` | holds `space_of`, `refusal` and every Kibana path literal; `defence/views_kibana.py` only calls them |
| Attacker box | `attack/box.py` | absorbs the command log reader, the tool image name and the kali address (removes two exceptions); `match/customers.py` sends only through `attack.service` |
| Platform jump host | `range/jump.py` | holds the grants file, key generation and the box account's `authorized_keys`; the box address is an argument (kali from `box.py` for the attack seat, cr-waf's management address for the defence seat's `analyst`). It sits under `range/` so both sides import it without importing each other (rule 3) |
| Target ground truth | `referee/loot.py` (board), `referee/effect.py` (corp) | moved; `referee.service.redact` is the only thing that strips the secret from probe recordings |

**Refill seed and posture.** A refilled slot gets `deploy/suricata/rules/local.rules` through `openstack.py` → `rules.suricata.seed`, so a slot never runs with an unknown rule file. Round start then applies the problem's Posture through `defence.service.apply_ids` over every sensor. The refill seed owns the slot's starting file; the posture owns the round's.

**Known exceptions that remain** (listed in CLAUDE.md and ARCHITECTURE):

- `wargames/<id>/topology.yaml`: the `cr-ids` device names the rule file and reload command, and the `cr-waf` device names the exclusion file and the nginx reload.
- `platform/nginx.conf`: the Kibana routes it refuses, the handoff to `defence/views_kibana.py`, and the `api/spaces/space` answer.
- `front/src/panes/Kibana.tsx`: the Kibana localStorage preset (once `front/` exists).
- `entrypoint.sh`: `vm-terminal.sh cr-kali attack` and `vm-terminal.sh cr-waf defence`, and the jump host's empty `authorized_keys`.
- `deploy/roles/infra/edge.nft`: declares the `pool` and `spent` sets that `range/edge.py` fills.
- `cr/config.py`: the defaults the seams are handed (the CRS exclusion file and the nginx reload, the box's label file, the node names, the log index pattern).
- `test/test_event_time.py`, `test/test_geoip_durable.py`, `test/test_origin_placement.py`, `test/test_waf_geolocation.py`: acceptance checks of Elasticsearch's own set-up (pipeline, node settings, index) that query it directly; moving them behind `/api/` is open.

**Exceptions that go away:** `register_pipeline.py`, `operator_log.py`, `redteam/tools.py` naming `cr-kali` (the box passes `launch` to `attack/firing.py`), and F6's step commands (deleted with the lesson content).

`tests/seams/test_isolation_seams.py` keeps one pattern per seam and adds patterns for infra nftables, packet capture, `authorized_keys` and `cr-session-`. `console/static` is gone, and the scan covers `platform/`, `front/src`, `bots/`, `test/` and `bin/`. It also looks for `cr-kali`, `cr-waf`, `cr-infra`, `cr-target`, index patterns and `/kibana/api|internal`. Its exemptions are a closed map from each file to the seams it may know: the files of the known exceptions above that the scan reaches (`bin/cloud`, `bin/platform-rebuild`, `test/range.py` and `test/test_range_isolation.py` match no pattern, so they are not in it). The test asserts that every listed file exists (or is named as not written yet), that each still knows exactly what it may, and that the list equals the one in CLAUDE.md's "Known exceptions" paragraph, so it cannot grow silently. It also reads `.md` and `.json`, so the bots' prompts are held to the same seams.

---

## 6. Data model per app

All migrations start fresh with `0001_initial`; `accounts.0002_first_account` makes the staff account `admin` / `123456` when none exists (the 2026-11-15 ruling). Users carry over with `bin/carry-users` (`dumpdata auth.User` from the old store, `loaddata` into the new one without primary keys; an old `admin` replaces the migrated one). Nothing else carries over. `bin/backup` stays a snapshot tool (`VACUUM INTO`, integrity check, row counts) with TABLES re-pointed to the new tables.

**accounts**
- Django `User` (approval via `is_active`, staff via `is_staff`).
- `SignInBlock(kind, value, username, reason, failures, created, until)`.

**events**
- `Event(id = cursor, round_id BigInteger, kind, seat_side null, at, body JSON)`, indexed `(round_id, id)`. No FK, so `events` is a leaf.
- `kinds.py`: `{kind: (schema, visible_to)}`:

| Kind | visible_to |
|---|---|
| `round.started`, `round.ended`, `seat.joined` | both |
| `action.sent`, `tool.started`, `tool.ended` (with `stopped_by`), `command.run`, `origin.charged` (aggregated per origin per tick), `origin.spent`, `origin.switched`, `origins.spent` | attack, staff |
| `alert.seen`, `rule.tested`, `rule.applied`, `rule.disabled`, `rule.drifted` | defence, staff |
| `objective.lost` | both (body: key and name only; attribution only to staff) |
| `step.answered`, `step.passed` | the lesson's seats, staff |

In a lesson round the one user holds every seat, so they see both sets.

**content**
- `Wargame(id, title, image, public_url, hosts, objective_model, case_file, default_traffic)`. `catalog.py` syncs it from `wargame.yaml`; read-only in the API. The scenario-level `difficulty`, `minutes` and `category` fields are dropped. Objective tiers in `objectives.yaml` keep their `difficulty` and `category`; tier difficulty is the weight `domain.scoring.objectives.tally` reads.
- `Posture(id, wargame FK, name, suricata_rules text, crs_tuning JSON)`. `crs_tuning` is validated by `rules.crs.checked`. Suricata syntax is checked when the posture is applied at round start, because `suricata -T` needs a sensor.
- `Problem(id, kind: lesson|round, wargame FK, side: attack|defence|both, title, summary, body, published, revision int, author, updated, start_posture FK null)`.
- `Step(problem FK, order, body, opens: pane enum, check JSON {kind, params}, answer JSON (withheld), hints list)`. Pane enum: `kibana, terminal_kali, terminal_waf, site, map, ids_rules, waf, alerts, none`.
- `RoundSetup(problem 1:1, matchups [pvp|def_vs_bot|atk_vs_bot], posture FK, probe_cases [case id], objectives [key], hp {budget, per_request, refused_x, burst_per_s, burst_x}, traffic profile (defaults to the wargame's), benign_every_s, time_limit_s or null)`.
- `ProbeSet(wargame FK, image_digest, recorded_at, cases JSON)`: the record of the committed `probes/manifest.json`.

**match**
- `Lease(id, wargame FK, purpose: round|lesson|probe, slot, opened_by FK, opened, expires_at, closed, browse_marker)`.
- `Round(id, lease FK, problem FK, kind: lesson|round, matchup, phase: created|starting|running|ended, snapshot JSON (content frozen at start, with problem revision), baseline JSON, read_of JSON, started, ends_at, ended, end_reason)`.
- `Seat(id, round FK, side: attack|defence, client: human|bot, user FK null, bot_name, token_hash null, token_revoked_at null)`, unique `(round, side)`. The token belongs to the seat; `rest_framework.authtoken` is not installed.
- `CustomerRequest(round FK, marker, action, user, origin, source_ip, method, path, status, refused_by, sent_at, elapsed_ms, benign_case null)`. Kept, because benign FP/TN needs it.

**referee**
- `Objective(round FK, key, name, achieved_at, earliest, latest, attributed_marker null, seen bool)`. The attribution is the marker string `correlate` already matches on; no FK to `attack`.

**attack**
- `Action(id, round FK, seat FK, kind: request|tool|command|case|site, case_id null, malicious null, expect null, marker, correlation: marker|window, source_ip, started, ended, meta JSON)`. A declared case has `kind=case`, `marker = case_id`, and `malicious`/`expect` from `redteam/cases`. A free action (`request`, `tool`, `command`, `site`) has `malicious = null`: the platform never decides its truth.
- `ToolRun(id, action 1:1, tool, argv, started, ended, exit_code, stopped_by: null|seat|origin_spent|round_end, output_path)`.
- `OriginBudget(round FK, origin_id, ip, label, budget, left, spent_at null)`.
- `AccessCursor(lease 1:1, cursor JSON)`.

**defence**
- `Detection(round FK, detection_id, engine, rule, signature, severity, timestamp, src_ip, marker, uri, blocked, raw JSON)`.
- `RuleSet(round FK, engine: ids|waf, version int, body, applied_at, tested FK RuleTest null, same_as_tested bool, sensors JSON)`.
- `RuleTest(id, round FK, seat FK, engine, body_sha, body, syntax_ok, result JSON, created)`.
- `DisabledRule(round FK, sid, original, reason, created, expires_at, enabled_at)`.
- `AlertCursor(lease 1:1, cursor JSON)`.

**lessons**
- `StepResult(round FK, step_order, verdict, given JSON, at)`.
- `Progress(user FK, problem FK, passed_order, passed_at)`, unique `(user, problem)`. It keeps the learner's place across rounds and lease closes; attempt counts are derived from `StepResult`. There is no separate Attempt: a lesson is a Round of kind `lesson` with its Seats.

---

## 7. Attack API

Base: `/api/rounds/<round>/attack/`. Auth is the session cookie (human console) or `Authorization: Bearer <seat token>` (bot). Permission is `HasSeat('attack')`, which resolves `request.seat`. Writes before `phase=running` return `409 round_not_started`; after the end, `409 round_closed`. Schema tag: `attack`.

Every response, success or error, carries an `hp` block and the headers `X-Origin` and `X-Origin-HP`:

```
hp: {origin: {id, label, ip}, left, budget,
     origins_left, spent: [ip],
     rule: {budget, per_request, refused_x, burst_per_s, burst_x, refused_statuses: [400, 403]}}
```

| Method and path | Request | Response | Notes |
|---|---|---|---|
| `GET state/` | none | `{round, matchup, phase, started, ends_at, end_reason, brief:{title, summary, body}, target:{public_url, hosts}, objectives:[{key, name, state: kept\|lost}], origins:[{id, label, ip, left, budget, spent_at}], hp}` | `objectives` from `referee.service.objectives` |
| `GET cases/` | none | `[{case, kind: http\|tool, malicious, title}]` | declared attack cases; no `expect` |
| `POST requests/` | `{method, path, host?, query?, headers?, body?}` | `{action, status, headers, body, truncated, hp}` | `attack.service` sets `X-Request-ID` to the action's own marker and sends from the box through the current origin; it does not rely on the proxy's label file. Charged on the spot (§11) |
| `POST cases/` | `{case}` | `202 {action, run?, hp}` | Fires a declared case through `attack/firing.py`. A tool case becomes a ToolRun |
| `GET tools/` | none | `{tools:[{tool, args_schema}], runs:[{run, tool, started, ended, exit_code, stopped_by}]}` | discovery and reconnect |
| `POST tools/` | `{tool, args:[str]}` | `202 {run, action, hp}` | Tool names from `attack/tools.py`. Asynchronous |
| `GET tools/<run>/?after=<offset>` | none | `{output, offset, done, exit_code, stopped_by, hp}` | |
| `DELETE tools/<run>/` | none | `204` | Stops the run on the box (`stopped_by: seat`) |
| `POST loot/` | `{value}` | `{lost: bool, objective?: {key, name}, hp}` | `referee.service.submit_loot`. Never reveals the secret |
| `POST origins/next/` | none | `{origin, hp}` | Gives up the current origin early (marked spent) |
| `GET terminal/` | none | `{ws_url, ssh:{host, port, user, private_key, expires_at}}` | `ws_url` is the seat's ttyd path to kali (`/vm-terminal/attack/<round>/`), which opens only while the round runs and the seat holds its grant; `ssh` is that jump grant from `range/jump.py`. The grant is revoked when the round ends, and an open shell closes with it |
| `POST forfeit/` | none | `{ended, reason: forfeit_attack}` | |

The events feed, topology and score are round routes (§9).

**Markers.** API sends and declared cases carry a marker the platform set. The proxy `deploy/roles/kali/stamp.py` stamps only requests that carry no `X-Request-ID`, from the box's label file; that file now marks window-correlated terminal and tool traffic only. A root learner can forge `X-Request-ID` on terminal traffic (§17 risk 7).

**Command log.** `box.commands` reads the bash `PROMPT_COMMAND` log, so it covers interactive shells only and a sudo learner can rewrite it. It feeds `command.run` events and the `kali` lesson check. It is never evidence for the score, and HP for shell traffic comes only from the WAF access log (§11).

**Errors** (shape §9): `401 not_signed_in`, `403 not_seated`, `400 invalid` (field errors), `404 unknown_case|unknown_tool|unknown_run`, `409 round_not_started|round_closed`, `409 origins_spent` (once `origins_left == 0`, every write refuses), `503 attacker_unavailable|range_unavailable`.

---

## 8. Defence API and the rule test

Base: `/api/rounds/<round>/defence/`. Permission `HasSeat('defence')`, the same phase rules as §7. Tag `defence`. The two engines are separate resources. Suricata takes rule text (`IdsCandidate{text}`). CRS takes a structured posture (`WafPosture{paranoia, exclusions, thresholds, detection_only}`, validated by `rules.crs.checked`). WAF free text is never accepted: it would let a seat write `SecRuleEngine Off`.

| Method and path | Request | Response |
|---|---|---|
| `GET state/` | none | `{round, matchup, phase, started, ends_at, end_reason, brief, target:{public_url, hosts}, objectives:[{key, name, state, seen}], ids:{version}, waf:{version}, alerts_total}` |
| `GET alerts/?after=<id>&engine=&rule=&src=` | none | `{alerts:[{id, time, engine, rule, signature, src_ip, request_id, uri, blocked}], next}`. Structured filters only, no KQL. Cursor = Detection id |
| `GET traffic/?after=<id>` | none | `{by_origin:[{ip, requests, refused, last_at}], next}` from `ingest.elastic.access_events` |
| `GET probes/` | none | `[{case, malicious, recorded, tool_case}]` the round's probe set |
| `GET ids/rules/` | none | `{text, version}` |
| `GET ids/rules/versions/`, `GET waf/versions/` | none | `[{version, applied_at, tested, same_as_tested}]` |
| `POST ids/rules/check/` | `{text}` | `{ok, errors:[{path:"text", code:"suricata_syntax"\|"unread_sid", line, message}]}` (every sensor, then `disable.unread`) |
| `POST ids/rules/test/` | `{text, cases?:[id]}` | RuleTestResult |
| `GET ids/rules/tests/<test>/`, `GET waf/tests/<test>/` | none | RuleTestResult |
| `POST ids/rules/apply/` | `{text, base_version, tested?}` | `{version, applied_at, same_as_tested, sensors:[{name, ok}]}` |
| `GET ids/disabled/` | none | `[{sid, original, reason, expires_at}]` |
| `POST ids/disabled/` | `{sid, minutes, reason?}` | `{sid, expires_at}` |
| `DELETE ids/disabled/<sid>/` | none | `204` |
| `GET waf/` | none | `{posture, version}` |
| `POST waf/check/` | `{posture}` | `{ok, errors:[{path:"exclusions[2].target", code:"crs_refused", message}]}` |
| `POST waf/test/` | `{posture, cases?}` | RuleTestResult |
| `POST waf/apply/` | `{posture, base_version, tested?}` | `{version, applied_at, same_as_tested}` |
| `GET terminal/` | none | `{ws_url, ssh:{host, port, user, private_key, expires_at, target_host, target_user}}` to cr-waf as the read-only `analyst` account; the jump grant from `range/jump.py`, revoked when the round ends |
| `GET kibana/` | none | `{space_url}` (human seats; bots use `alerts/` and `traffic/`) |
| `POST forfeit/` | none | `{ended, reason: forfeit_defence}` |

**RuleTestResult:**

```
{test, ok, errors:[...],
 cases:[{case, malicious, verdict: tp|fn|fp|tn, corroborated: bool|null,
         alerts:[{rule, signature}], recorded_run: bool}],
 totals:{tp, fn, fp, tn},
 untested:[{case, reason: tool_case|not_recorded}],
 against_applied:[{case, was, now}]}
```

The verdict codes are machine fields. The front end shows them only through Korean keys in `strings/console.json`.

**One test at a time.** A test is synchronous and holds a per-lease, per-engine lock; a second one returns `409 test_busy`. Each run uses its own scratch prefix and port named by the RuleTest id.

**Apply.**
- The version check and the write happen under one `select_for_update` on the head RuleSet. If `base_version` is not current, the call returns `409 {code: stale_version, current_version}` and writes nothing.
- Apply does not require a test. A test is feedback, not a gate: a slot with no recordings, or an urgent fix, must still apply. When `tested` is given, it must name a RuleTest of this seat and engine, and the RuleSet records `same_as_tested = (sha(body) == test.body_sha)`. A lesson can require test-then-apply through the `rule_applied` check (§10).
- IDS: `defence.service.apply_ids` calls `rules.suricata.apply` on each sensor from `cr/config.py`'s sensor list in order. If one refuses, it re-seeds the sensors already written with the previous head and returns `422 apply_refused` with `sensors:[{name, ok}]`. `disable.unread` refuses rule text that disables a sid the platform can no longer read.
- WAF: `rules.crs.apply` (write, `nginx -t && reload`, worker check, rollback).
- **WAF shell.** The defence terminal logs in as `analyst`, which can read the nginx and CRS config and logs but not write them. When the round ends and a defence grant is revoked, `range.jump.end_account` clears `analyst`'s crontab and `at` jobs, disables its linger and ends its logind sessions (and so its `systemd --user` manager), and kills its processes until none is left, so nothing it started (`nohup`, cron, `at`, a user unit) outlives the round. `defence/drift.py` compares the live CRS files' hash with the head RuleSet on each tick and appends `rule.drifted` if they differ; the score then carries `posture_drift: true`.

**Errors:** `400 invalid`, `422 suricata_syntax|crs_refused|apply_refused|unread_sid`, `409 stale_version|test_busy|round_not_started|round_closed`, `503 sensor_unavailable|waf_unavailable|elastic_unavailable`.

### The rule-test flow, step by step

1. **Call.** The editor's Test button and a bot send the same `POST …/test/`.
2. **Syntax.**
   - IDS: `rules.suricata.checked(text, sensor)` on every sensor runs `suricata -T -S` on a scratch copy and parses the output into `[{line, message}]` (line mapping unverified, §17).
   - WAF: `rules.crs.checked(posture)` turns `TuningRefused` into field errors. Then `rules.crs.scratch_check` writes `rendered()` into a scratch prefix and runs `nginx -t -c <scratch>/nginx.conf`. The live exclusion file is never written. This is new code.
   - On any error the call returns `ok: false` with the errors, and stops.
3. **Probe set.** The snapshot's `probe_cases`, plus every benign HTTP case in `redteam/cases/<wargame>.yaml`. Staff cannot remove the benign cases, so a block-everything rule shows its FPs here.
4. **Run against recordings, never the live range.**
   - **IDS:** `rules.suricata.offline_test(text, sensor, pcaps)` runs on the topology's sensor device (`cr-ids`, the `sensor` container's node): `docker run --rm` of the same pinned `jasonish/suricata` image with the same `suricata.yaml`, `-r <case>.pcap -S <candidate> -l <scratch>`, where the scratch volume is outside `/var/log/suricata` (whose `eve.json` rsyslog ships). It reads the scratch `eve.json` directly, so nothing lands in the alert index. The live sensor is a passive af-packet listener on `br0` and is not touched.
   - **WAF:** `rules.crs.scratch_test(posture, gateway, probes)` starts a separate nginx master on cr-waf with its own `-p` prefix and pid, listening on `127.0.0.1:<scratch port>`, with a copied CRS tree carrying the candidate exclusions and its own `SecAuditLog` under the scratch prefix, which `log-shipper.conf` does not read. Its upstream is `probe-upstream.py` on loopback, which answers each probe with its recorded (redacted) response, looked up by `X-Request-ID`. `crs.py` pipes each recorded request through `curl` to `127.0.0.1` on cr-waf, reads the scratch audit log and the status, then stops the master and removes the prefix. It never reloads the live master.
   - The attacker-side firing path (`attack/firing.py` through `launch` on cr-kali) is untouched.
5. **Verdict.** `domain.verdicts.table(probes, alerts)` uses `domain.scoring.correlate` (by marker), `metrics` (one decision per case) and `corroborate` (each case's `expect`, with `indiscriminate`). `against_applied` compares with the stored result of the applied version's test, when one exists.
6. **Store.** A `RuleTest` row (sha, body, result), and a `rule.tested` event (defence and staff only).
7. **Preview, not score.** Live alerts still go through ingest, and the round's per-case score is computed from them at the end.

### How probes are recorded and never make a round's target lose objectives

- No probe is ever sent to a round's target. The WAF test ends at a loopback stub, and the IDS test reads files.
- **Recording** is a staff REST operation: `POST /api/staff/wargames/<id>/probes/record/` → `202 {lease}`, then `GET /api/staff/probes/<lease>/` for progress. `match/probes.py` opens a `Lease(purpose=probe)` (no round, no seats), and through the side services only: applies CRS `{detection_only: true}`, fires every case through `attack/firing.py` from cr-kali, captures on the cr-ids interface through `rules.suricata.capture`, records each HTTP request and the target's response, passes every response through `referee.service.redact` (the secret's values replaced with same-length placeholders), and writes `wargames/<id>/probes/` with a `manifest.json` holding the markers and the target image digest. `bin/record-probes` is a thin HTTP client of that route. Corp's destructive cases change only the probe lease's target, whose stack is deleted and rebuilt on release.
- A test fails when `manifest.json`'s image digest differs from `wargame.yaml`'s image, so a stale recording is caught by tests. A case missing from the manifest is reported `untested: not_recorded`, never FN.
- An acceptance test proves that a rule test leaves the round's ground truth (`referee.service.objectives`) and the round's Detection count unchanged.

### sqlmap-type (tool) cases

- **IDS:** the tool run's recorded pcap is replayed with `-r`, and the case carries `recorded_run: true` (fidelity unverified, §17).
- **WAF:** tool cases are listed as `untested: tool_case`. Blocking changes what sqlmap sends next, so a fixed replay cannot stand for the adaptive run.
- In the live round a tool case is one Action, so it is one decision however many requests and alerts it draws (`board-sqli-orderby-sqlmap` sends about 2,000 requests).

---

## 9. Match, lessons and the events feed

### Accounts (tag `accounts`)

| Method and path | Request | Response |
|---|---|---|
| `GET /api/auth/csrf/` | none | sets the CSRF cookie, `{ok}` |
| `POST /api/auth/login/` | `{username, password}` | `{user}`; rate-limited by nginx's exact-match location |
| `POST /api/auth/signup/` | `{username, password}` | `201 {user, approved:false}`; rate-limited |
| `POST /api/auth/logout/` | none | `204` |
| `GET /api/me/` | none | `{user, is_staff, approved, seats:[{round, side, phase}], lessons:[{round, problem, phase}]}` |
| `GET /api/staff/users/`, `POST /api/staff/users/<id>/approve/`, `POST …/disable/` | | staff |
| `GET /api/staff/blocks/`, `DELETE /api/staff/blocks/<id>/` | | staff |

Session requests need CSRF; Bearer seat-token requests are CSRF-exempt. `match.auth.SeatTokenAuthentication` states this.

### Lease and rounds (tag `match`)

Who may act: the **operator** is `Lease.opened_by` or a staff user (`IsOperator`). Seats never open or close a lease and never end a round except by `forfeit`.

| Method and path | Who | Request | Response |
|---|---|---|---|
| `POST /api/leases/` | approved user | `{wargame}` | `201 {lease, slot, ready, expires_at}`; empty pool → `503 range_unavailable {retry_after}` |
| `GET /api/leases/<lease>/` | operator | none | `{lease, slot, ready, expires_at, rounds:[...]}` |
| `POST /api/leases/<lease>/heartbeat/` | operator, seats | none | `{expires_at}` |
| `POST /api/leases/<lease>/close/` | operator | none | `{closed}`; the slot is deleted and rebuilt |
| `POST /api/leases/<lease>/rounds/` | operator | `{problem, matchup, seats:{attack:{user}\|{bot:{name}}\|{open:true}, defence:{...}}}` | `201 {round, seats:[{side, client, user}], bot_tokens?:{side: token}}` (shown once) |
| `GET /api/rounds/?mine=1&state=open\|joinable` | user | none | `[{round, problem, matchup, seats:[{side, client, user}], phase}]` |
| `POST /api/rounds/<round>/seats/<side>/join/` | approved user | none | `{seat}`; appends `seat.joined`. `409 already_seated` if the user holds the other side of a non-lesson round, `409 seat_taken` |
| `POST /api/rounds/<round>/start/` | operator | none | `{phase}`. Freezes the snapshot, applies the posture (`defence.service`), takes the baseline (`referee.service`), fills `@pool` (`attack.service`), creates the Kibana space, starts customers and the benign schedule |
| `POST /api/rounds/<round>/end/` | operator | none | `{ended, reason: ended_by_operator}` |
| `GET /api/rounds/<round>/` | operator, seats | none | `{round, problem, matchup, phase, seats, started, ends_at, ended, end_reason}` |
| `GET /api/rounds/<round>/score/?correlation=marker\|window` | seats after `phase=ended`; operator and staff any time (`correlation` staff only) | none | see below; a seat mid-round gets `409 round_running` |
| `GET /api/rounds/<round>/events/?after=<cursor>` | seats, operator | none | `{events:[{id, kind, at, seat_side, body}], next}` filtered by the caller's side and each kind's `visible_to`. Short poll (waitress has 16 threads) |
| `GET /api/rounds/<round>/topology/` | seats, operator | none | the learner map from `range.topology`, filtered by side |
| `GET /api/rounds/<round>/site/requests/?after=` | seats | none | the site pane's request/response list |
| `GET /api/staff/range/` | staff | none | readiness and slot states |
| `POST\|DELETE /api/staff/range/fabric/`, `DELETE /api/staff/range/leftovers/`, `GET\|POST\|DELETE /api/staff/range/pool/` | staff | none | what `bin/cloud up` and `down` drive: the shared Neutron fabric, what an earlier range left, and the pool (`POST` owes every unheld slot a refill the follower builds and configures; `DELETE` drops owed refills and deletes every slot stack; `GET` lists each slot stack's servers). `409 range_not_cloud` on a range not built through OpenStack |

**Score:**

```
{objectives:{lost:[{key, name, seen, attributed_marker}], kept:[...], weighted},
 outcomes:{per_case:[{case, verdict, alerts, corroborated}], totals, note:"one_case_one_decision"},
 free_actions:{by_origin:[{ip, actions, alerts, refused}]},
 posture_drift}
```

`per_case` holds only declared cases (`Action.kind=case`) and the platform-fired benign cases. Free actions are reported in `free_actions` and never touch TP/FP/FN/TN; a domain test proves that N free requests leave `totals` unchanged.

**Seat token scope.** A seat token reaches its side's `/attack/` or `/defence/` routes, and the round's `GET /`, `events/`, `topology/` and (after the end) `score/`. After `round.ended` it stays valid read-only for 15 minutes, so the bot can read the end and the score; writes return `409 round_closed`.

**Site pane.** The pane stays on its own nginx listener (8002) with the sandbox CSP and stripped cookies: `/site/<round>/<host>/…` is proxied to Django `/site-proxy/<round>/<host>/…` (`match/site.py`). For an attack seat each request goes through `attack.service.send` with a marker, becomes an `Action(kind=site)` and is charged HP like `POST requests/`; the response carries `X-Origin-HP`. For defence and lesson seats it is stamped with `Lease.browse_marker` and attributed as neither attack nor FP.

**Terminals.** nginx's `/vm-terminal/kali/` and `/vm-terminal/waf/` locations become `/vm-terminal/<side>/<round>/`, with an uncached `auth_request /api/rounds/<round>/terminal-auth/<side>/` instead of `/signed-in`; a raw path whose seat differs from the one the location routes on is refused, and nginx hands ttyd the round as its only argument. `auth_request` passes on only 2xx, 401 and 403 and turns any other answer into a 500, so `terminal-auth` names its refusal code in an `X-Error-Code` header, the location keeps it with `auth_request_set`, and its `error_page 403 500` hands the request to `@terminal-refused`, which answers the API's status and error shape for that code (`409 round_closed`, `409 round_not_started`, `404 unknown_round`, `403 not_seated`) and `503 unavailable` for anything else; a 401 still goes to `@sign-in`. `vm-terminal.sh` opens only for a running round's seat that holds a jump grant, as `kali` on kali and as `analyst` (read-only) on waf, and closes the shell once the grant goes or the round ends. kali belongs to the attack seat, waf to the defence seat. In a round the defence seat never gets kali; a lesson whose problem side is `both` gives one user both seats.

**Benign cases are the platform's job.** `match.service.start_round` starts `match/customers.py`, which fires every benign case in `redteam/cases/<wargame>.yaml` every `benign_every_s` through `attack.service.send_as_customer` (customer origins, no HP, not on the attack API), plus the traffic profile (the wargame's default when the problem sets none). A match test proves that a round whose attack seat sends nothing still ends with `totals.tn > 0`.

**Round rules (`domain.round_rules`):**

- `may_start_scored(lease_state)` refuses a new scored round on a lease where an objective has already fallen: the board secret may not rotate (open, §17). The client then closes the lease and opens a new one.
- `ended(state)` returns `time_limit`, `all_objectives_lost` or `origins_spent`. `origins_spent` ends the round only when `may_end(state)` holds: the benign schedule has completed at least one full pass, so a block-everything defence still shows its FP before the round ends. Manual reasons are `ended_by_operator`, `forfeit_attack`, `forfeit_defence`, `steps_done` (set by lessons through `match.service.end_round`) and `lease_expired`.

**The follower** is the `follow` compose service: the same image, running `manage.py follow`. Each tick it:

- drives `range.refill` for every slot;
- closes leases past `expires_at` (`lease_expired`);
- for each running round calls `match.service.tick`, which calls `defence.service.ingest_alerts(round)` (appends `alert.seen`), `attack.service.charge_from_access(round)` (§11), `attack.service.refill_edge(round)` (re-adds `pool` and `spent` after a `slot-boot` reload), `referee.service.observe_effects` for corp, `attack.service.read_commands(round)`, `defence.service.check_drift(round)`, and `ended`.

Request-time ingest (`POST ingest`) is removed. HP and the feeds stay current with no browser open.

### Lessons (tag `lessons`)

`lessons` sits above `match`: it opens rounds through `match.service` and ends them with `match.service.end_round(reason='steps_done')`. `match` never reads lesson state.

| Method and path | Request | Response |
|---|---|---|
| `POST /api/lessons/` | `{problem}` | `201 {round, lease, phase: waiting_slot\|starting\|ready\|ended, slot_eta?}`. Opens a `Lease(purpose=lesson)` and a `Round(kind=lesson)` with the user in every seat the problem side needs; the round starts by itself when the slot is ready |
| `GET /api/lessons/?mine=1` | none | `[{round, problem, phase, passed_order}]` |
| `GET /api/lessons/<round>/` | none | `{round, lease, phase, problem, steps:[{order, body, opens, hints_available}], current, progress}`. Answers are never included |
| `POST /api/lessons/<round>/steps/<order>/check/` | `{answer?}` | `{verdict: passed\|not_yet, detail_code?, next?}`; `409 step_locked` if an earlier step has not passed |
| `POST /api/lessons/<round>/steps/<order>/hint/` | `{n}` | `{hint, n, left}` |
| `POST /api/lessons/<round>/end/` | none | `{ended}`; closes the lease |

Judging: `lessons.facts.gather(kind, round)` reads rows through the side services only (`defence.service.latest_test`, `defence.service.detections`, `attack.service.actions`, `attack.service.commands`, `referee.service.objectives`), as the kind's `facts_needed` names. Then `domain.checks.JUDGES[kind](spec, answer, facts)` decides. Events are not read by judges.

### One error shape for the whole API

Every non-2xx response is `{errors:[{path, code, line?, params?}]}`; attack routes add `hp`. `code` is stable English and is exported into `openapi/schema.yaml` as an enum. The front end turns `code` (with `params`) into Korean from `strings/console.json`; the API sends no Korean. `cr/errors.py` defines `DomainError(code, status)` and its subclasses: `Invalid 400`, `NotSignedIn 401`, `NotSeated 403`, `NotFound 404`, `Conflict 409`, `EngineRefused 422`, `Unavailable 503`. `cr/handler.py` maps them, DRF's `ValidationError` (to field paths), `ValueError` and `PermissionError`. No view builds its own error response. `LANGUAGE_CODE = 'ko'`.

---

## 10. Content and staff API; problem and step schema

**Learner reads (tag `catalog`):** `GET /api/problems/` lists published problems, and `GET /api/problems/<id>/` returns one. The serializer has no answer fields.

**Staff (tag `staff`, `IsStaff`):**
- `GET|POST /api/staff/problems/`
- `GET|PUT|DELETE /api/staff/problems/<id>/`. One nested document `{problem, steps[], round?, start_posture?}` is written in one `transaction.atomic()`. `PUT` requires `base_revision` and returns `409 stale_revision {current_revision}` when it is not current. `DELETE` of a problem referenced by a Round returns `409 in_use`; staff unpublish it instead.
- `GET /api/staff/problems/<id>/export/` and `POST /api/staff/problems/import/`: the same nested document, the only way problem text moves between stores.
- `POST /api/staff/problems/validate/` validates without saving.
- `GET|POST /api/staff/postures/`, `GET|PUT /api/staff/postures/<id>/`, `GET /api/staff/wargames/` (read-only).
- `POST /api/staff/steps/<problem>/<order>/try/ {round}` evaluates a step's check against the facts of any ended round of the same wargame.
- `POST /api/staff/wargames/<id>/probes/record/` (§8).

**One validator:** `domain.problems.validate_problem(doc, catalog) -> [FieldError]` is pure. The serializer, the staff validate route and any bot that writes problems all call it. It checks:

- the wargame id, case ids and objective keys exist in the catalog;
- the pane names are in the enum;
- each check kind is known, and its params match that kind's schema;
- the HP numbers are positive integers;
- the matchups are allowed for the problem's side;
- `probe_cases` are malicious cases with recordings. Benign cases are added automatically.

It does not check Suricata syntax, which needs a sensor. There is one validation language; error paths are DRF-style (`steps[3].check.params.case`).

**Check kinds** (`domain/checks.py`). `CHECK_SCHEMAS` and `JUDGES` have the same keys, and a test asserts it.

| Kind | Params | Passes when |
|---|---|---|
| `answer` | `{accept:[text], normalise}` | the answer matches |
| `choice` | `{options, correct}` | the choice is correct |
| `loot` | `{objective}` | referee reports the objective lost through this round's loot |
| `rule_test` | `{engine, case}` | the seat's latest test of this engine has `case` = tp, corroborated, and every benign case tn |
| `rule_applied` | `{engine, same_as_tested: bool}` | a RuleSet was applied after the step opened, with the flag as required |
| `alert_seen` | `{engine?, rule?, case?}` | a Detection matches |
| `sent` | `{method?, path_has}` | an Action matches |
| `kali` | `{command_has}` | a command-log line matches (teaching aid only, §7) |
| `waf_changed` | `{field, change}` | the posture diff |

Dropped on purpose: `click` (a DOM selector), `triage` (scenarios), `replay` (the rule test replaces it), and `rules` (replaced by `rule_test` and `rule_applied`).

**Korean problem text** lives only in DB rows and moves between stores through the staff export/import. No seed command, fixture or data migration carries problem text. Test fixtures are English placeholders in `platform/testing/factories.py`; Korean test inputs live only in the named test files of §13.

---

## 11. Hit-point ledger

**Rule** (numbers from `RoundSetup.hp`, the same field names in `bots/README.md` and in the `hp.rule` block):

- Each origin starts at `budget`.
- Each request costs `per_request`.
- A request the WAF refuses costs `per_request × refused_x`. Refused means the statuses in the vhost's one `$refused` map: 400 (the body and parse rules in `modsecurity.conf`) and 403 (CRS blocks).
- Requests from one origin beyond `burst_per_s` within one second cost `× burst_x`. The two multipliers combine by multiplication.
- When `left ≤ 0`, the origin is spent.

**Pure part:** `domain.ledger.debit(state, charges, rule) -> (state, newly_spent)`. `Charge(origin_ip, at, refused, marker)`. No I/O; tested over fixture lists.

**Where the counts come from:**

1. **API-sent requests** (`POST requests/`, HTTP `POST cases/`, attack-seat site pane) are charged synchronously from the status the box saw. The `hp` in the response is exact.
2. **Everything else** (terminal curl, sqlmap, `POST tools/`, bot shells). `board.com.conf` (both vhosts) writes a JSON access log of every request to `/var/log/nginx/access.json` (`time`, `client_ip`, `vhost`, `request`, `status`, `refused`, `request_id` from `X-Request-ID` when it has a marker's shape, `^[A-Za-z0-9._:-]{1,128}$`, and empty otherwise, so a padded or repeated header cannot push the line past the shipper's 64 KiB and lose its `client_ip`; Ubuntu's own `access.log` keeps the combined format). `log-shipper.conf` ships it under Tag `nginx-access`, in place of `refused.log`. `filebeat.yml` routes appname `nginx-access` to module `nginx_access`, and `ingest-pipeline.json` gets an `nginx_access` branch. `ingest.elastic.normalize` makes a refusal Detection only from `nginx_access` records with a refused status, and `access_events(index, slot, after)` reads only that module; it is the only reader. The follower feeds those events to `attack.service.charge_from_access`. An Action charged synchronously excuses exactly one event carrying its marker (`Action.access_seen` records that it has been used), so its own request is not charged twice and every further event a learner sends with that marker from kali is charged.

Requests are counted at the WAF edge, never from Suricata: cr-ids sits behind cr-waf, so Suricata's `src_ip` is the WAF, and refused requests never reach it. Traffic that is not HTTP never reaches the target: `edge.nft` forwards only tcp/80 to the WAF and drops everything else from the WAN, so it needs no HP.

**When an origin is spent** (`attack.service`):

1. `range.edge.spend(ip)` adds the address to the infra `spent` set and flushes its conntrack entries. In `edge.nft` the rule `iifname @wan@ ip saddr @spent drop` comes **before** the `ct state established,related accept` in the forward chain, so an open keep-alive or sqlmap connection stops too. `pool` holds the round's declared attack origins and the customer addresses; for a lesson, the lesson round's attack origins and customers; for a probe lease, which has no round, the origin it wears (`attack.fire_probe` admits it through `range.edge.admit` before each case). The next rule, `iifname @wan@ ip saddr != @pool drop`, also comes before the established accept, so a learner with sudo on kali who puts an unused origin-subnet address on the box reaches nothing: every address the target can see is one the HP rule charges or a customer's. Every sender from the attack side's origin subnets goes through `pool`: case firing, free tools, the attack-seat site pane and requests wear an origin through `attack.wearing` (which fills the pool if the round has none), the terminal fills it the same way before it grants a shell, the customers and the defence seat's site pane send from customer addresses, and the probe lease admits its origin. `slot-boot` reloading the table empties the sets, so `attack.service.refill_edge` re-adds them on each tick. The learner account `kali` has `NOPASSWD:ALL` sudo, so dropping at the infra router, the one hop the attacker does not control, is what stops a spent origin.
2. Running ToolRuns of the seat are stopped through `box.stop` (`stopped_by: origin_spent`).
3. `box.wear_origin(next)` runs `set-origin` with the next unspent attack origin from `box.origins()`, never from `customer_origins()`.
4. Events `origin.spent` and `origin.switched` are appended. When none are left, `origins.spent` is appended, attack writes return `409 origins_spent`, and `domain.round_rules.ended` returns `origins_spent` once `may_end` holds (§9).

**Customers are never hit:** `box.customer_origins` already excludes every attack `source_ip`, and the `spent` set holds exact addresses. `tests/attack/test_customers_survive_spend.py` proves that customers keep running and keep their TN after an origin is spent.

**Refusals and the hypothesis.** A refusal costs more, so a block-everything defence drains HP faster. The objective number may then look good for it, but the platform-fired benign set (§9) keeps running until at least one full pass, so its FPs show beside it. Acceptance proves it (§14).

A lease holds rounds one after another and its stack is rebuilt only when the lease is released, so each round start empties `pool` and `spent` and adds the new round's addresses in one load (`range.edge.restart` from `attack.fill_pool`); the tick's `refill_edge` only adds, and adds nothing once the round has ended. The round's end empties both sets (`attack.close`), so between rounds nothing from kali reaches the target, including a process the learner left running there, while the HP rule charges nothing.

---

## 12. Bots

- **Contract:** drf-spectacular exports `openapi/schema.yaml`, which is committed. `tests/contract/test_schema_fresh.py` fails when it is stale. `test_schema_complete.py` fails on any `/api/` route missing from the schema, any non-GET operation without a request serializer, any response without a serializer, any attack or defence operation without exactly one side tag, and any `DomainError` code missing from the error-code enum. Per-side schemas are served at `/api/schema/attack/` and `/api/schema/defence/`.
- **Client:** `bin/gen-clients` generates `bots/client/` (openapi-python-client) and `front/src/api/schema.d.ts` (openapi-typescript). Neither is committed: they carry generator docstrings and JSDoc, and the no-comments rule has no exception for them. `bin/verify`, the platform Dockerfile and `images.yml` generate them before use. `test/` and the bots use the generated Python client, so a path change breaks them at once.
- **One surface:** `bots/cli.py` exposes each operation as `python -m bots.cli <operation> --json '{...}'` with the seat token in the environment, and `bots/tools.py` turns the tagged operations into JSON Schema tool specs: a side's own operations plus the round reads (`round_read`, `round_events`, `round_topology`, `round_score` without the staff-only `correlation`) and `lease_heartbeat`, never the other side's, and not `defence_kibana`, which is for human seats. Any agent, Claude Code or another model, drives a seat through the CLI or the tool specs. A non-agent model plugs into `bots/play.py`'s turn loop through `bots/provider.py` (`run --provider package.module:factory`); none is wired in.
- **How Claude Code drives a seat:**
  1. The operator creates a round with a bot seat (`POST /api/leases/<l>/rounds/`) and receives the seat token once.
  2. Claude Code is started with `bots/prompts/claude_code.md` plus the side prompt: the rules of play, the HP rule, the error codes and the CLI.
  3. It reads `state/` (phase, brief, target, objectives, HP) and `events/`, discovers `cases/` and `tools/`, acts, reads `hp` on every response, and switches origin or stops on `origins_spent`.
  4. A bot that wants a shell asks for `GET terminal/`. Shell traffic is charged from the WAF access log by the same rule as a human's.
  5. After the end the token is read-only for 15 minutes; the bot reads `round.ended` and `score/`.
- **The attack bot's baseline** is firing the declared cases through `POST cases/`. That is the one path for declared cases; `redteam/run.py` is gone.
- **README:** `bots/README.md` gives the HP rule with field names, the error codes, the baseline, and the fact that free actions are attributed by source and time and never scored as TP/FP/FN/TN.

---

## 13. Front end

`front/` is a typed console: Vite, TypeScript and Preact, with vitest tests. It is built in a node stage of `platform/Dockerfile`, which first runs `bin/gen-clients`, and served by the existing nginx. `images.yml` adds `front`, `strings` and `openapi` to the platform image's `sources`, so a front-end change rebuilds the image. Generated types make a call to a renamed endpoint fail at build time, and "fetch `/api/` only" holds by construction.

- `api/client.ts` carries the CSRF renewal (`GET /api/auth/csrf/`), the 90 s request timeout, the long wait for slot readiness and the one error shape. `api/follow.ts` is the one events cursor client (it resumes after a drop), and every pane subscribes to it; it also sends the lease heartbeat. There are no other timers.
- **Panes** (shared by lessons and rounds): `Kibana` (same-origin iframe; the localStorage preset is the listed seam exception), `Terminal` (ttyd via the seat's `ws_url`), `Site` (the 8002 listener in an iframe, with the request list beside it), `Map` (cytoscape), `IdsRules` and `Waf` (editors with Check, Test and Apply, and `RuleTestTable` inline under the editor), `Alerts`, `Objectives`, `Hp`, `Score`, `StepCard`.
- **Pages:**
  - `Login`, `Signup`
  - `Home`: published problems, my lessons and seats, joinable rounds
  - `RoundLobby`: create a round, pick seats, join, start (operator)
  - `Lesson`: StepCard beside the panes the step names
  - `RoundAttack`: Terminal(kali), Site, loot, Hp, Objectives
  - `RoundDefence`: Kibana, Terminal(waf), Map, IdsRules, Waf, Alerts, Objectives
  - `Result`: Score only, the two numbers apart, with the "one case counts once" note
  - `staff/Problems`, `staff/Postures`: the nested document editors, with validator errors shown inline by path
  - `staff/Users`, `staff/Range` (slots, probe recording)
- **Korean tables:** `strings/console.json` (bundled into the front end) and `strings/server.json` (read only by `cr/strings.py`, for the Kibana gate page; never bundled). A vitest test fails when any `server.json` key appears in the built bundle.
- **Korean guards:**
  - `tests/seams/test_no_hangul.py` is one repo-wide scan over `.py .ts .tsx .html .json .yaml .md .sh .conf`. It allows Hangul only in `README.md`, `docs/ARCHITECTURE.md`, `docs/vocabulary.md`, `strings/console.json`, `strings/server.json`, `wargames/board/app/posts/templates/`, `wargames/board/app/posts/management/commands/seed.py`, and a named list of test files that stand in for Korean learner text or check the Korean the product shows. The test asserts the named list exists.
  - vitest: every `t(key)` exists in `console.json`; every error code in the schema enum has a key; no shown label is an English TP/FP/FN/TN abbreviation.
  - pytest `test_error_codes.py`: every code in `cr/errors.py` and every `detail_code` in `domain/checks.py` has a key in `console.json`.
- **CLAUDE.md** lists these Korean places, the generated-code rule (not committed), and the comment scan `tests/seams/test_no_comments.py` over `platform/`, `front/src`, `bots/`, `bin/`, `test/`, `deploy/`, `wargames/` and `redteam/` (Python, shell and TS/TSX/JS), exempting exactly `deploy/suricata/rules/`, Django's migration header and a script's shebang.
- **nginx.conf** is rewritten in the same step. It keeps the exact-match rate-limited `/api/auth/login/` and `/api/auth/signup/` locations and `@too-many` (now the one error shape, code `too_many`), `@sign-in`, `/signed-in` (now asking `/api/me/`, since the new tree has no `/auth-check/` view), `/site-proxy/` (refused from outside), the 8002 site listener (keyed by round), the `/vm-terminal/<side>/<round>/` locations with the seat `auth_request`, and the Kibana routes and gate, which also answers every refused Kibana route (`/kibana-refused/` is gone). `/static/map/` is dropped: the map ships with the front build. The SPA fallback (`/app/front/dist`, `try_files … /index.html`) is added last. Django admin is not installed, and a test asserts that no URL routes to it.

---

## 14. Tests

- **`tests/domain/`:** no `DJANGO_SETTINGS_MODULE`; its conftest imports no Django, and `bin/verify` runs it first. It covers correlate (marker on Action, free actions by window), metrics (one declared case one decision; free actions leave totals unchanged), corroborate (with `indiscriminate`), the objective tally (tier difficulty weights) and attribution, ledger (400 and 403 refusals, burst, spend order, no double charge), verdicts, every check judge, the problem validator, `ended`, `may_end` and `may_start_scored`. Fixture-driven.
- **`tests/seams/`:**
  - `test_imports.py`: the 15 rules in §2, by AST, including FK targets and migration dependencies, and every module assigned a layer.
  - `test_isolation_seams.py`: the single-owner patterns over `platform/`, `front/src`, `bots/`, `test/` and `bin/`, with the closed exemption list.
  - `test_no_hangul.py`, `test_no_comments.py`.
  - Each seam against fake runners from `platform/testing/fakes.py`: Suricata `checked` parsing, `offline_test` (pinned image, scratch volume outside `/var/log/suricata`), CRS `scratch_check` and `scratch_test` (never the live prefix, only 127.0.0.1), edge set commands and conntrack flush, `fetch_after` and `access_events` against a fake ES (only `nginx_access`; non-refused access records make no Detection), the box, and jump grants.
- **App tests** (`tests/<app>/`): only through public routes with DRF's `APIClient` and public service functions. They cover: permissions (a bot token reaches one side of one round, and read-only after the end); join and `already_seated`; lifecycle permissions (a seat cannot end or close, only forfeit); event visibility per kind in PvP; a stale apply giving 409; multi-sensor apply rollback; HP on every attack response, errors included; `origins_spent` refusals and `may_end`; customers surviving a spend; benign TN with a silent attacker; the attack-seat site pane charged; the rule test with a fake sensor and WAF and `test_busy`; snapshot freezing (a staff edit mid-round changes nothing); `stale_revision` on staff PUT; progress surviving a lease close; `step_locked`; lease expiry; and the score with separate `objectives`, `outcomes` and `free_actions`.
- **`tests/contract/`:** schema fresh, schema complete, error shape on every refusal path, error codes have Korean keys, no admin route, each `bin/backup` TABLES entry is a real table, and `test_opposite_seat.py`, which walks every round-scoped GET as the opposite seat and asserts nothing of the other side leaks.
- **Probe recordings:** a test that `manifest.json`'s image digest matches `wargame.yaml`; a test that every malicious case's response was passed through redaction.
- **`front/` vitest:** client error handling, the follow cursor, RuleTestTable rendering, the Korean guards, no `server.json` key in the bundle.
- **Live acceptance kept** (`test/`), ported to the generated client:
  - TP>0 and TN>0, objectives from ground truth, isolation, concurrent sessions, `test_geoip_durable`.
  - `test_indiscriminate_defence`, `test_strategy_honesty` and `test_strategy_comparison` (through `score/?correlation=`), `test_evasion`, `test_corp_authz`, `test_judge_isolation`, `test_tool_cases`. These guard the claim that block-everything scores perfectly on detection but not on the whole.
  - `test/range.py` keeps calling `manage.py run_on_role` through `docker exec`.
  - New: the rule test leaves ground truth and round detections unchanged; apply after test; HP spend drops the origin at the edge, including an open keep-alive connection, while customers keep running; a block-everything posture with the HP rule on shows FP>0 on the benign set before `origins_spent` ends the round; one round of each matchup driven by a Claude Code bot.
- The benign cases in `redteam/cases/` stay. A test fails if a wargame has no benign case.

---

## 15. What is deleted

- **Ratchet:** `metrics.json`, `bin/measure`, the ratchet step in `bin/verify`, `test_measure.py`, the ratchet test in `test_verify_stack.py`, and the ratchet text in CLAUDE.md, the orchestrate skill, `reference.md`, `.claude/settings.json`, `test/README.md`, README and `now.md`.
- **The whole `platform/api/`:** `views.py`, `scenario_run.py`, `models.py` and every migration. `management/commands/run_on_role.py` is rewritten under `match/management/commands/`. The other modules worth keeping are rewritten in their new homes (§3).
- **Old modules:** `platform/scenarios.py`, `game.py`, `wargames.py`, `lifecycle.py` (the ATT&CK/CAPEC stage list, used only by scenarios), `lesson.py` (its pure matchers move into `domain/checks.py`), `scoreboard.py` and `platform/scoring/` (into `domain/scoring/`), `register_pipeline.py` (into `ingest/elastic.py`), `operator_log.py` (into `attack/box.py`), `traffic.py` (into `match/customers.py`), `topology.py` (into `range/topology.py`), `attacker.py`, `jump.py`, `kibana.py`, `disable.py` (into their apps), and `redteam/harness.py`, `tools.py`, `run.py`, `signin.py`, `__init__.py` (into `platform/attack/` or `test/`).
- **`platform/console/`:** every template, including `blue_lesson_script.html`, `blue_dev*` with its `site.dev.*` strings, `blue_scenario*`, `blue_triage`, `blue_coach`, `debrief_script`, `session.html`, `main.html`, `blue.html`, `red.html` and `strings.html`. `console/strings.py` is replaced by `cr/strings.py` over `strings/server.json`.
- **Content:** `wargames/<id>/scenario.yaml` (replaced by `wargame.yaml`; its wargame-level `difficulty`, `minutes` and `category` are gone, objective tiers keep theirs). The 12 named defense profiles become Posture rows authored through the staff API. The rule files `no-xss`, `no-uri-sqli`, `broken-sort` and `spaced-sort`, which only those profiles used. The lessons f1-f6 and c1/c2.
- **Check kinds:** `click`, `triage`, `replay`, `rules`.
- **Deploy:** `refused.log`; `deploy/openstack/network.yaml`. `deploy/proxy/stamp.py` stays: `deploy/roles/kali/stamp.py` is a link to it, not a second copy.
- **Endpoints, with no replacement or replaced as listed:**
  - `/api/sessions/**` → `/api/leases/` and `/api/rounds/`
  - `PUT sessions/<id>/waf/` → `waf/apply/`
  - `lesson/addresses/`, `verify-window/`, `scenario/hints/`, `triage/`, the scenario and debrief routes
  - `POST ingest` → the follower
- **Tests:** `test_scenario_*`, `test_dev_tools`, the lesson-content tests, `test_lifecycle.py`, `test_strings.py` (replaced, §13), and every test that reached `views._*`.
- **Docs:** `docs/superpowers/plans/` and the superseded specs (git keeps them), STATE.md backlog 0 (rewritten).
- **Kept, not deleted:** `bin/fetch-geoip`, `pick-origins` and `worldmap` (the ingest pipeline uses geoip processors, and acceptance runs `test_geoip_durable`); `bin/backup` as a snapshot tool.

---

## 16. Build order (fresh build, dependency-ordered)

The work happens on a working branch. Old `platform/api/` and `platform/console/` are removed at step 2, and `dev` keeps the old product deployable until gate 2. Each step lists its proof.

1. **Remove the ratchet** (§15).
   *Proof:* `bin/verify --fast` passes. `bin/select-tests` does not import measure.
2. **Clear the old tree and keep a snapshot.** `bin/backup` of the live store into backup-safe. Delete `platform/api/`, `console/`, the scenario and lesson modules and their tests.
   *Proof:* the branch has no reference to `api.` or `scenario` (grep test).
3. **`domain/`.** Carry over `scoring/*` and `scoreboard.py` (split into `corroborate.py` and `objectives.py`) and lesson.py's pure matchers. Write `ledger`, `verdicts`, `checks`, `problems` and `round_rules` fresh.
   *Proof:* `tests/domain` passes with no Django in the test process. Import rule 1.
4. **Seams, Django-free, config injected.**
   - `cr/config.py`, `cr/errors.py`.
   - Carry over `ingest/elastic.py` (+ `fetch_after`, `access_events`, `register_pipeline`, the `nginx_access` split).
   - Carry over `rules/suricata.py` (+ `checked`, `offline_test`, `capture`) and `rules/crs.py` (+ `scratch_check`, `scratch_test`).
   - `range/`: carry over `openstack.py`, `wiring.py`, `pool.py`; rename and split `cloud.py`, `sandbox.py`+`clock.py`, `declared.py`, `fabric.py`, `ports.py` (§3); rewrite `refill.py` Django-free; write `substrate.py` and `edge.py`.
   - Write `attack/box.py`, `range/jump.py`, `attack/firing.py`, `attack/tools.py`.
   - Carry over `defence/kibana.py`, `referee/loot.py`, `effect.py`.

   *Proof:* `tests/seams` against fakes. Import rules 2, 4, 14. Seam scan.
5. **Deploy changes and rebake.**
   - `edge.nft`: `pool` and `spent` sets, the `spent` drop and the drop of every address outside `pool`, both before the established accept (§11).
   - `board.com.conf` (both vhosts): the `$refused` map (400, 403) and the JSON access log `access.json`; `log-shipper.conf` ships it as `nginx-access` and the infra's `log-relay.conf` relays it; `deploy/filebeat/filebeat.yml` routes it; `deploy/elastic/ingest-pipeline.json` gets the `nginx_access` branch.
   - `probe.conf`, `probe-upstream.py` and the `analyst` account on the WAF role.
   - `conntrack`, `tcpdump` and the offline rule test's scratch folder on the infra role.
   - Bake new role images for infra and waf (`docs/OPENSTACK.md` §3.7).

   *Proof:* on a slot, `nft list set ip edge spent` exists; an access-log line reaches Elasticsearch with `request_id` as module `nginx_access`, and a 200 makes no Detection; `rules.crs.scratch_test` returns a verdict for one case and leaves the live audit log unchanged; `rules.suricata.offline_test` leaves `/var/log/suricata/eve.json` unchanged.
6. **Django skeleton.** `cr/` (settings, DRF, spectacular, `handler.py`, `strings.py`), `strings/`, `accounts` (auth routes, blocks, staff users) and `events`.
   *Proof:* `tests/accounts` and `tests/events`. Error-shape test. No-admin test. `bin/carry-users` against a copy of the snapshot.
7. **`content`.** Catalog, `wargame.yaml` per wargame, models, the staff nested-document API with revisions and export/import, learner read API.
   *Proof:* `tests/content`. Validator errors come back by path. `test_no_hangul`.
8. **`match.models`, `match.auth` and `referee`** (baseline, loot, effects, objectives, redact, `score` taking records).
   *Proof:* `tests/referee` with a fake target. Import rules 4, 5, 11, 15.
9. **`defence`.** Rules and posture read, check, test and apply (multi-sensor), versions, probes list, disable, drift, alerts with AlertCursor, traffic, terminal, Kibana gate.
   *Proof:* `tests/defence` with fake runners (stale 409, rollback across sensors, `same_as_tested`, benign cases always probed, `untested` reasons, `test_busy`).
10. **`attack`.** State, cases, requests, tools (async, list), loot, origins, terminal, HP charge from both sources, spend at the edge, customer sends.
    *Proof:* `tests/attack` (HP on every response, no double charge, customers survive a spend, `origins_spent` 409).
11. **`match.service`, the follower and the probe recorder.** Lease and round lifecycle with permissions, join, heartbeat and expiry, `may_start_scored`, `tick`, `ended`/`may_end`, customers and the benign schedule, site pane, terminal auth, score, probe recording, `follow` in `compose.yaml`.
    *Proof:* `tests/match` with fakecloud (silent attacker still TN>0). Import rules 6, 7, 9.
12. **Probe recordings.** `bin/record-probes board` and `bin/record-probes corp` through the staff route. Commit `wargames/<id>/probes/`.
    *Proof:* the manifest lists every HTTP case with the image digest; the probe lease's stack is rebuilt after release; a live rule test on another slot returns a full table.
13. **`lessons`.** Lesson rounds, facts, judges, progress, hints.
    *Proof:* `tests/lessons` (a `rule_test` check reads RuleTest; progress survives a lease close; `step_locked`).
14. **Contract and clients.**
    - Export `openapi/schema.yaml`; `bin/gen-clients` in `bin/verify`.
    - Port every `test/` file, including `conftest.py`, `shared_sessions.py`, `opening.py`, and every `/api/sessions` reference in `test/` and `bin/` (71 lines today).
    - Re-point `bin/backup` TABLES and `bin/prune`.

    *Proof:* `tests/contract`. Import rule 12. `test_backup_tables`. A grep for `/api/sessions` finds nothing.
15. **`front/`** and the new `nginx.conf`. Node stage in the Dockerfile; `front`, `strings`, `openapi` in `images.yml` sources.
    *Proof:* vitest, including the Korean guards. Sign-in rate limiting checked live. A captured walk of every page as a learner on a live slot.
16. **`bots/`.** CLI, tool specs, prompts. Run one round of each matchup with Claude Code driving the bot seat.
    *Proof:* each round ends with a score; the HP events show at least one spend and switch in the attack-bot round.
17. **Docs and the full live check.** Rewrite CLAUDE.md (seams, exceptions, Korean places, generated-code and comment rules, gotchas: no `platform/__init__.py` still holds), ARCHITECTURE.md (Korean), DECISIONS.md (including the grafts and their sources from Appendix B), STATE.md and `now.md`. Archive the superseded specs.
    *Proof:* the full `bin/verify` with acceptance on the range, a live review round with zero countable findings, and a docs review. Then gate 2.

---

## 17. Open risks (unverified until measured)

1. **Offline IDS vs the live sensor.** `suricata -r` over recorded pcaps may differ from the passive af-packet sensor on the bridge (stream reassembly, capture timing, the WAF's rewriting). The live round stays the score, and acceptance compares one rule's test table with its live outcome.
2. **Suricata error lines.** Mapping `suricata -T` output back to a line of the candidate is not known to be reliable when rules are read from a file.
3. **Scratch CRS instance fidelity.** A different master, prefix and upstream may change outcomes (e.g. response-phase rules), and redacted responses may change outbound data-leak rule outcomes.
4. **Recorded sqlmap pcaps as an IDS preview** are fair only if Suricata's view does not depend on what the WAF blocked during recording, which is detection-only.
5. **Access-log volume on the UDP hop.** `log-relay.conf` forwards to the collector over UDP, which already drops alerts under sqlmap bursts. Lost access events mean HP undercharges. Measure on a sqlmap run; if the loss is real, aggregate per source on the WAF before shipping.
6. **HP lag.** Terminal and tool charges arrive one follower tick plus the shipping delay late. Only API sends are exact.
7. **Forged markers and customer addresses on a root box.** The learner has sudo on kali, so terminal traffic can carry any `X-Request-ID` (including a customer's or another action's marker; a reused action marker is still charged, since a synchronous charge excuses only one access event), and attack traffic could be sent from a customer address (in `@pool`, not spendable, counted as customer FP/TN). API sends are safe because the platform sets the marker. Comparing customer-source requests with the customer program's own records is a possible check; not designed yet.
8. **Board secret between rounds on one lease.** Until it is known whether the secret can rotate without a rebuild, `may_start_scored` refuses a scored round on a lease where an objective has fallen.
9. **Free-action attribution.** Terminal and tool actions correlate by source and time window. Overlapping tool runs from one origin may blur attribution. Free actions are never scored as TP/FP/FN/TN, so this affects only `free_actions` and objective attribution.
10. **The follower's single loop** over all open rounds may lag when 4 slots run sqlmap at once (SQLite WAL writes from the follower and the API).
11. **The Preact front end's** first build in `images.yml` and the SPA fallback order around the auth locations need a live check of sign-in rate limiting.
12. **The `analyst` account** must be able to read the CRS config and logs without write access; whether the current WAF image's file ownership allows it without changing the live reload path is unverified.

---

## Appendix A: Skeptic findings on by-side and how they are resolved

| Finding | Resolution |
|---|---|
| `range/reset.py` named "target pristine reset", plus a "reset target" step with no code | It is the slot refill state machine: `range/refill.py`, rewritten Django-free. A target is fresh because the stack is rebuilt on release |
| CRS "reuses nginx -t validation" | The CRS posture is structured; `crs.checked` gives field errors, and the new `crs.scratch_check` runs `nginx -t` on a scratch config (§8) |
| defence would import referee for `corroborated` | `corroborated` lives in `domain/scoring/corroborate.py` |
| attack and defence "never import referee" but need loot and objective state | They import `referee.service` only; referee takes records as arguments and never imports a side (§2 rules 4, 5) |
| `fetch-geoip` deletable with the map | Kept, with `pick-origins` and `worldmap` (§15) |
| The harness and the `/api/sessions` references missed | Firing moves to `platform/attack/firing.py`; `test/` and `bin/` go onto the generated client; a grep proves none remain (§16 step 14) |
| The CRS test reaches the real target across the live bridge | Scratch master on loopback with a stub upstream; recording on a probe lease whose stack is rebuilt; acceptance proves ground truth and detections unchanged (§8) |
| Guards blind to `console/static` and nested templates | The console moves to `front/`; the seam scan covers `front/src`, `bots/`, `test/`, `bin/`; one repo-wide Hangul scan (§5, §13) |
| How Korean seed problems enter the repo | They never do: staff API and export/import; fixtures are English (§10) |
| English TP/FP labels on screen | Codes in the API, Korean keys on screen, guard carried over (§8, §13) |
| Firing from the WAF box and capture on infra have no seam owner | Loopback replay inside the CRS seam; live firing on cr-kali; capture owned by `rules/suricata.py` (§5, §8) |
| The HP count has no owner for its Elasticsearch read | `ingest.elastic.access_events`, module `nginx_access` only (§11) |
| `click`, `triage`, `replay` dropped silently | Dropped by name with reasons, with `rules` (§10) |
| Fields dropped from scenario.yaml | `name`/`description` move to Problem; wargame-level `difficulty`, `minutes`, `category` dropped; tier difficulty stays as the objective weight (§6) |
| Acceptance trim weakens the hypothesis | No trim (§14) |
| `range.substrate` is a function in `__init__.py` | `range/substrate.py`, config injected |
| match becomes a fat coordinator | Lessons sit above match in their own app; facts gathered in one place; judges pure (§9) |
| String FKs hide coupling | Real FKs only downward; the AST test checks imports, FK targets and migration dependencies (§2) |
| No JS types or tests | Typed front end with generated types and vitest (§13) |
| Free bot traffic has no marker | API sends get a platform-set marker; terminal and tool traffic correlates by window and is never scored as TP/FP/FN/TN (§7, §9) |

## Appendix B: Grafts taken, by source

- **hexagonal:** `domain/` pure core; AST import test; the nftables `spent` set at the infra edge; HP from two sources with dedupe by marker; async tool runs; terminal access per seat; per-engine defence resources; one machine-readable error shape; a pure problem validator with a learner read API without answers; progress keyed by user and problem; panes shared by lessons and rounds; the layered test split; folding `register_pipeline`, `operator_log` and the tool image into their owners; explicit end conditions; geoip tools kept.
- **django-apps:** `corroborated` and the tally below the apps; the scratch CRS instance with a stub upstream and IDS read from scratch `eve.json`; non-destructive syntax checks; HP block on every attack response; a lessons app with a check registry; content snapshot at round start; seat-scoped tokens; `search_after` cursor ingest; one exception handler; explicit deletions and backup re-pointing; `browse_marker` and `CustomerRequest` kept. Not taken: the apply gate on a passed test; infra edge counters as the request count.
- **django-drf:** lease split from round, with the baseline per round; seat-token permission classes; per-side schemas and a completeness test; stale apply 409; Posture rows; the lesson rule check reuses the rule-test verdict; APIClient-only tests with English placeholders; no Django admin; ops scripts re-pointed; Django-free seams with config dataclasses.
- **thin-api:** committed OpenAPI contract with a staleness test; a generated client for bots and test/; the typed front end; the normalised alert shape and `traffic/`; `against_applied`; the seam scan over clients; the pane enum. Not taken: `RuleDraft` as a versioned resource; committed generated clients.
- **event-sourced:** the events app as a leaf feed with `visible_to` per kind; the follower service; recorded responses for the CRS stub; probes stored with the target app; only referee appends `objective.lost`; the score endpoint as separate objects; pure fixture tests. Not taken: events as the score store or as judge input, one event per request, long-poll.
- **minimal-cut:** the nested problem document saved atomically; checks as a registry of pure judges; hashed seat tokens; one refusal path; the request count from WAF-edge nginx records through ingest; a machine-readable HP rule and the all-spent end state; the separate scratch nginx master with its own audit log; every benign case always probed and `untested` reasons; probe recording with CRS detection-only; no KQL in the bot API; explicit delete and keep lists.

The body of the spec no longer carries these source tags; DECISIONS.md records them once at build time (§16 step 17).

---

## Review notes rejected

1. **"The offline IDS test on cr-infra creates a second Suricata host that topology does not declare."** Wrong: `cr-ids` is the `sensor` container on node `cr-infra` (`wargames/board/topology.yaml`: `cr-ids: {node: cr-infra, container: sensor}`), so there is no second host. The useful part is kept: `offline_test` takes the host from the topology's sensor device and runs the same pinned image and `suricata.yaml` (§8).
2. **"Do not raise the cost of a refusal by the defender's WAF; charge by request count and burst only."** Rejected: "faster when refused" is a decided product rule. The concern behind it holds and is fixed another way: the platform fires the benign set in every round, `origins_spent` cannot end a round before one full benign pass (`may_end`), and acceptance proves a block-everything posture shows FP>0 under the HP rule (§9, §11, §14).
3. **"`attack/jump.py` is attacker-box knowledge and a second box owner."** (Now `range/jump.py`, since the defence terminal needs the same grants.) Partly wrong: `jump.py` manages the platform VM's own sshd jump grants (`authorized_keys_line(public_key, address, …)` with `box_address(given)` taking the address as an argument) and writes one key line into the given account's `authorized_keys` through the runner it is handed; it reads nothing else of the box. Kept as its own seam owner, with the box address supplied by the side service and `authorized_keys`/`cr-session-` added to the seam patterns (§5).
4. **"Drop the provenance tags and Appendices A and B from the spec."** Partly rejected: this is the gate-1 design, and the user asked for a fusion of the other options' strengths, so the reviewer of this gate needs to see where each graft came from. The inline tags are removed from the body; the appendices stay, and DECISIONS.md takes them over at build time.
5. **"range/ is carried over wholesale, which bends to keep old code."** Partly rejected: the user ruling names the range adapter as one of the good parts to carry over. The parts of the issue that hold are fixed: each file gets an owner row, opaque names are renamed or merged, `refill.py` is a rewrite, and the Django imports in `range/__init__.py` and `api/reset.py` go (§3, §4, §16 step 4).
6. **"Lesson rule-test judge reads a RuleTest row, breaking service-only."** Partly rejected: reading the RuleTest is the point (the lesson card and the editor cannot disagree). It now goes through `defence.service.latest_test`, which satisfies rule 9 (§9).
