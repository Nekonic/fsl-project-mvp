import time
import uuid
from datetime import datetime, timedelta, timezone

import requests

import test_corp_cve_content_write as content
import test_corp_observe_live as exploits
from conftest import PLATFORM_URL


def _session():
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=120
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _close(session_id):
    requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120
    )


def _record_window(session_id, name, fired_at, done_at):
    window = {
        "case_id": f"{name}-{uuid.uuid4().hex[:8]}",
        "name": name,
        "malicious": True,
        "correlation": "marker",
        "started_at": (fired_at - timedelta(seconds=3)).isoformat(),
        "ended_at": (done_at + timedelta(seconds=3)).isoformat(),
    }
    recorded = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/", json=window, timeout=60
    )
    assert recorded.status_code == 201, recorded.text


def _observe(session_id):
    observed = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=120
    ).json()
    assert observed["total"] == 3, observed
    return observed


def _credited_keys(session_id):
    listed = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
    ).json()
    return {o["key"] for o in listed}


def _score(session_id):
    return requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60
    ).json()


def _fire(session_id, case):
    posted = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": case}, timeout=120,
    )
    assert posted.status_code == 201, posted.text
    return posted.json()["case_id"]


def test_corp_is_offered_in_the_console_catalogue(stack_is_up):
    catalogue = requests.get(f"{PLATFORM_URL}/api/wargames/", timeout=60).json()
    corp = next((w for w in catalogue if w["id"] == "corp"), None)
    assert corp is not None, catalogue
    assert corp["judged"] is True, corp
    assert corp["public_url"] == "http://corp.com", corp


def test_a_live_rogue_admin_is_credited_from_the_targets_own_row_with_no_signature(stack_is_up):
    baseline = exploits._admin_ids()
    created = set()
    session_id = None
    try:
        session_id = _session()
        time.sleep(2)
        fired_at = datetime.now(timezone.utc)
        code = exploits._submit(exploits._register_nonce(), f"rogue_{uuid.uuid4().hex[:8]}")
        assert code == "302", f"the rogue-admin registration did not complete, got {code!r}"
        done_at = datetime.now(timezone.utc)

        created = exploits._admin_ids() - baseline
        assert created and all(uid > 1 for uid in created), (
            f"no non-baseline administrator was committed; admins {sorted(exploits._admin_ids())}"
        )

        _record_window(session_id, "corp-rogue-admin", fired_at, done_at)
        _observe(session_id)

        assert "corp-rogue-admin" in _credited_keys(session_id)

        score = _score(session_id)
        breach = next((b for b in score["breaches"] if b["key"] == "corp-rogue-admin"), None)
        assert breach is not None, score["breaches"]
        assert breach["detected"] is False, breach
        assert breach["detection_ids"] == [], breach
        assert score["objectives"]["objectives"] >= 1, score["objectives"]
    finally:
        for uid in sorted(created):
            exploits._delete(uid)
        assert exploits._admin_ids() == baseline, (
            f"left corp-db dirty: admins now {sorted(exploits._admin_ids())}, baseline {sorted(baseline)}"
        )
        if session_id is not None:
            _close(session_id)


def test_a_live_option_flip_is_credited_from_the_targets_own_row(stack_is_up):
    session_id = None
    try:
        session_id = _session()
        time.sleep(2)
        fired_at = datetime.now(timezone.utc)
        nonce = exploits._ajax_nonce()
        assert exploits._flip(nonce, "users_can_register", "1") == "200"
        assert exploits._flip(nonce, "default_role", "administrator") == "200"
        assert exploits._option("users_can_register") == "1"
        done_at = datetime.now(timezone.utc)

        _record_window(session_id, "corp-self-registration", fired_at, done_at)
        _observe(session_id)

        assert "corp-self-registration" in _credited_keys(session_id)

        score = _score(session_id)
        assert "corp-self-registration" in {b["key"] for b in score["breaches"]}, score["breaches"]
    finally:
        exploits._set_option("users_can_register", "0")
        exploits._set_option("default_role", "subscriber")
        assert exploits._option("users_can_register") == "0"
        assert exploits._option("default_role") == "subscriber"
        if session_id is not None:
            _close(session_id)


def test_a_live_content_overwrite_is_credited_from_the_targets_own_row(stack_is_up):
    original = content._target_post()
    session_id = None
    title = "Defaced by an unauthenticated guest"
    excerpt = "overwritten without owning this post"
    body = "overwritten without owning this post via rbsm_submit_post postId overwrite"
    try:
        session_id = _session()
        time.sleep(2)
        fired_at = datetime.now(timezone.utc)
        response = content._overwrite_post(content._nonce(), original["ID"], title, excerpt, body)
        assert '"success":true' in response, f"the postId overwrite was refused: {response!r}"
        after = content._row(original["ID"])
        assert after["post_title"] == title and after["post_content"] == body, after
        done_at = datetime.now(timezone.utc)

        _record_window(session_id, "corp-content-write", fired_at, done_at)
        _observe(session_id)

        assert "corp-content-overwrite" in _credited_keys(session_id)

        score = _score(session_id)
        assert "corp-content-overwrite" in {b["key"] for b in score["breaches"]}, score["breaches"]
    finally:
        content._restore(original)
        restored = content._row(original["ID"])
        assert restored == {
            "post_title": original["post_title"],
            "post_content": original["post_content"],
            "post_excerpt": original["post_excerpt"],
            "post_status": original["post_status"],
        }, restored
        if session_id is not None:
            _close(session_id)
