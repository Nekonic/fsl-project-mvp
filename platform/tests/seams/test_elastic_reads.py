import json
from unittest.mock import patch

import pytest

from cr.config import ElasticConfig
from telemetry import elastic
from testing.fakes import FakeElastic

URL = "http://es:9200"


def access(at, status=200, ip="5.188.10.10", marker=None, module="nginx_access"):
    return {"@timestamp": at, "time": at, "event": {"module": module}, "client_ip": ip, "status": status,
            "request": "GET / HTTP/1.1", **({"request_id": marker} if marker else {})}


def test_fetch_after_moves_its_cursor_and_never_hands_a_document_twice():
    es = FakeElastic()
    for n, at in enumerate(["2026-11-19T10:00:00Z", "2026-11-19T10:00:01Z", "2026-11-19T10:00:01Z",
                            "2026-11-19T10:00:02Z"]):
        es.add(f"d{n}", access(at))

    with patch("telemetry.elastic.requests.post", es.post):
        first, cursor = elastic.fetch_after(URL, "logs-1-*", None, size=2)
        second, cursor = elastic.fetch_after(URL, "logs-1-*", cursor, size=2)
        third, cursor = elastic.fetch_after(URL, "logs-1-*", cursor, size=2)
        fourth, kept = elastic.fetch_after(URL, "logs-1-*", cursor, size=2)

    ids = [doc_id for page in (first, second, third) for doc_id, _ in page]
    assert ids == ["d0", "d1", "d2", "d3"]
    assert fourth == [] and kept == cursor
    assert cursor == {"at": "2026-11-19T10:00:02Z", "seen": ["d3"]}


def test_documents_sharing_the_cursor_s_timestamp_across_pages_are_all_handed_once():
    es = FakeElastic()
    for n in range(3):
        es.add(f"same{n}", access("2026-11-19T10:00:00Z"))

    with patch("telemetry.elastic.requests.post", es.post):
        first, cursor = elastic.fetch_after(URL, "logs-*", None, size=2)
        second, cursor = elastic.fetch_after(URL, "logs-*", cursor, size=2)

    assert [d for d, _ in first + second] == ["same0", "same1", "same2"]
    assert cursor["seen"] == ["same0", "same1", "same2"]


def test_access_events_read_only_the_nginx_access_module():
    es = FakeElastic()
    es.add("a1", access("2026-11-19T10:00:00Z", status=403, marker="action-2"))
    es.add("s1", {"@timestamp": "2026-11-19T10:00:01Z", "event": {"module": "suricata"}, "event_type": "alert"})
    es.add("a2", access("2026-11-19T10:00:02Z", status=200))

    with patch("telemetry.elastic.requests.post", es.post):
        events, cursor = elastic.access_events(URL, "logs-1-*", None)

    assert [(one["id"], one["status"], one["refused"], one["marker"]) for one in events] == [
        ("a1", 403, True, "action-2"), ("a2", 200, False, None)]
    sent = es.posted[0][1]
    assert {"term": {"event.module": "nginx_access"}} in sent["query"]["bool"]["filter"]


def test_the_ingest_pipeline_is_put_from_its_file_and_retried_until_elasticsearch_answers(tmp_path):
    pipeline = tmp_path / "ingest-pipeline.json"
    pipeline.write_text(json.dumps({"processors": []}))
    config = ElasticConfig(url=URL, pipeline_file=str(pipeline))
    answers = iter([OSError, 503, 200])
    put = []

    def answering(url, data=b"", timeout=0.0, headers=None):
        answer = next(answers)
        put.append((url, data))
        if answer is OSError:
            raise elastic.requests.ConnectionError("refused")
        return type("Answer", (), {"status_code": answer})()

    paused = []
    with patch("telemetry.elastic.requests.put", answering):
        assert elastic.register_pipeline(config, tries=5, pause=paused.append) is True

    assert put[-1] == (f"{URL}/_ingest/pipeline/geoip", pipeline.read_bytes())
    assert len(paused) == 2


def test_a_pipeline_elasticsearch_never_takes_is_reported_false(tmp_path):
    pipeline = tmp_path / "p.json"
    pipeline.write_text("{}")
    es = FakeElastic(put_status=500)

    with patch("telemetry.elastic.requests.put", es.put_pipeline):
        assert elastic.register_pipeline(ElasticConfig(pipeline_file=str(pipeline)), tries=3,
                                         pause=lambda _: None) is False
    assert len(es.put) == 3


def test_the_shipped_pipeline_file_is_the_one_the_config_points_at():
    from cr import config

    assert __import__("pathlib").Path(config.build({}).elastic.pipeline_file).is_file()


def test_an_unreachable_elasticsearch_is_a_domain_unavailable():
    with patch("telemetry.elastic.requests.post", side_effect=elastic.requests.ConnectionError("x")):
        with pytest.raises(elastic.ElasticUnavailable) as refused:
            elastic.fetch_after(URL, "logs-*")
    assert refused.value.code == "elastic_unavailable" and refused.value.status == 503
