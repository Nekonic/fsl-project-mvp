from datetime import datetime, timedelta, timezone

import pytest

from telemetry.access import OriginRequest
from tests import rounds
from training.attack.actions import origin_record
from training.round import debrief

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
ORIGIN = "5.188.10.10"


def test_the_attack_lane_carries_tunnelled_requests_grouped_by_origin_with_the_score_s_alert_count(monkeypatch):
    found = rounds.opened(rounds.problem(), started=AT - timedelta(minutes=30))
    tunnelled = tuple(origin_record(OriginRequest(id=doc_id, at=AT + timedelta(seconds=offset), ip=ORIGIN,
                                                  method="GET", host="board.com", path="/search/"))
                      for doc_id, offset in (("a1", 0), ("a2", 30)))
    between = rounds.detection("d2", AT + timedelta(seconds=15), marker=None, src_ip=ORIGIN)
    monkeypatch.setattr(debrief.attack, "origin_records", lambda round_: tunnelled)
    monkeypatch.setattr(debrief.alert_feed, "detections",
                        lambda round_: [rounds.detection("d1", AT + timedelta(seconds=31), marker=None, src_ip=ORIGIN), between])

    composed = debrief.compose(found)

    rows = [row for row in composed["timeline"] if row["kind"] == "free_actions"]
    assert rows == [{"lane": "attack", "kind": "free_actions", "at": AT.isoformat(), "origin": ORIGIN, "count": 2,
                     "until": (AT + timedelta(seconds=30)).isoformat(), "alerts": 1}]
    assert [origin["alerts"] for origin in composed["score"]["free_actions"]["by_origin"]] == [1]
