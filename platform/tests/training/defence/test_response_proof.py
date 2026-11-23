from django.utils import timezone

from training.defence import rules as service
from training.models import Action, RuleSet, RuleTest

BASE = "/api/rounds/{round}/defence/"
HTTP = "/etc/nginx/defence/http.conf"
DENY = "deny 203.0.113.9;\n"
FREE = {"method": "POST", "path": "/search/", "host": "board.com", "status": 200, "query": {"q": "' or 2=2--"},
        "headers": {"Content-Type": "text/plain"}, "body": "x=1"}


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def sent(found, player, marker, kind, **fields):
    now = timezone.now()
    return Action.objects.create(round=found, player=player, kind=kind, marker=marker, correlation="marker",
                                 source_ip="198.51.100.7", started=now, ended=now, **fields)


def test_a_waf_test_replays_the_round_s_attack_requests_and_records_which_it_refused(as_defender, board_round,
                                                                                   defender, cyber_range):
    sent(board_round, defender, "m-case", "case", case_id="board-sqli-search", malicious=True)
    sent(board_round, defender, "m-free", "request", meta=FREE)
    sent(board_round, defender, "m-tool", "tool", meta={"tool": "sqlmap", "args": []})
    cyber_range.gateway.refused_paths = ("/search/?q=%27+or+2%3D2--",)

    shown = as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json").json()

    stored = RuleTest.objects.get(pk=shown["test"]).result
    assert stored["actions"] == [{"marker": "m-case", "refused": False}, {"marker": "m-free", "refused": True}]
    free = next(probe for probe in cyber_range.gateway.probes if probe.get("body") == "x=1")
    assert (free["method"], free["path"], free["body"]) == ("POST", "/search/?q=%27+or+2%3D2--", "x=1")
    assert "actions" not in shown and shown["totals"]["fp"] == 0


def test_a_rule_keyed_on_the_live_request_id_refuses_no_replayed_attack(as_defender, board_round, defender,
                                                                       cyber_range):
    sent(board_round, defender, "m-free", "request", meta=FREE)
    cyber_range.gateway.blocks = {"m-free": "matched the logged request id"}

    shown = as_defender.post(url(board_round, "waf/test/"), {"files": {HTTP: DENY}}, format="json").json()

    assert RuleTest.objects.get(pk=shown["test"]).result["actions"] == [{"marker": "m-free", "refused": False}]
    assert "m-free" not in {probe["marker"] for probe in cyber_range.gateway.probes}


def test_only_a_waf_version_whose_passed_test_replayed_attacks_is_a_response(board_round):
    waf = RuleTest.objects.create(round=board_round, engine="waf", sha="a", syntax_ok=True,
                                  result={"passed": True, "actions": [{"marker": "m-free", "refused": True},
                                                                      {"marker": "m-case", "refused": False}]})
    failed = RuleTest.objects.create(round=board_round, engine="waf", sha="b", syntax_ok=True,
                                     result={"passed": False, "actions": [{"marker": "m-free", "refused": True}]})
    ids = RuleTest.objects.create(round=board_round, engine="ids", sha="c", syntax_ok=True,
                                  result={"passed": True, "actions": []})
    for version, (engine, test) in enumerate((("waf", waf), ("waf", failed), ("ids", ids)), start=1):
        RuleSet.objects.create(round=board_round, engine=engine, version=version, sha=test.sha, source="console",
                               applied_at=timezone.now(), tested=test, same_as_tested=True)

    found = service.applied(board_round)

    assert [(one.replayed, one.refused) for one in found] == [(frozenset({"m-free", "m-case"}), frozenset({"m-free"}))]
