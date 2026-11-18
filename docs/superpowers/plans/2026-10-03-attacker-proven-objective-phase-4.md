# Attacker-Proven Objective — Phase 4 (board-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove OWASP Juice Shop, its wiki sub-target, and the `self_judged` objective model so the cyber range runs on the Django board alone with `objective_model` ∈ {`loot_verified`, `none`}, retargeting or deleting every Juice-coupled test and lowering the `tests` floor once, with justification.

**Architecture:** Three ordered movements, each ending green under a full live `bin/verify`. (1) Additive prerequisites while Juice still runs: fix two payload-less board cases, harden the cloud WAF for `/internal`, guard against real `urlopen` in unit tests, and remove the board's `members.json` over-exposure. (2) Flip the default scenario to `board` and retarget the flip/rename-coupled tests while Juice still exists, proving the board alone satisfies acceptance (TP>0, TN>0). (3) One atomic destructive commit: delete Juice/wiki/`self_judged`/`platform/objectives.py`, collapse the three objective gates, replace the READY "nothing solved" check, delete the Juice-only tests, repurpose the `self_judged`/stamp tests onto board loot behaviour, add removal guards, update docs, then measure and lower the floor.

**Tech Stack:** Python 3 (repo venv at worktree root `.venv/`), Django 5.2 (platform) + Django 3.2.4 (board target), pytest, Docker Compose, Suricata + ModSecurity/CRS, Elasticsearch, MySQL (board-db). Run Python as `.venv/bin/python` (from `platform/` or `test/` as `../.venv/bin/python`); `python` is not on PATH.

**Authoritative references (cite, do not re-derive):**
- Removal/retarget analysis with per-test edit tables and line citations: `.superpowers/sdd/phase4-analysis.md` (hereafter **ANALYSIS**). Its §3.3 (platform tests) and §3.4 (acceptance tests) are the per-file edit authority; §4 is the floor math; §5 is ordering, risks (R1–R11), pre-existing defects (P1–P4), and human decisions (H1–H9).
- Design spec, "Juice Shop removal (phase 4, sequenced)": `docs/superpowers/specs/2026-10-03-attacker-proven-objective-model-design.md` L199–271.
- Constraints: `CLAUDE.md`. Current true state: `docs/STATE.md`.
- Do **not** read `platform/console/templates/console/strings.html` (0 Juice/wiki/shop.com matches, cost rule) or `docs/vocabulary.md`.

## Global Constraints

Every task's requirements implicitly include this section. Exact values, verbatim:

- **`core_loc` stays ≤ 461.** Core = `platform/scoring/`, `platform/ingest/`, `platform/rules/`, `redteam/harness.py`. Nothing new lands there. The only core edit permitted this phase is two same-line replacements in `redteam/harness.py` (measured 461 → 461 in ANALYSIS §0/§1.1). Never add a line to a core file (`bin/measure` counts physical lines).
- **`dependencies` stays 6.** Do NOT add `mysqlclient` or any pip package.
- **`services` and `wargame_services` may only drop** (`services` 7 stays; `wargame_services` 4 → 2 is allowed and expected). Never grow either.
- **The `tests` floor is being deliberately lowered THIS phase, with an itemized justification** — the one sanctioned exception (user-authorised, ANALYSIS H1). It is lowered exactly once, in the final task, to whatever `bin/measure` reports after the final green `bin/verify`.
- **No code comments or docstrings** anywhere — Python, JavaScript, HTML templates, Dockerfiles, `compose.yaml`, YAML. Name things so the code says what it does. Sole exception: `deploy/suricata/rules/` (commenting a rule out is how suppression works).
- **The target decides ground truth.** The platform never credits an objective from its own belief about what an attack did; it only credits loot the attacker proved against the target-owned snapshot.
- **Every UI action exists as a REST API first.** Console templates fetch `/api/`; they never receive server-rendered data.
- **Acceptance must stay green with the board alone:** TP > 0 and TN > 0 from the board's own cases (`redteam/cases/board.yaml`).

**Session protocol reminder:** `bin/verify` refuses any change that grows a gated number or shrinks the floor; a shrunk floor is normally a stop-and-report condition, lifted here only by the user's explicit Phase 4 authorisation. Commit, never push. On a red result or any gated-metric growth, `git reset --hard` and report.

---

## Task graph

- **Task 1** — Prerequisite: send the two payload-less board cases, guard request-case keys. (additive; Juice still runs)
- **Task 2** — Prerequisite: harden the cloud WAF vhost for `/internal`; guard it. (additive; cloud, static guard)
- **Task 3** — Remove the board's `members.json`; repoint the live loot-credit test to the internal read channel. (additive security fix)
- **Task 4** — Flip the default scenario to `board`; retarget the flip/rename-coupled *unit* tests; add the `urlopen` guard and migration-state guard. (unit suite green, no stack)
- **Task 5** — Retarget the flip/rename-coupled *acceptance* tests; pin the Juice-only acceptance tests; prove board-first acceptance on the live stack. (full `bin/verify` green, Juice still present)
- **Task 6** — Destructive removal, one commit: delete Juice/wiki/`self_judged`/`objectives.py`, collapse the gates, replace READY, delete Juice-only tests, repurpose the `self_judged`/stamp tests, add removal guards, harden the Docker default vhost. (full `bin/verify` green, board-only)
- **Task 7** — Docs: `README(.ko)`, `ARCHITECTURE(.ko)`, `THREAT-MODEL`, `CLAUDE.md` (H6). (no metric impact)
- **Final Task 8** — Full `bin/verify` green → `bin/measure --save` → `docs/STATE.md` → lower `metrics.json` `tests` floor with itemized justification → commit.

**Why this order (ANALYSIS §5.1):** prerequisites are additive and raise the count. The retarget (Tasks 4–5) proves the board alone passes acceptance *before* anything is destroyed, so a later red run is attributable to the board's behaviour, not to a wrong deletion. The removal (Task 6) is one commit because splitting retarget from deletion would leave a red `test/` run un-attributable, and the session protocol answers red with `git reset --hard`.

---

## Task 1: Send the two payload-less board cases + request-case key guard

Pre-existing defect P1 (ANALYSIS §5.2, R1/P1): `redteam/cases/board.yaml:36,88` use a `data:` key under `request:`, but `redteam/harness.py:build_request` (lines 36–48) only reads `method`, `path`, `headers`, `json`, `params`. So `board-sqli-login-bypass` and `board-xss-img-onerror-in-comment` POST an empty body today — they carry no payload and cannot be detected for the reason they declare. Fix the YAML (not `harness.py`: it is core, and a new line grows `core_loc` past 461 — R9). Verified by scan: only these two cases carry `data:`; `default.yaml` request specs are clean, so the guard passes while `default.yaml` still exists.

**Files:**
- Modify: `redteam/cases/board.yaml:36` and `redteam/cases/board.yaml:88` (`data:` → `json:`)
- Create (guard 7): `platform/tests/test_case_payloads.py`

**Interfaces:**
- Consumes: `redteam/harness.py:build_request` request keys `{method, path, headers, json, params}` (lines 36–48).
- Produces: a standing guard that every request case in `redteam/cases/*.yaml` uses only those keys.

- [ ] **Step 1: Write the failing guard test**

Create `platform/tests/test_case_payloads.py`:

```python
from pathlib import Path

import yaml

ALLOWED_REQUEST_KEYS = {"method", "path", "headers", "json", "params"}
CASES_DIR = Path(__file__).resolve().parents[2] / "redteam" / "cases"


def _request_specs():
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            spec = case.get("request")
            if spec:
                yield path.name, case.get("name"), spec


def test_every_request_case_uses_only_keys_the_harness_sends():
    offenders = [
        (file, name, sorted(set(spec) - ALLOWED_REQUEST_KEYS))
        for file, name, spec in _request_specs()
        if set(spec) - ALLOWED_REQUEST_KEYS
    ]
    assert offenders == [], offenders
```

