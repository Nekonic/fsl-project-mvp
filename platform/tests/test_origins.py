import pathlib
from dataclasses import replace
from unittest.mock import patch

import pytest

import attacker
from attacker import AttackerUnavailable
from range.ports import Node, RangeUnavailable, Segment, Shape

PROXY = "fsl-proxy"
KALI = "fsl-kali"
WAF = "fsl-waf"

EDGE = Segment(
    id="edge", name="Internet", origin="Moscow, Russia",
    subnet="5.188.10.0/24", network="fsl_edge",
    nodes=(Node(PROXY, "5.188.10.7"), Node(KALI, "5.188.10.2"),
           Node(WAF, "5.188.10.9")),
)
HK = Segment(
    id="edge-hk", name="Internet", origin="Kwai Chung, Hong Kong",
    subnet="103.152.220.0/24", network="fsl_edge-hk",
    nodes=(Node(PROXY, "103.152.220.7"), Node(WAF, "103.152.220.9")),
)
BR = Segment(
    id="edge-br", name="Internet", origin="Sao Paulo, Brazil",
    subnet="177.54.144.0/24", network="fsl_edge-br",
    nodes=(Node(PROXY, "177.54.144.7"), Node(WAF, "177.54.144.9")),
)
ESTATE = Segment(
    id="estate", name="Application estate", origin="",
    subnet="172.30.0.0/24", network="fsl_estate",
    nodes=(Node(PROXY, "172.30.0.7"), Node("fsl-juice-shop", "172.30.0.2"),
           Node(WAF, "172.30.0.9")),
)

SHAPE = Shape(segments=(EDGE, HK, BR, ESTATE), sensors=())

def stub(described=SHAPE, error=None):
    class Stub:
        def segments(self):
            return self.describe().segments

        def describe(self):
            if error is not None:
                raise error
            return described

        def launcher(self, segment_id):
            def launch(image, argv, timeout=600.0):
                raise AssertionError("no case here runs a tool")

            return launch

        def runner(self, role, segment_id=""):
            raise RangeUnavailable(f"this stub range runs nothing on {role}")

    return patch("api.views.substrate", Stub)

def origins(described=SHAPE):
    return attacker.origins(described)

def test_every_declared_network_is_an_origin():
    assert {o["id"] for o in origins()} == {"edge", "edge-hk", "edge-br"}

def test_an_origin_carries_both_addresses_the_terminal_can_leave_by():
    edge = next(o for o in origins() if o["id"] == "edge")

    assert edge["source_ip"] == "5.188.10.7"
    assert edge["direct_ip"] == "5.188.10.2"

def test_an_origin_the_attacker_box_cannot_reach_says_so():
    hk = next(o for o in origins() if o["id"] == "edge-hk")

    assert hk["direct_ip"] == ""

def test_a_missing_attacker_box_does_not_lose_the_origins():
    without_kali = Shape(
        segments=tuple(
            replace(s, nodes=tuple(n for n in s.nodes if n.name != KALI))
            for s in SHAPE.segments
        ),
        sensors=(),
    )

    assert {o["id"] for o in origins(without_kali)} == {
        "edge", "edge-hk", "edge-br",
    }

def test_an_origin_carries_the_address_the_attack_will_come_from():
    found = {o["id"]: o["source_ip"] for o in origins()}

    assert found["edge-hk"] == "103.152.220.7"
    assert found["edge"] == "5.188.10.7"

def test_an_attack_leaves_for_an_address_the_range_gave():
    hk = next(o for o in origins() if o["id"] == "edge-hk")

    assert hk["target_url"] == "http://103.152.220.9:8080", (
        "the address was a name assembled out of the origin id - 'waf-' plus "
        "'edge-hk' - which only resolves because compose was asked to put that "
        "alias on that network. Neutron hands out no aliases"
    )

def test_an_origin_with_no_way_in_is_not_offered():
    stranded = replace(HK, nodes=(Node(PROXY, "103.152.220.7"),))

    listed = attacker.origins(Shape(segments=(EDGE, stranded), sensors=()))

    assert [o["id"] for o in listed] == ["edge"], (
        "an origin whose segment the gateway does not stand on was offered, "
        "and an attack fired from it would have gone nowhere"
    )

def test_no_name_is_assembled_from_an_origin_id_anywhere():
    for source in (
        pathlib.Path(attacker.__file__),
        pathlib.Path(attacker.__file__).resolve().parents[1] / "deploy/proxy/stamp.py",
    ):
        assert "waf-" not in source.read_text(), (
            f"{source.name} builds a hostname by pasting 'waf-' in front of an "
            f"origin id, so the range has to be told to answer to it"
        )

def test_the_label_is_the_stack_s_own_description():
    hk = next(o for o in origins() if o["id"] == "edge-hk")

    assert hk["label"] == "Kwai Chung, Hong Kong"
    assert hk["subnet"] == "103.152.220.0/24"

