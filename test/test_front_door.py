import ipaddress

import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

EDGE = ipaddress.ip_network("5.188.10.0/24")

def _outside(alerts):
    return {
        a["attributed"] for a in alerts
        if ipaddress.ip_address(a["attributed"]) in EDGE
    }

def _raised(alerts):
    assert alerts, "the probe raised no alert at all, so nothing can be said about it"
    return alerts

def _inside(alerts, inside):
    return {
        a["src_ip"] for a in alerts
        if a.get("src_ip") and ipaddress.ip_address(a["src_ip"]) in inside
        and ipaddress.ip_address(a["attributed"]) in EDGE
    }


def _ids_alerts(session_id):
    listed = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120).json()
    return [dict(requests.get(f"{PLATFORM_URL}/api/detections/{d['id']}/", timeout=60).json()["raw"],
                 attributed=d["src_ip"]) for d in listed if d["source"] == "suricata"]

@pytest.fixture
def probe(terminal_session):
    return _raised(terminal_session["front"])

@pytest.fixture
def past_the_waf(tuned_session):
    session_id = tuned_session["session_id"]
    inside = ipaddress.ip_network(tuned_session["inside"])

    def crossed(totals):
        return bool(_inside(_ids_alerts(session_id), inside))

    score_when_ready(session_id, until=crossed)
    return inside, _ids_alerts(session_id)

def test_the_front_door_is_on_the_outside(probe):
    sources = {a["src_ip"] for a in probe}

    assert _outside(probe), (
        f"an attack through the published port arrived from {sorted(sources)}, "
        f"none of it from {EDGE} - the way in is on the inside of the estate"
    )

def test_the_inside_leg_is_still_the_inside(past_the_waf):
    inside, detections = past_the_waf

    assert _inside(detections, inside), (
        f"an attack the WAF let through drew no IDS alert from inside {inside} naming the attacker in "
        f"X-Forwarded-For: {sorted({(d.get('src_ip'), d['attributed']) for d in detections})}"
    )
