import pytest
import requests

from conftest import PLATFORM_URL

PORTED_RULE = 'alert http $EXTERNAL_NET any -> $HOME_NET $HTTP_PORTS (msg:"FSL ported SQLi probe"; flow:established,to_server; http.uri; pcre:"/(\\x27[\\s+]*(or|and)[\\s+]*[\\x27\\d]|union[\\s+]+select|--[\\s+]|\\x27[\\s+]*--|\\x27[\\s+]*\\x29)/i"; sid:9009996; rev:1;)\n'

@pytest.fixture(scope="module")
def fired_with_a_ported_rule(stack_is_up, baseline_rules):
    from conftest import score_when_ready

    requests.post(
        f"{PLATFORM_URL}/api/rules/apply/",
        json={"content": baseline_rules + PORTED_RULE}, timeout=180,
    ).raise_for_status()
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    try:
        for name in ("sqli-login-bypass", "sqli-union-user-table"):
            sent = requests.post(
                f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
                json={"case": name}, timeout=300,
            )
            assert sent.status_code == 201, sent.text
        score_when_ready(session_id, lambda totals: totals["tp"] > 0)
        listed = requests.get(
            f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
        ).json()
        yield listed if isinstance(listed, list) else listed["detections"]
    finally:
        requests.post(
            f"{PLATFORM_URL}/api/rules/apply/",
            json={"content": baseline_rules}, timeout=180,
        )

def test_a_rule_written_against_http_ports_actually_fires(fired_with_a_ported_rule):
    ported = [
        d for d in fired_with_a_ported_rule
        if d["signature"] == "FSL ported SQLi probe"
    ]

    assert ported, (
        "a rule identical to the shipped one except that it says $HTTP_PORTS "
        "instead of any never fired. Every published HTTP signature is written "
        "that way, so a defender pasting one gets a validated rule, a reloaded "
        "sensor, a case scored FN, and no way to tell a wrong regex from a "
        "wrong port variable"
    )

def test_the_variable_names_the_ports_the_sensor_can_see(stack_is_up):
    import pathlib

    import yaml

    sensor = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1]
         / "deploy/suricata/suricata.yaml").read_text()
    )
    declared = sensor["vars"]["port-groups"]["HTTP_PORTS"]

    assert "8080" not in str(declared), (
        f"HTTP_PORTS is {declared!r}. 8080 is the host-published port; it is "
        f"translated before the packet reaches any interface the sensor taps. "
        f"Measured over the last six hours: every alert is on 80 or 3000"
    )
