from unittest.mock import patch

import pytest

from tests.sessions import open_session

pytestmark = pytest.mark.django_db

T0 = "2026-09-20T12:00:00Z"
MOSCOW = {
    "country_name": "Russia", "country_iso_code": "RU",
    "continent_name": "Europe", "location": {"lat": 55.7386, "lon": 37.6068},
}

def suricata(doc_id, src_ip, geo=None, signature="SQLi"):
    source = {
        "event": {"module": "suricata"}, "event_type": "alert", "timestamp": T0,
        "src_ip": src_ip, "alert": {"signature": signature, "severity": 1},
    }
    if geo:
        source["src_geo"] = geo
    return (doc_id, source)

def modsecurity(doc_id, src_ip, message="SQL Injection"):
    return (
        doc_id,
        {
            "event": {"module": "modsecurity"},
            "transaction": {
                "time_stamp": "Sun Sep 20 12:00:00 2026", "client_ip": src_ip,
                "messages": [{"message": message}],
            },
        },
    )

@pytest.fixture
def session_id(client):
    return open_session(client)

def ingest(client, session_id, documents):
    with patch("api.views.elastic.fetch", return_value=(documents, None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return client.get(f"/api/sessions/{session_id}/map/").json()

def test_located_addresses_in_one_place_become_one_point_and_an_unplaced_one_is_not_invented(client, session_id):
    drawn = ingest(client, session_id, [
        suricata("a", "5.188.10.2", MOSCOW),
        suricata("b", "5.188.10.6", MOSCOW),
        modsecurity("m", "5.188.10.2"),
        suricata("x", "172.30.0.3"),
    ])

    [point] = drawn["points"]
    assert (point["lat"], point["lon"], point["country"], point["country_code"]) == (55.7386, 37.6068, "Russia", "RU")
    assert point["detections"] == 3, "an alert without geo counts once its address is placed by another"
    assert sorted(point["ips"]) == ["5.188.10.2", "5.188.10.6"]
    assert drawn["unlocated"] == 1
