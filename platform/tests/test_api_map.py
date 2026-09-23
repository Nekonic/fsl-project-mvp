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
        "fsl_source": "suricata", "event_type": "alert", "timestamp": T0,
        "src_ip": src_ip, "alert": {"signature": signature, "severity": 1},
    }
    if geo:
        source["src_geo"] = geo
    return (doc_id, source)

def modsecurity(doc_id, src_ip, message="SQL Injection"):
                                                                              
                                                                     
    return (
        doc_id,
        {
            "fsl_source": "modsecurity",
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

def test_a_located_address_becomes_a_point(client, session_id):
    drawn = ingest(client, session_id, [suricata("a", "5.188.10.2", MOSCOW)])

    assert len(drawn["points"]) == 1
    point = drawn["points"][0]
    assert (point["lat"], point["lon"]) == (55.7386, 37.6068)
    assert point["country"] == "Russia"
    assert point["country_code"] == "RU"
    assert point["detections"] == 1

def test_an_address_the_pipeline_could_not_place_is_not_invented(client, session_id):
    drawn = ingest(client, session_id, [suricata("a", "172.30.0.3")])

    assert drawn["points"] == []
    assert drawn["unlocated"] == 1

def test_an_alert_without_geo_still_counts_once_its_address_is_known(client, session_id):
                                                                              
                                                  
    drawn = ingest(client, session_id, [
        suricata("a", "5.188.10.2", MOSCOW),
        modsecurity("m", "5.188.10.2"),
    ])

    assert len(drawn["points"]) == 1
    assert drawn["points"][0]["detections"] == 2
    assert drawn["unlocated"] == 0

def test_addresses_in_one_place_become_one_point(client, session_id):
    drawn = ingest(client, session_id, [
        suricata("a", "5.188.10.2", MOSCOW),
        suricata("b", "5.188.10.6", MOSCOW),
    ])

    assert len(drawn["points"]) == 1
    assert drawn["points"][0]["detections"] == 2
    assert sorted(drawn["points"][0]["ips"]) == ["5.188.10.2", "5.188.10.6"]

def test_points_come_back_busiest_first(client, session_id):
    elsewhere = {
        "country_name": "Brazil", "country_iso_code": "BR",
        "continent_name": "South America",
        "location": {"lat": -23.5475, "lon": -46.6361},
    }
    drawn = ingest(client, session_id, [
        suricata("a", "5.188.10.2", MOSCOW),
        suricata("b", "5.188.10.2", MOSCOW),
        suricata("c", "177.54.144.9", elsewhere),
    ])

    assert [p["country"] for p in drawn["points"]] == ["Russia", "Brazil"]

def test_a_session_with_nothing_in_it_draws_nothing(client, session_id):
    drawn = client.get(f"/api/sessions/{session_id}/map/").json()

    assert drawn == {"points": [], "unlocated": 0}

def test_the_map_of_a_session_that_does_not_exist_is_404(client):
    assert client.get("/api/sessions/9999/map/").status_code == 404
