import json
from unittest.mock import patch

import pytest

import kibana

MINE = {"soc-logs-1": "logs-1-*"}
SPACE = "/kibana/s/soc-logs-1/"
DISCOVER_SEARCH = {
    "params": {
        "index": "logs-1-*",
        "body": {
            "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "boolean"}}],
            "fields": [{"field": "rule"}, {"field": "@timestamp", "format": "strict_date_optional_time"}],
            "query": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-15m"}}}]}},
            "runtime_mappings": {"rule": {"type": "keyword", "script": {"source": "emit('x')"}}},
            "aggs": {"0": {"date_histogram": {"field": "@timestamp", "fixed_interval": "30s"}}},
        },
        "track_total_hits": True,
        "preference": 1763300000000,
    },
    "legacyHitsTotal": False,
}


def body(given):
    return json.dumps(given).encode()


DISCOVER_CALLS = [
    ("GET", "api/banners/info", b""),
    ("GET", "api/licensing/info", b""),
    ("GET", "api/saved_objects_tagging/tags", b""),
    ("GET", "api/index_patterns/has_user_index_pattern", b""),
    ("GET", "internal/data_views/has_data_views", b""),
    ("GET", "internal/spaces/_active_space", b""),
    ("GET", "internal/telemetry/config", b""),
    ("GET", "internal/kibana/settings", b""),
    ("GET", "internal/security/user_profile?dataPath=avatar%2CuserSettings", b""),
    ("POST", "api/core/capabilities", body({"applications": ["discover", "kibana"]})),
    ("POST", "internal/licensing/feature_usage/register", body([{"featureName": "x", "licenseType": "gold"}])),
    ("POST", "api/content_management/rpc/get", body({"contentTypeId": "index-pattern", "id": "soc-logs-1",
                                                     "version": 1})),
    ("POST", "api/content_management/rpc/search", body({"contentTypeId": "index-pattern", "query": {"limit": 10000},
                                                        "options": {"fields": ["title"]}, "version": 1})),
    ("GET", "internal/data_views/fields?pattern=logs-1-*&meta_fields=_source&allow_no_index=true&apiVersion=1", b""),
    ("POST", "internal/data_views/_fields_for_wildcard?pattern=logs-1-*&meta_fields=_source&allow_no_index=true",
     body({"index_filter": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-15m"}}}]}}})),
    ("POST", "internal/kibana/suggestions/values/logs-1-*",
     body({"query": "", "field": "event_type", "filters": [], "method": "terms_enum"})),
    ("POST", "internal/search/ese", body(DISCOVER_SEARCH)),
    ("POST", "internal/search/ese/FkxWT3JVeHZNU2FtaEs4ZjNNSWJ1amcdMVlY=",
     body({"id": "FkxWT3JVeHZNU2FtaEs4ZjNNSWJ1amcdMVlY=", **DISCOVER_SEARCH})),
    ("DELETE", "internal/search/ese/FkxWT3JVeHZNU2FtaEs4ZjNNSWJ1amcdMVlY=", b""),
]


@pytest.mark.parametrize("method, route, sent", DISCOVER_CALLS)
def test_every_call_discover_makes_in_the_learner_s_own_space_goes_through(method, route, sent):
    assert kibana.refusal(method, SPACE + route, sent, MINE) is None


def searching(index, **body_extra):
    return body({"params": {"index": index, "body": {"query": {"match_all": {}}, **body_extra}}})


def one_document(backing):
    return searching("logs-1-*", query={"bool": {"filter": [{"ids": {"values": ["YI-k6KEB4D26E1k_qnIo"]}},
                                                            {"term": {"_index": backing}}]}},
                     stored_fields=["*"], version=True, _source=True,
                     fields=[{"field": "*", "include_unmapped": True}],
                     runtime_mappings={"url": {"type": "keyword"}, "request_header": {"type": "composite"}})


def test_the_document_flyout_reads_one_document_of_the_session_s_own_backing_index():
    assert kibana.refusal("POST", SPACE + "internal/search/ese",
                          one_document(".ds-logs-1-sensors-2026.11.17-000001"), MINE) is None
    assert kibana.refusal("POST", SPACE + "internal/search/ese", one_document("logs-1-sensors"), MINE) is None


@pytest.mark.parametrize("backing", [
    ".ds-logs-2-sensors-2026.11.17-000001", ".ds-logs-10-sensors-2026.11.17-000001", ".kibana", "*",
    ["logs-1-sensors"], {"value": ".ds-logs-1-sensors-2026.11.17-000001"},
])
def test_the_document_flyout_names_no_index_outside_the_session_s_pattern(backing):
    assert kibana.refusal("POST", SPACE + "internal/search/ese", one_document(backing), MINE)


def test_the_document_flyout_s_json_shows_only_what_the_data_view_shows():
    sent = json.loads(kibana.shown_as_the_view_shows(
        "POST", SPACE + "internal/search/ese", one_document(".ds-logs-1-sensors-2026.11.17-000001")))
    search = sent["params"]["body"]

    assert {"event", "log", "agent", "message", "http.request_headers*"} <= set(search["_source"]["excludes"])
    assert not {"stored_fields", "docvalue_fields", "script_fields"} & set(search)
    assert search["fields"] == [{"field": "url"}, {"field": "url.*"},
                                {"field": "request_header"}, {"field": "request_header.*"}], (
        "the fields API asked for * would hand back the raw syslog line and the request headers the data view "
        "hides; the view's own runtime fields are what the table shows")
    assert search["query"]["bool"]["filter"][0] == {"ids": {"values": ["YI-k6KEB4D26E1k_qnIo"]}}
    assert kibana.shown_as_the_view_shows("POST", SPACE + "internal/search/ese", body(DISCOVER_SEARCH)) == body(
        DISCOVER_SEARCH)


def test_an_index_term_counts_only_as_a_whole_clause_of_its_own():
    widened = searching("logs-1-*", query={"bool": {"filter": [
        {"term": {"_index": ".ds-logs-1-sensors-2026.11.17-000001"}, "terms": {"x": {"index": "logs-2-x"}}}]}})
    assert kibana.refusal("POST", SPACE + "internal/search/ese", widened, MINE)


def test_request_batching_is_off_so_every_search_arrives_as_its_own_checked_request():
    assert kibana.SPACE_SETTINGS["bfetch:disable"] is True


class Answer:
    def __init__(self):
        self.headers = {"Content-Type": "application/json; charset=utf-8", "kbn-name": "kibana",
                        "Set-Cookie": "sid=x", "Content-Encoding": "gzip"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return 200

    def read(self):
        return b'{"rawResponse": {}}'


def test_the_gate_forwards_the_raw_uri_and_kibana_s_own_headers_alone():
    sent = []

    def send(request, timeout):
        sent.append(request)
        return Answer()

    with patch.object(kibana, "URL", "http://kibana:5601/kibana"):
        status, headers, answer = kibana.forward(
            "POST", SPACE + "internal/search/ese?x=1", {
                "Content-Type": "application/json", "kbn-version": "8.15.0", "x-elastic-internal-origin": "Kibana",
                "elastic-api-version": "1", "Cookie": "cr_session=secret", "Host": "range", "Accept-Encoding": "gzip",
            }, b"{}", send=send)

    assert sent[0].full_url == "http://kibana:5601/kibana/s/soc-logs-1/internal/search/ese?x=1"
    assert {name.lower() for name, _ in sent[0].header_items()} == {
        "content-type", "kbn-version", "x-elastic-internal-origin", "elastic-api-version"}
    assert (status, answer) == (200, b'{"rawResponse": {}}')
    assert {name for name, _ in headers} == {"Content-Type", "kbn-name"}


