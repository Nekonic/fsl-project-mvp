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


# ── 실제 스택에서 확인한 사실에 대한 회귀 테스트 ────────────────────────
#
# 1. Suricata 8.0.7 의 alert 이벤트는 HTTP 요청 헤더를 담지 않는다. 헤더는
#    같은 flow_id 를 가진 별도의 http 이벤트에만 실린다. 따라서 마커는
#    문서 하나만 보고는 알 수 없고 flow_id 로 조인해야 한다.
# 2. ModSecurity 감사 로그의 time_stamp 는 ISO 가 아니라 ctime 형식이다.


def suricata_http_event(marker=MARKER, flow_id=42, doc_id="h1"):
    return (
        doc_id,
        {
            "fsl_source": "suricata",
            "event_type": "http",
            "flow_id": flow_id,
            "timestamp": "2026-09-18T12:00:01.000000+0000",
            "src_ip": "172.20.0.5",
            "http": {
                "url": "/rest/products/search",
                "request_headers": [
                    {"name": "Host", "value": "localhost"},
                    {"name": "X-FSL-Case", "value": marker},
                ],
            },
        },
    )


def suricata_alert_event(flow_id=42, doc_id="a1"):
    doc = suricata_alert()
    doc["flow_id"] = flow_id
    doc["http"] = {"url": "/rest/products/search"}  # alert 에는 헤더가 없다
    return (doc_id, doc)


def test_normalize_all_joins_marker_from_http_event_by_flow_id():
    from ingest.elastic import normalize_all

    [det] = normalize_all([suricata_alert_event(), suricata_http_event()])

    assert det["detection_id"] == "a1"
    assert det["marker"] == MARKER


def test_normalize_all_does_not_join_across_different_flows():
    from ingest.elastic import normalize_all

    [det] = normalize_all(
        [suricata_alert_event(flow_id=1), suricata_http_event(flow_id=2)]
    )

    assert det["marker"] is None


def test_normalize_all_keeps_a_marker_the_document_already_carries():
    from ingest.elastic import normalize_all

    own = suricata_alert()
    own["flow_id"] = 42
    other = "99999999-9999-4999-8999-999999999999"

    [det] = normalize_all([("a1", own), suricata_http_event(marker=other)])

    assert det["marker"] == MARKER


def test_normalize_all_returns_detections_from_every_document():
    from ingest.elastic import normalize_all

    dets = normalize_all(
        [
            suricata_alert_event(flow_id=1, doc_id="a1"),
            suricata_alert_event(flow_id=2, doc_id="a2"),
            suricata_http_event(flow_id=1, doc_id="h1"),
        ]
    )

    assert {d["detection_id"] for d in dets} == {"a1", "a2"}


def test_normalize_all_accepts_an_empty_document_list():
    from ingest.elastic import normalize_all

    assert normalize_all([]) == []


def test_modsecurity_ctime_timestamp_is_parsed_as_utc():
    doc = modsec_doc([{"message": "SQLi"}])
    doc["transaction"]["time_stamp"] = "Fri Sep 18 15:25:02 2026"

    [det] = normalize("es2", doc)

    assert det["timestamp"] == datetime(2026, 9, 18, 15, 25, 2, tzinfo=timezone.utc)


def test_modsecurity_unparseable_timestamp_falls_back_to_beat_timestamp():
    doc = modsec_doc([{"message": "SQLi"}])
    doc["transaction"]["time_stamp"] = "설명할 수 없는 형식"
    doc["@timestamp"] = "2026-09-18T15:25:02.000Z"

    [det] = normalize("es2", doc)

    assert det["timestamp"] == datetime(2026, 9, 18, 15, 25, 2, tzinfo=timezone.utc)
