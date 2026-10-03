# Attacker-Proven Objective Model — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Django board a `loot_verified` objective layer: the platform snapshots the board's real `auth_user` hashes at session start, the attacker submits exfiltrated loot to `POST /api/sessions/<id>/loot/`, and the platform credits tiered objectives only on exact stored-hash matches — crediting flows into the existing zero-sum game unchanged.

**Architecture:** The board exposes an internal, off-WAF HTTP endpoint returning `{username: stored_password_hash}`, reachable only platform→board over the estate network (the WAF 404s it). A new product-space module `platform/api/loot.py` reads that ground truth, canonicalizes a submission to a set of `(username, hash)` tuples, intersects on exact hash strings, and reports which tiers of a declared ladder (`wargames/board/objectives.yaml`) fired. `platform/api/views.py` snapshots the truth onto `Session.baseline` (reusing the JSONField, no migration) at start, and a new loot endpoint writes each fired tier as an ordinary `Objective` row windowed to the exfil case so `_breaches` / `scoreboard.attribute` / `game.Taken` credit detection from the attack, never from the quiet submission.

**Tech Stack:** Python 3.9 (board) / platform Django, MySQL (board), PyYAML, Django `JsonResponse` + `urllib`, pytest with `unittest.mock.patch`, nginx (WAF), Docker Compose acceptance stack.

## Global Constraints

- core_loc stays flat at 461 (nothing added to platform/scoring, platform/ingest, platform/rules, redteam/harness.py).
- tests floor only rises; no comments/docstrings anywhere; no new gated service or dependency; no DB migration (reuse Session.baseline JSON + Objective rows).
- The ground-truth endpoint must be unreachable through the WAF (attacker-facing board.com), reachable only platform→board over estate.
- The target still owns ground truth; the platform matches the attacker's proof against it and never credits from alerts/belief.
- Each task ends green under the per-task gate; full bin/verify is the phase-end gate.
- Board is Django 3.2.4 (unpatched) from Phase 1; objective_model enum + derived judged + the three gates exist from Phase 2.

### Gated-number accounting (where new code lands)

| Code | Location | Metric | Allowed to grow? |
|---|---|---|---|
| board view + url | `wargames/board/app/posts/` | product_loc | yes (reported) |
| `deploy/nginx/board.conf` | `deploy/` | product_loc | yes (reported) |
| `wargames/board/objectives.yaml` | wargame data | not counted as core | yes |
| `platform/api/loot.py` | `platform/api/` | product_loc | yes (reported) |
| edits to `platform/api/views.py`, `platform/wargames.py`, `platform/fsl/settings.py`, `platform/fsl/urls.py` | product | product_loc | yes (reported) |
| tests | `platform/tests/`, `test/` | tests floor | must only rise |

Nothing in this phase touches `platform/scoring/`, `platform/ingest/`, `platform/rules/`, or `redteam/harness.py`, so `core_loc` stays `461`. No new pip package, compose service, or `wargame_services` entry is added.

### Key facts about the code this phase builds on

- `platform/wargames.py:30` — the board's `objective_model` is `"none"` today; `platform/wargames.py:34-38` define `objective_model()` and the derived `judged()`; `platform/wargames.py:85-89` load case YAML from `settings.WARGAME_CASES_DIR`; `platform/wargames.py:120` derives the catalogue `judged` boolean.
- `platform/api/views.py:181-188` — the `sessions` POST baseline capture fires only on `self_judged`.
- `platform/api/views.py:362-368` — `wargame_objectives` early-returns `[]` on `none`, else runs the Juice-Shop self-judge catalogue.
- `platform/api/views.py:380-419` — `_observe_objectives` early-returns on `none`, else runs the Juice-Shop `objectives.observe()` self-judge path and bulk-creates `Objective` rows (the pattern the loot endpoint mirrors).
- `platform/api/views.py:829-846` — `_breaches` iterates `session.objectives.all()` and calls `scoreboard.attribute(objective.achieved_at, attempts, objective.earliest, objective.latest)`; `platform/api/views.py:848-864` — `_achieved` is the self-judge window builder (the model for `_loot_window`).
- `platform/api/views.py:784-812` — `_game` turns breaches into `game.Taken(key, difficulty, detected)` and calls `game.settle`.
- `platform/api/models.py:10` — `Session.baseline` is a nullable `JSONField` (holds the solved-key list for self_judged; holds the `{username: hash}` ground-truth dict for loot_verified). `platform/api/models.py:76-91` — `Objective(key, name, category, difficulty, achieved_at, earliest, latest)` with `unique_together(session, key)`.
- `platform/scoreboard.py:8,10,28-43` — `ATTRIBUTION_WINDOW` (2 min), `CLOCK_SKEW` (100 ms), and `attribute(achieved_at, attempts, earliest, latest)` which returns the latest malicious `Attempt` whose window overlaps `[earliest, latest]`.
- `platform/objectives.py:103-116` — `_fetch` reads Juice Shop's internal `/api/Challenges/` by direct `urllib.request.urlopen(settings.WARGAME_API_URL + ...)`; the board ground-truth read mirrors this exactly (no runner, direct HTTP over estate).
- `deploy/nginx/board.conf:5-14` — the WAF proxies `location /` to `http://board:8000$request_uri`; the attacker reaches the board only via board.com through this.
- `wargames/board/app/posts/views.py:10-11` / `urls.py:6` — the Phase-1 `members.json` `User.objects.values()` endpoint, the model for the new view. `wargames/board/app/posts/management/commands/seed.py:6-10` — the seed makes `admin` the superuser; `jiwoo` and `minseo` are non-admin.
- The platform container is on the `estate` network (`compose.yaml:186`), so `http://board:8000` resolves platform→board. The acceptance `scorer` role is `fsl-platform` (`platform/range/declaration.yaml:50`), so `run(SCORER, ...)` executes on the platform container.
- Unit tests subclass `django.test.Client` as `ApiClient` with `post_json` (`platform/tests/conftest.py:13-22`); the autouse `no_real_substrate` fixture refuses real docker calls (`platform/tests/conftest.py:28-51`). Acceptance tests reach the attacker/scorer via `test/range.py`'s `run(ROLE, argv)` and the live platform via `conftest.PLATFORM_URL`.

---

### Task 1: Board internal ground-truth endpoint, denied through the WAF

