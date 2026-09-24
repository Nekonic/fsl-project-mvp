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
        "http": {
            "hostname": "waf",
            "request_headers": [{"name": "X-FSL-Case", "value": MARKER}],
        },
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

def test_modsecurity_header_name_is_matched_case_insensitively():
    doc = modsec_doc([{"message": "SQLi"}])
    doc["transaction"]["request"]["headers"] = {"x-fsl-case": MARKER}

    [det] = normalize("es2", doc)

    assert det["marker"] == MARKER

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
    doc["http"] = {"url": "/rest/products/search"}
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
    doc["transaction"]["time_stamp"] = "not a shape anything can parse"
    doc["@timestamp"] = "2026-09-18T15:25:02.000Z"

    [det] = normalize("es2", doc)

    assert det["timestamp"] == datetime(2026, 9, 18, 15, 25, 2, tzinfo=timezone.utc)


def keepalive_pair(tx_id, marker, flow_id=7):
    alert = suricata_alert()
    alert["flow_id"] = flow_id
    alert["tx_id"] = tx_id
    alert["http"] = {"url": f"/tx/{tx_id}"}

    http = {
        "fsl_source": "suricata",
        "event_type": "http",
        "flow_id": flow_id,
        "tx_id": tx_id,
        "timestamp": "2026-09-18T12:00:01.000000+0000",
        "http": {
            "url": f"/tx/{tx_id}",
            "request_headers": [{"name": "X-FSL-Case", "value": marker}],
        },
    }
    return [(f"a{tx_id}", alert), (f"h{tx_id}", http)]

def test_keepalive_transactions_keep_their_own_markers():
    from ingest.elastic import normalize_all

    first = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    second = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    documents = keepalive_pair(0, first) + keepalive_pair(1, second)

    by_id = {d["detection_id"]: d["marker"] for d in normalize_all(documents)}

    assert by_id["a0"] == first
    assert by_id["a1"] == second, (
        "the second transaction on this flow inherited the first one's marker, "
        "so under keep-alive every alert lands on the first request"
    )

def test_marker_does_not_leak_to_a_transaction_without_one():
    from ingest.elastic import normalize_all

    marked = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    documents = keepalive_pair(0, marked)

    alert = suricata_alert()
    alert["flow_id"] = 7
    alert["tx_id"] = 1
    alert["http"] = {"url": "/tx/1"}
    documents.append(("a1", alert))

    by_id = {d["detection_id"]: d["marker"] for d in normalize_all(documents)}

    assert by_id["a0"] == marked
    assert by_id["a1"] is None

class _Response:
    def __init__(self, hits, total):
        self.status_code = 200
        self.ok = True
        self._body = {
            "hits": {
                "total": {"value": total, "relation": "eq"},
                "hits": [{"_id": str(n), "_source": {}} for n in range(hits)],
            }
        }

    def json(self):
        return self._body

def _fetch(hits, total, monkeypatch, **kwargs):
    from datetime import datetime, timezone
    from ingest import elastic

    monkeypatch.setattr(
        elastic.requests, "post", lambda *a, **k: _Response(hits, total)
    )
    when = datetime(2026, 9, 21, tzinfo=timezone.utc)
    return elastic.fetch("http://es", "fsl-logs-*", when, when, **kwargs)

def test_a_fetch_that_saw_everything_says_nothing(monkeypatch):
    documents, truncated = _fetch(120, 120, monkeypatch)

    assert len(documents) == 120
    assert truncated is None

def test_a_fetch_that_hit_the_cap_says_what_it_lost(monkeypatch):
    _, truncated = _fetch(5000, 25937, monkeypatch, size=5000)

    assert truncated == (5000, 25937), (
        "the window held 25937 documents and only 5000 were read; a caller "
        "that cannot see that scores a session on a fifth of its evidence"
    )

def test_a_waf_detection_keeps_where_its_source_is():
    doc = modsec_doc([{"message": "SQL Injection Attack Detected", "details": {}}])
    doc["src_geo"] = {"country_name": "Brazil", "location": {"lat": -23.5, "lon": -46.6}}

    [det] = normalize("es1", doc)

    assert det["raw"]["src_geo"]["country_name"] == "Brazil", (
        "the map places an address by the detections it has, and an address "
        "the WAF alone caught was never placed anywhere"
    )


def test_a_search_that_lost_a_shard_is_refused_rather_than_read_as_complete():
    from unittest.mock import patch

    from ingest import elastic

    with patch("ingest.elastic.requests.post") as posted:
        posted.return_value.ok = True
        posted.return_value.json.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        try:
            elastic.fetch("http://es:9200", "fsl-logs-*", datetime(2026, 9, 24, tzinfo=timezone.utc), datetime(2026, 9, 24, 1, tzinfo=timezone.utc))
        except elastic.ElasticUnavailable:
            pass

    assert "allow_partial_search_results=false" in posted.call_args.args[0], (
        "a search that lost a shard answers 200 with fewer hits, and ingest "
        "read the window as complete"
    )
