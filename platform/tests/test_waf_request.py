from unittest.mock import patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def waf_record(uri="/rest/user/login", method="POST", host_ip="5.188.10.4", port=80):
    return {
        "event": {"module": "modsecurity"},
        "transaction": {
            "time_stamp": timezone.now().strftime("%a %b %d %H:%M:%S %Y"),
            "client_ip": "5.188.10.1",
            "host_ip": host_ip,
            "host_port": port,
            "request": {"method": method, "uri": uri, "headers": {}},
            "messages": [{"message": "SQL Injection Attack Detected", "details": {"severity": "2"}}],
        },
    }


def ingested(client, record):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    with patch("api.views.elastic.fetch", return_value=([("waf1", record)], None)):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
    return session_id


def test_a_waf_alert_is_listed_and_counted_with_its_path_method_and_destination(client):
    session_id = ingested(client, waf_record())

    [listed] = client.get(f"/api/sessions/{session_id}/detections/").json()

    assert (listed["method"], listed["path"], listed["dest_ip"], listed["dest_port"]) == (
        "POST", "/rest/user/login", "5.188.10.4", 80,
    ), (
        f"the WAF's alerts showed '-' for path and destination while Suricata's "
        f"did, and the KPI beside them counted both: {listed}"
    )

    top = client.get(f"/api/sessions/{session_id}/top/").json()
    assert [p["path"] for p in top["paths"]] == ["/rest/user/login"]
    assert [(d["dest_ip"], d["dest_port"]) for d in top["destinations"]] == [("5.188.10.4", 80)]