- [ ] **Step 2: Run the guard to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_case_payloads.py -v`
Expected: FAIL — offenders lists `board.yaml board-sqli-login-bypass ['data']` and `board.yaml board-xss-img-onerror-in-comment ['data']`.

- [ ] **Step 3: Fix the two cases**

In `redteam/cases/board.yaml`, change the key `data:` to `json:` in the `board-sqli-login-bypass` request (line 36) and the `board-xss-img-onerror-in-comment` request (line 88). The nested payload mappings are unchanged, e.g. the login case becomes:

```yaml
  request:
    method: POST
    path: /accounts/login/
    json:
      username: "' OR 1=1--"
      password: "anything"
```

and the comment case becomes:

```yaml
  request:
    method: POST
    path: /posts/1/comments/
    json:
      body: "<img src=x onerror=alert(1)>"
```

Detection is by the WAF/IDS seeing the request body; Django rejecting a JSON body on a form endpoint is fine.

- [ ] **Step 4: Run the guard to verify it passes, plus the harness tests**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_case_payloads.py tests/test_harness.py -v`
Expected: PASS (guard green; `test_harness.py::test_default_cases_survive_request_preparation` still green — it reads `default.yaml` here, which is clean).

- [ ] **Step 5: Commit**

```bash
git add redteam/cases/board.yaml platform/tests/test_case_payloads.py
git commit -m "fix(cases): board SQLi/XSS POST cases send their payload; guard request keys"
```

---

## Task 2: Harden the cloud WAF vhost for `/internal`

Pre-existing defect P2 (ANALYSIS §5.2 R2/P2, §1.2): `deploy/waf/range.conf` is the OpenStack/cloud WAF nginx config. Its `board.com` server (lines 35–47) has **no** `location /internal/ { return 404; }`, so on the cloud WAF the ground-truth endpoint is readable through `board.com` today. Mirror `deploy/nginx/board.conf:5-7`. This is the cloud path; the Docker path proves it live in Task 6. Per the memory note, the cloud is user-verified — this is a code change the user validates live later. Guard it statically (guard 5).

**Files:**
- Modify: `deploy/waf/range.conf:39-47` (board.com server block gains the `/internal/` 404)
- Create (guard 5): `platform/tests/test_internal_blocked_at_waf.py`

**Interfaces:**
- Consumes: the pattern in `deploy/nginx/board.conf:5-7` (`location /internal/ { return 404; }`).
- Produces: a standing static guard that every server block in `deploy/waf/range.conf` that proxies the board refuses `/internal/`.

- [ ] **Step 1: Write the failing guard test**

Create `platform/tests/test_internal_blocked_at_waf.py`:

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RANGE_CONF = ROOT / "deploy" / "waf" / "range.conf"


def _server_blocks(text):
    return re.findall(r"server\s*\{.*?\n\}", text, flags=re.DOTALL)


def test_the_cloud_waf_404s_internal_in_every_board_server_block():
    text = RANGE_CONF.read_text(encoding="utf-8")
    for block in _server_blocks(text):
        if "board:8000" in block:
            assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", block), block
```

- [ ] **Step 2: Run the guard to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_internal_blocked_at_waf.py -v`
Expected: FAIL — the board server block has no `/internal/` 404.

- [ ] **Step 3: Add the 404 to the board server in `deploy/waf/range.conf`**

Inside the `server { ... server_name board.com; ... }` block (around lines 39–47), add, before `location /`:

```
    location /internal/ {
        return 404;
    }
```

- [ ] **Step 4: Run the guard to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_internal_blocked_at_waf.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/waf/range.conf platform/tests/test_internal_blocked_at_waf.py
git commit -m "fix(waf): cloud WAF 404s /internal on the board vhost; guard it"
```

---

## Task 3: Remove the board's `members.json`; repoint the live loot-credit test

ON TOP of ANALYSIS scope (ANALYSIS did not cover `members.json`). `wargames/board/app/posts/views.py:10-11` (`members`) returns `list(User.objects.values())`, which includes the stored `password` verbatim — a deliberately-planted over-exposure endpoint. **Rationale (state in the commit):** `members.json` was a planted vulnerable page; the realistic exfil path is the unpatched-Django `order_by` SQL injection (CVE-2021-35042) via `?sort=`, which stays. Remove the planted page. The internal ground-truth read channel `/internal/auth-users` (`views.py:14-15`) is KEPT — it is scoring plumbing, not attacker-reachable (WAF 404s it, user decision #4). Keep the board's unit-test `TRUTH` fixtures and the loot submit/verify/credit tests intact.

`test/test_board_loot.py` currently exfiltrates via `members.json`. After removal, the live loot-credit test obtains the expected `auth_user` hashes through the platform's internal read channel — the SCORER reading `http://board:8000/internal/auth-users` over estate, exactly as `test/test_board_exfil.py::test_the_platform_reads_the_auth_user_hashes_over_estate` (lines 46–61) already does — and submits those, proving the verify-and-credit path without depending on a working live exfil.

**Files:**
- Modify: `wargames/board/app/posts/views.py:10-11` (delete the `members` view)
- Modify: `wargames/board/app/posts/urls.py:6` (delete the `members.json` route)
- Modify: `test/test_board_exfil.py:24-36` (delete `test_members_endpoint_leaks_real_password_hashes`)
- Modify: `test/test_board_loot.py:19-22` (repoint `_members_from_the_attacker` to the SCORER internal read channel; rename for honesty)

**Interfaces:**
- Consumes: `/internal/auth-users` served by the board to the platform over estate (`wargames/board/app/posts/views.py:14-15`); the acceptance `SCORER`/`run` helpers in `test/range.py`.
- Produces: a board app with no `members.json`; a loot-credit acceptance test that reads truth over estate and submits it.

- [ ] **Step 1: Delete the `members` view and its route**

In `wargames/board/app/posts/views.py` delete lines 10–11 (the `members` function and its trailing blank line), keeping `auth_users` (the internal endpoint) and everything else. In `wargames/board/app/posts/urls.py` delete line 6 (`path("members.json", views.members, name="members"),`), keeping the `internal/auth-users` route and the rest.

- [ ] **Step 2: Delete the members leak acceptance test and repoint the loot test**

In `test/test_board_exfil.py` delete `test_members_endpoint_leaks_real_password_hashes` (lines 24–36). Keep `test_the_internal_ground_truth_is_blocked_through_the_waf` and `test_the_platform_reads_the_auth_user_hashes_over_estate`.

In `test/test_board_loot.py` replace the `_members_from_the_attacker` helper (lines 19–22) with a read over estate via the SCORER, mirroring `test_board_exfil.py:46-61`:

```python
def _auth_users_over_estate():
    body = run(SCORER, [
        "python3", "-c",
        "import urllib.request,sys; "
        "sys.stdout.write(urllib.request.urlopen("
        "'http://board:8000/internal/auth-users', timeout=20).read().decode())",
    ]).stdout
    return json.loads(body)
```

Update the import at the top of `test/test_board_loot.py` from `from range import ATTACKER, run` to `from range import SCORER, run`, and change the call site in `test_submitting_the_exfiltrated_hashes_credits_the_full_ladder` (line 34) and the row-building that follows (lines 34–35) to:

```python
    truth = _auth_users_over_estate()
    rows = [{"username": name, "hash": digest} for name, digest in truth.items()]
```

Leave `test_fabricated_loot_is_refused_against_the_live_snapshot` unchanged (it submits a fabricated plaintext row and asserts `credited == []`).

