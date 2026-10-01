from unittest.mock import patch

import pytest

from range import fabric
from range.ports import Drifted

URL = "/api/range/fabric/"

class Built:
    def __init__(self, drifted=False):
        self.ensured = 0
        self.torn = 0
        self.drifted = drifted

    def plan_fabric(self):
        return fabric.Plan(
            networks=("internet",),
            subnets=(fabric.Subnet("internet", "fsl-us", "73.0.0.0/24", False, True),),
            keypair=True,
            present=("fsl-estate",),
            leftovers=("network fsl-edge carries fsl.segment.id=edge, which the declaration does not name",),
        )

    def ensure_fabric(self):
        if self.drifted:
            raise Drifted("subnet fsl-us 73.0.0.0/24: dhcp is on, declared off")
        self.ensured += 1
        return self.plan_fabric()

    def teardown_fabric(self):
        self.torn += 1
        return [("subnet", "sub-1"), ("network", "net-1"), ("keypair", "fsl-platform")]

@pytest.fixture
def built():
    found = Built()
    with patch("api.views.substrate", lambda: found):
        yield found

def test_the_docker_range_has_no_fabric_to_build(client):
    response = client.get(URL)

    assert response.status_code == 409, response.content
    assert "compose" in response.json()["detail"]

def test_reading_the_fabric_says_what_is_missing_and_what_is_left_over(client, built):
    answer = client.get(URL).json()

    assert answer["networks"] == ["internet"]
    assert answer["subnets"] == [{
        "segment": "internet", "name": "fsl-us", "cidr": "73.0.0.0/24",
        "dhcp": False, "gateway": True,
    }]
    assert answer["keypair"] is True and answer["clean"] is False
    assert answer["leftovers"] and answer["present"] == ["fsl-estate"]
    assert built.ensured == 0

def test_building_it_is_a_post(client, built):
    response = client.post_json(URL)

    assert response.status_code == 200 and built.ensured == 1

def test_taking_it_down_is_a_delete_and_says_what_went(client, built):
    response = client.delete(URL)

    assert response.status_code == 200 and built.torn == 1
    assert response.json()["removed"][0] == {"kind": "subnet", "id": "sub-1"}

def test_a_fabric_that_drifted_is_a_conflict_not_a_rebuild(client):
    drifted = Built(drifted=True)
    with patch("api.views.substrate", lambda: drifted):
        response = client.post_json(URL)

    assert response.status_code == 409
    assert "dhcp is on" in response.json()["detail"]
