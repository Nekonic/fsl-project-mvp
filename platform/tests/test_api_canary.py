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

def _passed(at):
    return ("es-http", {"event": {"module": "suricata"}, "event_type": "http", "timestamp": at.isoformat(),
                        "http": {"request_headers": [{"name": "X-Request-ID", "value": f"{TOKEN}-passed"}]}})

def _canary(client, hits, documents):
    with patch("api.views.substrate", lambda: Box()), patch(
        "api.views.uuid.uuid4", return_value=_Uuid()
    ), patch("api.views._standing"), patch(
        "api.views.attacker.find", return_value=ORIGIN
    ), patch("api.views.attacker.wear_origin"), patch(
        "api.views.harness.fire"
    ) as fired, patch("api.views.time.sleep"), patch(
        "api.views.elastic.fetch", return_value=(documents, None)
    ), patch("api.views.elastic.normalize_all", return_value=hits):
        return client.post_json(URL), fired

@pytest.mark.parametrize("hits, documents, corroborated", [
    ([_detection("modsecurity", AT + timedelta(seconds=1))], [_passed(AT)], True),
    ([_detection("modsecurity", AT)], [], False),
    ([], [_passed(AT)], False),
    ([_detection("modsecurity", AT + timedelta(seconds=30))], [_passed(AT)], False),
], ids=["both-in-sync", "waf-only", "ids-only", "clocks-disagree"])
def test_the_canary_needs_the_waf_s_alert_on_the_blocked_probe_and_the_ids_record_of_the_passed_one(
        client, hits, documents, corroborated):
    answer, fired = _canary(client, hits, documents)
    body = answer.json()

    assert body["corroborated"] is corroborated
    assert bool(body["blocked"]) is not corroborated, body
    assert [call.args[0]["case_id"] for call in fired.call_args_list] == [TOKEN, f"{TOKEN}-passed"], (
        "behind the WAF the IDS never sees the probe the WAF blocks, so a second request the WAF passes "
        "shows the IDS is reading the web servers' segment")