- [ ] **Step 3: Verify the board app imports and the unit suite is unaffected**

Run: `cd platform && ../.venv/bin/python -m pytest tests -q`
Expected: PASS (no unit test imports `members`; `test_loot_submit.py`/`test_loot_scoring.py` only use the string `"board-members-json"` as a fabricated case label, not the endpoint).

- [ ] **Step 4: Prove live on the stack**

Bring the stack up if needed (`docker compose up -d --build`), then run the board acceptance tests:

Run: `cd test && ../.venv/bin/python -m pytest test_board_exfil.py test_board_loot.py -v`
Expected: PASS — `/members.json` is gone; the loot ladder still credits from hashes read over estate; the fabricated-loot test still refuses.

- [ ] **Step 5: Commit**

```bash
git add wargames/board/app/posts/views.py wargames/board/app/posts/urls.py test/test_board_exfil.py test/test_board_loot.py
git commit -m "fix(board): remove members.json over-exposure; loot test reads truth over estate

members.json was a planted User.objects.values() leak; the realistic exfil path
is the unpatched-Django order_by SQLi (CVE-2021-35042) via ?sort=, which stays.
/internal/auth-users (platform->board over estate, WAF-404) is unaffected."
```

---

## Task 4: Flip the default scenario to `board`; retarget the flip/rename-coupled unit tests

ANALYSIS §5.1 step "4a", unit half. Flip the defaults so a session with no scenario is a board session, and retarget every unit test that breaks **from the flip, the case/URL/port renames, and the settings changes** while `platform/objectives.py` and Juice still exist. Tests that break only because `import objectives` disappears, or that assert `_nothing_solved`/`_achieved`/`TARGET_SETTLE`/wiki behaviour, are **deferred to Task 6** — the code they assert against changes there. This task does not need the live stack.

**Default-flip rule (R5):** `POST /api/sessions/ {}` and `Session.objects.create()` with no scenario now take the `loot_verified` branch, which calls `loot.ground_truth` → `urllib.request.urlopen("http://board:8000/internal/auth-users")`. Add an autouse guard (step 1) so no unit test makes a real network read, before flipping.

**Files:**
- Modify: `platform/tests/conftest.py` (add autouse `no_real_board_read`)
- Modify: `platform/api/views.py:166-168` (default scenario `"juice-shop"` → `"board"`)
- Modify: `platform/api/models.py:7` (`Session.scenario` default `"juice-shop"` → `"board"`)
- Create: `platform/api/migrations/0013_alter_session_scenario_default.py`
- Modify: `redteam/harness.py:26,79` (core — two same-line replacements only)
- Modify: `redteam/run.py:22,25` (`DEFAULT_CASES` → `board.yaml`; `--target` default → `http://board.com`)
- Modify: `platform/fsl/settings.py:67,69,70` (URL defaults `shop.com`/`localhost:8080` → `board.com`)
- Create (guard 9): `platform/tests/test_migration_state.py`
- Modify: the flip/rename-coupled unit tests per ANALYSIS §3.3 (see step 7)

**Interfaces:**
- Consumes: `wargames.WARGAMES["board"]` with `objective_model: "loot_verified"` (unchanged); `api.views.loot.ground_truth(scenario)` (`platform/api/loot.py:19-29`).
- Produces: `board` as the default scenario everywhere; a fast unit suite that never reads the live board; model state equal to migration state.

- [ ] **Step 1: Add the autouse guard against a real board read (write it, then rely on it)**

In `platform/tests/conftest.py`, add an autouse fixture modelled on `no_real_substrate` (lines 28–51). It makes `loot.ground_truth` raise `GroundTruthUnavailable` unless a test opts out with a marker, so a board-default session start records `baseline = None` without a 15 s socket timeout:

```python
@pytest.fixture(autouse=True)
def no_real_board_read(request):
    if request.node.get_closest_marker("reads_ground_truth"):
        yield
        return
    from api import loot

    def refuse(wargame_id):
        raise loot.GroundTruthUnavailable(
            f"this unit test supplied no board; ground_truth({wargame_id!r}) was "
            f"refused. A test that needs it must patch api.views.loot.ground_truth "
            f"or mark reads_ground_truth"
        )

    with patch("api.views.loot.ground_truth", refuse):
        yield
```

Register the marker so `-W error` on unknown markers does not fire: add to `platform/pytest.ini` under `[pytest]` a `markers =` entry `reads_ground_truth: the test provides its own board ground-truth stub` (append to the existing `markers =` list; keep `stands_in_for_docker`).

- [ ] **Step 2: Run a broad slice to confirm the guard holds and nothing hangs**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_api_sessions.py tests/test_session_start.py -v`
Expected: these FAIL on assertions (scenario still defaults to `juice-shop`), not on timeouts — confirms the guard short-circuits the board read.

- [ ] **Step 3: Flip the defaults (platform + harness + run + settings)**

`platform/api/views.py:166-168` — change the fallback:

```python
    scenario = _payload(request).get("scenario")
    if scenario is None:
        scenario = "board"
```

`platform/api/models.py:7` — `scenario = models.CharField(max_length=128, default="board")`.

`redteam/harness.py` — two same-line replacements only (keep line count): line 26 `DEFAULT_TOOL_TARGET = "http://board.com"`; line 79 `json={"scenario": "board"}`.

`redteam/run.py` — line 22 `DEFAULT_CASES = Path(__file__).resolve().parent / "cases" / "board.yaml"`; line 25 `parser.add_argument("--target", default="http://board.com")`.

`platform/fsl/settings.py` — line 67 `ATTACKER_TARGET_URL` default `"http://board.com"`; line 69 `TARGET_URL` default `"http://board.com"`; line 70 `PUBLIC_TARGET_URL` default `"http://board.com"`. (Leave `BOARD_PUBLIC_URL`, `WIKI_*`, `WARGAME_API_URL`, `TARGET_SETTLE` for Task 6.)

- [ ] **Step 4: Write the migration and its state guard (guard 9)**

Create `platform/api/migrations/0013_alter_session_scenario_default.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("api", "0012_remove_session_truncated")]

    operations = [
        migrations.AlterField(
            model_name="session",
            name="scenario",
            field=models.CharField(default="board", max_length=128),
        ),
    ]
```

Confirm the real name of the latest `api` migration first and set `dependencies` to it:

Run: `ls platform/api/migrations/`

Create `platform/tests/test_migration_state.py`:

```python
import os

import django
from django.core.management import call_command


def test_model_state_matches_the_migrations():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")
    django.setup()
    call_command("makemigrations", "api", check=True, dry_run=True, verbosity=0)
```

Leave the historical `0001_initial.py:29` `default='juice-shop'` alone (ANALYSIS §1.6: Django-side only, no DB default, harmless; rewriting it is wrong).

- [ ] **Step 5: Run the migration guard**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_migration_state.py -v`
Expected: PASS (no pending migration). If it FAILS with "would create migration", the `dependencies` name is wrong — fix it to the actual latest migration and retry.

- [ ] **Step 6: Run the whole unit suite to see what the flip broke**

Run: `cd platform && ../.venv/bin/python -m pytest tests -q`
Expected: a set of failures confined to the flip/rename-coupled files below. Use this list as the work queue for step 7.

- [ ] **Step 7: Retarget the flip/rename-coupled unit tests (ANALYSIS §3.3 is the per-test authority)**

Apply the §3.3 "A"/"CF" edits **only** to tests that fail now with `objectives.py` still present. These recurring transformations cover them; the exact per-file lines are in ANALYSIS §3.3:

