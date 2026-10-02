from unittest.mock import patch

import pytest

from range import slot
from range.ports import Drifted

URL = "/api/range/slot/"

class Built:
    def __init__(self, blocked=False):
        self.ensured = 0
        self.torn = 0
        self.blocked = blocked

    def plan_slot(self):
        return slot.Plan(
            boot=("fsl-wiki",),
            ports=(slot.Port("fsl-wiki", "estate", "fsl-wiki.estate"),
                   slot.Port("fsl-waf", "internet", "fsl-waf.internet",
                             (("sub-us", "73.0.0.1"),))),
            standing=(("fsl-waf", "srv-1", "ACTIVE"),),
        )

    def ensure_slot(self):
        if self.blocked:
            raise Drifted("image fsl-board is not ready")
        self.ensured += 1
        return self.plan_slot()

    def teardown_slot(self):
        self.torn += 1
        return [("server", "srv-1"), ("port", "port-1")]

@pytest.fixture
def built():
    found = Built()
    with patch("api.views.substrate", lambda: found):
        yield found

def test_the_docker_range_has_no_slot_to_boot(client):
    response = client.get(URL)

    assert response.status_code == 409 and "compose" in response.json()["detail"]

def test_reading_the_slot_says_what_stands_and_what_would_boot(client, built):
    answer = client.get(URL).json()

    assert answer["boot"] == ["fsl-wiki"]
    assert answer["standing"] == [{"host": "fsl-waf", "server": "srv-1", "status": "ACTIVE"}]
    assert answer["ports"][1] == {"host": "fsl-waf", "segment": "internet",
                                  "name": "fsl-waf.internet", "addresses": ["73.0.0.1"]}
    assert answer["clean"] is False and built.ensured == 0

def test_booting_it_is_a_post(client, built):
    assert client.post_json(URL).status_code == 200 and built.ensured == 1

def test_a_slot_that_cannot_boot_is_a_conflict_that_says_why(client):
    with patch("api.views.substrate", lambda: Built(blocked=True)):
        response = client.post_json(URL)

    assert response.status_code == 409 and "fsl-board" in response.json()["detail"]

def test_taking_it_down_is_a_delete_and_says_what_went(client, built):
    response = client.delete(URL)

    assert response.status_code == 200 and built.torn == 1
    assert response.json()["removed"] == [{"kind": "server", "id": "srv-1"},
                                          {"kind": "port", "id": "port-1"}]

class Rebuilt:
    def __init__(self):
        self.rebuilt = 0

    def rebuild_slot(self):
        self.rebuilt += 1
        return [("fsl-waf", "srv-1"), ("fsl-juice-shop", "srv-2")]

def test_rebuilding_the_slot_is_a_post_that_says_what_reset(client):
    found = Rebuilt()
    with patch("api.views.substrate", lambda: found):
        response = client.post_json("/api/range/slot/rebuild/")

    assert response.status_code == 200 and found.rebuilt == 1
    assert response.json() == {"rebuilt": [
        {"host": "fsl-waf", "server": "srv-1"},
        {"host": "fsl-juice-shop", "server": "srv-2"},
    ]}

def test_the_docker_range_has_no_slot_to_rebuild(client):
    response = client.post_json("/api/range/slot/rebuild/")

    assert response.status_code == 409 and "compose" in response.json()["detail"]

def test_rebuilding_is_only_a_post(client):
    with patch("api.views.substrate", lambda: Rebuilt()):
        assert client.get("/api/range/slot/rebuild/").status_code == 405

class Configured:
    def __init__(self):
        self.configured = 0

    def configure_slot(self):
        self.configured += 1
        return [("fsl-pfsense", ("wan 73.0.0.1 120.96.0.1", "logs 10.31.0.195:5140"))]

def test_configuring_the_slot_is_a_post_that_says_what_each_host_reported(client):
    found = Configured()
    with patch("api.views.substrate", lambda: found):
        response = client.post_json("/api/range/configure/")

    assert response.status_code == 200 and found.configured == 1
    assert response.json() == {"configured": [
        {"host": "fsl-pfsense", "reported": ["wan 73.0.0.1 120.96.0.1", "logs 10.31.0.195:5140"]}
    ]}

def test_the_docker_range_has_nothing_to_configure(client):
    response = client.post_json("/api/range/configure/")

    assert response.status_code == 409 and "compose" in response.json()["detail"]

def test_configuring_is_only_a_post(client):
    with patch("api.views.substrate", lambda: Configured()):
        assert client.get("/api/range/configure/").status_code == 405
