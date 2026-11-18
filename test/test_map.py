import pytest

EDGE_COUNTRY = "Russia"

@pytest.fixture(scope="module")
def drawn(tuned_session):
    session_map = tuned_session["map"]
    return dict(
        session_map,
        points=[p for p in session_map["points"] if tuned_session["own"] & set(p["ips"])],
        every_point=session_map["points"],
        listed=tuned_session["listed"],
    )

def test_it_is_placed_where_the_attacker_actually_is_with_coordinates_a_map_can_use(drawn):
    countries = {p["country"] for p in drawn["points"]}

    assert EDGE_COUNTRY in countries, f"placed in {sorted(countries)} instead"
    point = next(p for p in drawn["points"] if p["country"] == EDGE_COUNTRY)
    assert -90 <= point["lat"] <= 90
    assert -180 <= point["lon"] <= 180
    assert point["detections"] > 0

def test_every_detection_is_placed_or_counted_as_unlocated(drawn):
    placed = {ip for point in drawn["every_point"] for ip in point["ips"]}
    unplaced = [d for d in drawn["listed"] if d["src_ip"] not in placed]

    assert not [d for d in drawn["listed"] if d["source"] == "suricata" and d["src_ip"] not in placed], (
        "an IDS alert behind the WAF is credited to the client X-Forwarded-For names, which the map places")
    assert drawn["unlocated"] == len(unplaced), (
        f"{len(unplaced)} detections come from no placed address and the map "
        f"reports {drawn['unlocated']} unlocated"
    )
    assert sum(p["detections"] for p in drawn["every_point"]) + drawn["unlocated"] == len(
        drawn["listed"]
    ), (
        "the map and the alert list disagree on how many detections the "
        "session holds, so the map dropped or double-counted some"
    )
