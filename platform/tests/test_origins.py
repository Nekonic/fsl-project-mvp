"""Where an attack comes from.

One subnet is one place, so a range on one edge network can only ever be
attacked from one city. The origins are the networks the stack declares, and
they are discovered rather than listed here: a table in Python drifts from the
compose file that actually decides which addresses exist, and the score is read
off the addresses.
"""

import json
from unittest.mock import patch

import pytest

import attacker
from attacker import AttackerUnavailable

NETWORKS = [
    {"Name": "fsl_edge", "Labels": {"fsl.origin": "Moscow, Russia"},
     "IPAM": {"Config": [{"Subnet": "5.188.10.0/24"}]}},
    {"Name": "fsl_edge-hk", "Labels": {"fsl.origin": "Kwai Chung, Hong Kong"},
     "IPAM": {"Config": [{"Subnet": "103.152.220.0/24"}]}},
    {"Name": "fsl_edge-br", "Labels": {"fsl.origin": "Sao Paulo, Brazil"},
     "IPAM": {"Config": [{"Subnet": "177.54.144.0/24"}]}},
]

ATTACHED = {
    "fsl_edge": {"IPAddress": "5.188.10.7"},
    "fsl_edge-hk": {"IPAddress": "103.152.220.7"},
    "fsl_edge-br": {"IPAddress": "177.54.144.7"},
}


class _Run:
    """Stands in for the two docker calls origins() makes, in order."""

    def __init__(self, networks=NETWORKS, attached=ATTACHED, code=0, stderr=""):
        self.networks, self.attached, self.code, self.stderr = (
            networks, attached, code, stderr,
        )

    def __call__(self, argv, **kwargs):
        if argv[:2] == ["docker", "network"]:
            out = "\n".join(json.dumps(n) for n in self.networks)
        else:
            out = json.dumps(self.attached)
        return type("R", (), {"returncode": self.code, "stdout": out,
                              "stderr": self.stderr})()


def origins(**kwargs):
    with patch("attacker.subprocess.run", _Run(**kwargs)):
        return attacker.origins()


def test_every_declared_network_is_an_origin():
    assert {o["id"] for o in origins()} == {"edge", "edge-hk", "edge-br"}


def test_an_origin_carries_the_address_the_attack_will_come_from():
    found = {o["id"]: o["source_ip"] for o in origins()}

    assert found["edge-hk"] == "103.152.220.7"
    assert found["edge"] == "5.188.10.7"


def test_an_origin_names_the_way_in_rather_than_the_host():
    # The WAF is on every edge network, so "waf" alone is ambiguous - the same
    # reason the default target is waf-edge and not waf. Naming the segment is
    # what makes the source address come out of that segment.
    hk = next(o for o in origins() if o["id"] == "edge-hk")

    assert hk["target_url"] == "http://waf-edge-hk:8080"


def test_the_label_is_the_stack_s_own_description():
    hk = next(o for o in origins() if o["id"] == "edge-hk")

    assert hk["label"] == "Kwai Chung, Hong Kong"
    assert hk["subnet"] == "103.152.220.0/24"


def test_origins_are_in_a_stable_order_because_rotation_depends_on_it():
    assert [o["id"] for o in origins()] == sorted(o["id"] for o in origins())


def test_the_default_origin_is_the_one_the_terminal_already_used():
    # settings.ATTACKER_NETWORK is what /api/attacker/ has always reported.
    # Rotation must not silently move it, or every existing window case would
    # be labelled with an address that matches no alert.
    assert [o["id"] for o in origins() if o["default"]] == ["edge"]


def test_a_network_the_attacker_is_not_on_is_not_an_origin():
    # Declared but unattached: the address does not exist, so an attack cannot
    # come from there and offering it would produce a case matching nothing.
    attached = {k: v for k, v in ATTACHED.items() if k != "fsl_edge-br"}

    assert {o["id"] for o in origins(attached=attached)} == {"edge", "edge-hk"}


def test_docker_that_cannot_answer_is_an_error_not_an_empty_list():
    # An empty list reads as "nowhere to attack from" and the console would
    # quietly offer nothing; the address is never guessed.
    with pytest.raises(AttackerUnavailable):
        origins(code=1, stderr="Cannot connect to the Docker daemon")


def test_source_ip_still_answers_for_the_default_origin():
    with patch("attacker.subprocess.run", _Run()):
        assert attacker.source_ip() == "5.188.10.7"


