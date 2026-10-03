from datetime import datetime, timedelta, timezone
from unittest.mock import patch

URL = "/api/range/canary/"
TOKEN = "canary-deadbeef"
ORIGIN = {"id": "ru", "target_url": "http://shop.com", "source_ip": "5.188.10.3"}
AT = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)

class Box:
    def runner(self, role):
        return lambda *a, **k: None

    def launcher(self, origin):
        return lambda *a, **k: None

class _Uuid:
    hex = "deadbeef"

def _detection(source, at):
    return {"source": source, "marker": TOKEN, "timestamp": at}

def _canary(client, hits):
    with patch("api.views.substrate", lambda: Box()), patch(
        "api.views.uuid.uuid4", return_value=_Uuid()
    ), patch("api.views._standing"), patch(
        "api.views.attacker.find", return_value=ORIGIN
    ), patch("api.views.attacker.wear_origin"), patch(
        "api.views.harness.fire"
    ), patch("api.views.time.sleep"), patch(
        "api.views.elastic.fetch", return_value=([], None)
    ), patch("api.views.elastic.normalize_all", return_value=hits):
        return client.post_json(URL)

def test_firing_the_canary_is_only_a_post(client):
    assert client.get(URL).status_code == 405

def test_the_canary_corroborates_when_both_engines_alert_in_sync(client):
    hits = [_detection("suricata", AT), _detection("modsecurity", AT + timedelta(seconds=1))]

    body = _canary(client, hits).json()

    assert body["corroborated"] is True
    assert body["suricata"] is True and body["modsecurity"] is True
    assert body["skew_seconds"] == 1.0
    assert body["blocked"] == []

def test_the_canary_does_not_corroborate_when_only_one_engine_alerts(client):
    body = _canary(client, [_detection("suricata", AT)]).json()

    assert body["corroborated"] is False
    assert body["suricata"] is True and body["modsecurity"] is False
    assert any("ModSecurity" in reason for reason in body["blocked"])

def test_the_canary_does_not_corroborate_when_the_clocks_disagree(client):
    hits = [_detection("suricata", AT), _detection("modsecurity", AT + timedelta(seconds=30))]

    body = _canary(client, hits).json()

    assert body["corroborated"] is False
    assert body["suricata"] is True and body["modsecurity"] is True
    assert any("clock" in reason for reason in body["blocked"])

def test_the_canary_reports_when_it_could_not_fire(client):
    from range.ports import RangeUnavailable

    with patch("api.views.substrate", lambda: Box()), patch(
        "api.views._standing"
    ), patch("api.views.attacker.find", return_value=ORIGIN), patch(
        "api.views.attacker.wear_origin", side_effect=RangeUnavailable("proxy is down")
    ):
        body = client.post_json(URL).json()

    assert body["corroborated"] is False
    assert any("proxy is down" in reason for reason in body["blocked"])
