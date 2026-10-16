from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

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

@pytest.mark.parametrize("hits, corroborated", [
    ([_detection("suricata", AT), _detection("modsecurity", AT + timedelta(seconds=1))], True),
    ([_detection("suricata", AT)], False),
    ([_detection("suricata", AT), _detection("modsecurity", AT + timedelta(seconds=30))], False),
], ids=["both-in-sync", "one-engine", "clocks-disagree"])
def test_the_canary_corroborates_only_when_both_engines_alert_in_sync(client, hits, corroborated):
    body = _canary(client, hits).json()

    assert body["corroborated"] is corroborated
    assert bool(body["blocked"]) is not corroborated, body