**Files:**
- Modify: `wargames/board/app/posts/views.py:1-11` (add the `auth_users` view)
- Modify: `wargames/board/app/posts/urls.py:5-12` (route it)
- Modify: `deploy/nginx/board.conf:4` (add a `location /internal/` that 404s)
- Test: `test/test_board_exfil.py` (append acceptance checks — live stack)

**Interfaces:**
- Produces: board URL `GET /internal/auth-users` returning a JSON object `{username: stored_password_hash, ...}` over `http://board:8000`, 404 via `http://board.com`. Later tasks read it through `BOARD_API_URL + "/internal/auth-users"`.

- [ ] **Step 1: Write the failing acceptance tests**

Append to `test/test_board_exfil.py` (it already defines `BOARD = "http://board.com"` and `_from_range`):

```python
def test_the_internal_ground_truth_is_blocked_through_the_waf(stack_is_up):
    assert _from_range("/internal/auth-users") == "404", (
        "the attacker-facing WAF served the internal ground-truth path; it must "
        "be reachable only platform->board over estate, never through board.com"
    )


def test_the_platform_reads_the_auth_user_hashes_over_estate(stack_is_up):
    from range import SCORER, run

    body = run(SCORER, ["curl", "-s", "--max-time", "20",
                        "http://board:8000/internal/auth-users"]).stdout
    import json

    truth = json.loads(body)
    assert {"admin", "jiwoo", "minseo"} <= set(truth), truth
    assert all(h.startswith("pbkdf2_sha256$") for h in truth.values()), (
        "the internal endpoint did not return the stored salted-hash column"
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd test && python -m pytest test_board_exfil.py -k "internal or over_estate" -v`
Expected: FAIL — `/internal/auth-users` 200s through the WAF (proxied) and the SCORER curl 404s (no route) until the view and the WAF deny exist. (Requires the stack up: `docker compose up -d --build`.)

- [ ] **Step 3: Add the board view**

In `wargames/board/app/posts/views.py`, the top already imports `from django.contrib.auth.models import User` and `from django.http import JsonResponse`. Add:

```python
def auth_users(request):
    return JsonResponse({u.username: u.password for u in User.objects.all()})
```

- [ ] **Step 4: Route it**

In `wargames/board/app/posts/urls.py`, add the route inside `urlpatterns` (before the catch-all `""`):

```python
    path("internal/auth-users", views.auth_users, name="auth_users"),
```

- [ ] **Step 5: Deny it at the WAF**

In `deploy/nginx/board.conf`, inside the `server { ... }` block and before `location /`, add:

```nginx
    location /internal/ {
        return 404;
    }
```

- [ ] **Step 6: Rebuild the board and WAF, run the tests**

Run:
```bash
docker compose up -d --build board gateway
cd test && python -m pytest test_board_exfil.py -k "internal or over_estate" -v
```
Expected: PASS — SCORER (platform, estate) reads the hash map; the attacker via board.com gets 404.

- [ ] **Step 7: Commit**

```bash
git add wargames/board/app/posts/views.py wargames/board/app/posts/urls.py deploy/nginx/board.conf test/test_board_exfil.py
git commit -m "feat(board): internal auth_user ground-truth endpoint, 404 through the WAF"
```

---

### Task 2: The board objective spec and the `wargames.objectives()` accessor

**Files:**
- Create: `wargames/board/objectives.yaml`
- Modify: `platform/wargames.py:1-10` (add `import yaml`), `platform/wargames.py:34-38` (add `objectives()` + `checked_objectives()`)
- Test: `platform/tests/test_board_objectives_spec.py`

**Interfaces:**
- Consumes: `settings.FSL_SOURCE` (`platform/fsl/settings.py:90`, defaults to the repo root).
- Produces: `wargames.objectives(wargame_id) -> dict` with shape `{"secret": {"scope": str, "columns": [str], "read_path": str}, "tiers": [{"key","name","category","difficulty":int, <one condition>}, ...]}`. Tier conditions are exactly one of `min_matched:int`, `account:str`, or `coverage:float`. Raises `wargames.UnknownWargame` for an unknown id and `wargames.InvalidCatalogue` for a malformed file.

- [ ] **Step 1: Write the failing test**

Create `platform/tests/test_board_objectives_spec.py`:

```python
import pytest

import wargames


def test_the_board_declares_a_secret_and_a_read_path():
    spec = wargames.objectives("board")

    assert spec["secret"]["scope"] == "auth_user"
    assert spec["secret"]["read_path"] == "/internal/auth-users"
    assert "username" in spec["secret"]["columns"]
    assert "password" in spec["secret"]["columns"]


def test_the_board_declares_the_partial_admin_and_full_tiers():
    tiers = {t["key"]: t for t in wargames.objectives("board")["tiers"]}

    assert set(tiers) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert tiers["board-auth-user-partial"]["min_matched"] == 1
    assert tiers["board-auth-user-partial"]["difficulty"] == 2
    assert tiers["board-auth-user-admin"]["account"] == "admin"
    assert tiers["board-auth-user-admin"]["difficulty"] == 4
    assert tiers["board-auth-user-full"]["coverage"] == 1.0
    assert tiers["board-auth-user-full"]["difficulty"] == 5


def test_every_tier_carries_an_integer_difficulty_and_a_name():
    for tier in wargames.objectives("board")["tiers"]:
        assert isinstance(tier["difficulty"], int)
        assert isinstance(tier["name"], str) and tier["name"]


def test_an_unknown_wargame_has_no_objective_spec():
    with pytest.raises(wargames.UnknownWargame):
        wargames.objectives("no-such-wargame")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd platform && python -m pytest tests/test_board_objectives_spec.py -v`
Expected: FAIL with `AttributeError: module 'wargames' has no attribute 'objectives'`.

- [ ] **Step 3: Create the objective spec**

Create `wargames/board/objectives.yaml`:

```yaml
secret:
  scope: auth_user
  columns: [username, password]
  read_path: /internal/auth-users
tiers:
  - key: board-auth-user-partial
    name: Board accounts (partial)
    category: Credential Access
    difficulty: 2
    min_matched: 1
  - key: board-auth-user-admin
    name: Board admin account
    category: Credential Access
    difficulty: 4
    account: admin
  - key: board-auth-user-full
    name: Board accounts (full)
    category: Credential Access
    difficulty: 5
    coverage: 1.0
```

