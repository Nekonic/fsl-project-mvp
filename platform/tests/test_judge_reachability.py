from types import SimpleNamespace
from unittest.mock import patch

import pytest

from range.ports import Node, Segment, Shape

pytestmark = pytest.mark.django_db

SHAPE = Shape(
    segments=(
        Segment(id="edge", name="Internet", origin="Moscow, Russia",
                subnet="5.188.10.0/24", network="fsl_edge",
                gateway="5.188.10.1",
                nodes=(Node("fsl-kali", "5.188.10.2"),
                       Node("fsl-proxy", "5.188.10.3"),
                       Node("fsl-platform", "5.188.10.5"))),
        Segment(id="estate", name="Application estate", subnet="172.30.0.0/24",
                network="fsl_estate", gateway="172.30.0.1",
                nodes=(Node("fsl-juice-shop", "172.30.0.2"),
                       Node("fsl-platform", "172.30.0.4"))),
    ),
    sensors=(),
)

from range.ports import Ran

class Stub:
    def segments(self):
        return SHAPE.segments

    def describe(self):
        return SHAPE

    def runner(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            return Ran(exit_code=0, output="")

        return run

class _Both:
    def __init__(self, stub):
        self.patches = [
            patch("api.views.substrate", stub),
            patch("api.reachability.substrate", stub),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

def ranged(stub=None):
    return _Both(stub or Stub)

@pytest.fixture(autouse=True)
def fresh_cache():
    from api import reachability

    reachability._cached = (0.0, frozenset())
    yield
    reachability._cached = (0.0, frozenset())

def get(client, path, addr):
    from api import reachability

    reachability._cached = (0.0, frozenset())
    return client.get(path, REMOTE_ADDR=addr)

@pytest.mark.parametrize("address, refused", [
    ("5.188.10.2", True),
    ("172.30.0.2", True),
    ("5.188.10.1", False),
    ("5.188.10.5", False),
])
def test_the_attacker_box_cannot_read_the_rules_the_defence_is_scored_on(client, address, refused):
    with ranged():
        answered = get(client, "/api/rules/", address)

    assert (answered.status_code == 403) is refused, (
        "range nodes (attacker box, estate hosts) must not reach the scoring API; "
        "the operator through the published port (the gateway) and the platform itself must"
    )

def test_a_range_that_cannot_be_read_does_not_lock_everyone_out(client):
    from range.ports import RangeUnavailable

    class Gone(Stub):
        def segments(self):
            return self.describe().segments

        def describe(self):
            raise RangeUnavailable("docker is not there")

    with ranged(Gone):
        response = get(client, "/api/rules/", "5.188.10.2")

    assert response.status_code != 403, (
        "with no range to consult there is no list of participants, and "
        "refusing everything would mean the console dies whenever Docker does"
    )

def test_a_range_that_comes_back_is_noticed_within_the_cache_window(monkeypatch):
    from api import reachability
    from range.ports import RangeUnavailable

    assert reachability.TTL <= 60, (
        f"the set of hosts standing in the range is cached for "
        f"{reachability.TTL}s, so a container recreated inside that window "
        f"keeps its old answer"
    )

    now = [1000.0]
    monkeypatch.setattr(reachability, "time", SimpleNamespace(monotonic=lambda: now[0]))

    class Returning(Stub):
        reads = 0

        def segments(self):
            Returning.reads += 1
            if Returning.reads == 1:
                raise RangeUnavailable("docker is not there")
            return SHAPE.segments

    with patch("api.reachability.substrate", Returning):
        gone = reachability.scored_hosts()
        now[0] += reachability.TTL - 1
        still_gone = reachability.scored_hosts()
        now[0] += 2
        back = reachability.scored_hosts()

    assert gone == still_gone == frozenset()
    assert Returning.reads == 2, Returning.reads
    assert "5.188.10.2" in back, (
        f"the range came back after {reachability.TTL}s and the attacker box is "
        f"still not refused: {sorted(back)}"
    )


def test_a_stopped_sensor_does_not_open_the_judge_to_the_range(client):
    from range.ports import RangeUnavailable

    class SensorDown(Stub):
        def describe(self):
            raise RangeUnavailable("fsl-suricata is declared to watch fsl-waf and stands in nothing")

    with ranged(SensorDown):
        answered = get(client, "/api/rules/", "5.188.10.2")

    assert answered.status_code == 403, (
        f"stopping the sensor made describe() fail, the rule failed open, and "
        f"the attacker box reached the rules API ({answered.status_code}). "
        f"Who stands inside the range does not depend on where the sensor is"
    )
