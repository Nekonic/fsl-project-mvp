from datetime import datetime, timezone

from ingest.elastic import normalize

MARKER = "11111111-1111-4111-8111-111111111111"


def suricata_alert(**overrides):
    doc = {
        "fsl_source": "suricata",
        "event_type": "alert",
        "timestamp": "2026-09-18T12:00:01.500000+0000",
        "src_ip": "172.20.0.5",
        "alert": {"signature": "ET WEB SQL Injection", "severity": 1},
        "http": {"hostname": "waf", "x_fsl_case": MARKER},
    }
    doc.update(overrides)
    return doc


def test_suricata_alert_becomes_one_detection():
    [det] = normalize("es1", suricata_alert())

    assert det["source"] == "suricata"
    assert det["signature"] == "ET WEB SQL Injection"
    assert det["severity"] == 1
    assert det["src_ip"] == "172.20.0.5"
    assert det["marker"] == MARKER
    assert det["timestamp"] == datetime(2026, 9, 18, 12, 0, 1, 500000, tzinfo=timezone.utc)
    assert det["detection_id"] == "es1"


def test_suricata_non_alert_events_are_dropped():
    assert normalize("es1", suricata_alert(event_type="http")) == []


def test_suricata_marker_read_from_dashed_header_name():
    doc = suricata_alert(http={"X-FSL-Case": MARKER})

    [det] = normalize("es1", doc)

    assert det["marker"] == MARKER


def test_suricata_marker_read_from_request_headers_list():
    doc = suricata_alert(
        http={"request_headers": [{"name": "X-FSL-Case", "value": MARKER}]}
    )

    [det] = normalize("es1", doc)

    assert det["marker"] == MARKER


def test_suricata_alert_without_marker_has_none():
    doc = suricata_alert(http={"hostname": "waf"})

    [det] = normalize("es1", doc)

    assert det["marker"] is None


def test_suricata_alert_without_http_section_has_none():
    doc = suricata_alert()
    del doc["http"]

    [det] = normalize("es1", doc)

    assert det["marker"] is None


def modsec_doc(messages):
    return {
        "fsl_source": "modsecurity",
        "transaction": {
            "time_stamp": "2026-09-18T12:00:02.000000+0000",
            "client_ip": "172.20.0.5",
            "request": {"headers": {"X-FSL-Case": MARKER}},
            "messages": messages,
        },
    }


def test_modsecurity_message_becomes_one_detection():
    [det] = normalize("es2", modsec_doc([{"message": "SQL Injection Attack Detected"}]))

    assert det["source"] == "modsecurity"
    assert det["signature"] == "SQL Injection Attack Detected"
    assert det["marker"] == MARKER
    assert det["src_ip"] == "172.20.0.5"
    assert det["detection_id"] == "es2:0"


def test_modsecurity_multiple_messages_become_multiple_detections():
    dets = normalize("es2", modsec_doc([{"message": "first"}, {"message": "second"}]))

    assert [d["signature"] for d in dets] == ["first", "second"]
    assert [d["detection_id"] for d in dets] == ["es2:0", "es2:1"]


def test_modsecurity_transaction_without_messages_is_dropped():
    assert normalize("es2", modsec_doc([])) == []


def test_modsecurity_falls_back_to_rule_id_when_message_is_missing():
    [det] = normalize("es2", modsec_doc([{"details": {"ruleId": "942100"}}]))

    assert det["signature"] == "ruleId 942100"


def test_unknown_source_is_dropped():
    assert normalize("es3", {"fsl_source": "nginx-access"}) == []


def test_document_without_source_field_is_dropped():
    assert normalize("es3", {"message": "hello"}) == []


def test_raw_document_is_preserved():
    [det] = normalize("es1", suricata_alert())

    assert det["raw"]["alert"]["signature"] == "ET WEB SQL Injection"
