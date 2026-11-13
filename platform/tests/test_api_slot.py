from unittest.mock import patch

import pytest

from range import slot

pytestmark = pytest.mark.django_db

URL = "/api/range/slot/"

class Built:
    def __init__(self):
        self.ensured = 0
        self.torn = 0
        self.rebuilt = 0
        self.configured = 0

    def plan_slot(self):
        return slot.Plan(
            boot=("cr-range",),
            standing=(("cr-range", "srv-1", "ACTIVE"),),
        )

    def ensure_slot(self):
        self.ensured += 1
        return self.plan_slot()

    def teardown_slot(self):
        self.torn += 1
        return [("project", "s1")]

    def rebuild_slot(self):
        self.rebuilt += 1
        return []

    def teardown_range_host(self):
        self.torn += 1
        return [("server", "srv-1"), ("port", "port-1")]

    def configure_slot(self):
        self.configured += 1
        return [("cr-edge", ("logs 10.31.0.195:5140",))]

@pytest.fixture
def built():
    found = Built()
    with patch("api.views.substrate", lambda: found):
        yield found

def test_reading_the_slot_changes_nothing_and_only_a_post_or_delete_acts_on_the_range(client, built):
    answer = client.get(URL).json()
    assert answer["boot"] == ["cr-range"]
    assert answer["standing"] == [{"host": "cr-range", "server": "srv-1", "status": "ACTIVE"}]
    assert client.get("/api/range/slot/rebuild/").status_code == 405
    assert client.get("/api/range/configure/").status_code == 405
    assert (built.ensured, built.torn, built.rebuilt, built.configured) == (0, 0, 0, 0)

    assert client.post_json(URL).status_code == 200
    assert client.post_json("/api/range/slot/rebuild/").json() == {
        "rebuilt": []}
    assert client.post_json("/api/range/configure/").json() == {
        "configured": [{"host": "cr-edge", "reported": ["logs 10.31.0.195:5140"]}]}
    assert client.delete(URL).json()["removed"] == [{"kind": "project", "id": "s1"},
                                                    {"kind": "server", "id": "srv-1"},
                                                    {"kind": "port", "id": "port-1"}]
    assert (built.ensured, built.torn, built.rebuilt, built.configured) == (1, 2, 1, 1)