| transformation | applies to |
|---|---|
| case name `sqli-login-bypass` → `board-sqli-search`; `sqlmap-boolean-blind` → `board-sqli-orderby-sqlmap`; `normal-product-search` → `board-normal-search`; `sqli-union-user-table` → `board-sqli-union-search`; `path-traversal-ftp` → `board-path-traversal-static` | test_api_corroboration, test_origins, test_substrate_cost, test_tools, test_map, test_lifecycle, test_tool_cases, test_slot-adjacent fixtures |
| catalogue/path `default.yaml` → `board.yaml`; `cases("juice-shop")` → `cases("board")`; `/api/wargames/juice-shop/cases/` → `/api/wargames/board/cases/` | test_catalogue, test_harness, test_lifecycle, test_api_redteam (`a_case` fixture) |
| scenario `"juice-shop"` → `"board"` in request/fixture bodies; `patch("api.views.objectives.solved_keys")` → `patch("api.views.loot.ground_truth")` returning a `{username: hash}` map | test_api_sessions, test_session_start |
| host/image name `fsl-juice-shop`/`fsl-wiki` → `fsl-board`; `runner("wiki")` → `runner("sensor")` where the role is incidental | test_openstack_images, test_openstack_sketch, test_slot, test_docker_runner |
| CF infra flips: `["juice-shop","board"]` → `["board"]`; `"juice-shop" in i` → `"mysql" in i`; WAF names `{"shop.com","board.com"}` → `{"board.com"}`; `"3000"` → `"8000"`; `services["wiki"]`/role `wiki` → `services["board-db"]`/role `board-db`; openstack-slot estate assertion → `fsl-board`/`board board-db` | test_api_redteam, test_compose, test_flavor, test_sensor_rules, test_declaration, test_openstack_slot, test_board_wargame (drop the juice public_url assert) |
| `test_loot_submit::test_a_non_loot_wargame_refuses_loot` → `patch.dict(wargames.WARGAMES, {"detect": {...board fields..., "objective_model": "none"}})`, scenario `"detect"` → 400 (keeps the `none` branch covered now and after removal) | test_loot_submit |

Representative real edit — `patch` retarget in a session-start unit test (pattern for test_api_sessions / test_session_start):

```python
from unittest.mock import patch


def test_create_session_returns_id_and_start_time(client):
    with patch("api.views.loot.ground_truth", return_value={"admin": "pbkdf2_sha256$x"}):
        created = client.post_json("/api/sessions/", {"scenario": "board"})
    assert created.status_code == 201
    body = created.json()
    assert body["scenario"] == "board"
    assert body["started_at"]
```

**Defer to Task 6 (do NOT edit here)** — these fail only on `import objectives` / assert removed behaviour: `test_api_ready` (nothing_solved/collateral), `test_channels` (wiki/collateral), `test_api_objectives`, `test_objective_descriptions`, `test_objective_stamps`, `test_session_close` (BR/BD), `test_wiki_read`, `test_range_seam` (needs `test/range.py` `TARGET`/`ROLES` change), `test_wargames_objective_model` (the `self_judged` CD test). While `objectives.py` still exists, these pass as-is or are not reached by the flip; if any fails now purely from the flip (e.g. a session-creating test in these files), apply the minimal scenario/patch retarget to it and leave the rest to Task 6.

Apply edits file-by-file, re-running that file after each:
Run (example): `cd platform && ../.venv/bin/python -m pytest tests/test_api_corroboration.py -v`

- [ ] **Step 8: Run the whole unit suite green**

Run: `cd platform && ../.venv/bin/python -m pytest tests -q`
Expected: PASS. `objectives.py` is untouched; Juice-only/collateral tests still pass against the still-present `objectives.py`.

- [ ] **Step 9: Commit**

```bash
git add platform/tests/conftest.py platform/pytest.ini platform/api/views.py platform/api/models.py platform/api/migrations/0013_alter_session_scenario_default.py platform/tests/test_migration_state.py redteam/harness.py redteam/run.py platform/fsl/settings.py platform/tests/
git commit -m "refactor(scenario): default sessions to the board; retarget flip-coupled unit tests

Flips scenario default juice-shop->board (views, models + migration 0013, harness,
run, settings URLs). Retargets the unit tests coupled to the default, case names,
URLs and ports onto the board while objectives.py/Juice still exist. Adds an autouse
guard against a real board read in unit tests and a makemigrations --check guard."
```

---

## Task 5: Retarget the flip/rename-coupled acceptance tests; prove board-first acceptance live

ANALYSIS §5.1 step "4a", acceptance half, plus the central `test/` plumbing. Point the acceptance suite's shared helpers and the flip/rename-coupled acceptance tests at the board, and **pin the Juice-only acceptance tests** (`test_inside.py`, `test_case_objectives.py`, `test_objectives.py`'s Juice cases) to an explicit `{"scenario": "juice-shop"}` / `http://shop.com` so they stay green one more step. Then a full live `bin/verify` proves the board alone satisfies TP > 0, TN > 0 and every retargeted acceptance test *before* anything is destroyed. This is the step that surfaces R4-type surprises (encoding distinctions, rule coverage) while Juice is still available to compare against.

**Files:**
- Modify: `test/conftest.py:16` (`TARGET_PUBLIC` → `http://board.com`); `:156-164` `from_attacker` URL → `board.com`
- Modify: the flip/rename-coupled acceptance tests per ANALYSIS §3.4 (case names, paths, `PUBLIC_HOST`, `ATTACK_PATH`/`BENIGN_PATH`)
- Modify (pin to Juice): `test/test_inside.py`, `test/test_case_objectives.py`, the two Juice cases in `test/test_objectives.py`
- Leave `test/range.py` as-is this task (its `TARGET`/`WIKI`/`ROLES` edits are removal-coupled; `reset_target()` still truncates the wiki log, which still exists)

**Interfaces:**
- Consumes: board acceptance control cases proven by `test/test_board.py` — `board-sqli-search` (GET SQLi, detected), `board-normal-search` / `board-normal-search-with-apostrophe` (benign, TN).
- Produces: an acceptance suite whose generic tests run against the board; Juice-only tests still pinned to Juice.

- [ ] **Step 1: Point the shared acceptance helpers at the board**

In `test/conftest.py`: line 16 `TARGET_PUBLIC = "http://board.com"`; in `from_attacker` (lines 156–164) change `http://shop.com{path}` to `http://board.com{path}`. Leave `reset_target()` (it still calls `forget_wiki_reads()` + `recreate(TARGET)`; both still work while Juice/wiki exist).

- [ ] **Step 2: Retarget the flip/rename-coupled acceptance tests (ANALYSIS §3.4 is the per-test authority)**

Recurring transformations (exact lines in §3.4):

| transformation | applies to |
|---|---|
| probe/attack path `/rest/products/search?q=...` → `/search/?q=...`; `ATTACK_PATH` → `/search/?q=%27%20OR%201%3D1--`; `BENIGN_PATH` `q=apple` → `/search/?q=release` | test_attacker_box, test_event_time, test_front_door, test_strategy_comparison, test_window_correlation, test_strategy_honesty |
| case name `sqli-login-bypass` → `board-sqli-search`; `sqlmap-boolean-blind` → `board-sqli-orderby-sqlmap`; `path-traversal-ftp` → `board-path-traversal-static` (silenced), control → `board-sqli-search`; `sqli-union-user-table` → `board-sqli-union-search`; `normal-product-search` → `board-normal-search` | test_bufferless_rule, test_suppression, test_tool_cases, test_map, test_origins, test_topology (drawn fixture), test_front_door, test_strategy_honesty, test_indiscriminate_defence (full CASES list per §3.4 L449-451) |
| `PUBLIC_HOST` `"shop.com"` → `"board.com"` | test_attacker_box |
| evasion percent/plus pair → `board-sqli-search` / `board-sqli-union-search` (degrades to "both SQLi shapes are detected" — the percent-vs-plus distinction has no board pair, R4) | test_evasion |
| CF infra: `TARGET_INSIDE http://juice-shop:3000/` → `http://board:8000/`; `WAF_INSIDE http://shop.com/` → `http://board.com/`; `segments(TARGET)` → `segments(BOARD)`; node name `fsl-juice-shop` → `fsl-board`; `NOISY_RULE content:"apple"` → a board benign word e.g. `"release"` | test_segmentation, test_topology (`test_the_target_is_only_ever_on_the_inside`), test_acceptance (criterion 4) |