def test_origins_are_in_a_stable_order_because_rotation_depends_on_it():
    assert [o["id"] for o in origins()] == sorted(o["id"] for o in origins())

def test_the_default_origin_is_the_one_the_terminal_already_used():
    assert [o["id"] for o in origins() if o["default"]] == ["edge"]

def test_a_segment_that_carries_no_origin_is_not_a_place_to_attack_from():
    assert "estate" not in {o["id"] for o in origins()}

def test_a_network_the_attacker_is_not_on_is_not_an_origin():
    elsewhere = Shape(
        segments=tuple(
            replace(s, nodes=tuple(n for n in s.nodes if n.name != PROXY))
            if s.id == "edge-br" else s
            for s in SHAPE.segments
        ),
        sensors=(),
    )

    assert {o["id"] for o in origins(elsewhere)} == {"edge", "edge-hk"}

def test_an_attacker_box_on_nothing_at_all_is_an_error_not_an_empty_list():
    nowhere = Shape(
        segments=(replace(EDGE, nodes=(Node(KALI, "5.188.10.2"),)),), sensors=(),
    )

    with pytest.raises(AttackerUnavailable):
        origins(nowhere)

def test_an_attacker_box_that_cannot_be_reached_is_a_range_that_cannot_be_read():
    assert issubclass(AttackerUnavailable, RangeUnavailable)

def test_finding_an_origin_never_names_the_substrate():
    source = pathlib.Path(attacker.__file__).read_text()

    assert "docker" not in source.lower()
    assert "subprocess" not in source

def test_the_default_origin_answers_when_none_was_asked_for():
    assert attacker.find(SHAPE, None)["source_ip"] == "5.188.10.7"

def test_a_chosen_origin_answers_with_its_own_address():
    assert attacker.find(SHAPE, "edge-hk")["source_ip"] == "103.152.220.7"

def test_an_unknown_origin_is_refused_rather_than_falling_back():
    with pytest.raises(attacker.UnknownOrigin):
        attacker.find(SHAPE, "edge-antarctica")

pytestmark = pytest.mark.django_db

PLACES = [
    {"id": "edge", "label": "Moscow, Russia", "source_ip": "5.188.10.7", "direct_ip": "5.188.10.7",
     "target_url": "http://5.188.10.9:8080", "subnet": "5.188.10.0/24",
     "network": "fsl_edge", "default": True},
    {"id": "edge-br", "label": "Sao Paulo, Brazil", "source_ip": "177.54.144.7", "direct_ip": "177.54.144.7",
     "target_url": "http://177.54.144.9:8080", "subnet": "177.54.144.0/24",
     "network": "fsl_edge-br", "default": False},
    {"id": "edge-hk", "label": "Kwai Chung, Hong Kong", "source_ip": "103.152.220.7", "direct_ip": "103.152.220.7",
     "target_url": "http://103.152.220.9:8080", "subnet": "103.152.220.0/24",
     "network": "fsl_edge-hk", "default": False},
]

def _fire(client, session_id, payload):
    with stub(), patch("api.views.attacker.origins", return_value=PLACES), \
            patch("api.views.harness.fire") as fired:
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", payload
        )
    return response, fired

@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]

def test_the_console_can_ask_where_it_may_attack_from(client):
    with stub(), patch("api.views.attacker.origins", return_value=PLACES):
        response = client.get("/api/origins/")

    assert response.status_code == 200
    assert [o["id"] for o in response.json()["origins"]] == [
        "edge", "edge-br", "edge-hk",
    ]

def test_origins_that_cannot_be_discovered_are_503_not_an_empty_list(client):
    with stub(error=RangeUnavailable("Cannot connect to the Docker daemon")):
        response = client.get("/api/origins/")

    assert response.status_code == 503
    assert "Docker" in response.json()["detail"]

def test_an_attack_with_no_origin_still_leaves_by_the_front_door(client, session_id):
    from django.conf import settings

    response, fired = _fire(client, session_id, {"case": "sqli-login-bypass"})

    assert response.status_code == 201
    assert fired.call_args.args[2] == settings.TARGET_URL
    assert "origin" not in response.json()["meta"]

def test_an_attack_leaves_by_the_origin_it_was_given(client, session_id):
    response, fired = _fire(
        client, session_id, {"case": "sqli-login-bypass", "origin": "edge-hk"}
    )

    assert response.status_code == 201
    assert fired.call_args.args[2] == "http://103.152.220.9:8080"

def test_the_origin_is_recorded_but_not_an_address(client, session_id):
    response, _ = _fire(
        client, session_id, {"case": "sqli-login-bypass", "origin": "edge-hk"}
    )
    meta = response.json()["meta"]

    assert meta["origin"] == "edge-hk"
    assert meta["target_url"] == "http://103.152.220.9:8080"
    assert "source_ip" not in meta

