from datetime import timedelta
from functools import partial

import pytest

from telemetry import elastic
from telemetry import events as log
from telemetry.events import Viewer
from telemetry.models import AccessCursor
from testing.fakerange import BR, RU, US_CUSTOMERS
from testing.fakes import FakeElastic
from tests.training.attack.conftest import (
    after_start,
    denied_line,
    error_document,
    limited_line,
    spent_from_log,
)
from training.attack import origins
from training.models import Origin, RuleSet

pytestmark = pytest.mark.django_db

ATTACK_VIEW = Viewer(sides=frozenset({"attack"}))
DEFENCE_VIEW = Viewer(sides=frozenset({"defence"}))
CRS_REFUSAL = ('2026/11/21 10:00:00 [error] 812#812: *43 [client 5.188.10.10] ModSecurity: Access denied with code 403 '
               '(phase 2). Matched "Operator `Ge\' with parameter `5\' against variable `TX:BLOCKING_INBOUND_ANOMALY_SCORE\' '
               '[id "949110"], client: 5.188.10.10, server: board.com, request: "GET /?q=1%27 HTTP/1.1", host: "board.com"')
LIMITS = ("limit_req_zone $binary_remote_addr zone=perip:10m rate={rate};\n"
          "server {{ location / {{ limit_req zone=perip burst=5; }} }}\n")


def spent_ips(found):
    return sorted(Origin.objects.filter(round=found).exclude(spent_at=None).values_list("ip", flat=True))


def kinds(found, viewer):
    return [(event["kind"], event["body"]) for event in log.after(found.pk, 0, viewer).events
            if event["kind"].startswith(("origin", "limit"))]


def with_limit(found, rate, since=0.0):
    version = RuleSet.objects.filter(round=found, engine="waf").count() + 1
    RuleSet.objects.create(round=found, engine="waf", version=version, sha=str(version),
                           files={"/etc/nginx/defence/http.conf": LIMITS.format(rate=rate)},
                           applied_at=after_start(found, since))


def test_a_deny_rule_in_the_waf_error_log_spends_the_origin_it_names(attack_round):
    es = FakeElastic().add("e1", error_document(after_start(attack_round), denied_line(RU)))

    assert spent_from_log(es, attack_round) == 1
    assert spent_ips(attack_round) == [RU]
    assert Origin.objects.get(round=attack_round, ip=RU).spent_by == "deny"


def test_a_crs_refusal_in_the_same_error_log_spends_nothing(attack_round):
    es = FakeElastic().add("e1", error_document(after_start(attack_round), CRS_REFUSAL))

    assert spent_from_log(es, attack_round) == 0
    assert spent_ips(attack_round) == []


def test_a_rate_limit_at_or_above_the_floor_spends_the_origin(make_round, cloud):
    found = make_round(floor=90)
    with_limit(found, "90r/m")
    es = FakeElastic().add("e1", error_document(after_start(found), limited_line(RU)))

    assert spent_from_log(es, found) == 1
    assert Origin.objects.get(round=found, ip=RU).spent_by == "limit_req"


def test_a_rate_limit_below_the_floor_spends_nothing_and_warns_the_defender_once(make_round, cloud):
    found = make_round(floor=90)
    with_limit(found, "1r/s")
    es = FakeElastic()
    es.add("e1", error_document(after_start(found, 1), limited_line(RU)))
    es.add("e2", error_document(after_start(found, 2), limited_line(RU)))
    spent_from_log(es, found)
    es.add("e3", error_document(after_start(found, 3), limited_line(RU)))

    assert spent_from_log(es, found) == 0
    assert spent_ips(found) == []
    assert kinds(found, DEFENCE_VIEW) == [("limit.below_floor", {"zone": "perip", "rate_rpm": 60, "floor_rpm": 90})]
    assert kinds(found, ATTACK_VIEW) == [], "the attacker is not told the defender's limit is too low"


def test_a_limit_line_is_judged_by_the_waf_version_in_force_when_it_was_written(make_round, cloud):
    found = make_round(floor=90)
    with_limit(found, "90r/m")
    with_limit(found, "1r/s", since=10)
    es = FakeElastic()
    es.add("e1", error_document(after_start(found, 5), limited_line(RU)))
    es.add("e2", error_document(after_start(found, 15), limited_line(BR)))

    assert spent_from_log(es, found) == 1
    assert spent_ips(found) == [RU]


def test_a_limit_the_waf_version_in_force_does_not_declare_spends_nothing(make_round, cloud):
    found = make_round(floor=90)
    with_limit(found, "5r/s")
    es = FakeElastic().add("e1", error_document(after_start(found), limited_line(RU, zone="gone")))

    assert spent_from_log(es, found) == 0


def test_a_dry_run_limit_spends_nothing(make_round, cloud):
    found = make_round(floor=90)
    with_limit(found, "5r/s")
    line = limited_line(RU).replace("limiting requests, excess", "limiting requests, dry run, excess")
    es = FakeElastic().add("e1", error_document(after_start(found), line))

    assert spent_from_log(es, found) == 0


def test_customers_and_lines_before_the_round_or_after_its_end_cost_the_attacker_nothing(attack_round):
    attack_round.ends_at = after_start(attack_round, 60)
    attack_round.save(update_fields=["ends_at"])
    es = FakeElastic()
    es.add("e1", error_document(after_start(attack_round), denied_line(US_CUSTOMERS[0])))
    es.add("e2", error_document(attack_round.started - timedelta(minutes=5), denied_line(RU)))
    es.add("e3", error_document(attack_round.ends_at + timedelta(seconds=1), denied_line(BR)))

    assert spent_from_log(es, attack_round) == 0
    assert spent_ips(attack_round) == []


def test_the_error_cursor_moves_so_a_second_read_spends_nothing_again(attack_round):
    es = FakeElastic().add("e1", error_document(after_start(attack_round), denied_line(RU)))

    first, second = spent_from_log(es, attack_round), spent_from_log(es, attack_round)

    assert (first, second) == (1, 0)
    assert AccessCursor.objects.get(allocation=attack_round.allocation).cursor["errors"]["seen"] == ["e1"]


def test_one_read_over_many_pages_spends_each_origin_it_names(attack_round, monkeypatch):
    monkeypatch.setattr(elastic, "error_events", partial(elastic.error_events, size=1))
    es = FakeElastic()
    es.add("e1", error_document(after_start(attack_round, 1), denied_line(RU)))
    es.add("e2", error_document(after_start(attack_round, 2), denied_line(RU)))
    es.add("e3", error_document(after_start(attack_round, 3), denied_line(BR)))

    assert spent_from_log(es, attack_round) == 2
    assert spent_ips(attack_round) == sorted([RU, BR])
    assert origins.remaining(attack_round).left == 1