For `test_segmentation` and `test_topology`'s `segments(BOARD)`, `BOARD` is not yet exported by `test/range.py` (added in Task 6). This task keeps those two using `TARGET` **only if** `TARGET` still resolves to a board-reachable host; since `TARGET` maps to `fsl-juice-shop` until Task 6, pin these two assertions' host to the literal `"fsl-board"`/`http://board:8000/` and the segment lookup to a board-standing role that exists now. If a clean retarget is not possible without the Task 6 `range.py` change, pin that single test to Juice here and move its board retarget into Task 6 (note it in the commit).

- [ ] **Step 3: Pin the Juice-only acceptance tests to Juice**

In `test/test_inside.py`, `test/test_case_objectives.py`, and the two Juice-objective tests in `test/test_objectives.py`, make every session creation explicit `{"scenario": "juice-shop"}` and every target URL `http://shop.com`, so the default flip does not change what they exercise. These are deleted or repurposed in Task 6; here they only need to stay green with Juice still running.

- [ ] **Step 4: Full live `bin/verify` (board-first, Juice still present)**

Ensure the stack is up and rebuilt for the new cases:
```bash
docker compose up -d --build
```
Run: `bin/verify`
Expected: GREEN. The board's own cases give TP > 0 and TN > 0; every retargeted acceptance test passes against the board; the pinned Juice-only tests pass against Juice; the ratchet sees no gated growth and no floor shrink (the count rose from the guards added in Tasks 1–2 and the migration/payload guards).

If red: `git reset --hard` and report which retarget did not hold on the board (R4 candidates: `test_evasion`, `test_suppression`, `test_bufferless_rule`, `test_rule_variables`). A test that cannot hold on the board is a redesign, recorded, not forced.

- [ ] **Step 5: Commit**

```bash
git add test/
git commit -m "test(acceptance): retarget generic acceptance onto the board; pin Juice-only tests

Shared helpers and flip/rename-coupled acceptance tests now run against board.com
and the board cases; Juice-only tests pinned to {scenario: juice-shop}/shop.com for
one more step. Live bin/verify green: board alone gives TP>0, TN>0."
```

---

## Task 6: Destructive removal — delete Juice, the wiki, `self_judged`, and `objectives.py` (one commit)

ANALYSIS §5.1 step "4b". One atomic commit (otherwise a red `test/` run is un-attributable). This deletes the Juice/wiki stack, `platform/objectives.py`, the `self_judged` value and its three view branches, the `default.yaml` cases, the `shop.com` vhost and Juice/wiki settings; collapses the gates (ANALYSIS §2); replaces the READY "nothing solved" check (H2); drops `TARGET_SETTLE`; deletes the Juice-only tests (BD/CD); repurposes the `self_judged`/stamp/close tests onto board loot behaviour (BR, ANALYSIS §3.6); adds the remaining removal guards; and hardens the Docker default vhost for `/internal` (R2, guard 6 + an IP-Host acceptance probe). Decision defaults adopted: H2 (ground-truth-readable), H3 (wiki/lateral-movement shelved), H5 (keep `POST /objectives/`, drop the sleep/`TARGET_SETTLE`/`unobserved`), H8 (keep stored Juice sessions), H9 (drop `shop.com`, keep `PUBLIC_TARGET_URL`).

**Files — product code:**
- Delete: `platform/objectives.py`
- Modify: `platform/api/refusals.py:5,14`; `platform/api/views.py` (imports, gates, READY, canary — lines below); `platform/wargames.py:14-21,31`; `platform/fsl/settings.py:69-77`
- Modify: `redteam/run.py` already points at board (Task 4) — no change
- Delete: `redteam/cases/default.yaml`

**Files — stack/deploy/data:**
- Delete: `wargames/juice-shop/` (`git rm -r`), `wargame/juice-shop/README.md` (`git rm -r wargame`)
- Modify: `compose.yaml:57,71-72,76,88,101,169-170,194-195`; `platform/range/declaration.yaml:54-55,67-76,102`; `deploy/waf/range.conf:10-33,35`; `deploy/waf/setup.sh:66`; `deploy/suricata/suricata.yaml:8`; `deploy/kali/setup.sh:49-50`, `deploy/kali/motd:15`; `bin/verify:75,79`; `.gitignore:9-10`; `deploy/nginx/board.conf` (default vhost + already has `/internal/` 404)

**Files — acceptance plumbing & tests:**
- Modify: `test/range.py:17,19,23-24,29-38,61-62,80,85,181-184` (drop `TARGET`/`WIKI`/node-reporter; add `BOARD`, `BOARD_DB`); `test/conftest.py:122-137` (`reset_target`), `:10-11` imports, `session_id` fixture
- Delete / repurpose / add tests per ANALYSIS §3.3, §3.4, §3.6 and the guard list below

**Interfaces:**
- Consumes: `api.views.loot.ground_truth("board")` (`platform/api/loot.py:19`), `wargames.objective_model` / `wargames.objectives` (`platform/wargames.py:36,42`), `scoreboard`/`game` (unchanged).
- Produces: `objective_model` ∈ {`loot_verified`, `none`} only; a board-only stack; the removal guards as standing tests.

### 6A — collapse the objective gates and READY (product code, test-first)

- [ ] **Step 1: Write/adjust the `none`-branch and guard tests first**

Add `platform/tests/test_objective_model_values.py` (guards 1–3):

```python
from unittest.mock import patch

import wargames


def test_every_wargame_model_is_loot_verified_or_none():
    for entry in wargames.WARGAMES.values():
        assert entry["objective_model"] in {"loot_verified", "none"}, entry


def test_a_none_model_lists_no_objectives(client):
    detect = dict(wargames.WARGAMES["board"], id="detect", objective_model="none")
    with patch.dict(wargames.WARGAMES, {"detect": detect}):
        listed = client.get("/api/wargames/detect/objectives/")
    assert listed.status_code == 200
    assert listed.json() == []


def test_a_none_model_observes_nothing(client):
    detect = dict(wargames.WARGAMES["board"], id="detect", objective_model="none")
    with patch.dict(wargames.WARGAMES, {"detect": detect}):
        created = client.post_json("/api/sessions/", {"scenario": "detect"})
        session_id = created.json()["id"]
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json() == {"achieved": 0, "total": 0}
```

- [ ] **Step 2: Run them to confirm they fail against the current gates**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_objective_model_values.py -v`
Expected: FAIL — the `none`/`self_judged` branches still call `objectives.*`.

- [ ] **Step 3: Collapse the gates in `platform/api/views.py`**

Drop `import objectives` (line 27) and `CLOCK_SLACK` (line 81).

Session-start baseline (lines 182–194) becomes:

```python
    baseline = []
    if wargames.objective_model(scenario) == "loot_verified":
        try:
            baseline = loot.ground_truth(scenario)
        except loot.GroundTruthUnavailable:
            baseline = None
```

`wargame_objectives` (lines 373–378) becomes:

```python
    model = wargames.objective_model(wargame_id)
    if model == "none":
        return _reply([])
    return _reply(_loot_catalogue(wargames.objectives(wargame_id)))
```

`_observe_objectives` (lines 404–443) collapses to:

```python
def _observe_objectives(session) -> dict:
    return {"achieved": 0, "total": session.objectives.count()}
