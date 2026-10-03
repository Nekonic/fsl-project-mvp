# Attacker-Proven Objective — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Juice-Shop-shaped `judged: bool` switch with an `objective_model` enum and make the objective layer dispatch on it — a pure refactor with no behavior change, so every existing test stays green while the seam is ready for Phase 3's `loot_verified`.

**Architecture:** Each wargame declares `objective_model` (`"self_judged"` for Juice Shop, `"none"` for the board). `wargames.objective_model(id)` is the source of truth; `wargames.judged(id)` becomes a derived helper (`!= "none"`) so the `/api/wargames/` catalogue field and every current caller behave identically. The three objective call sites in `views.py` dispatch on the enum. `"loot_verified"` is a recognized value with no behavior yet (no wargame uses it until Phase 3).

**Tech Stack:** Django, pytest.

## Global Constraints

- No behavior change: every existing test green at each task; `bin/verify` green at the end. The `/api/wargames/` catalogue must still return the same `judged` boolean per wargame (juice-shop true, board false).
- `core_loc` (platform/scoring, platform/ingest, platform/rules, redteam/harness.py) stays flat at 461 — this phase touches none of it.
- `tests` floor only rises; no existing `def test_` removed or renamed.
- `services`/`dependencies`/`wargame_services` unchanged.
- No code comments or docstrings in any file.
- `objective_model` values this phase: `"self_judged"` (juice-shop), `"none"` (board). `"loot_verified"` is accepted by the dispatcher but unused until Phase 3.

---

## File structure

- `platform/wargames.py` — `WARGAMES` entries carry `objective_model` instead of `judged`; add `objective_model(id)`; `judged(id)` derived; `_summarise` derives the catalogue `judged` field.
- `platform/api/views.py` — the three objective call sites (`sessions` baseline :182, `wargame_objectives` catalogue :366, `_observe_objectives` :381) dispatch on `wargames.objective_model(...)`.
- `platform/tests/test_wargames_objective_model.py` — new unit tests pinning the enum values and the derived `judged`.

---

### Task 1: Introduce `objective_model` as the source of truth in `wargames.py`

**Files:**
- Modify: `platform/wargames.py` (WARGAMES entries, `judged`, new `objective_model`, `_summarise`)
- Test: `platform/tests/test_wargames_objective_model.py`

**Interfaces:**
- Produces: `wargames.objective_model(wargame_id) -> str` (`"self_judged" | "none" | "loot_verified"`); `wargames.judged(wargame_id) -> bool` now returns `objective_model(wargame_id) != "none"`.

- [ ] **Step 1: Write the failing test.** Create `platform/tests/test_wargames_objective_model.py`:

```python
import wargames


def test_juice_shop_is_self_judged_and_counts_as_judged():
    assert wargames.objective_model("juice-shop") == "self_judged"
    assert wargames.judged("juice-shop") is True


def test_board_has_no_objective_model_and_is_not_judged():
    assert wargames.objective_model("board") == "none"
    assert wargames.judged("board") is False


def test_the_catalogue_still_exposes_the_derived_judged_boolean():
    by_id = {w["id"]: w for w in wargames.catalogue()}
    assert by_id["juice-shop"]["judged"] is True
    assert by_id["board"]["judged"] is False
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd platform && DJANGO_SETTINGS_MODULE=fsl.settings ../.venv/bin/python -m pytest tests/test_wargames_objective_model.py -q`
Expected: FAIL — `wargames.objective_model` does not exist yet (AttributeError).

- [ ] **Step 3: Refactor `wargames.py`.** In `WARGAMES`, replace the juice-shop entry's `"judged": True,` with `"objective_model": "self_judged",` and the board entry's `"judged": False,` with `"objective_model": "none",`. Replace the `judged` function and add the accessor:

```python
def objective_model(wargame_id: str) -> str:
    return WARGAMES[wargame_id]["objective_model"]


def judged(wargame_id: str) -> bool:
    return objective_model(wargame_id) != "none"
```

In `_summarise`, replace `"judged": wargame["judged"],` with `"judged": wargame["objective_model"] != "none",`.

- [ ] **Step 4: Run the new test and the touched suites.**

Run: `cd platform && DJANGO_SETTINGS_MODULE=fsl.settings ../.venv/bin/python -m pytest tests/test_wargames_objective_model.py tests/test_board_wargame.py tests/test_catalogue.py -q`
Expected: PASS — new tests pass and the catalogue/board tests are unaffected (the derived `judged` matches the old values).

- [ ] **Step 5: Commit.**

```bash
git add platform/wargames.py platform/tests/test_wargames_objective_model.py
git commit -m "refactor(wargames): objective_model enum is the source of truth, judged derived"
```

---

### Task 2: Dispatch the objective call sites on `objective_model`

**Files:**
- Modify: `platform/api/views.py` (three call sites)

**Interfaces:**
- Consumes: `wargames.objective_model(id)` from Task 1.

- [ ] **Step 1: Switch the three call sites.** In `platform/api/views.py`, change each `wargames.judged(...)` objective gate to read the enum, preserving behavior exactly:

In `sessions` (the baseline capture, currently `if wargames.judged(scenario):`):
```python
    if wargames.objective_model(scenario) == "self_judged":
```

In `wargame_objectives` (currently `if not wargames.judged(wargame_id):`):
```python
    if wargames.objective_model(wargame_id) == "none":
        return _reply([])
```

In `_observe_objectives` (currently `if not wargames.judged(session.scenario):`):
```python
    if wargames.objective_model(session.scenario) == "none":
        return {"achieved": 0, "total": 0}
```

(Leave all other lines in these functions unchanged. `judged()` remains for any non-objective caller and the catalogue.)

- [ ] **Step 2: Run the objective/session suites to confirm no behavior change.**

Run: `cd platform && DJANGO_SETTINGS_MODULE=fsl.settings ../.venv/bin/python -m pytest tests/test_api_objectives.py tests/test_api_sessions.py tests/test_session_close.py tests/test_board_wargame.py tests/test_api_corroboration.py -q`
Expected: PASS — juice-shop (`self_judged`) still captures a baseline, observes, and lists objectives; board (`none`) still returns none. Behavior is identical because for the two current wargames `objective_model == "self_judged"` is exactly the old `judged == True` and `== "none"` is the old `judged == False`.

- [ ] **Step 3: Commit.**

```bash
git add platform/api/views.py
git commit -m "refactor(objectives): dispatch the objective gates on objective_model"
```

---

## Self-review

- **Spec coverage:** Phase 2 of the spec = "`judged:bool` → `objective_model` enum dispatcher refactor; transitional `self_judged` for Juice Shop; no behavior change." Task 1 introduces the enum + derived `judged`; Task 2 moves the dispatch onto it. Covered.
- **No behavior change:** for the only two wargames, `self_judged` ≡ old `judged True` and `none` ≡ old `judged False`; the catalogue `judged` field is derived to the same booleans; `loot_verified` is unused this phase.
- **Placeholders:** none — all code is literal.
- **Consistency:** `objective_model(id)` defined in Task 1 is the exact symbol Task 2 calls.
- **Phase-end gate:** after Task 2, run full `bin/verify` (controller does this) and `bin/measure --save`; core_loc must stay 461.
