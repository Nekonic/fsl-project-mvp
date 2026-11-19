from datetime import datetime, timezone

import pytest

from attack import service
from attack.models import Action
from events import log
from events.kinds import Viewer
from tests.attack.conftest import codes, url
from testing.fakerange import REFUSED_PAGE, RU

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, 0, tzinfo=timezone.utc)


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


def test_a_sent_request_is_charged_on_the_spot_and_a_refusal_costs_more(as_attacker, attacker, cloud):
    first = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/"}, format="json")
    cloud.box.answer("cr.status=", REFUSED_PAGE)
    second = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/admin/"}, format="json")

    assert first.json()["hp"]["left"] == 99
    assert second.json()["status"] == 403
    assert second.json()["hp"]["left"] == 96
    assert second["X-Origin-HP"] == "96"
    charged = [event["body"] for event in log.after(attacker.round_id, 0, Viewer(sides=frozenset({"attack"}))).events
               if event["kind"] == "origin.charged"]
    assert charged == [{"ip": RU, "charged": 1, "left": 99}, {"ip": RU, "charged": 3, "left": 96}]


def test_requests_beyond_the_burst_within_one_second_cost_double(as_attacker, attacker, monkeypatch):
    monkeypatch.setattr(service, "now", lambda: AT)

    lefts = [as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/"},
                              format="json").json()["hp"]["left"] for _ in range(7)]

    assert lefts == [99, 98, 97, 96, 95, 93, 91]


def test_a_host_the_wargame_does_not_serve_is_refused_by_path_and_charges_nothing(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/", "host": "corp.com"},
                              format="json")

    assert answer.status_code == 400
    assert answer.json()["errors"][0]["path"] == "host"
    assert answer.json()["hp"]["left"] == 100
    assert sent_requests(cloud) == []


def test_a_header_that_would_split_the_request_is_refused(as_attacker, attacker, cloud):
    answer = as_attacker.post(url(attacker.round, "requests/"), {
        "method": "GET", "path": "/", "headers": {"X-Note": "a\r\nX-Other: b"}}, format="json")

    assert answer.status_code == 400
    assert codes(answer) == ["invalid"]
    assert sent_requests(cloud) == []


def test_a_request_that_never_reaches_the_target_is_a_box_fault_and_charges_nothing(as_attacker, attacker, cloud):
    cloud.box.answer("cr.status=", "curl: (7) Failed to connect\ncr.status=000\n", 7)

    answer = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/"}, format="json")

    assert answer.status_code == 503
    assert codes(answer) == ["attacker_unavailable"]
    assert answer.json()["hp"]["left"] == 100
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
