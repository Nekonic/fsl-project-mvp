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
    token = f"zz{uuid.uuid4().hex[:10]}"
                                                                            
                                                                    
                                                            
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
                                                                            
                                                                            
    inside = {
        a["src_ip"] for a in probe
        if ipaddress.ip_address(a["src_ip"]) in ESTATE
    }

    assert inside, f"nothing crossed the estate at all: {sorted(a['src_ip'] for a in probe)}"

def test_an_attack_fired_from_the_console_comes_from_outside(stack_is_up):
                                                                              
                                                               
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
