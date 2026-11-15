from unittest.mock import patch

import pytest

from range.ports import Ran, Shape

pytestmark = pytest.mark.django_db

HOME = [{"id": "edge", "label": "Moscow, Russia", "source_ip": "172.20.0.7", "direct_ip": "172.20.0.9",
         "target_url": "http://5.188.10.9:8080", "subnet": "", "network": "cr_edge",
         "address": "5.188.10.9", "default": True}]
REFUSED = "iptables: Permission denied (you must be root)"

def refusing(argv, stdin=None, timeout=60.0):
    return Ran(1, REFUSED)

def stub(proxy=None):
    class Stub:
        def segments(self):
            return self.describe().segments

        def describe(self):
            return Shape(segments=(), sensors=())

        def runner(self, role, segment_id=""):
            return proxy

    return patch("api.views.substrate", Stub)

def test_attacker_reports_the_address_alerts_will_carry(client):
    with stub(), patch("api.views.attacker.origins", return_value=HOME):
        response = client.get("/api/attacker/")

    assert response.status_code == 200
    assert response.json()["source_ip"] == "172.20.0.7"
    assert response.json()["direct_ip"] == "172.20.0.9"
    assert response.json()["terminal_url"]
    assert "container" not in response.json()

@pytest.mark.parametrize("path, body", [
    ("/api/attacker/label/", {"case_id": "c0ffee"}),
    ("/api/attacker/label/", {"case_id": None}),
    ("/api/attacker/origin/", {"origin": "edge"}),
])
def test_a_label_or_origin_the_proxy_did_not_take_is_503_with_its_reason(client, path, body):
    with stub(proxy=refusing), patch("api.views.attacker.origins", return_value=HOME):
        response = client.post_json(path, body)

    assert response.status_code == 503, (
        f"{path} answered {response.status_code} for a write the proxy refused, "
        f"so the console believed the terminal was stamped or moved when it was not"
    )
    assert REFUSED in response.json()["detail"]

def test_choosing_an_origin_wears_its_source_address(client):
    worn = []

    def runner(argv, stdin=None, timeout=60.0):
        worn.append((argv, stdin))
        return Ran(0, "")

    with stub(proxy=runner), patch("api.views.attacker.origins", return_value=HOME):
        response = client.post_json("/api/attacker/origin/", {"origin": "edge"})

    assert response.status_code == 200
    [(argv, stdin)] = worn
    assert argv == ["sudo", "/usr/local/sbin/set-origin", "172.20.0.7", "board.com"], (
        "the box's outgoing source is rewritten to the origin's address, "
        "which the port already owns, for what it sends to the target unbound"
    )
    assert stdin is None

def test_a_source_the_box_refused_is_503(client):
    with stub(proxy=refusing), patch("api.views.attacker.origins", return_value=HOME):
        response = client.post_json("/api/attacker/origin/", {"origin": "edge"})

    assert response.status_code == 503
