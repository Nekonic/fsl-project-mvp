from unittest.mock import patch

import pytest

from tests.test_origins import PLACES
from tests.test_range_shape import _Run
from tests.test_topology import SHAPE

pytestmark = pytest.mark.django_db

class Counting:
    def __init__(self, described=SHAPE):
        self.described = described
        self.calls = 0

    def segments(self):
        return self.describe().segments

    def describe(self):
        self.calls += 1
        return self.described

    def runner(self, role, segment_id=""):
        raise AssertionError("reading the range is not running a command on it")

    def launcher(self, segment_id):
        def launch(image, argv, timeout=600.0):
            raise AssertionError("no case here runs a tool")

        return launch

def polled(client, path):
    counter = Counting()
    with patch("api.views.substrate", lambda: counter):
        response = client.get(path)

    assert response.status_code == 200, response.content[:200]
    return counter.calls

@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]

def test_drawing_the_topology_asks_the_range_once(client, session_id):
    assert polled(client, f"/api/sessions/{session_id}/topology/") == 1

def test_counting_the_busiest_addresses_asks_the_range_once(client, session_id):
    assert polled(client, f"/api/sessions/{session_id}/top/") == 1

def test_listing_the_origins_asks_the_range_once(client):
    assert polled(client, "/api/origins/") == 1

def test_the_attacker_box_asks_the_range_once(client):
    assert polled(client, "/api/attacker/") == 1

def test_firing_from_an_origin_asks_the_range_once(client, session_id):
    counter = Counting()
    with patch("api.views.substrate", lambda: counter), \
            patch("api.views.attacker.origins", return_value=PLACES), \
            patch("api.views.harness.fire"):
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/",
            {"case": "sqli-login-bypass", "origin": "rotate"},
        )

    assert response.status_code == 201
    assert counter.calls == 1

def test_firing_by_the_front_door_does_not_ask_the_range_at_all(client, session_id):
    counter = Counting()
    with patch("api.views.substrate", lambda: counter), \
            patch("api.views.harness.fire"):
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", {"case": "sqli-login-bypass"},
        )

    assert response.status_code == 201
    assert counter.calls == 0

def _round_trips(client, path):
    spy = _Run()
    with patch("range.docker.subprocess.run", spy):
        response = client.get(path)

    assert response.status_code == 200, response.content[:200]
    return [" ".join(argv[:3]) for argv in spy.argv]

def test_a_topology_poll_costs_one_round_trip_per_question(client, session_id):
    trips = _round_trips(client, f"/api/sessions/{session_id}/topology/")

    assert trips == [
        "docker network ls",
        "docker network inspect",
        "docker ps --filter",
        "docker container inspect",
    ], f"the shape was read {len(trips)} times over: {trips}"

def test_asking_where_to_attack_from_is_the_same_one_reading(client):
    assert _round_trips(client, "/api/origins/") == [
        "docker network ls",
        "docker network inspect",
        "docker ps --filter",
        "docker container inspect",
    ]
