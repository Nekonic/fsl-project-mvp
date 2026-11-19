from datetime import timedelta
from functools import partial
from unittest.mock import patch

import pytest

from attack import service
from attack.models import AccessCursor, OriginBudget
from events import log
from events.kinds import Viewer
from ingest import elastic
from testing.fakes import FakeElastic
from tests.attack.conftest import url
from tests.attack.fakes import RU, US_CUSTOMERS

pytestmark = pytest.mark.django_db

ATTACK_VIEW = Viewer(sides=frozenset({"attack"}))


def access(at, *, ip=RU, status=200, marker=None):
    stamp = at.isoformat().replace("+00:00", "Z")
    return {"@timestamp": stamp, "time": stamp, "event": {"module": "nginx_access"}, "client_ip": ip,
            "status": status, "request": "GET / HTTP/1.1", **({"request_id": marker} if marker else {})}


def charged_from(es, found):
    with patch("ingest.elastic.requests.post", es.post):
        return service.charge_from_access(found)


def left(found, ip=RU):
    return OriginBudget.objects.get(round=found, ip=ip).left


def test_an_api_send_seen_again_in_the_access_log_is_not_charged_twice(as_attacker, attacker):
    sent = as_attacker.post(url(attacker.round, "requests/"), {"method": "GET", "path": "/"}, format="json").json()
    marker = service.actions(attacker.round)[0].marker
    es = FakeElastic().add("a1", access(attacker.round.started + timedelta(seconds=1), marker=marker))

    charged = charged_from(es, attacker.round)

    assert sent["hp"]["left"] == 99
    assert charged == {}
    assert left(attacker.round) == 99


def test_terminal_and_tool_traffic_is_charged_from_the_access_log_with_refusals_costing_more(attacker):
    start = attacker.round.started
    es = FakeElastic()
    es.add("a1", access(start + timedelta(seconds=1)))
    es.add("a2", access(start + timedelta(seconds=2), status=403))
    es.add("a3", access(start + timedelta(seconds=3), status=400, marker="terminal-forged"))

    charged = charged_from(es, attacker.round)

    assert charged == {RU: 7}
    assert left(attacker.round) == 93


def test_a_marked_tool_run_is_charged_from_the_log_because_nothing_charged_it_on_the_spot(as_attacker, attacker):
    started = as_attacker.post(url(attacker.round, "tools/"), {"tool": "curl", "args": ["http://board.com/"]},
                               format="json").json()
    marker = next(record.marker for record in service.actions(attacker.round) if record.kind == "tool")
    es = FakeElastic().add("a1", access(attacker.round.started + timedelta(seconds=1), marker=marker))

    assert started["hp"]["left"] == 100
    assert charged_from(es, attacker.round) == {RU: 1}


def test_customers_and_traffic_before_the_round_cost_the_attacker_nothing(attacker):
    start = attacker.round.started
    es = FakeElastic()
    es.add("a1", access(start + timedelta(seconds=1), ip=US_CUSTOMERS[0]))
    es.add("a2", access(start - timedelta(minutes=5)))

    assert charged_from(es, attacker.round) == {}
    assert left(attacker.round) == 100


def test_the_access_cursor_moves_so_a_second_tick_charges_nothing_again(attacker):
    es = FakeElastic().add("a1", access(attacker.round.started + timedelta(seconds=1)))

    first, second = charged_from(es, attacker.round), charged_from(es, attacker.round)

    assert (first, second) == ({RU: 1}, {})
    assert AccessCursor.objects.get(lease=attacker.round.lease).cursor["access"]["seen"] == ["a1"]


def test_a_burst_seen_only_in_the_log_costs_double_beyond_the_rule(attacker):
    at = attacker.round.started.replace(microsecond=0) + timedelta(seconds=10)
    es = FakeElastic()
    for n in range(7):
        es.add(f"a{n}", access(at + timedelta(milliseconds=n)))

    assert charged_from(es, attacker.round) == {RU: 9}


def test_one_tick_over_many_pages_reports_one_charge_per_origin(attacker, monkeypatch):
    monkeypatch.setattr(elastic, "access_events", partial(elastic.access_events, size=1))
    start = attacker.round.started
    es = FakeElastic()
    for n in range(3):
        es.add(f"a{n}", access(start + timedelta(seconds=n + 1)))

    charged = charged_from(es, attacker.round)

    reports = [event["body"] for event in log.after(attacker.round.pk, 0, ATTACK_VIEW).events
               if event["kind"] == "origin.charged"]
    assert charged == {RU: 3}
    assert reports == [{"ip": RU, "charged": 3, "left": 97}]
