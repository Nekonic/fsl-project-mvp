import json

import pytest

from cr import strings
from sandbox import kibana
from tests import rounds

GATE = "/kibana-gate/"
OWN_SPACE = "soc-logs-1"
SEARCH = {"params": {"index": "logs-1-*", "body": {"query": {"match_all": {}}}}}


@pytest.fixture
def forwarded(monkeypatch):
    sent = []

    def forward(method, uri, headers, body, config):
        sent.append((method, uri, body))
        return 200, [("Content-Type", "application/json"), ("kbn-name", "kibana")], b'{"rawResponse":{"hits":{}}}'

    monkeypatch.setattr(kibana, "forward", forward)
    return sent


def gated(client, uri, method="post", body=None):
    return getattr(client, method)(GATE, data=json.dumps(body) if body is not None else None,
                                   content_type="application/json", HTTP_X_KIBANA_URI=uri)


def test_the_gate_forwards_a_discover_search_of_the_player_s_own_space(as_defender, forwarded):
    answer = gated(as_defender, f"/kibana/s/{OWN_SPACE}/internal/search/ese", body=SEARCH)

    assert answer.status_code == 200
    assert answer.content == b'{"rawResponse":{"hits":{}}}'
    assert answer["kbn-name"] == "kibana"
    assert forwarded[0][:2] == ("POST", f"/kibana/s/{OWN_SPACE}/internal/search/ese")


def test_the_gate_refuses_another_round_s_space_in_korean_without_forwarding(as_defender, forwarded):
    answer = gated(as_defender, "/kibana/s/soc-logs-2/internal/search/ese", body=SEARCH)

    assert answer.status_code == 403
    assert answer.json() == {"statusCode": 403, "error": "Forbidden", "message": strings.line("kibana.refused.space")}
    assert forwarded == []


def test_the_gate_refuses_a_call_discover_never_makes(as_defender, forwarded):
    answer = gated(as_defender, f"/kibana/s/{OWN_SPACE}/api/saved_objects/_find", method="get")

    assert answer.status_code == 403
    assert answer.json()["message"] == strings.line("kibana.refused.call")
    assert forwarded == []


def test_a_search_that_reaches_past_the_round_s_index_is_refused(as_defender, forwarded):
    answer = gated(as_defender, f"/kibana/s/{OWN_SPACE}/internal/search/ese",
                   body={"params": {"index": "logs-*", "body": {}}})

    assert answer.status_code == 403
    assert forwarded == []


def test_a_user_with_no_defence_player_reaches_no_space(browser, board_round, make_user, forwarded):
    attacker = make_user("attacker")
    rounds.playing(board_round, "attack", user=attacker)
    browser.force_authenticate(attacker)

    answer = gated(browser, f"/kibana/s/{OWN_SPACE}/internal/search/ese", body=SEARCH)

    assert answer.status_code == 403
    assert forwarded == []


def test_staff_reach_every_space(browser, board_round, staff, forwarded):
    browser.force_authenticate(staff)

    answer = gated(browser, "/kibana/s/soc-logs-2/internal/search/ese", body={"params": {"index": "logs-2-*"}})

    assert answer.status_code == 200
    assert forwarded[0][:2] == ("POST", "/kibana/s/soc-logs-2/internal/search/ese")


def test_a_signed_out_caller_is_refused_with_the_one_error_shape(browser, board_round, forwarded):
    answer = gated(browser, f"/kibana/s/{OWN_SPACE}/internal/search/ese", body=SEARCH)

    assert answer.status_code == 401
    assert answer.json() == {"errors": [{"path": "", "code": "not_signed_in"}]}
    assert forwarded == []


def test_an_unanswering_kibana_is_a_bad_gateway(as_defender, monkeypatch):
    def down(*given, **named):
        raise OSError("connection refused")

    monkeypatch.setattr(kibana, "forward", down)

    answer = gated(as_defender, f"/kibana/s/{OWN_SPACE}/internal/search/ese", body=SEARCH)

    assert answer.status_code == 502
    assert answer.json()["message"] == strings.line("kibana.unanswered")


def test_the_player_gets_the_discover_url_of_its_space_once_the_view_is_ready(as_defender, board_round, monkeypatch):
    monkeypatch.setenv("KIBANA_URL", "http://kibana:5601/kibana")
    monkeypatch.setattr(kibana, "VIEWS", {})
    asked = []
    monkeypatch.setattr(kibana, "send_json", lambda request: asked.append(request.full_url) or {"success": True})

    answer = as_defender.get(f"/api/rounds/{board_round.pk}/defence/kibana/")

    assert answer.status_code == 200
    assert answer.json() == {"space_url": f"/kibana/s/{OWN_SPACE}/app/discover"}
    assert any(f"/s/{OWN_SPACE}/api/saved_objects/_import" in url for url in asked)


def test_a_kibana_that_cannot_make_the_view_is_unavailable(as_defender, board_round, monkeypatch):
    monkeypatch.setattr(kibana, "VIEWS", {})

    answer = as_defender.get(f"/api/rounds/{board_round.pk}/defence/kibana/")

    assert answer.status_code == 503
    assert answer.json()["errors"][0]["code"] == "kibana_unavailable"
