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

    reachability.forget()
    yield
    reachability.forget()

def get(client, path, addr):
    from api import reachability

    reachability.forget()
    return client.get(path, REMOTE_ADDR=addr)

def test_the_attacker_box_cannot_read_the_rules_the_defence_is_scored_on(client):
    with ranged():
        refused = get(client, "/api/rules/", "5.188.10.2")

    assert refused.status_code == 403, (
        f"the terminal the red team types at reached the scoring API and got "
        f"{refused.status_code}. POST /api/rules/apply/ from there rewrites "
        f"the detector: blank it and every attack is a miss, match the marker "
        f"header and every attack is a hit. Every cell of the confusion matrix "
        f"is writable by the party being measured"
    )

def test_the_operator_at_the_published_port_is_not_shut_out(client):
    with ranged():
        allowed = get(client, "/api/rules/", "5.188.10.1")

    assert allowed.status_code != 403, (
        "the console arrives through Docker's published port, so its source is "
        "the segment's gateway, not a node. Blocking it locks the operator out "
        "of their own range"
    )

def test_a_host_inside_the_estate_is_refused_too(client):
    with ranged():
        refused = get(client, "/api/rules/", "172.30.0.2")

    assert refused.status_code == 403, (
        "the target is a machine the red team is trying to get code execution "
        "on. A foothold there must not become control of the scoreboard"
    )

def test_the_platform_may_talk_to_itself(client):
    with ranged():
        allowed = get(client, "/api/rules/", "5.188.10.5")

    assert allowed.status_code != 403, (
        "the platform stands on the range too, and refusing its own address "
        "would break every call it makes to itself"
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

def test_the_refusal_says_what_it_is(client):
    with ranged():
        refused = get(client, "/api/rules/", "5.188.10.2")

    assert b"scored" in refused.content or b"range" in refused.content, (
        refused.content[:200]
    )

def test_deciding_who_may_call_does_not_read_the_range_on_every_request(client):
    from api import reachability

    class Counting(Stub):
        calls = 0

        def segments(self):
            return self.describe().segments

        def describe(self):
            Counting.calls += 1
            return SHAPE

    reachability.forget()
    with ranged(Counting):
        for _ in range(8):
            client.get("/api/rules/", REMOTE_ADDR="5.188.10.1")

    assert Counting.calls == 1, (
        f"the console polls several endpoints every few seconds and each one "
        f"cost a full read of the range: {Counting.calls} reads for 8 requests"
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
