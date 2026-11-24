from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from telemetry import access
from testing.fakes import FakeElastic
from tests import rounds
from training.models import Action, Origin

pytestmark = pytest.mark.django_db

START = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
CURRENT, SPENT, CUSTOMER = "5.188.10.10", "5.188.10.11", "203.0.113.50"


def logged(seconds, ip, marker=None, request="GET /search/?q=x HTTP/1.1"):
    at = (START + timedelta(seconds=seconds)).isoformat()
    return {"@timestamp": at, "time": at, "event": {"module": "nginx_access"}, "client_ip": ip, "status": 200,
            "vhost": "board.com", "request": request, **({"request_id": marker} if marker else {})}


def test_rows_from_the_round_s_attacker_origins_become_origin_requests_and_nothing_else_does():
    found = rounds.opened(rounds.problem(), started=START, ended=START + timedelta(minutes=10))
    player = rounds.playing(found, "attack", bot_name="attack-bot")
    Origin.objects.create(round=found, origin_id="o1", ip=CURRENT, label="current")
    Origin.objects.create(round=found, origin_id="o2", ip=SPENT, label="spent", spent_at=START, spent_by="deny")
    Action.objects.create(round=found, player=player, kind="request", marker="m1", correlation="marker",
                          source_ip=CURRENT, started=START, ended=START)
    es = FakeElastic()
    es.add("before", logged(-60, CURRENT))
    es.add("tunnelled", logged(10, CURRENT))
    es.add("from-spent", logged(20, SPENT, request="POST /accounts/login/ HTTP/1.1"))
    es.add("known", logged(30, CURRENT, marker="m1"))
    es.add("customer", logged(40, CUSTOMER))
    es.add("after", logged(900, CURRENT))

    with patch("telemetry.elastic.requests.post", es.post):
        found_requests = access.origin_requests(found)

    assert found_requests == (
        access.OriginRequest(id="tunnelled", at=START + timedelta(seconds=10), ip=CURRENT, method="GET",
                             host="board.com", path="/search/?q=x"),
        access.OriginRequest(id="from-spent", at=START + timedelta(seconds=20), ip=SPENT, method="POST",
                             host="board.com", path="/accounts/login/"))
    assert [one.marker for one in found_requests] == ["log:tunnelled", "log:from-spent"]