- [ ] **Step 4: Add the accessor and validator to `platform/wargames.py`**

Add `import yaml` to the imports (after `from urllib.parse import urlsplit` at `platform/wargames.py:5`). Then add, next to `objective_model`/`judged` (after `platform/wargames.py:38`):

```python
def objectives(wargame_id: str) -> dict[str, Any]:
    if wargame_id not in WARGAMES:
        raise UnknownWargame(wargame_id)
    path = Path(settings.FSL_SOURCE) / "wargames" / wargame_id / "objectives.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return checked_objectives(loaded, path)

def checked_objectives(loaded: Any, source) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        raise InvalidCatalogue(f"{source}: an objective spec is a mapping")
    secret = loaded.get("secret")
    if not isinstance(secret, dict) or not secret.get("read_path"):
        raise InvalidCatalogue(f"{source}: secret.read_path is required")
    tiers = loaded.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        raise InvalidCatalogue(f"{source}: tiers must be a non-empty list")
    for tier in tiers:
        if not isinstance(tier, dict) or not isinstance(tier.get("key"), str) \
                or not isinstance(tier.get("difficulty"), int) \
                or not isinstance(tier.get("name"), str):
            raise InvalidCatalogue(
                f"{source}: each tier needs a key, a name, and an integer difficulty"
            )
    return loaded
```

`UnknownWargame` and `InvalidCatalogue` already exist (`platform/wargames.py:43-47`); `Path`, `Any`, `settings` are already imported.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd platform && python -m pytest tests/test_board_objectives_spec.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add wargames/board/objectives.yaml platform/wargames.py platform/tests/test_board_objectives_spec.py
git commit -m "feat(wargames): board objective spec + wargames.objectives() accessor"
```

---

### Task 3: The product-space loot verifier module

**Files:**
- Create: `platform/api/loot.py`
- Modify: `platform/fsl/settings.py:75` (add `BOARD_API_URL`)
- Test: `platform/tests/test_loot_verifier.py`

**Interfaces:**
- Consumes: `wargames.objectives(wargame_id)` (Task 2); `settings.BOARD_API_URL`.
- Produces:
  - `loot.ground_truth(wargame_id) -> dict[str, str]` — GETs `BOARD_API_URL + spec["secret"]["read_path"]`, returns `{username: hash}`; raises `loot.GroundTruthUnavailable` on any read/parse failure.
  - `loot.canonicalize(submitted) -> set[tuple[str, str]]` — accepts a `{username: hash}` dict or a list of `{"username","hash"|"password"}` dicts or `[username, hash]` pairs; ignores malformed rows.
  - `loot.matched(submitted, truth) -> set[str]` — usernames whose submitted hash exactly equals `truth[username]`.
  - `loot.tiers_fired(spec, matched_usernames, truth) -> tuple[list[dict], float]` — returns the fired tiers (in ladder order) and `coverage = |matched| / |truth|`.

- [ ] **Step 1: Write the failing test**

Create `platform/tests/test_loot_verifier.py`:

```python
from unittest.mock import patch

import pytest

from api import loot

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}

SPEC = {
    "secret": {"read_path": "/internal/auth-users"},
    "tiers": [
        {"key": "board-auth-user-partial", "name": "partial", "difficulty": 2,
         "min_matched": 1},
        {"key": "board-auth-user-admin", "name": "admin", "difficulty": 4,
         "account": "admin"},
        {"key": "board-auth-user-full", "name": "full", "difficulty": 5,
         "coverage": 1.0},
    ],
}


def test_canonicalize_accepts_dicts_pairs_and_mappings():
    pairs = loot.canonicalize([{"username": "admin", "hash": "h1"},
                               {"username": "jiwoo", "password": "h2"},
                               ["minseo", "h3"]])
    assert pairs == {("admin", "h1"), ("jiwoo", "h2"), ("minseo", "h3")}
    assert loot.canonicalize({"admin": "h1"}) == {("admin", "h1")}
    assert loot.canonicalize("garbage") == set()
    assert loot.canonicalize([{"username": "admin"}, 7, None]) == set()


def test_matched_requires_the_exact_stored_hash():
    submitted = [{"username": "admin", "hash": TRUTH["admin"]},
                 {"username": "jiwoo", "hash": "pbkdf2_sha256$600000$bbb$WRONG="}]
    assert loot.matched(submitted, TRUTH) == {"admin"}


def test_a_plaintext_guess_never_matches_a_salted_hash():
    assert loot.matched([{"username": "admin", "password": "admin1234"}], TRUTH) == set()


def test_a_single_non_admin_row_fires_only_partial():
    fired, coverage = loot.tiers_fired(SPEC, {"jiwoo"}, TRUTH)
    assert [t["key"] for t in fired] == ["board-auth-user-partial"]
    assert coverage == pytest.approx(1 / 3)


def test_a_single_admin_row_fires_partial_and_admin():
    fired, _ = loot.tiers_fired(SPEC, {"admin"}, TRUTH)
    assert [t["key"] for t in fired] == ["board-auth-user-partial", "board-auth-user-admin"]


def test_a_whole_table_fires_all_three_tiers():
    fired, coverage = loot.tiers_fired(SPEC, set(TRUTH), TRUTH)
    assert [t["key"] for t in fired] == [
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    ]
    assert coverage == 1.0


def test_ground_truth_reads_the_declared_read_path():
    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"admin": "h1"}'

    with patch("api.loot.wargames.objectives", return_value=SPEC), patch(
        "api.loot.urllib.request.urlopen", return_value=Fake()
    ) as opened:
        assert loot.ground_truth("board") == {"admin": "h1"}
    assert opened.call_args.args[0].endswith("/internal/auth-users")


def test_ground_truth_raises_when_the_channel_is_unreadable():
    import urllib.error

    with patch("api.loot.wargames.objectives", return_value=SPEC), patch(
        "api.loot.urllib.request.urlopen",
        side_effect=urllib.error.URLError("refused"),
    ):
        with pytest.raises(loot.GroundTruthUnavailable):
            loot.ground_truth("board")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd platform && python -m pytest tests/test_loot_verifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.loot'`.

- [ ] **Step 3: Write the module**

Create `platform/api/loot.py`:

