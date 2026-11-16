import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

import kibana
from api.models import Session
from tests.conftest import ApiClient

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


@pytest.mark.parametrize("method, uri, sent", [
    ("POST", "/kibana/s/soc-logs-2/internal/search/ese", searching("logs-2-*")),
    ("POST", SPACE + "internal/search/ese", searching("logs-2-*")),
    ("POST", SPACE + "internal/search/ese", searching("logs-*")),
    ("POST", SPACE + "internal/search/ese", searching("*")),
    ("POST", SPACE + "internal/search/ese", searching("logs-1-*,logs-2-*")),
    ("POST", SPACE + "internal/search/ese", searching(".ds-logs-2-sensors-2026.11.15-000001")),
    ("POST", SPACE + "internal/search/ese", searching(["logs-1-*", "logs-2-*"])),
    ("POST", SPACE + "internal/search/ese", body({"params": {"body": {"query": {"match_all": {}}}}})),
    ("POST", SPACE + "internal/search/ese", searching("logs-1-*", query={"terms": {"source_ip": {
        "index": "logs-2-sensors", "id": "x", "path": "src_ip"}}})),
    ("POST", SPACE + "internal/search/ese", searching("logs-1-*", query={"more_like_this": {
        "like": [{"_index": "logs-2-sensors", "_id": "x"}]}})),
    ("POST", SPACE + "internal/search/es", searching("logs-2-*")),
    ("POST", SPACE + "internal/search/esql", body({"params": {"query": "FROM logs-2-* | LIMIT 5"}})),
    ("POST", SPACE + "internal/search/sql", body({"params": {"query": "SELECT * FROM \"logs-2-*\""}})),
    ("POST", SPACE + "internal/search/eql", body({"params": {"index": "logs-2-*", "body": {"query": "any where true"}}})),
    ("POST", SPACE + "internal/bsearch", body({"batch": [{"request": {"params": {"index": "logs-2-*"}},
                                                        "options": {"strategy": "es"}}]})),
    ("POST", SPACE + "api/console/proxy?path=logs-2-*/_search&method=GET", b""),
    ("GET", SPACE + "internal/data_views/fields?pattern=logs-2-*", b""),
    ("GET", SPACE + "internal/data_views/fields?pattern=logs-1-*&pattern=logs-2-*", b""),
    ("GET", SPACE + "internal/data_views/fields?%70attern=logs-2-*&pattern=logs-1-*", b""),
    ("GET", SPACE + "internal/data_views/fields?pattern=logs-1-%2A", b""),
    ("POST", SPACE + "internal/data_views/_fields_for_wildcard?pattern=logs-2-*", body({"index_filter": {}})),
    ("POST", SPACE + "internal/kibana/suggestions/values/logs-2-*", body({"field": "url", "query": ""})),
    ("GET", SPACE + "internal/index-pattern-management/resolve_index/*", b""),
    ("POST", SPACE + "api/content_management/rpc/create", body({"contentTypeId": "index-pattern",
                                                               "data": {"title": "logs-2-*"}, "version": 1})),
    ("POST", SPACE + "api/content_management/rpc/search", body({"contentTypeId": "index-pattern",
                                                               "options": {"namespaces": ["*"]}, "version": 1})),
    ("POST", SPACE + "api/saved_objects/index-pattern", body({"attributes": {"title": "logs-2-*"}})),
    ("GET", SPACE + "api/saved_objects/_find?type=index-pattern&namespaces=*", b""),
    ("POST", SPACE + "internal/search/ese/../../api/console/proxy", searching("logs-1-*")),
    ("POST", SPACE + "internal/search/%65se", searching("logs-1-*")),
    ("POST", SPACE + "Internal/search/ese", searching("logs-1-*")),
    ("POST", "/kibana/S/soc-logs-1/internal/search/ese", searching("logs-1-*")),
    ("POST", SPACE + "internal/search/ese", b"{\"params\": "),
    ("POST", SPACE + "internal/search/ese", b"logs-1-*"),
    ("PUT", SPACE + "internal/kibana/settings", body({"changes": {"bfetch:disable": False}})),
    ("POST", SPACE + "internal/kibana/settings", body({"changes": {"defaultIndex": "x"}})),
    ("DELETE", SPACE + "internal/search/ese", b""),
])
def test_a_learner_reaches_no_index_beyond_the_session_s_own_slot(method, uri, sent):
    assert kibana.refusal(method, uri, sent, MINE)


def test_staff_open_any_space_and_any_index_but_the_same_short_list_of_calls():
    assert kibana.refusal("POST", "/kibana/s/soc-logs-2/internal/search/ese", searching("logs-*"), None) is None
    assert kibana.refusal("GET", "/kibana/s/soc-logs-7/internal/data_views/fields?pattern=logs-*", b"", None) is None
    assert kibana.refusal("POST", SPACE + "api/console/proxy?path=_search&method=GET", b"", None)
    assert kibana.refusal("POST", SPACE + "internal/bsearch", b"{}", None)
    assert kibana.refusal("POST", SPACE + "internal/search/ese", searching("logs-*", query={"terms": {"x": {
        "index": ".kibana", "id": "x", "path": "y"}}}), None)


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


@pytest.fixture
def a_learner_on_slot_1(db, settings):
    settings.ELASTIC_SESSION_INDEX = "logs-{slot}-*"
    user = get_user_model().objects.create_user("learner1", password="range-practice-42")
    Session.objects.create(owner=user, slot=1)
    Session.objects.create(owner=user, slot=2, ended_at="2026-11-16T00:00:00Z")
    other = get_user_model().objects.create_user("learner2", password="range-practice-42")
    Session.objects.create(owner=other, slot=3)
    client = ApiClient()
    client.force_login(user)
    return client


def gate(client, uri, sent):
    return client.post("/kibana-gate/", sent, content_type="application/json", HTTP_X_KIBANA_URI=uri)


def test_the_gate_lets_a_learner_search_their_open_session_s_slot_only(a_learner_on_slot_1):
    forwarded = []

    def forward(method, uri, headers, sent):
        forwarded.append(uri)
        return 200, [("Content-Type", "application/json")], b'{"rawResponse": {"hits": {"total": 1}}}'

    with patch.object(kibana, "forward", forward):
        own = gate(a_learner_on_slot_1, SPACE + "internal/search/ese", searching("logs-1-*"))
        closed = gate(a_learner_on_slot_1, "/kibana/s/soc-logs-2/internal/search/ese", searching("logs-2-*"))
        others = gate(a_learner_on_slot_1, "/kibana/s/soc-logs-3/internal/search/ese", searching("logs-3-*"))
        typed = gate(a_learner_on_slot_1, SPACE + "internal/search/ese", searching("logs-3-*"))

    assert own.status_code == 200 and own.json()["rawResponse"]["hits"]["total"] == 1
    assert [closed.status_code, others.status_code, typed.status_code] == [403, 403, 403]
    assert typed.json()["statusCode"] == 403 and "logs-1-*" in typed.json()["message"]
    assert forwarded == [SPACE + "internal/search/ese"]


def test_the_gate_lets_staff_into_every_slot_s_space(client, settings):
    settings.ELASTIC_SESSION_INDEX = "logs-{slot}-*"
    with patch.object(kibana, "forward", lambda *asked: (200, [], b"{}")):
        assert gate(client, "/kibana/s/soc-logs-3/internal/search/ese", searching("logs-3-*")).status_code == 200


def test_the_gate_asks_for_a_sign_in_first(db):
    assert gate(ApiClient(), SPACE + "internal/search/ese", searching("logs-1-*")).status_code == 302