def test_rotation_moves_on_with_every_attack(client, session_id):
    seen = []
    for _ in range(4):
        _, fired = _fire(
            client, session_id, {"case": "sqli-login-bypass", "origin": "rotate"}
        )
        seen.append(fired.call_args.args[2])

    assert seen == [
        "http://5.188.10.9:8080",
        "http://177.54.144.9:8080",
        "http://103.152.220.9:8080",
        "http://5.188.10.9:8080",
    ], "rotation stalled: every attack would land on the same pin"

ROTATE = {"case": "sqli-login-bypass", "origin": "rotate"}

def test_two_rotated_attacks_in_flight_at_once_leave_from_different_places(client, session_id):
    left_from = []

    def still_running(http, case, target_url, *rest):
        left_from.append(target_url)
        if len(left_from) == 1:
            client.post_json(f"/api/sessions/{session_id}/attacks/", ROTATE)

    with stub(), patch("api.views.attacker.origins", return_value=PLACES), \
            patch("api.views.harness.fire", side_effect=still_running):
        client.post_json(f"/api/sessions/{session_id}/attacks/", ROTATE)

    assert len(left_from) == 2
    assert left_from[0] != left_from[1], (
        "the second rotated attack was fired while the first was still running, "
        "so no case had been recorded yet and both took the same turn: two "
        "attacks left from one place and one origin was skipped"
    )

def test_a_rotated_attack_that_starts_while_another_reads_the_range_takes_its_own_turn(
    client, session_id
):
    reads = []

    def read_while_another_starts(described):
        reads.append(described)
        if len(reads) == 1:
            client.post_json(f"/api/sessions/{session_id}/attacks/", ROTATE)
        return PLACES

    with stub(), patch("api.views.attacker.origins", side_effect=read_while_another_starts), \
            patch("api.views.harness.fire") as fired:
        client.post_json(f"/api/sessions/{session_id}/attacks/", ROTATE)

    left_from = [call.args[2] for call in fired.call_args_list]
    assert len(left_from) == 2
    assert left_from[0] != left_from[1], (
        "both attacks loaded the session before either took a turn, and the "
        "turn was written back from what each had loaded rather than advanced "
        "in the database"
    )

def test_attacks_pinned_to_a_place_or_recorded_by_hand_do_not_move_the_rotation(
    client, session_id
):
    rotated = []
    for step in ("rotate", "edge-hk", "rotate", "recorded", "rotate"):
        if step == "recorded":
            with patch("api.views._observe_objectives", return_value={"achieved": 0}):
                recorded = client.post_json(f"/api/sessions/{session_id}/cases/", {
                    "case_id": "55555555-5555-4555-8555-555555555555",
                    "name": "terminal-something", "malicious": True,
                    "correlation": "window", "source_ip": "5.188.10.7",
                    "started_at": "2026-09-24T10:00:00Z",
                    "ended_at": "2026-09-24T10:00:01Z",
                })
            assert recorded.status_code == 201, recorded.content
            continue
        _, fired = _fire(client, session_id, {"case": "sqli-login-bypass", "origin": step})
        if step == "rotate":
            rotated.append(fired.call_args.args[2])

    assert rotated == [
        "http://5.188.10.9:8080",
        "http://177.54.144.9:8080",
        "http://103.152.220.9:8080",
    ], (
        "the rotation counted every case in the session, so an attack pinned to "
        "one place or a case typed in the terminal shifted it and skipped an origin"
    )

def test_an_origin_that_does_not_exist_is_refused(client, session_id):
    response, fired = _fire(
        client, session_id, {"case": "sqli-login-bypass", "origin": "edge-mars"}
    )

    assert response.status_code == 404
    assert not fired.called

def test_the_terminal_s_address_follows_the_chosen_origin(client):
    with stub(), patch("api.views.attacker.origins", return_value=PLACES):
        response = client.get("/api/attacker/?origin=edge-hk")

    assert response.status_code == 200
    assert response.json()["source_ip"] == "103.152.220.7"
    assert response.json()["direct_ip"] == "103.152.220.7"
    assert response.json()["target_url"] == "http://103.152.220.9:8080"


@pytest.mark.django_db
def test_the_places_to_attack_from_are_listed_while_the_sensor_is_down(client):
    class SensorDown:
        def segments(self):
            return SHAPE.segments

        def describe(self):
            raise RangeUnavailable("fsl-suricata is declared to watch fsl-waf and stands in nothing")

    with patch("api.views.substrate", SensorDown):
        listed = client.get("/api/origins/")
        box = client.get("/api/attacker/")

    assert (listed.status_code, box.status_code) == (200, 200), (
        "the red console could not list where to attack from, or reach its own "
        "terminal, while the sensor was down - neither needs the sensor"
    )