```python
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

import wargames

TIMEOUT = 15


class GroundTruthUnavailable(RuntimeError):
    pass


def ground_truth(wargame_id: str) -> dict[str, str]:
    spec = wargames.objectives(wargame_id)
    url = settings.BOARD_API_URL.rstrip("/") + spec["secret"]["read_path"]
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GroundTruthUnavailable(f"could not read ground truth from {url}: {exc}") from exc
    if not isinstance(body, dict):
        raise GroundTruthUnavailable(f"{url} did not return a username to hash map")
    return {str(name): str(digest) for name, digest in body.items()}


def canonicalize(submitted: Any) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    if isinstance(submitted, dict):
        rows = list(submitted.items())
    elif isinstance(submitted, list):
        rows = submitted
    else:
        return pairs
    for row in rows:
        username, digest = _row(row)
        if isinstance(username, str) and isinstance(digest, str):
            pairs.add((username, digest))
    return pairs


def _row(row: Any):
    if isinstance(row, dict):
        return row.get("username"), row.get("hash", row.get("password"))
    if isinstance(row, (list, tuple)) and len(row) == 2:
        return row[0], row[1]
    return None, None


def matched(submitted: Any, truth: dict[str, str]) -> set[str]:
    return {name for name, digest in canonicalize(submitted) if truth.get(name) == digest}


def tiers_fired(spec: dict, matched_usernames: set[str], truth: dict[str, str]):
    coverage = len(matched_usernames) / len(truth) if truth else 0.0
    fired = [tier for tier in spec["tiers"] if _fires(tier, matched_usernames, coverage)]
    return fired, coverage


def _fires(tier: dict, matched_usernames: set[str], coverage: float) -> bool:
    if "min_matched" in tier:
        return len(matched_usernames) >= tier["min_matched"]
    if "account" in tier:
        return tier["account"] in matched_usernames
    if "coverage" in tier:
        return coverage >= tier["coverage"]
    return False
```

Note: `canonicalize` reduces a `{username: hash}` dict through `_row` too — the mapping path yields `(username, hash)` pairs from `.items()`, where each item is a 2-tuple handled by `_row`'s pair branch.

- [ ] **Step 4: Add the `BOARD_API_URL` setting**

In `platform/fsl/settings.py`, after the `WARGAME_API_URL` line (`platform/fsl/settings.py:75`), add:

```python
BOARD_API_URL = os.environ.get("BOARD_API_URL", "http://board:8000")
```

The board service is named `board` on the estate network and the platform is on estate (`compose.yaml:186`), so the default resolves with no compose change.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd platform && python -m pytest tests/test_loot_verifier.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add platform/api/loot.py platform/fsl/settings.py platform/tests/test_loot_verifier.py
git commit -m "feat(api): product-space loot verifier (ground truth read, canonicalize, tiers)"
```

---

### Task 4: Switch the board to `loot_verified`; snapshot at start; revisit the three Phase-2 gates

**Files:**
- Modify: `platform/wargames.py:21-31` (board `objective_model` → `"loot_verified"`)
- Modify: `platform/api/views.py:25-44` (add `from api import loot`), `:181-188` (snapshot branch), `:362-368` (loot catalogue branch), `:380-382` (observe gate)
- Test: `platform/tests/test_loot_session_start.py` (new)
- Modify: `platform/tests/test_wargames_objective_model.py`, `platform/tests/test_board_wargame.py` (the Phase-2 assumptions that the board is unjudged)

**Interfaces:**
- Consumes: `loot.ground_truth` (Task 3), `wargames.objectives` (Task 2).
- Produces: a board session whose `Session.baseline` is the `{username: hash}` snapshot dict (or `None` if the channel was unreadable at start); `GET /api/wargames/board/objectives/` returns the three-tier ladder; `_observe_objectives` never self-judges a `loot_verified` session.

- [ ] **Step 1: Write the failing test (new behavior)**

Create `platform/tests/test_loot_session_start.py`:

```python
from unittest.mock import patch

import pytest

from api.models import Session

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}


