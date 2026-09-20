"""An attack from outside has to arrive from outside.

Segmenting the network put the attacker on public space, but the way in stayed
on the inside: traffic published to the host port reached the WAF on its
app-side address, so the red team's own attacks were logged as coming from
`172.30.0.1` - a private address inside the estate, geolocating to nothing.

Half a topology is worse than none, because the half that is wrong is the half
the score is read from.
"""

import ipaddress
import json
import subprocess
import uuid

import pytest
import requests

from conftest import PLATFORM_URL, TARGET_URL

EDGE = ipaddress.ip_network("5.188.10.0/24")
ESTATE = ipaddress.ip_network("172.30.0.0/24")


def _alerts_mentioning(token, lines=400):
    """Alerts Suricata has just written whose request carries this token."""
    out = subprocess.run(
        ["docker", "exec", "fsl-suricata", "sh", "-c",
         f"tail -{lines} /var/log/suricata/eve.json"],
        capture_output=True, text=True, timeout=60,
    )
    found = []
    for line in out.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event_type") != "alert":
            continue
        if token in json.dumps(event.get("http", {})):
            found.append(event)
    return found


def _outside(alerts):
    return {
        a["src_ip"] for a in alerts
        if ipaddress.ip_address(a["src_ip"]) in EDGE
    }


@pytest.fixture
def probe(stack_is_up):
    """One attack through the published port, tagged so it can be found again."""
    token = f"zz{uuid.uuid4().hex[:10]}"
    # Percent-encoded by hand rather than through `params=`, which encodes a
    # space as `+`. The rules match `\x27\s*(or|and)` and `+` is not
    # whitespace, so a payload sent that way walks past them - see DECISIONS.
    requests.get(
        f"{TARGET_URL}/rest/products/search?q=%27%20OR%201%3D1--%20{token}",
        timeout=30,
    )
    import time; time.sleep(4)
    alerts = _alerts_mentioning(token)
    assert alerts, "the probe raised no alert at all, so nothing can be said about it"
    return alerts


def test_the_front_door_is_on_the_outside(probe):
    sources = {a["src_ip"] for a in probe}

    assert _outside(probe), (
        f"an attack through the published port arrived from {sorted(sources)}, "
        f"none of it from {EDGE} - the way in is on the inside of the estate"
    )


def test_the_inside_leg_is_still_the_inside(probe):
    # The WAF forwarding to the target is estate traffic and should stay so.
    # If this ever showed an edge address the segments would be meaningless.
    inside = {
        a["src_ip"] for a in probe
        if ipaddress.ip_address(a["src_ip"]) in ESTATE
    }

    assert inside, f"nothing crossed the estate at all: {sorted(a['src_ip'] for a in probe)}"


def test_an_attack_fired_from_the_console_comes_from_outside(stack_is_up):
    # The console fires from the platform, which sits on every segment - so it
    # can reach the WAF without crossing the edge, and used to.
    session_id = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120).json()["id"]
    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "sqli-login-bypass"}, timeout=300,
    )
    assert fired.status_code == 201, fired.text

    import time; time.sleep(6)
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/ingest/", timeout=300)
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    assert detections, "the console's attack produced no detections"

    sources = {d["src_ip"] for d in detections if d["src_ip"]}
    outside = {ip for ip in sources if ipaddress.ip_address(ip) in EDGE}

    assert outside, (
        f"the console's attack arrived from {sorted(sources)}, none of it from "
        f"{EDGE} - the platform reached the WAF without going outside"
    )
