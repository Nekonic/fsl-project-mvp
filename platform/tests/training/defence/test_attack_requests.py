from datetime import timedelta

from training.defence import rules as service
from training.models import Origin

ORIGIN = "5.188.10.10"


def logged(at, request):
    return {"@timestamp": at.isoformat(), "time": at.isoformat(), "event": {"module": "nginx_access"},
            "client_ip": ORIGIN, "status": 200, "vhost": "board.com", "request": request}


def test_the_replay_list_carries_origin_requests_once_per_identical_line_without_a_body(board_round, es, at):
    Origin.objects.create(round=board_round, origin_id="o1", ip=ORIGIN, label="current")
    es.add("a1", logged(at, "GET /search/?q=%27+or+1%3D1-- HTTP/1.1"))
    es.add("a2", logged(at + timedelta(seconds=1), "GET /search/?q=%27+or+1%3D1-- HTTP/1.1"))
    es.add("a3", logged(at + timedelta(seconds=2), "POST /accounts/login/ HTTP/1.1"))

    replayed = service.attack_requests(board_round)

    assert replayed == [
        {"marker": "log:a1", "markers": ["log:a1", "log:a2"], "method": "GET", "host": "board.com",
         "path": "/search/?q=%27+or+1%3D1--", "headers": {}, "body": None, "response": None, "body_missing": False},
        {"marker": "log:a3", "markers": ["log:a3"], "method": "POST", "host": "board.com",
         "path": "/accounts/login/", "headers": {}, "body": None, "response": None, "body_missing": True}]