```

`_settle_and_observe` (lines 581–586) loses the sleep and the dead except:

```python
def _settle_and_observe(session):
    return _observe_objectives(session)["achieved"]
```

`close_session` (lines 617–629) loses the `unobserved` try/except and reply key:

```python
    closed_at = timezone.now()
    if not Session.objects.filter(pk=session.pk, ended_at=None).update(ended_at=closed_at):
        session.refresh_from_db()
        _refuse_closed(session)
    session.ended_at = closed_at
    reply = _shape(session, SESSION_FIELDS)
```

Delete `_achieved` entirely (lines 947–963).

Replace `_nothing_solved` (lines 1243–1247) with a ground-truth-readable check (H2):

```python
def _ground_truth_readable(adapter) -> bool:
    try:
        loot.ground_truth("board")
        return True
    except loot.GroundTruthUnavailable:
        return False
```

In `_range_ready` (lines 1264–1297) rename the check key and its uses: `checks["nothing_solved"]` → `checks["ground_truth"]` (value `_ground_truth_readable(adapter)`), update the `elif not (checks["ground_truth"] and checks["rules_baseline"])` guard, and change the blocked message (lines 1283–1284) to:

```python
    if not checks["ground_truth"]:
        blocked.append("the target's ground truth could not be read")
```

Retarget `CANARY_CASE` (lines 1306–1315) to a path the board serves:

```python
CANARY_CASE = {
    "name": "range-canary",
    "malicious": True,
    "correlation": "marker",
    "request": {
        "method": "GET",
        "path": "/search/",
        "params": {"q": "' OR 1=1--"},
    },
}
```

`platform/api/refusals.py`: drop `import objectives` (line 5) and the `objectives.ObjectivesUnavailable` entry from `UNAVAILABLE` (line 14).

- [ ] **Step 4: Run the `none`-branch guards green**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_objective_model_values.py -v`
Expected: PASS.

### 6B — delete `objectives.py`, `self_judged`, Juice settings, the cases file

- [ ] **Step 5: Remove the module, the enum value, the settings**

`git rm platform/objectives.py`.

`platform/wargames.py`: delete the whole `"juice-shop"` entry (lines 14–21); set the board's `public_url` to `settings.PUBLIC_TARGET_URL` (line 31, replacing `settings.BOARD_PUBLIC_URL`). Keep `objective_model()`/`judged()`/`objectives()` (lines 36–47) — `none` stays a legal value.

`platform/fsl/settings.py`: delete `BOARD_PUBLIC_URL` (line 71), `WIKI_READ_LOG`/`WIKI_SECRET_PATH`/`WARGAME_API_URL` (lines 73–75), `TARGET_SETTLE` (line 77). In `platform/tests/conftest.py` delete the `no_settle` autouse fixture (lines 24–26), which referenced `TARGET_SETTLE`.

`git rm redteam/cases/default.yaml`.

- [ ] **Step 6: Delete the Juice/wiki-only unit tests (BD/CD) and the collateral importers that cannot be salvaged**

Delete per ANALYSIS §3.3 (BD/CD rows): all of `test_wiki_read.py` (18); the 4 wiki tests in `test_channels.py` (keep the 6 proxy/channel A tests, removing their `import objectives`); all 8 of `test_objective_descriptions.py`; the BD rows in `test_api_objectives.py`, `test_objective_stamps.py`, `test_session_close.py`; the `self_judged` CD test in `test_wargames_objective_model.py` and the wiki-healthcheck CD in `test_deployment.py`; the no-shell node-reporter CD in `test_range_seam.py`. Fix the collateral A tests in `test_api_ready.py`, `test_channels.py`, `test_session_close.py`, `test_docker_runner.py`, `test_session_start.py` by removing `import objectives` and retargeting `objectives.solved_keys`/`runner("wiki")` patches to `api.views.loot.ground_truth` / `runner("sensor")` as §3.3 prescribes. For `test_api_ready.py`, retarget the `nothing_solved` tests to the new `ground_truth` check (patch `api.views.loot.ground_truth` with `side_effect=loot.GroundTruthUnavailable` to drive "not ready"; the check key is now `ground_truth`).

- [ ] **Step 7: Repurpose the BR tests onto distinct board loot behaviour (ANALYSIS §3.6)**

The 14 platform BR slots each assert a distinct board/loot behaviour; all patch `api.views.loot.ground_truth` to a fixed `{username: hash}` map (as `test_loot_submit.py` already does), or call the pure `_loot_window`. Use the §3.6 table verbatim. Representative repurpose — `test_objective_stamps.py` millisecond/no-stamp windows become pure `_loot_window` assertions:

```python
from datetime import timedelta

from django.utils import timezone

import scoreboard
from api.views import _loot_window
from api.models import Case, Session


def test_a_loot_window_with_a_case_is_the_case_interval(db):
    session = Session.objects.create(scenario="board")
    now = timezone.now()
    case = Case.objects.create(
        session=session, case_id="c1", name="board-sqli-search", malicious=True,
        correlation="marker", started_at=now - timedelta(seconds=2), ended_at=now,
    )
    at, earliest, latest = _loot_window(session, "c1", now + timedelta(seconds=30))
    assert at == case.ended_at
    assert earliest == case.started_at - scoreboard.CLOCK_SKEW
    assert latest == case.ended_at + scoreboard.CLOCK_SKEW


def test_a_loot_window_without_a_case_uses_the_attribution_window(db):
    session = Session.objects.create(scenario="board")
    now = timezone.now()
    at, earliest, latest = _loot_window(session, None, now)
    assert at == now
    assert earliest == now - scoreboard.ATTRIBUTION_WINDOW
    assert latest == now + scoreboard.CLOCK_SKEW
```

