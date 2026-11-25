from datetime import timedelta

from training.defence import rules as service
from training.models import Origin

ORIGIN = "5.188.10.10"


def logged(at, request, vhost="board.com"):
    return {"@timestamp": at.isoformat(), "time": at.isoformat(), "event": {"module": "nginx_access"},
            "client_ip": ORIGIN, "status": 200, "vhost": vhost, "request": request}


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


def test_an_origin_request_by_the_bare_address_is_replayed_to_the_round_s_own_wargame_site(board_round, es, at):
    board_round.snapshot = {**board_round.snapshot, "wargame": {**board_round.snapshot["wargame"], "hosts": ["corp.com"]}}
    board_round.save(update_fields=["snapshot"])
    Origin.objects.create(round=board_round, origin_id="o1", ip=ORIGIN, label="current")
    es.add("a1", logged(at, "GET /wp-login.php HTTP/1.1", vhost="121.134.88.42"))
    es.add("a2", logged(at + timedelta(seconds=1), "GET /wp-login.php HTTP/1.1", vhost="corp.com"))
    es.add("a3", logged(at + timedelta(seconds=2), "GET /search/ HTTP/1.1", vhost="board.com"))

    replayed = service.attack_requests(board_round)

    assert [(one["host"], one["markers"]) for one in replayed] == [
        ("corp.com", ["log:a1", "log:a2"]), ("board.com", ["log:a3"])]
