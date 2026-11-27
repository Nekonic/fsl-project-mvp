from datetime import datetime, timedelta, timezone

import pytest

from telemetry import alerts as alert_feed
from telemetry.models import Detection
from tests import rounds

pytestmark = pytest.mark.django_db

AT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def stored(found, count: int, engine: str = "waf") -> list[int]:
    return [Detection.objects.create(round=found, detection_id=f"{engine}-{n}", engine=engine, rule="942100",
                                     timestamp=AT + timedelta(seconds=n), src_ip="5.188.10.10").pk
            for n in range(count)]


def test_the_newest_page_comes_first_and_the_next_page_goes_on_from_where_it_stopped(monkeypatch):
    monkeypatch.setattr(alert_feed, "ALERTS_PAGE", 3)
    found = rounds.opened(rounds.problem())
    ids = stored(found, 5)

    first = alert_feed.alert_page(found, before=0)
    second = alert_feed.alert_page(found, before=first.next)

    assert [row.pk for row in first.alerts] == ids[:1:-1] and first.more and first.total == 5
    assert [row.pk for row in second.alerts] == ids[1::-1] and not second.more


def test_a_page_that_lists_everything_says_there_is_no_more_and_the_total_follows_the_filter():
    found = rounds.opened(rounds.problem())
    stored(found, 2)
    ids = stored(found, 3, engine="ids")

    page = alert_feed.alert_page(found, before=0, engine="ids")

    assert [row.pk for row in page.alerts] == ids[::-1] and not page.more and page.total == 3
    assert alert_feed.alert_page(found, before=0).total == 5


def test_the_cursor_after_an_id_still_reads_forward_for_the_bots():
    found = rounds.opened(rounds.problem())
    ids = stored(found, 3)

    page = alert_feed.alert_page(found, after=ids[0])

    assert [row.pk for row in page.alerts] == ids[1:] and page.next == ids[-1] and not page.more
