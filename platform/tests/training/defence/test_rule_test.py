import pytest

from cr import errors
from sandbox.runner import Ran
from telemetry.models import Event
from tests.training.defence.conftest import BASELINE, LOGIN_RULE, RECORDED, SEARCH_RULE
from training.defence import rules as service

BASE = "/api/rounds/{round}/defence/"
BENIGN = ("board-normal-search", "board-normal-search-with-apostrophe", "board-normal-post-list", "board-normal-sort",
          "board-normal-search-korean", "board-normal-comment")


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def verdicts(result):
    return {row["case"]: row["verdict"] for row in result["cases"]}


def test_an_ids_test_replays_the_probe_set_offline_and_returns_a_verdict_per_case(as_defender, board_round,
                                                                                  cyber_range):
    answer = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")

    assert answer.status_code == 200
    result = answer.json()
    assert result["ok"] is True and result["errors"] == []
    assert verdicts(result) == {
        "board-sqli-search": "tp", "board-sqli-login-bypass": "fn", "board-sqli-orderby-sqlmap": "tp",
        "board-normal-search": "tn", "board-normal-search-with-apostrophe": "fp", "board-normal-post-list": "tn",
        "board-normal-sort": "tn", "board-normal-search-korean": "tn"}
    assert result["totals"] == {"tp": 2, "fn": 1, "fp": 1, "tn": 4}
    assert result["untested"] == [{"case": "board-normal-comment", "reason": "not_recorded"}]
    search = next(row for row in result["cases"] if row["case"] == "board-sqli-search")
    assert search["alerts"] == [{"rule": "1001", "signature": "SQL injection in search"}]
    assert search["corroborated"] is False and search["recorded_run"] is False
    assert next(row for row in result["cases"] if row["case"] == "board-sqli-orderby-sqlmap")["recorded_run"] is True


def test_a_signature_that_names_the_mechanism_and_spares_the_benign_cases_corroborates(as_defender, board_round):
    result = as_defender.post(url(board_round, "ids/rules/test/"), {"text": LOGIN_RULE}, format="json").json()

    login = next(row for row in result["cases"] if row["case"] == "board-sqli-login-bypass")
    assert login["verdict"] == "tp" and login["corroborated"] is True


def test_the_ids_test_runs_on_the_sensor_node_in_a_scratch_and_never_touches_the_live_rules(as_defender, board_round,
                                                                                           cyber_range):
    as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")

    node = cyber_range.nodes["sensor"].texts()
    assert any("docker run --rm" in text and "/var/lib/cr-ruletest/test-1" in text for text in node)
    assert not any("-l /var/log/suricata" in text for text in node)
    assert node[-1].startswith("rm -rf /var/lib/cr-ruletest/test-1-pcaps")
    assert cyber_range.sensors["sensor"].rules == BASELINE
    assert not any("reload-rules" in text for text in cyber_range.sensors["sensor"].texts())


def test_benign_cases_are_always_probed_even_when_the_caller_names_only_attacks(as_defender, board_round):
    answer = as_defender.post(url(board_round, "ids/rules/test/"),
                              {"text": SEARCH_RULE, "cases": ["board-sqli-login-bypass"]}, format="json")

    tested = set(verdicts(answer.json())) | {row["case"] for row in answer.json()["untested"]}
    assert tested == {"board-sqli-login-bypass", *BENIGN}


def test_a_case_the_wargame_does_not_declare_is_not_found(as_defender, board_round):
    answer = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE, "cases": ["made-up"]},
                              format="json")

    assert answer.status_code == 404
    assert answer.json()["errors"] == [{"path": "cases", "code": "unknown_case"}]


def test_a_waf_test_lists_tool_cases_untested_and_replays_http_probes_against_the_scratch_instance(
        as_defender, board_round, cyber_range):
    cyber_range.gateway.blocks = {"probe-board-sqli-search": "SQL Injection Attack Detected via libinjection"}

    answer = as_defender.post(url(board_round, "waf/test/"), {"posture": {"paranoia": 2}}, format="json")

    result = answer.json()
    assert result["ok"] is True
    assert {"case": "board-sqli-orderby-sqlmap", "reason": "tool_case"} in result["untested"]
    assert {"case": "board-normal-comment", "reason": "not_recorded"} in result["untested"]
    assert verdicts(result)["board-sqli-search"] == "tp"
    assert verdicts(result)["board-sqli-login-bypass"] == "fn"
    assert verdicts(result)["board-normal-search"] == "tn"
    replayed = {probe["marker"]: probe for probe in cyber_range.gateway.probes}
    assert "probe-board-sqli-orderby-sqlmap" not in replayed
    assert replayed["probe-board-sqli-login-bypass"]["body"] == RECORDED["board-sqli-login-bypass"]["body"]
    assert replayed["probe-board-sqli-search"]["response"] == {"status": 200, "body": "ok"}
    assert not any("nginx -s reload" in text for text in cyber_range.gateway.texts())
    assert cyber_range.gateway.file == ""


def test_a_test_whose_rules_do_not_parse_returns_the_errors_and_no_verdicts(as_defender, board_round, cyber_range):
    cyber_range.sensors["sensor"].syntax = {1: "unknown keyword"}

    answer = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")

    result = answer.json()
    assert answer.status_code == 200 and result["ok"] is False and result["cases"] == []
    assert result["errors"][0]["code"] == "suricata_syntax" and result["errors"][0]["line"] == 1
    assert not cyber_range.nodes.get("sensor") or not cyber_range.nodes["sensor"].sent


