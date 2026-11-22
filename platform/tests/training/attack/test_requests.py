import pytest

from testing.fakerange import REFUSED_PAGE, RU
from tests.shape import refused
from tests.training.attack.conftest import codes, url
from training.attack import actions as service
from training.models import Action

pytestmark = pytest.mark.django_db

def sent_requests(cloud):
    return cloud.box.matching("cr.status=")


def test_a_request_goes_out_from_the_box_with_the_action_s_own_marker_and_the_chosen_host(as_attacker, attacker,
                                                                                         cloud):
    answer = as_attacker.post(url(attacker.round, "requests/"), {
        "method": "POST", "path": "/search/", "query": {"q": "it's"},
        "headers": {"X-Request-ID": "forged", "Host": "evil.test", "Accept": "text/html"}, "body": "a=1"},
        format="json")

    assert answer.status_code == 200
    body = answer.json()
    action = Action.objects.get(pk=body["action"])
    [sent] = sent_requests(cloud)
    assert f"X-Request-ID: {action.marker}" in sent.argv and "X-Request-ID: forged" not in sent.argv
    assert "Host: board.com" in sent.argv and "Host: evil.test" not in sent.argv
    assert "Accept: text/html" in sent.argv
    assert sent.argv[-1] == "http://board.com/search/?q=it%27s"
    assert sent.stdin == "a=1"
    assert (body["status"], body["body"], body["truncated"]) == (200, "<p>hello</p>", False)
    assert body["marker"] == action.marker
    assert ["Server", "nginx"] in body["headers"]
    assert (action.kind, action.correlation, action.source_ip, action.malicious) == ("request", "marker", RU, None)


def test_a_request_is_logged_whole_so_a_rule_test_can_replay_it(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "requests/"), {
        "method": "POST", "path": "/search/", "query": {"q": "it's"},
        "headers": {"X-Request-ID": "forged", "Accept": "text/html"}, "body": "a=1"}, format="json")

    meta = Action.objects.get(pk=answer.json()["action"]).meta
    assert (meta["method"], meta["path"], meta["query"], meta["body"]) == ("POST", "/search/", {"q": "it's"}, "a=1")
    assert meta["headers"] == {"Accept": "text/html"}


def test_a_refused_request_does_not_spend_the_origin_it_went_out_from(as_attacker, attacker, cloud):
    cloud.box.answer("cr.status=", REFUSED_PAGE)

    answer = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/admin/"}, format="json")

    assert answer.json()["status"] == 403
    assert answer.json()["remaining"]["spent"] == []
    assert answer["X-Origin"] == RU, "only the WAF's error log spends an origin; a CRS 403 leaves it standing"


def test_a_host_the_wargame_does_not_serve_is_refused_by_path_and_sends_nothing(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/", "host": "corp.com"},
                              format="json")

    refused(answer, 400, "invalid_choice", path="host")
    assert sent_requests(cloud) == []


def test_a_header_that_would_split_the_request_is_refused(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "requests/"), {
        "method": "GET", "path": "/", "headers": {"X-Note": "a\r\nX-Other: b"}}, format="json")

    assert answer.status_code == 400
    assert codes(answer) == ["invalid"]
    assert sent_requests(cloud) == []


def test_a_request_that_never_reaches_the_target_is_a_box_fault_and_records_nothing(as_attacker, attacker, cloud):
    cloud.box.answer("cr.status=", "curl: (7) Failed to connect\ncr.status=000\n", 7)

    answer = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/"}, format="json")

    assert answer.status_code == 503
    assert codes(answer) == ["attacker_unavailable"]
    assert not Action.objects.filter(round=attacker.round).exists()


def test_a_long_body_comes_back_truncated(as_attacker, attacker, cloud):
    cloud.box.answer("cr.status=", "HTTP/1.1 200 OK\r\n\r\n" + "x" * (service.BODY_LIMIT + 5) + "\ncr.status=200\n")

    answer = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/"}, format="json")

    assert answer.json()["truncated"] is True
    assert len(answer.json()["body"]) == service.BODY_LIMIT


def test_the_sent_action_is_a_free_action_record_with_no_verdict(as_attacker, attacker):
    as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/search/"}, format="json")

    [record] = service.actions(attacker.round)

    assert (record.kind, record.malicious, record.method, record.path) == ("request", None, "GET", "/search/")
    assert record.as_case().declared is False
