from datetime import datetime, timedelta, timezone

import pytest

from domain.scoring.objectives import ATTRIBUTION_WINDOW, CLOCK_SKEW
from domain.types import RESPONSE_ORIGIN, ResponseRecord
from scoring import baseline as baselines
from scoring import losses
from scoring import score as service
from scoring.models import Objective
from telemetry.access import OriginRequest
from tests import rounds
from tests.scoring.targets import ROGUE_ADMIN_AT, TRUTH
from training.attack.actions import origin_record

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
ORIGIN = "5.188.10.10"
SQLI = "board-sqli-search"


def tunnelled(doc_id, at):
    return origin_record(OriginRequest(id=doc_id, at=at, ip=ORIGIN, method="GET", host="board.com",
                                       path="/search/?q=%27+or+1%3D1--"))


def test_an_origin_request_is_a_free_action():
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    actions = [rounds.case(SQLI, AT - timedelta(seconds=20), malicious=True, expect="sql injection"),
               tunnelled("a1", AT - timedelta(seconds=10)), tunnelled("a2", AT - timedelta(seconds=5))]
    alerts = [rounds.detection("d1", AT - timedelta(seconds=10), marker=None, src_ip=ORIGIN)]

    scored = service.score(found, actions, alerts).shown()

    assert scored["outcomes"]["totals"] == {"tp": 0, "fp": 0, "fn": 1, "tn": 0}
    assert [line["case"] for line in scored["outcomes"]["per_case"]] == [SQLI]
    assert scored["free_actions"] == {"by_origin": [{"ip": ORIGIN, "actions": 2, "alerts": 1, "refused": 0}]}


def test_a_loss_through_origin_requests_can_earn_response_by_spend(board_target):
    found = rounds.opened(rounds.problem(objectives=["board-auth-user-admin"]), started=AT - timedelta(minutes=30))
    baselines.take_baseline(found, board_target)
    losses.submit_loot(found, {"admin": TRUTH["admin"]}, actions=(), at=AT)
    actions = [tunnelled("a1", AT - timedelta(seconds=90)), tunnelled("a2", AT - timedelta(seconds=60))]
    spent = [ResponseRecord(at=AT - timedelta(seconds=30), kind=RESPONSE_ORIGIN, source_ip=ORIGIN)]

    lost = service.score(found, actions, [], responses=spent).shown()["objectives"]["lost"]

    assert [(one["key"], one["responded"], one["attributed_marker"]) for one in lost] == [
        ("board-auth-user-admin", True, "log:a2")]


def test_a_corp_effect_without_an_action_takes_the_attribution_window(corp_target):
    found = rounds.opened(rounds.problem("corp"), started=ROGUE_ADMIN_AT - timedelta(minutes=5))
    baselines.take_baseline(found, corp_target)

    losses.observe_effects(found, corp_target, [])

    stored = Objective.objects.get(round=found)
    assert (stored.earliest, stored.latest) == (ROGUE_ADMIN_AT - ATTRIBUTION_WINDOW, ROGUE_ADMIN_AT + CLOCK_SKEW)