def test_source_ip_answers_for_a_chosen_origin():
    with patch("attacker.subprocess.run", _Run()):
        assert attacker.source_ip("edge-hk") == "103.152.220.7"


def test_an_unknown_origin_is_refused_rather_than_falling_back():
    with patch("attacker.subprocess.run", _Run()):
        with pytest.raises(attacker.UnknownOrigin):
            attacker.source_ip("edge-antarctica")


# -- the API surface -------------------------------------------------------
# Every UI action is a REST call first, so the console's origin selector is
# this and nothing more.


pytestmark = pytest.mark.django_db

PLACES = [
    {"id": "edge", "label": "Moscow, Russia", "source_ip": "5.188.10.7",
     "target_url": "http://waf-edge:8080", "subnet": "5.188.10.0/24",
     "network": "fsl_edge", "default": True},
    {"id": "edge-br", "label": "Sao Paulo, Brazil", "source_ip": "177.54.144.7",
     "target_url": "http://waf-edge-br:8080", "subnet": "177.54.144.0/24",
     "network": "fsl_edge-br", "default": False},
    {"id": "edge-hk", "label": "Kwai Chung, Hong Kong", "source_ip": "103.152.220.7",
     "target_url": "http://waf-edge-hk:8080", "subnet": "103.152.220.0/24",
     "network": "fsl_edge-hk", "default": False},
]


def _fire(client, session_id, payload):
    with patch("api.views.attacker.origins", return_value=PLACES), \
            patch("api.views.harness.fire") as fired:
        response = client.post_json(
            f"/api/sessions/{session_id}/attacks/", payload
        )
    return response, fired


@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]


def test_the_console_can_ask_where_it_may_attack_from(client):
    with patch("api.views.attacker.origins", return_value=PLACES):
        response = client.get("/api/origins/")

    assert response.status_code == 200
    assert [o["id"] for o in response.json()["origins"]] == [
        "edge", "edge-br", "edge-hk",
    ]


def test_origins_that_cannot_be_discovered_are_503_not_an_empty_list(client):
    with patch(
        "api.views.attacker.origins",
        side_effect=AttackerUnavailable("Cannot connect to the Docker daemon"),
    ):
        response = client.get("/api/origins/")

    assert response.status_code == 503
    assert "Docker" in response.json()["detail"]


def test_an_attack_with_no_origin_still_leaves_by_the_front_door(client, session_id):
    # The default has to stay where it was: every existing case, every
    # acceptance test and the whole recorded baseline came from there.
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
    assert fired.call_args.args[2] == "http://waf-edge-hk:8080"


def test_the_origin_is_recorded_but_not_an_address(client, session_id):
    # Origins are discovered from the attacker box, and a case fired from the
    # console leaves from the platform - a different container with its own
    # address on the same network. Recording the attacker's would name a
    # source that appears in no alert.
    response, _ = _fire(
        client, session_id, {"case": "sqli-login-bypass", "origin": "edge-hk"}
    )
    meta = response.json()["meta"]

    assert meta["origin"] == "edge-hk"
    assert meta["target_url"] == "http://waf-edge-hk:8080"
    assert "source_ip" not in meta


def test_rotation_moves_on_with_every_attack(client, session_id):
    seen = []
    for _ in range(4):
        _, fired = _fire(
            client, session_id, {"case": "sqli-login-bypass", "origin": "rotate"}
        )
        seen.append(fired.call_args.args[2])

    assert seen == [
        "http://waf-edge:8080",
        "http://waf-edge-br:8080",
        "http://waf-edge-hk:8080",
        "http://waf-edge:8080",
    ], "rotation stalled: every attack would land on the same pin"


def test_an_origin_that_does_not_exist_is_refused(client, session_id):
    # Falling back to the default would send the attack from somewhere else
    # and record it as having come from here.
    response, fired = _fire(
        client, session_id, {"case": "sqli-login-bypass", "origin": "edge-mars"}
    )

    assert response.status_code == 404
    assert not fired.called


def test_the_terminal_s_address_follows_the_chosen_origin(client):
    # /api/attacker/ is what a labelled window is scored against. If the
    # attacker leaves by Hong Kong and the window records Moscow, window
    # correlation matches nothing and the attack is scored as a miss.
    with patch("api.views.attacker.origins", return_value=PLACES):
        response = client.get("/api/attacker/?origin=edge-hk")

    assert response.status_code == 200
    assert response.json()["source_ip"] == "103.152.220.7"
    assert response.json()["target_url"] == "http://waf-edge-hk:8080"