The acceptance BR (15th, `test/test_objectives.py`) becomes: fire a detected board case (`board-sqli-search`), read `/internal/auth-users` over estate (as in Task 3's helper), `POST /loot/` with that `case_id`, assert the score's breach `detected` equals the case's. Mark it `reads_ground_truth` only if run as a unit; as acceptance it uses the live board.

Also disambiguate the duplicated twins (ANALYSIS P4): `test_board_wargame.py` and `test_loot_session_start.py` — give one of each pair the BR #1 field-shape assertion (name/category/difficulty/solved:false/solved_at:null per tier) rather than deleting, to avoid an extra −2 on the floor.

- [ ] **Step 8: Run the full unit suite green (objectives.py gone)**

Run: `cd platform && ../.venv/bin/python -m pytest tests -q`
Expected: PASS, 0 failures, no collection/import errors. If any test still imports `objectives` or patches `objectives.*`, it was missed in steps 6–7.

### 6C — tear down the Juice/wiki stack and acceptance plumbing

- [ ] **Step 9: Remove the Juice/wiki directories, compose include, declaration, vhost, settings in deploy**

`git rm -r wargames/juice-shop wargame`.

`compose.yaml`: drop `- wargames/juice-shop/compose.yaml` from `include:` (line 57); change `waf.depends_on` (lines 71–72) to `board: {condition: service_healthy}` (accepting the MySQL warm-up delay) or remove the block; `aliases: [shop.com, board.com]` → `[board.com]` (line 76); `BACKEND: "http://board:8000"` (line 88); kali `FSL_TARGET`/`FSL_TARGET_HOST` → `board.com` (lines 169–170); platform `TARGET_URL`/`PUBLIC_TARGET_URL` → `http://board.com` (lines 194–195). (The WAF default-vhost `/internal` hardening is step 11.)

`platform/range/declaration.yaml`: delete roles `target: fsl-juice-shop` and `wiki: fsl-wiki` (lines 54–55); delete the `fsl-juice-shop` and `fsl-wiki` host entries (lines 67–76); OpenStack WAF `names: [shop.com, board.com]` → `[board.com]` (line 102).

`deploy/waf/range.conf`: delete the `shop.com` server (lines 10–33); make the `board.com` server `listen 80 default_server;` (line 36) and keep its `/healthz` and the `/internal/` 404 added in Task 2.

`deploy/waf/setup.sh:66`: `echo "127.0.0.1 juice-shop board"` → `127.0.0.1 board`.

`deploy/suricata/suricata.yaml:8`: `HTTP_PORTS: "[80,3000]"` → `"[80,8000]"`.

`deploy/kali/setup.sh:49-50` + `deploy/kali/motd:15`: `FSL_TARGET`/`_HOST` → `board.com`; sqlmap example `/rest/products/search?q=1` → `/search/?q=1`.

`bin/verify:75,79`: `fsl-juice-shop` → `fsl-board`.

`.gitignore:9-10`: drop the `wargames/juice-shop/wiki/logs` lines.

- [ ] **Step 10: Fix the acceptance plumbing (`test/range.py`, `test/conftest.py`)**

`test/range.py`: drop `TARGET` (line 17), `WIKI` (line 19), `WIKI_READ_LOG` (line 24); add `BOARD = "board"` and `BOARD_DB = "board-db"`; set `ROLES = (ATTACKER, BOARD, BOARD_DB, SENSOR, GATEWAY)` (line 23); delete the Juice-only node-reporter helpers `TARGET_NODE`/`NODE_REPORT` (lines 29–36), `through_node` (lines 61–62), `WITHOUT_A_SHELL` (line 80, and its use in `DOCKER_HOSTS` line 85), and `forget_wiki_reads` (lines 181–184).

`test/conftest.py`: remove `forget_wiki_reads`/`TARGET` from the import (lines 10–11); delete `reset_target()` (lines 122–137) and make the `session_id` fixture just `return run_redteam()` (the board has no persistent score state to reset); any acceptance test that imported `BOARD`/`BOARD_DB` from `range` now resolves (completes the two `test_segmentation`/`test_topology` retargets deferred from Task 5, step 2).

### 6D — harden the Docker default vhost for `/internal` (R2, guard 6 + IP-Host probe)

- [ ] **Step 11: Write the IP-Host acceptance probe first**

With `BACKEND` now `board:8000`, any request whose Host is not `board.com` reaches the board through the WAF's default vhost. Add to `test/test_board_exfil.py` a probe by raw IP Host (not `board.com`), alongside the existing `board.com` probe:

```python
def test_the_internal_ground_truth_is_blocked_by_any_host(stack_is_up):
    from range import ATTACKER, run

    waf = run(ATTACKER, ["getent", "hosts", "board.com"]).stdout.split()[0]
    code = run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                          "--max-time", "20", "-H", "Host: not-board",
                          f"http://{waf}/internal/auth-users"]).stdout.strip()
    assert code == "404", (
        "the WAF default vhost served /internal to a non-board.com Host; the "
        "ground truth must be reachable only platform->board over estate"
    )
```

Add the static guard 6 to `platform/tests/test_internal_blocked_at_waf.py`:

```python
def test_the_docker_board_vhost_is_default_and_404s_internal():
    conf = (ROOT / "deploy" / "nginx" / "board.conf").read_text(encoding="utf-8")
    assert "default_server" in conf
    assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", conf), conf
```

- [ ] **Step 12: Make the board the single default vhost in Docker**

Edit `deploy/nginx/board.conf` so its server is the WAF's default vhost: `listen 80 default_server;` (line 2). It already 404s `/internal/` (lines 5–7) and proxies the board. Ensure the WAF image's own generated default server no longer coexists as a second default: the OWASP CRS image generates `/etc/nginx/conf.d/default.conf` from `BACKEND` at startup. Mount `deploy/nginx/board.conf` so it **replaces** that generated default (e.g. mount it at `/etc/nginx/conf.d/default.conf`, or at the image's template path, read-only) rather than sitting beside it — adjust the `compose.yaml` volume for `board.conf` (line 101) accordingly. The exact image mechanism (conf.d vs templates + envsubst) is confirmed live in step 13; iterate the mount/`listen` until the IP-Host probe returns 404 with no nginx "duplicate default server" error. The IP-Host probe is the gate.

### 6E — prove the whole board-only stack green

- [ ] **Step 13: Rebuild the board-only stack and run live `bin/verify`**

Orphan removal is required (compose does not stop containers whose include was removed — R10) and the WAF must recreate (its `BACKEND`, vhost mount and dependency changed):

```bash
docker compose up -d --build --remove-orphans
docker compose up -d --force-recreate waf suricata
```

Confirm `fsl-juice-shop` and `fsl-wiki` are gone (`docker ps`), then:

Run: `bin/verify`
Expected: GREEN on the board-only stack — unit suite, acceptance (TP > 0, TN > 0 from board cases), the IP-Host `/internal` probe 404, and the ratchet (gated numbers flat or dropped: `services` 7, `wargame_services` 4 → 2, `product_loc` down, `core_loc` 461). The `tests` count has dropped below the floor; `bin/verify` will report the floor breach — that is expected and is resolved only in Task 8. If any other failure appears, `git reset --hard` and report.

- [ ] **Step 14: Commit the removal (do not adjust the floor yet)**

```bash
git add -A
git commit -m "feat(board-only): remove Juice Shop, the wiki, self_judged and objectives.py

Deletes the Juice/wiki stack, platform/objectives.py, the self_judged value and its
three view branches, default.yaml and the shop.com vhost. objective_model is now
loot_verified|none. READY checks ground-truth-readable in place of nothing-solved.
Docker default vhost 404s /internal by any Host. Juice-only tests deleted; the
self_judged/stamp/close tests repurposed onto board loot behaviour; removal guards
added. tests count is below the floor pending Task 8 (user-authorised)."
```

---

## Task 7: Documentation (no metric impact)

ANALYSIS §5.1 step "4c" and H6. Surgical edits only; docs and `CLAUDE.md` are not counted by `bin/measure`. Reply-language rule: keep English in the repo; the Korean docs (`*.ko.md`) are edited only to track the English ones.

**Files:** `CLAUDE.md`, `README.md`, `README.ko.md`, `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE.ko.md`, `docs/THREAT-MODEL.md` (`docs/vocabulary.md` is reference-only — do not read/edit unless naming something new; it has 5 stale Juice hits a later naming pass can take).

- [ ] **Step 1: Edit `CLAUDE.md` (H6)**

Make these surgical changes, preserving voice and length:
- "How the score works" paragraph 1 (currently "Juice Shop ships challenges and flips its own `solved`...") → describe attacker-proven possession on the board: the attacker exfiltrates the board's `auth_user` hashes and proves possession against the platform's start-of-session snapshot; the platform credits only verified loot.
- "These stay, by the user's decision" list — remove "Juice Shop" from the replaceable list; the list of kept pieces (OpenStack, Docker, Suricata, nginx, Elasticsearch) is unchanged.
- "Running it" — the `--target http://shop.com` example → `--target http://board.com`.
- Layout table — delete the `platform/objectives.py` row; ensure `platform/api/loot.py` (the verifier) and `wargames/<id>/objectives.yaml` are represented.

- [ ] **Step 2: Edit `README.md` / `README.ko.md`**

Remove the Juice/wiki references (README.md hits at L3, 76–96 diagram, 103, 140–142, 210, 287–293 per ANALYSIS §1.5; README.ko.md ~9). State two targets became one: the Django board as the single `loot_verified` target; a PHP company site (sub-project B) is the planned second target. Keep port/diagram facts true to the board-only stack.

- [ ] **Step 3: Edit `docs/ARCHITECTURE.md` / `.ko.md` and `docs/THREAT-MODEL.md`**

ARCHITECTURE: remove the objectives-via-Juice narrative and the wiki-SSRF lateral-movement objective; describe the loot_verified snapshot/verify/credit flow and the internal off-WAF ground-truth channel (ANALYSIS §1.5 lists the hit lines). THREAT-MODEL L13, 45–46: drop the wiki/SSRF objective; note lateral movement is shelved until sub-project B (H3).

- [ ] **Step 4: Confirm no stray references remain in counted/referenced files**

Run: `grep -rn -i "juice\|wiki\|shop.com\|self_judged\|objectives.py" platform redteam deploy wargames compose.yaml platform/range/declaration.yaml bin README.md docs/ARCHITECTURE.md docs/THREAT-MODEL.md | grep -v deploy/suricata/logs`
Expected: no functional references (allowed leftovers: `deploy/suricata/logs/` fixture data, `docs/superpowers/plans|specs/` archived history, `docs/vocabulary.md`, `strings.html` which has none).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md README.ko.md docs/ARCHITECTURE.md docs/ARCHITECTURE.ko.md docs/THREAT-MODEL.md
git commit -m "docs: board-only, loot_verified reality; drop Juice Shop and the wiki"
```

---

## Task 8 (final): Verify green, measure, update STATE, lower the `tests` floor

The one sanctioned floor reduction (ANALYSIS H1/§4). Lower `metrics.json` `tests` to the number `bin/measure` reports after the final green `bin/verify` — take the measured value, do not pre-commit a number (expected ≈ 1196–1197: ANALYSIS S1 projects 1197; `members.json` removal deletes one more acceptance test). `core_loc` must stay ≤ 461.

**Files:** `metrics.json`, `docs/STATE.md`.

- [ ] **Step 1: Full live `bin/verify` on the board-only stack**

```bash
docker compose up -d --build --remove-orphans
```
Run: `bin/verify`
Expected: everything green except the ratchet's `tests` floor breach (still reported until step 3). Confirm `core_loc` is ≤ 461 and `services`/`wargame_services`/`product_loc` only dropped in the printed ratchet summary.

- [ ] **Step 2: Measure and read the new counts**

Run: `bin/measure --json`
Record the printed `tests` value (call it N) and confirm `core_loc` ≤ 461, `services` 7, `wargame_services` 2, `dependencies` 6, `product_loc` < 8580.

- [ ] **Step 3: Lower the floor in `metrics.json` and save the rest**

Edit `metrics.json` `tests` to N (the measured value from step 2). Then write the measured snapshot:

Run: `bin/measure --save`
Expected: `metrics.json` now records the board-only numbers with `tests = N`.

- [ ] **Step 4: Update `docs/STATE.md`**

Replace the "In progress / Phase 4" narrative with a true board-only handover: Juice Shop, the wiki and `self_judged` are removed; `objective_model` ∈ {`loot_verified`, `none`}; the board is the single target; `members.json` is gone (realistic exfil is the `?sort=` order_by SQLi, CVE-2021-35042); the internal `/internal/auth-users` ground-truth channel stays (WAF-404, estate-only); the `tests` floor was lowered 1252 → N by the user's Phase 4 authorisation. Fix "Two targets"/"What exists now" to one target. Update the backlog (Phase 4 done; sub-project B — the PHP company site — is next, its own spec). Record the itemized floor justification (step 5 message).

- [ ] **Step 5: Final verify, then commit with the itemized justification**

Run: `bin/verify`
Expected: GREEN, including the ratchet (the floor now equals the measured count).

```bash
git add metrics.json docs/STATE.md
git commit -m "chore(ratchet): board-only metrics; lower tests floor 1252 -> N (user-authorised)

Phase 4 removed the Juice self_judged adapter, the wiki and its lateral-movement
objective, and the board's planted members.json. Floor justification:
- deleted ~64 Juice/wiki-only tests: 29 wiki log/channel/acceptance, 8 Juice
  description-HTML (objectives._displayed), 17 challenge poll/stamp/close-observe,
  7 acceptance (case_objectives + Juice objectives), 3 infra (wiki healthcheck,
  no-shell node reporter, self_judged value);
- deleted 1 more for members.json removal (test_members_endpoint_leaks...);
- repurposed 15 self_judged/stamp/close tests onto board loot behaviour (count-neutral);
- added removal/prerequisite guards (request-case keys, cloud + Docker /internal 404,
  objective_model values, none-branch, migration state).
core_loc held at 461; services 7; wargame_services 4 -> 2; product_loc down;
dependencies 6. Measured count N from bin/measure after green bin/verify."
```

Replace `N` with the measured value from step 2 before committing.

---

## Self-Review

**Spec coverage** — every user decision (#1–#9) and ANALYSIS movement maps to a task:

- #1 remove Juice + wiki (compose, declaration, `wargames/juice-shop/`, `default.yaml`, WARGAMES entry, Juice/wiki settings, keep `PUBLIC_TARGET_URL`, drop `services`/`wargame_services`, migration 0013, leave 0001): Tasks 4 (defaults, migration) + 6 (deletions, settings, compose, declaration).
- #2 remove `self_judged`, delete `objectives.py`, collapse the three gates, keep `none` reachable + patch.dict tested: Task 6 (6A/6B) + guard tests.
- #3 remove `members.json`, delete the leak test, repoint the loot test to the internal read channel, keep `TRUTH`/loot tests, state rationale: Task 3.
- #4 keep `/internal/auth-users`: preserved throughout; Tasks 2/6 guard it at the WAF, never delete the view.
- #5 fix (a) board.yaml `data:`→`json:` (Task 1) and (b) cloud `range.conf` `/internal` 404 (Task 2, user verifies live).
- #6 retarget per buckets A/CF/CD/BR/BD (Tasks 4–6 citing ANALYSIS §3.3/§3.4/§3.6), the ~9 removal guards (distributed: guard 7 T1, guard 5 T2, guard 9 T4, guards 1–3+6 T6), the conftest autouse `urlopen` guard (T4).
- #7 READY "nothing solved" → ground-truth-readable (T6 H2); keep `POST /objectives/`, drop `TARGET_SETTLE`/`unobserved` (T6 H5); keep stored Juice sessions (T6 H8, no prune).
- #8 CLAUDE.md + docs board-only (T7 H6).
- #9 last task lowers the floor to the measured value with itemized justification, after green verify + measure --save + STATE (T8).
- Global constraints block present with verbatim values; ordering matches ANALYSIS §5.1 (prereqs → retarget → destroy → floor).

**Placeholder scan** — no "TBD"/"handle edge cases"/"write tests for the above". Bulk per-test edits are delegated to the committed ANALYSIS §3.3/§3.4/§3.6 tables (a real document the implementer reads), with concrete transformation maps and representative real code for every new or changed piece of logic (guards, gate collapse, READY replacement, `_loot_window`, members repoint, board.yaml fix, floor). The one genuinely live-iterated step (WAF default-vhost mount mechanism, Task 6 step 12) is TDD-gated by the IP-Host probe written first — not a placeholder but an explicitly empirical step.

**Type/name consistency** — `objective_model` values `loot_verified|none` used consistently; `loot.ground_truth(wargame_id) -> dict[str,str]` and `loot.GroundTruthUnavailable` used the same way in the conftest guard, the session-start gate, the READY check, and the test patches; `_ground_truth_readable`, `_loot_window(session, case_id, submitted_at)`, `_observe_objectives(session) -> dict`, `_loot_catalogue(spec)`, `CANARY_CASE` names match `platform/api/views.py`; `SCORER`/`BOARD`/`ATTACKER`/`run` match `test/range.py` exports; migration `0013` depends on the confirmed latest `api` migration (verified in Task 4 step 4).
