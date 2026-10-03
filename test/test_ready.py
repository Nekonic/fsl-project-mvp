import requests

from conftest import PLATFORM_URL

def test_the_compose_range_reports_itself_ready():
    answer = requests.get(f"{PLATFORM_URL}/api/range/ready/", timeout=60)

    assert answer.status_code == 200
    assert answer.json() == {"ready": True, "substrate": "compose", "slot": None}

def test_the_canary_corroborates_both_engines_on_the_live_stack():
    answer = requests.post(f"{PLATFORM_URL}/api/range/canary/", timeout=180)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["corroborated"] is True, body["blocked"]
    assert body["suricata"] is True and body["modsecurity"] is True
    assert body["skew_seconds"] is not None