def test_a_waf_test_nginx_refuses_comes_back_as_errors(as_defender, board_round, cyber_range):
    cyber_range.gateway.nginx_errors = "unknown directive"

    result = as_defender.post(url(board_round, "waf/test/"), {"posture": {"paranoia": 2}}, format="json").json()

    assert result["ok"] is False
    assert result["errors"] == [{"path": "posture", "code": "crs_refused", "line": 3, "message": "unknown directive"}]


def test_a_second_test_while_one_runs_on_the_same_lease_and_engine_is_busy(as_defender, board_round, defender,
                                                                           cyber_range):
    seen = []

    def again():
        if seen:
            return
        with pytest.raises(errors.Conflict) as refused:
            service.test_rules(board_round, defender, "ids", SEARCH_RULE)
        seen.append(refused.value.code)
        seen.append(service.test_rules(board_round, defender, "waf", {"paranoia": 2}).result["ok"])

    cyber_range.node_runner("sensor").during = again

    answer = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")

    assert answer.status_code == 200
    assert seen == ["test_busy", True]
    assert as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json").status_code == 200


def test_the_busy_refusal_reaches_the_api_as_409(as_defender, board_round, cyber_range):
    answers = []
    cyber_range.node_runner("sensor").during = lambda: answers.append(as_defender.post(
        url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")) if not answers else None

    as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")

    assert answers[0].status_code == 409
    assert answers[0].json() == {"errors": [{"path": "", "code": "test_busy"}]}


def test_a_stored_test_reads_back_and_records_the_event_for_the_defence_side_only(as_defender, board_round):
    made = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json").json()

    again = as_defender.get(url(board_round, f"ids/rules/tests/{made['test']}/"))

    assert again.json() == made
    assert as_defender.get(url(board_round, f"waf/tests/{made['test']}/")).status_code == 404
    event = Event.objects.get(round_id=board_round.pk, kind="rule.tested")
    assert event.body == {"test": made["test"], "engine": "ids", "ok": True} and event.seat_side == "defence"


def test_a_test_compares_its_verdicts_with_the_applied_version_s_test(as_defender, board_round):
    tested = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json").json()
    as_defender.post(url(board_round, "ids/rules/apply/"),
                     {"text": SEARCH_RULE, "base_version": 0, "tested": tested["test"]}, format="json")

    candidate = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE + LOGIN_RULE},
                                 format="json").json()

    assert candidate["against_applied"] == [{"case": "board-sqli-login-bypass", "was": "fn", "now": "tp"}]


def test_the_probe_set_lists_the_round_s_cases_with_their_recordings(as_defender, board_round):
    listed = {row["case"]: row for row in as_defender.get(url(board_round, "probes/")).json()}

    assert set(listed) == {"board-sqli-search", "board-sqli-login-bypass", "board-sqli-orderby-sqlmap", *BENIGN}
    assert listed["board-sqli-orderby-sqlmap"] == {"case": "board-sqli-orderby-sqlmap", "malicious": True,
                                                   "recorded": True, "tool_case": True}
    assert listed["board-normal-comment"]["recorded"] is False


def test_the_check_routes_return_errors_without_running_any_probe(as_defender, board_round, cyber_range):
    cyber_range.sensors["sensor"].syntax = {2: "bad"}

    ids = as_defender.post(url(board_round, "ids/rules/check/"), {"text": SEARCH_RULE + LOGIN_RULE}, format="json")
    unread = as_defender.post(url(board_round, "ids/rules/check/"), {"text": "alert x (msg:\"a\";)\n"},
                              format="json")
    waf = as_defender.post(url(board_round, "waf/check/"), {"posture": {"paranoia": 7}}, format="json")
    fine = as_defender.post(url(board_round, "waf/check/"), {"posture": {"paranoia": 1}}, format="json")

    assert ids.json()["ok"] is False and ids.json()["errors"][0]["line"] == 2
    assert unread.json() == {"ok": False, "errors": [{"path": "text", "code": "unread_sid", "line": 1,
                                                      "message": 'alert x (msg:"a";)'}]}
    assert waf.json()["ok"] is False and waf.json()["errors"][0]["code"] == "crs_refused"
    assert fine.json() == {"ok": True, "errors": []}
    assert not cyber_range.nodes.get("sensor") or not cyber_range.nodes["sensor"].sent
    assert not any(one.argv[0] == "curl" for one in cyber_range.gateway.sent)


def test_a_posture_the_validator_refuses_names_the_field_it_refuses(as_defender, board_round, cyber_range):
    posture = {"paranoia": 2, "exclusions": [{"rule_id": 942100, "target": "ARGS:q"},
                                             {"rule_id": 942100, "target": "NOT A VARIABLE"}]}

    checked = as_defender.post(url(board_round, "waf/check/"), {"posture": posture}, format="json").json()
    applied = as_defender.post(url(board_round, "waf/apply/"), {"posture": posture, "base_version": 0},
                               format="json")

    assert [(error["path"], error["code"]) for error in checked["errors"]] == [
        ("exclusions[1].target", "crs_refused")]
    assert applied.status_code == 422
    assert [(error["path"], error["code"]) for error in applied.json()["errors"]] == [
        ("exclusions[1].target", "crs_refused")]


def test_a_test_the_sensor_cannot_finish_leaves_no_test_behind(as_defender, board_round, cyber_range):
    def unreachable(argv, stdin=None, timeout=60.0):
        return Ran(255, "ssh: connect to host refused")

    cyber_range.nodes["sensor"] = unreachable

    answer = as_defender.post(url(board_round, "ids/rules/test/"), {"text": SEARCH_RULE}, format="json")

    assert answer.status_code == 503
    assert answer.json()["errors"][0]["code"] == "sensor_unavailable"
    assert service.latest_test(board_round, "ids") is None
    assert not Event.objects.filter(round_id=board_round.pk, kind="rule.tested").exists()