def _start_board(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def test_a_board_session_snapshots_the_ground_truth_at_start(client):
    session_id = _start_board(client)

    assert Session.objects.get(pk=session_id).baseline == TRUTH, (
        "a loot_verified session must snapshot username->hash onto baseline at "
        "start so a close-time rebuild cannot wipe the comparison set"
    )


def test_a_board_session_opens_blind_when_the_channel_is_down(client):
    from api import loot

    with patch("api.views.loot.ground_truth",
               side_effect=loot.GroundTruthUnavailable("board down")):
        session_id = client.post_json(
            "/api/sessions/", {"scenario": "board"}
        ).json()["id"]

    assert Session.objects.get(pk=session_id).baseline is None


def test_the_board_lists_its_tier_ladder_and_never_asks_juice_shop(client):
    with patch("objectives._fetch") as fetched:
        response = client.get("/api/wargames/board/objectives/")

    assert {o["key"] for o in response.json()} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    fetched.assert_not_called()


def test_observing_a_board_session_does_not_self_judge(client):
    session_id = _start_board(client)

    with patch("objectives._fetch") as fetched, patch(
        "api.views.objectives.observe"
    ) as observed:
        response = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert response.json() == {"achieved": 0, "total": 0}
    fetched.assert_not_called()
    observed.assert_not_called()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd platform && python -m pytest tests/test_loot_session_start.py -v`
Expected: FAIL — board is still `"none"`, so start sets `baseline == []`, the objectives endpoint returns `[]`, and `_observe_objectives` returns `{"achieved": 0, "total": 0}` from the `none` branch (the self-judge assertions pass but the ladder/baseline assertions fail).

- [ ] **Step 3: Flip the board to `loot_verified`**

In `platform/wargames.py`, change the board's `objective_model` (`platform/wargames.py:30`) from `"none"` to `"loot_verified"`:

```python
        "objective_model": "loot_verified",
```

- [ ] **Step 4: Import the loot module in views**

In `platform/api/views.py`, add to the imports near `import wargames` (`platform/api/views.py:31`):

```python
from api import loot
```

- [ ] **Step 5: Snapshot ground truth at session start**

Replace the baseline-capture block in `sessions` (`platform/api/views.py:181-187`) with:

```python
    baseline = []
    model = wargames.objective_model(scenario)
    if model == "self_judged":
        try:
            baseline = sorted(objectives.solved_keys(adapter.runner("wiki")))
        except objectives.ObjectivesUnavailable:
            baseline = None
    elif model == "loot_verified":
        try:
            baseline = loot.ground_truth(scenario)
        except loot.GroundTruthUnavailable:
            baseline = None
    session = Session.objects.create(scenario=scenario, baseline=baseline)
```

- [ ] **Step 6: Return the tier ladder from `wargame_objectives`**

Replace `wargame_objectives` (`platform/api/views.py:362-368`) with:

```python
@require_http_methods(["GET"])
def wargame_objectives(request, wargame_id):
    if wargame_id not in wargames.WARGAMES:
        raise Http404(wargame_id)
    model = wargames.objective_model(wargame_id)
    if model == "none":
        return _reply([])
    if model == "loot_verified":
        return _reply(_loot_catalogue(wargames.objectives(wargame_id)))
    return _reply(objectives.catalogue(substrate().runner("wiki")))

def _loot_catalogue(spec):
    return [
        {
            "key": tier["key"],
            "name": tier["name"],
            "category": tier.get("category") or "",
            "difficulty": int(tier["difficulty"]),
            "description": tier.get("description") or "",
            "solved": False,
            "solved_at": None,
        }
        for tier in spec["tiers"]
    ]
```

- [ ] **Step 7: Make `_observe_objectives` self-judge only for `self_judged`**

Change the guard at the top of `_observe_objectives` (`platform/api/views.py:380-382`) from the `== "none"` early-return to:

```python
def _observe_objectives(session) -> dict:
    if wargames.objective_model(session.scenario) != "self_judged":
        return {"achieved": 0, "total": session.objectives.count()}
    found, unreadable = objectives.observe(substrate().runner("wiki"))
```

The rest of the function (the Juice-Shop path from `platform/api/views.py:383` on) is unchanged. A `loot_verified` close still calls `_observe_objectives` (returns `{"achieved": 0, "total": count}`, no `unreadable`), so the rebuild path at `platform/api/views.py:532-542` runs unchanged.

- [ ] **Step 8: Update the Phase-2 tests that assumed the board is unjudged**

In `platform/tests/test_wargames_objective_model.py`, replace `test_board_has_no_objective_model_and_is_not_judged` (`:9-11`) and fix the catalogue assertion (`:17`):

```python
def test_board_is_loot_verified_and_counts_as_judged():
    assert wargames.objective_model("board") == "loot_verified"
    assert wargames.judged("board") is True
```

```python
    assert by_id["board"]["judged"] is True
```

In `platform/tests/test_board_wargame.py`: update `test_only_juice_shop_judges_its_own_defeat` (`:21-25`), `test_the_board_lists_no_objectives_and_never_asks_juice_shop` (`:33-37`), `test_a_board_session_never_asks_juice_shop_what_fell` (`:40-48`), and `test_a_board_session_opens_with_nothing_already_taken` (`:50-54`). Replace the `board_session` helper (`:9-10`) and those four tests with:

```python
TRUTH = {"admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
         "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO="}


def board_session(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]
```

```python
def test_both_wargames_are_judged_but_by_different_models(client):
    wargames = listed(client)

    assert wargames["juice-shop"]["judged"] is True
    assert wargames["board"]["judged"] is True
```

```python
def test_the_board_lists_its_loot_tiers_and_never_asks_juice_shop(client):
    with patch("objectives._fetch") as fetched:
        response = client.get("/api/wargames/board/objectives/")

    assert {o["key"] for o in response.json()} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    fetched.assert_not_called()


def test_a_board_session_never_asks_juice_shop_what_fell(client):
    with patch("objectives._fetch") as fetched:
        session_id = board_session(client)
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
        closed = client.post_json(f"/api/sessions/{session_id}/close/")

    assert observed.json() == {"achieved": 0, "total": 0}
    assert "unobserved" not in closed.json()
    fetched.assert_not_called()


def test_a_board_session_opens_with_the_ground_truth_snapshot(client):
    session_id = board_session(client)

    assert Session.objects.get(pk=session_id).baseline == TRUTH
```

`test_a_board_case_is_addressed_to_the_board` (`:57-64`) uses `board_session`, which now patches `loot.ground_truth`, so it keeps working. `patch` is already imported in that file (`:1`).

- [ ] **Step 9: Run the task's tests**

Run:
```bash
cd platform && python -m pytest tests/test_loot_session_start.py tests/test_wargames_objective_model.py tests/test_board_wargame.py -v
```
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add platform/wargames.py platform/api/views.py platform/tests/test_loot_session_start.py platform/tests/test_wargames_objective_model.py platform/tests/test_board_wargame.py
git commit -m "feat(objectives): board is loot_verified; snapshot at start; gates skip self-judge"
```

---

### Task 5: `POST /api/sessions/<id>/loot/` — verify, credit tiers, attribute

**Files:**
- Modify: `platform/api/views.py` (add `session_loot`, `_loot_window`, `_malicious_attempts`)
- Modify: `platform/fsl/urls.py:19` (route the loot endpoint)
- Test: `platform/tests/test_loot_submit.py`

**Interfaces:**
- Consumes: `loot.matched`, `loot.tiers_fired` (Task 3); `wargames.objectives` (Task 2); `scoreboard.ATTRIBUTION_WINDOW`, `scoreboard.CLOCK_SKEW`, `scoreboard.Attempt`, `scoreboard.attribute`; `Objective` model; `_refuse_closed`, `_payload`, `_reply`, `Conflict`, `BadRequest` (all already in views).
- Produces: `POST /api/sessions/<id>/loot/` accepting `{"loot": <submission>, "case_id": <optional marker>}`, writing an `Objective` row per fired tier via `bulk_create(ignore_conflicts=True)`, and replying `{"matched": [usernames], "coverage": float, "credited": [keys], "objectives": int, "attempted": bool, "unattributed": [keys]}`.

- [ ] **Step 1: Write the failing test**

Create `platform/tests/test_loot_submit.py`:

```python
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Objective, Session

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}


def start(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        return client.post_json("/api/sessions/", {"scenario": "board"}).json()["id"]


def fire_exfil(client, session_id, case_id="22222222-2222-4222-8222-222222222222"):
    now = timezone.now()
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": case_id, "name": "board-members-json", "malicious": True,
        "correlation": "marker", "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=2)).isoformat(),
    })
    return case_id


def submit(client, session_id, rows, case_id=None):
    body = {"loot": rows}
    if case_id is not None:
        body["case_id"] = case_id
    return client.post_json(f"/api/sessions/{session_id}/loot/", body)


def rows_for(*names):
    return [{"username": n, "hash": TRUTH[n]} for n in names]


def test_a_whole_dump_credits_partial_admin_and_full(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    response = submit(client, session_id, rows_for("admin", "jiwoo", "minseo"))

    assert response.status_code == 200, response.content
    assert set(response.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert response.json()["coverage"] == 1.0
    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }


def test_one_non_admin_row_fires_only_partial(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    response = submit(client, session_id, rows_for("jiwoo"))

    assert response.json()["credited"] == ["board-auth-user-partial"]


def test_the_admin_hash_fires_partial_and_admin(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    response = submit(client, session_id, rows_for("admin"))

    assert set(response.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin"
    }


def test_fabricated_and_plaintext_loot_credits_nothing(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    fabricated = submit(client, session_id, [
        {"username": "admin", "hash": "pbkdf2_sha256$600000$zzz$FORGED="},
        {"username": "admin", "password": "admin1234"},
    ])

    assert fabricated.json()["credited"] == []
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_crediting_requires_at_least_one_malicious_attempt_in_session(client):
    session_id = start(client)

    response = submit(client, session_id, rows_for("admin", "jiwoo", "minseo"))

    assert response.status_code == 200
    assert response.json()["attempted"] is False
    assert response.json()["credited"] == []
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_a_bigger_dump_adds_higher_tiers_monotonically(client):
    session_id = start(client)
    fire_exfil(client, session_id)

    submit(client, session_id, rows_for("jiwoo"))
    submit(client, session_id, rows_for("admin", "jiwoo", "minseo"))

    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }


def test_a_closed_session_refuses_loot(client):
    session_id = start(client)
    fire_exfil(client, session_id)
    client.post_json(f"/api/sessions/{session_id}/close/")

    response = submit(client, session_id, rows_for("admin"))

    assert response.status_code == 409
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_a_non_loot_wargame_refuses_loot(client):
    with patch("api.views.objectives.solved_keys", return_value=set()):
        session_id = client.post_json("/api/sessions/", {}).json()["id"]

    response = submit(client, session_id, rows_for("admin"))

    assert response.status_code == 400


def test_the_case_id_windows_the_objective_to_the_exfil_case(client):
    session_id = start(client)
    case_id = fire_exfil(client, session_id)

    submit(client, session_id, rows_for("admin"), case_id=case_id)

    objective = Objective.objects.get(session_id=session_id, key="board-auth-user-admin")
    case = Session.objects.get(pk=session_id).cases.get(case_id=case_id)
    assert objective.earliest <= case.ended_at <= objective.latest
    assert objective.earliest <= case.started_at


def test_a_take_with_no_overlapping_case_is_flagged_unattributed(client):
    session_id = start(client)
    old = timezone.now() - timedelta(minutes=30)
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": "33333333-3333-4333-8333-333333333333", "name": "old-attack",
        "malicious": True, "correlation": "marker",
        "started_at": old.isoformat(),
        "ended_at": (old + timedelta(seconds=2)).isoformat(),
    })

    response = submit(client, session_id, rows_for("admin"))

    assert response.status_code == 200
    assert response.json()["attempted"] is True
    assert set(response.json()["unattributed"]) == {
        "board-auth-user-partial", "board-auth-user-admin"
    }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd platform && python -m pytest tests/test_loot_submit.py -v`
Expected: FAIL — `/api/sessions/<id>/loot/` is 404 (no route) / `AttributeError: session_loot`.

- [ ] **Step 3: Add the loot view and its helpers to `platform/api/views.py`**

Add after `session_objectives`/`_observe_objectives` (after `platform/api/views.py:419`):

```python
@require_http_methods(["POST"])
def session_loot(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    if wargames.objective_model(session.scenario) != "loot_verified":
        raise BadRequest(
            f"{session.scenario!r} does not take loot; its objective model is "
            f"{wargames.objective_model(session.scenario)!r}"
        )
    truth = session.baseline
    if not isinstance(truth, dict):
        raise Conflict(
            f"session {session.pk} captured no ground-truth snapshot at start, "
            f"so submitted loot cannot be verified"
        )
    body = _payload(request)
    spec = wargames.objectives(session.scenario)
    matched_users = loot.matched(body.get("loot"), truth)
    fired, coverage = loot.tiers_fired(spec, matched_users, truth)

    attempted = session.cases.filter(malicious=True).exists()
    credited = fired if attempted else []

    at, earliest, latest = _loot_window(session, body.get("case_id"), timezone.now())
    attributed = scoreboard.attribute(at, _malicious_attempts(session), earliest, latest)

    before = session.objectives.count()
    Objective.objects.bulk_create(
        [
            Objective(
                session=session, key=tier["key"], name=tier["name"],
                category=tier.get("category") or "", difficulty=int(tier["difficulty"]),
                achieved_at=at, earliest=earliest, latest=latest,
            )
            for tier in credited
        ],
        ignore_conflicts=True,
    )
    return _reply({
        "matched": sorted(matched_users),
        "coverage": coverage,
        "credited": [tier["key"] for tier in credited],
        "objectives": session.objectives.count() - before,
        "attempted": attempted,
        "unattributed": [] if attributed else [tier["key"] for tier in credited],
    })

def _loot_window(session, case_id, submitted_at):
    if case_id:
        case = session.cases.filter(case_id=case_id, malicious=True).first()
        if case is not None:
            return (
                case.ended_at,
                case.started_at - scoreboard.CLOCK_SKEW,
                case.ended_at + scoreboard.CLOCK_SKEW,
            )
    return (
        submitted_at,
        submitted_at - scoreboard.ATTRIBUTION_WINDOW,
        submitted_at + scoreboard.CLOCK_SKEW,
    )

def _malicious_attempts(session):
    return [
        scoreboard.Attempt(
            case_id=case.case_id,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=True,
            detected=False,
            detection_ids=(),
        )
        for case in session.cases.filter(malicious=True)
    ]
```

- [ ] **Step 4: Route the endpoint**

In `platform/fsl/urls.py`, add after the objectives route (`platform/fsl/urls.py:19`):

```python
    path("api/sessions/<int:session_id>/loot/", views.session_loot),
```

- [ ] **Step 5: Run the task's tests**

Run: `cd platform && python -m pytest tests/test_loot_submit.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add platform/api/views.py platform/fsl/urls.py platform/tests/test_loot_submit.py
git commit -m "feat(api): POST /sessions/<id>/loot/ verifies and credits tiered objectives"
```

---

### Task 6: Credited loot flows into breaches and the zero-sum game

**Files:**
- Test only: `platform/tests/test_loot_scoring.py`

**Interfaces:**
- Consumes: the loot endpoint (Task 5), `_breaches`/`_game` (`platform/api/views.py:784-846`), the correlation/marker ingest already exercised by `platform/tests/test_api_corroboration.py` (`T0`, `alert`).
- Produces: nothing new — this task proves the loot `Objective` rows credit into `score["objectives"]`, `score["breaches"]`, and `score["game"]` unchanged, and that `detected` follows the attributed exfil case.

- [ ] **Step 1: Write the failing test**

Create `platform/tests/test_loot_scoring.py`:

```python
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Session
from tests.test_api_corroboration import T0, alert

pytestmark = pytest.mark.django_db

TRUTH = {
    "admin": "pbkdf2_sha256$600000$aaa$AAAADMIN=",
    "jiwoo": "pbkdf2_sha256$600000$bbb$BBBJIWOO=",
    "minseo": "pbkdf2_sha256$600000$ccc$CCCMINSEO=",
}
EXFIL = "44444444-4444-4444-8444-444444444444"


def _board_with_detected_exfil(client):
    with patch("api.views.loot.ground_truth", return_value=dict(TRUTH)):
        session_id = client.post_json(
            "/api/sessions/", {"scenario": "board"}
        ).json()["id"]
    Session.objects.filter(pk=session_id).update(started_at=T0 - timedelta(minutes=1))
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": EXFIL, "name": "board-members-json", "malicious": True,
        "expect": "", "correlation": "marker",
        "started_at": T0.isoformat(),
        "ended_at": (T0 + timedelta(seconds=3)).isoformat(),
    })
    with patch("api.views.elastic.fetch", return_value=([alert(EXFIL, "FSL exfil")], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return session_id


def test_a_credited_loot_objective_reaches_the_scoreboard_and_game(client):
    session_id = _board_with_detected_exfil(client)
    rows = [{"username": n, "hash": TRUTH[n]} for n in TRUTH]
    client.post_json(f"/api/sessions/{session_id}/loot/",
                     {"loot": rows, "case_id": EXFIL})

    client.post_json(f"/api/sessions/{session_id}/close/")
    score = client.get(f"/api/sessions/{session_id}/score/").json()

    assert score["objectives"]["objectives"] == 3
    assert {b["key"] for b in score["breaches"]} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert score["game"]["revealed"] is True
    assert score["game"]["attacker"] > 0


def test_detected_follows_the_attributed_exfil_case_not_the_quiet_submission(client):
    session_id = _board_with_detected_exfil(client)
    rows = [{"username": "admin", "hash": TRUTH["admin"]}]
    client.post_json(f"/api/sessions/{session_id}/loot/",
                     {"loot": rows, "case_id": EXFIL})

    score = client.get(f"/api/sessions/{session_id}/score/").json()
    admin = next(b for b in score["breaches"] if b["key"] == "board-auth-user-admin")

    assert admin["detected"] is True, (
        "the loot objective must inherit detection from the correlated exfil "
        "case, not from whether the quiet submission itself was alerted"
    )
    assert admin["detection_ids"] == ["es1"]
```

- [ ] **Step 2: Run it to verify it fails or passes**

Run: `cd platform && python -m pytest tests/test_loot_scoring.py -v`
Expected: PASS if Tasks 4-5 wired `_loot_window`/`earliest`/`latest` correctly (the exfil case window `[T0, T0+3s]` is bracketed by `earliest = T0 - CLOCK_SKEW`, `latest = T0+3s + CLOCK_SKEW`, and the `alert` fires at `T0+1s` with marker `EXFIL`, so correlation detects the case and `scoreboard.attribute` credits it). If it fails, the defect is in Task 5's window math — fix `_loot_window` there, not the test.

- [ ] **Step 3: Commit**

```bash
git add platform/tests/test_loot_scoring.py
git commit -m "test(loot): credited objectives credit the zero-sum game via the exfil case"
```

---

### Task 7: End-to-end acceptance over the live stack + phase-end gate

**Files:**
- Create: `test/test_board_loot.py`
- Modify: `test/test_board.py:47-54` (the "defence alone, no objectives" assumption)
- Modify: `docs/STATE.md`, `metrics.json`

**Interfaces:**
- Consumes: the whole phase against the live compose stack via `conftest.PLATFORM_URL`, `test/range.py`'s `run(ATTACKER, ...)`/`run(SCORER, ...)`, and the Phase-1 `members.json` leak.
- Produces: proof that a real board session snapshots truth at start, that submitting the exfiltrated `members.json` hashes credits the ladder, and that the full `bin/verify` is green.

- [ ] **Step 1: Write the failing acceptance test**

Create `test/test_board_loot.py`:

```python
import json

import requests

from conftest import PLATFORM_URL
from range import ATTACKER, run

BOARD = "http://board.com"


def _board_session():
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "board"}, timeout=120
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _members_from_the_attacker():
    body = run(ATTACKER, ["curl", "-s", "--max-time", "20",
                          f"{BOARD}/members.json"]).stdout
    return {u["username"]: u["password"] for u in json.loads(body)["users"]}


def test_submitting_the_exfiltrated_hashes_credits_the_full_ladder(stack_is_up):
    session_id = _board_session()

    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "board-sqli-search"}, timeout=300,
    )
    assert fired.status_code == 201, fired.text

    loot = _members_from_the_attacker()
    rows = [{"username": name, "hash": digest} for name, digest in loot.items()]
    submitted = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/loot/",
        json={"loot": rows}, timeout=120,
    )

    assert submitted.status_code == 200, submitted.text
    assert set(submitted.json()["credited"]) == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }
    assert submitted.json()["coverage"] == 1.0


def test_fabricated_loot_is_refused_against_the_live_snapshot(stack_is_up):
    session_id = _board_session()
    requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "board-sqli-search"}, timeout=300,
    )

    submitted = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/loot/",
        json={"loot": [{"username": "admin", "password": "admin1234"}]},
        timeout=120,
    )

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["credited"] == []
```

- [ ] **Step 2: Fix the stale "no objectives" assumption in `test/test_board.py`**

`test_a_board_session_is_scored_on_defence_alone_with_no_objectives` (`test/test_board.py:47-54`) still passes as written (observe returns `{"achieved": 0, "total": 0}` before any loot), but the board is no longer defence-only. Rename and re-point it so the suite documents the new truth:

```python
def test_a_board_session_lists_its_loot_tiers_and_starts_with_none_taken(stack_is_up):
    tiers = requests.get(
        f"{PLATFORM_URL}/api/wargames/board/objectives/", timeout=60
    ).json()
    assert {t["key"] for t in tiers} == {
        "board-auth-user-partial", "board-auth-user-admin", "board-auth-user-full"
    }

    session_id = _board_session()
    observed = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
    )
    assert observed.status_code == 200, observed.text
    assert observed.json() == {"achieved": 0, "total": 0}, observed.json()
```

- [ ] **Step 3: Bring the stack up and run the board acceptance slice**

Run:
```bash
docker compose up -d --build
cd test && python -m pytest test_board_loot.py test_board.py test_board_exfil.py -v
```
Expected: PASS. (If the board/WAF image is stale from Task 1, `docker compose up -d --build board gateway` first.)

- [ ] **Step 4: Run the phase-end gate**

Run: `bin/verify`
Expected: green — unit suite, acceptance against the live stack, and the ratchet all pass.

- [ ] **Step 5: Check the gated numbers held**

Run: `bin/measure`
Expected: `core_loc` still `461`; `dependencies` `6`; `services` `7`; `wargame_services` `4`; `product_loc` risen; `tests` risen above `1220`. If `core_loc`, `dependencies`, `services`, or `wargame_services` moved, stop and find what leaked into a gated path (the loot verifier must be `platform/api/loot.py`, never `scoring/`/`ingest/`/`rules/`/`harness.py`).

- [ ] **Step 6: Record the baseline**

Run: `bin/measure --save`
Expected: `metrics.json` updated with the new `product_loc` and `tests` floor; gated numbers unchanged.

- [ ] **Step 7: Update `docs/STATE.md`**

In the "In progress" section of `docs/STATE.md`, replace the "Phase 3 ... next" note with a Phase-3-done entry: the board is `loot_verified`; the internal `/internal/auth-users` endpoint returns the `auth_user` hash map over estate and 404s through the WAF; `wargames/board/objectives.yaml` declares the partial/admin/full ladder; `POST /api/sessions/<id>/loot/` + `platform/api/loot.py` snapshot truth onto `Session.baseline`, verify exact hash matches, and credit tiers that flow into the game via the exfil case; record the new `product_loc`/`tests` from `metrics.json` and that `core_loc` held at 461. Note what is left: Phase 4 (retarget the Juice-Shop tests and remove Juice Shop + the `self_judged` value) and sub-project B (the PHP company site).

- [ ] **Step 8: Commit**

```bash
git add test/test_board_loot.py test/test_board.py metrics.json docs/STATE.md
git commit -m "test(loot): live-stack board exfil->submit->credit; record phase 3 metrics + STATE"
```

---

## Self-Review

**1. Spec coverage.**
- Internal off-WAF ground-truth endpoint returning `{username: hash}`, 404 through board.com → Task 1.
- `wargames/board/objectives.yaml` (secret scope, read path, partial=2 / admin=4 / full=5 ladder) + loader + `wargames.objectives()` accessor → Task 2.
- Product-space verifier (canonicalize → exact-hash intersect → coverage → tiers), ground-truth read mirroring `objectives._fetch` → Task 3.
- Board flipped to `loot_verified`; session-start snapshot onto `Session.baseline` (no migration); the three Phase-2 gates revisited (sessions capture at `:181-188`, `wargame_objectives` at `:362-368`, `_observe_objectives` at `:380-382`) so loot never self-judges → Task 4.
- `POST /api/sessions/<id>/loot/` writes `Objective` rows via `bulk_create(ignore_conflicts=True)` (monotonic tier upgrade), refuses after close, requires ≥1 malicious attempt, optional `case_id` → Task 5.
- Attribution/detection via `achieved_at`+`earliest`/`latest` through the unchanged `_breaches`/`scoreboard.attribute`/`game.Taken`; unattributed-take surfacing → Tasks 5 (window + flag) and 6 (game flow).
- Tests: endpoint returns hashes + 404 (T1), spec loads (T2), verifier units (T3), snapshot at start (T4), credit partial/admin/full + fabricated/partial/wrong + ≥1-malicious guard + closed refuses (T5), game flow + detected-follows-case (T6), live-stack flow + replay/fabrication over the live snapshot (T7).

**2. Placeholder scan.** Every code and test step carries full, runnable content; no "TBD"/"similar to"/"add validation". The one explicitly-deferred-to-a-later-sub-project item (sub-project B, Phase 4) is out of scope by the spec, not a placeholder.

**3. Type consistency.** `loot.ground_truth`/`canonicalize`/`matched`/`tiers_fired`/`GroundTruthUnavailable` names match between Task 3 (definition), Task 4 (`api.views.loot.ground_truth` + `GroundTruthUnavailable`), and Task 5 (`loot.matched`, `loot.tiers_fired`). `wargames.objectives(wargame_id) -> dict` with `spec["secret"]["read_path"]` and `spec["tiers"]` is consistent across Tasks 2, 3, 4, 5. `Objective(session, key, name, category, difficulty, achieved_at, earliest, latest)` matches `platform/api/models.py:76-91`. `_loot_window` returns `(achieved_at, earliest, latest)` consumed by both the row build and `scoreboard.attribute`, matching `_breaches` at `platform/api/views.py:833`. The loot response keys (`matched`, `coverage`, `credited`, `objectives`, `attempted`, `unattributed`) are asserted identically in Tasks 5-7. Tier keys `board-auth-user-{partial,admin,full}` are identical in the YAML (T2) and every test.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-10-03-attacker-proven-objective-phase-3.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
