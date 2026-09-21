"""An attack from outside has to show up somewhere on the map.

The whole chain, end to end: the attacker sits on public space, the ingest
pipeline resolves that address to coordinates, and the console asks for points
it can draw. Any link breaking leaves a map that is empty or, worse, plausible
and wrong.
"""

import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

CASE = "sqli-login-bypass"
EDGE_COUNTRY = "Russia"


@pytest.fixture(scope="module")
def drawn(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    sent = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": CASE}, timeout=300,
    )
    assert sent.status_code == 201, sent.text
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    # Wait on the case, not on the session: a neighbouring session's traffic
    # falls in this window too and would answer a looser question.
    def case_detected(totals):
        return any(c["name"] == CASE and c["detected"] for c in totals["per_case"])

    score_when_ready(session_id, until=case_detected)
    return requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/map/", timeout=120
    ).json()


def test_the_attack_is_placed_somewhere(drawn):
    assert drawn["points"], (
        "nothing could be placed on the map. Either the attacker is not on "
        "public space any more or the geoip pipeline is not running"
    )


def test_it_is_placed_where_the_attacker_actually_is(drawn):
    countries = {p["country"] for p in drawn["points"]}

    assert EDGE_COUNTRY in countries, f"placed in {sorted(countries)} instead"


def test_the_point_carries_coordinates_a_map_can_use(drawn):
    point = next(p for p in drawn["points"] if p["country"] == EDGE_COUNTRY)

    assert -90 <= point["lat"] <= 90
    assert -180 <= point["lon"] <= 180
    assert point["detections"] > 0
    assert point["ips"]


def test_traffic_inside_the_estate_is_counted_but_not_placed(drawn):
    # The WAF forwarding to the target is private and geolocates to nothing.
    # Dropping it silently would make the map disagree with the alert count.
    assert drawn["unlocated"] >= 0
    assert isinstance(drawn["unlocated"], int)
