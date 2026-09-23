from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from range.ports import RangeUnavailable
from tests.test_topology import stub

pytestmark = pytest.mark.django_db

MOSCOW = {
    "country_name": "Russia", "country_iso_code": "RU", "city_name": "Moscow",
    "location": {"lat": 55.7386, "lon": 37.6068},
}
QUIET = "5.188.10.99"
BUSIER = [f"172.30.0.{host}" for host in range(10, 35)]

def recorded(*sent):
    from api.models import Detection, Session

    session = Session.objects.create()
    started = timezone.now()
    Detection.objects.bulk_create(
        Detection(
            session=session, detection_id=f"d{index}", source=source,
            signature="FSL SQLi attempt - URI", severity=2,
            timestamp=started + timedelta(seconds=index), src_ip=src_ip,
            raw={"src_ip": src_ip, "src_geo": geo},
        )
        for index, (src_ip, source, geo) in enumerate(sent)
    )
    return session

def busiest_and_one_more():
    return recorded(
        *[(address, "suricata", {}) for address in BUSIER for _ in range(2)],
        (QUIET, "suricata", MOSCOW),
    )

def listed(client, session, after=None):
    path = f"/api/sessions/{session.id}/detections/"
    return client.get(path if after is None else f"{path}?after={after}").json()

def placed(row):
    return (row["zone"], row["outside"], row["country"], row["city"])

def test_an_alert_from_beyond_the_busiest_sources_still_says_where_it_came_from(client):
    session = busiest_and_one_more()

    with stub():
        top = client.get(f"/api/sessions/{session.id}/top/").json()
        rows = listed(client, session)

    assert len(top["sources"]) == 25 and QUIET not in {s["src_ip"] for s in top["sources"]}
    [quiet] = [row for row in rows if row["src_ip"] == QUIET]
    assert placed(quiet) == ("Internet", True, "Russia", "Moscow"), (
        "the alert came from the 26th busiest source, which the top table does "
        "not list, so the alert table had nowhere to read its zone or place from"
    )

def test_a_waf_alert_is_placed_by_what_the_sensor_saw_of_the_same_address(client):
    session = recorded(
        ("5.188.10.2", "modsecurity", {}),
        ("5.188.10.2", "suricata", MOSCOW),
        ("5.188.10.2", "modsecurity", {}),
    )
    sensed = listed(client, session)[1]["id"]

    with stub():
        [waf] = listed(client, session, after=sensed)
        [source] = client.get(f"/api/sessions/{session.id}/top/").json()["sources"]

    assert waf["source"] == "modsecurity"
    assert placed(waf) == ("Internet", True, "Russia", "Moscow"), (
        "only Suricata's records carry the place, the WAF's carry an empty one, "
        "and this WAF alert arrived in a later poll than the record that placed it"
    )
    assert placed(waf) == (source["zone"], source["outside"], source["country"], source["city"])

def test_an_address_is_placed_where_it_is_and_nowhere_it_is_not(client):
    session = recorded(
        ("172.30.0.2", "suricata", {}),
        ("10.9.9.9", "suricata", {}),
    )

    with stub():
        rows = {row["src_ip"]: placed(row) for row in listed(client, session)}

    assert rows == {
        "172.30.0.2": ("Application estate", False, "", ""),
        "10.9.9.9": ("", False, "", ""),
    }

def test_an_alert_is_listed_with_its_place_while_the_range_cannot_be_read(client):
    session = recorded((QUIET, "suricata", MOSCOW))

    with stub(error=RangeUnavailable("no daemon")):
        [row] = listed(client, session)

    assert placed(row) == ("", False, "Russia", "Moscow"), (
        "the range could not be read, which leaves the zone unknown and says "
        "nothing about the place the pipeline already put on the alert"
    )

def test_placing_a_page_of_alerts_is_one_query_however_many_addresses_it_holds(client):
    session = busiest_and_one_more()
    last = max(row["id"] for row in listed(client, session))

    def asked(after):
        with stub(), CaptureQueriesContext(connection) as queries:
            listed(client, session, after)
        return len(queries)

    assert asked(after=0) - asked(after=last) == 1, (
        "each of the 26 addresses in the page was looked up on its own"
    )
