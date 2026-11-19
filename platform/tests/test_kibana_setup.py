import json
import pathlib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


import kibana

ROOT = pathlib.Path(__file__).resolve().parents[2]
OBJECTS = ROOT / "deploy/kibana/objects.ndjson"
ENTRYPOINT = ROOT / "platform/entrypoint.sh"


def saved_objects():
    return [json.loads(line) for line in OBJECTS.read_text().splitlines() if line.strip()]


class FakeKibana:
    def __init__(self, success=True):
        self.success = success
        self.sent = []

    def __call__(self, request):
        self.sent.append(request)
        if request.full_url.endswith("/_import?overwrite=true"):
            return {"success": self.success, "successCount": 7, "errors": [] if self.success else ["x"]}
        return {"settings": {}}


def test_bring_up_imports_the_objects_with_overwrite_then_sets_the_default_route():
    fake = FakeKibana()
    payload = OBJECTS.read_bytes()

    kibana.settle("http://kibana:5601/kibana/", payload, fake)
    kibana.settle("http://kibana:5601/kibana/", payload, fake)

    urls = [request.full_url for request in fake.sent]
    assert urls == [
        "http://kibana:5601/kibana/api/status",
        "http://kibana:5601/kibana/api/saved_objects/_import?overwrite=true",
        "http://kibana:5601/kibana/api/kibana/settings",
    ] * 2, "running bring-up twice repeats the same overwrite import, never a second copy"
    assert all(request.get_header("Kbn-xsrf") for request in fake.sent if request.get_method() == "POST"), (
        "Kibana refuses a write without the kbn-xsrf header"
    )
    assert payload in fake.sent[1].data


def test_the_saved_objects_parse_and_hang_off_the_one_data_view():
    found = saved_objects()
    by_type = {}
    for item in found:
        by_type.setdefault(item["type"], []).append(item)

    (view,) = by_type["index-pattern"]
    assert view["id"] == kibana.DATA_VIEW
    assert view["attributes"]["title"] == "logs-*"
    assert view["attributes"]["timeFieldName"] == "@timestamp", (
        "the geoip pipeline writes the event's own time to @timestamp"
    )
    ids = {item["id"] for item in found}
    for item in found:
        for reference in item["references"]:
            assert reference["id"] in ids, f"{item['id']} points at {reference['id']}, which is not imported"
    for item in by_type["search"] + by_type["visualization"]:
        assert any(r["id"] == kibana.DATA_VIEW for r in item["references"]), item["id"]


def test_no_saved_object_id_names_the_platform():
    assert not [item["id"] for item in saved_objects() if re.search(r"\bcr[-_.]", item["id"])], (
        "a lookup in the learner's space prints the ids"
    )


def unquoted(path):
    return urllib.parse.unquote(path)


def test_the_discover_link_opens_the_session_view_inside_its_own_space():
    start = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)
    view = kibana.session_view_id("logs-2-*")

    closed = unquoted(kibana.discover_path(view, start, end, kibana.query("")))
    running = unquoted(kibana.discover_path(view, start, None, kibana.query("")))

    assert closed.startswith("/kibana/s/soc-logs-2/app/discover#/?"), (
        "a link that overrides the saved search's query marks it 'Unsaved changes'; "
        "the pane opens an unsaved Discover state on the session's view in the session's space instead"
    )
    assert "dataSource:(dataViewId:'soc-logs-2',type:dataView)" in closed
    assert "from:'2026-10-10T05:00:00+00:00',to:'2026-10-10T05:30:00+00:00'" in closed
    assert "to:now" in running
    assert "grid:(columns:(" in closed and "source_ip:(width:" in closed and "'@timestamp':(width:" in closed, (
        "the saved search sets the column widths; a link that replaces the state keeps them, or an IP wraps"
    )
    assert "_index" not in closed and "logs'" not in closed, "no link reaches the shared view or another index"


def a_session_view(pattern="logs-2-*"):
    return kibana.session_view(pattern, "waf", kibana.shared_runtime(OBJECTS.read_bytes()))


def test_the_session_data_view_keeps_the_shared_columns_and_adds_the_engine_the_sensor_and_the_headers():
    runtime = json.loads(a_session_view()["attributes"]["runtimeFieldMap"])
    observer = runtime["sensor"]["script"]["source"]

    assert {"rule", "rule_id", "source_ip", "destination", "url", "status", "log_source", "sensor",
            "request_headers"} <= set(runtime)
    assert "in_iface" in observer, (
        "sensor is the leg the one IDS saw the event on, its sniffing interface: dmz before the WAF, web after it"
    )
    assert "emit(\"waf\")" in observer, "a ModSecurity record is written by the WAF"
    assert '"x-request-id"' in runtime["request_headers"]["script"]["source"], (
        "the request headers are shown without the step marker"
    )


def test_the_session_data_view_shows_the_waf_s_recorded_request_body_as_one_field_and_keeps_the_rest_hidden():
    view = a_session_view()
    runtime = json.loads(view["attributes"]["runtimeFieldMap"])
    hidden = {entry["value"] for entry in json.loads(view["attributes"]["sourceFilters"])}
    parts = re.search(r"^SecAuditLogParts (\S+)", (ROOT / "deploy/waf/modsecurity.conf").read_text(), re.M).group(1)

    assert "C" in parts and not set(parts) & set("DGIK"), (
        "ModSecurity v3 writes the request body only for part C and has no D, G, I or K; ABIJDEFHZ dropped the body")
    assert "['transaction']" in runtime["request_body"]["script"]["source"]
    assert "['body']" in runtime["request_body"]["script"]["source"]
    assert "transaction.*" in hidden, "walk round 28: 3.4's comment body shows as request_body, the record stays hidden"

def test_the_operator_objects_carry_no_platform_name_and_hide_the_same_fields_as_a_session_view():
    found = saved_objects()
    view = next(item for item in found if item["type"] == "index-pattern")

    assert not any(re.search(r"\bcr[-_.]", item["attributes"].get("title", "").lower()) for item in found)
    assert json.loads(view["attributes"]["sourceFilters"]) == json.loads(a_session_view()["attributes"]["sourceFilters"])


def test_opening_the_session_view_makes_its_space_and_imports_the_view_and_the_route_into_it():
    fake = FakeKibana()

    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), patch.object(kibana, "OBJECTS", str(OBJECTS)):
        made = kibana.ensure_session_view("logs-2-*", "waf", fake)

    space, imported, route = fake.sent
    base = "http://kibana:5601/kibana"
    assert made == "soc-logs-2"
    assert space.full_url == f"{base}/api/spaces/space" and space.get_method() == "POST"
    body = json.loads(space.data)
    assert body["id"] == made and "discover" not in body["disabledFeatures"]
    assert {"dashboard", "visualize", "dev_tools", "advancedSettings", "indexPatterns",
            "savedObjectsManagement"} <= set(body["disabledFeatures"])
    assert imported.full_url == f"{base}/s/{made}/api/saved_objects/_import?overwrite=true"
    assert body["name"] == "SOC" and b'"name": "logs-*"' in imported.data
    assert route.full_url == f"{base}/s/{made}/api/kibana/settings"
    changes = json.loads(route.data)["changes"]
    assert changes["defaultRoute"] == f"/app/discover#/view/{kibana.SESSION_SEARCH}"
    assert changes["defaultIndex"] == made, "an unset default makes the browser write it, which the front refuses"
    assert changes["enableESQL"] is False, "ES|QL reads every index, past the view's pattern and hidden fields"
    assert changes["defaultColumns"] == list(kibana.SESSION_COLUMNS), "a new Discover tab shows the same columns"
    saved = [json.loads(line) for line in imported.data.decode().splitlines() if line.startswith("{")]
    search = next(item for item in saved if item["type"] == "search")
    assert search["id"] == kibana.SESSION_SEARCH and search["attributes"]["columns"] == list(kibana.SESSION_COLUMNS)
    assert search["references"][0]["id"] == made


def test_a_space_that_exists_is_updated_not_recreated():
    import io
    import urllib.error

    sent = []

    def send(request):
        sent.append((request.get_method(), request.full_url))
        if request.get_method() == "POST" and request.full_url.endswith("/api/spaces/space"):
            raise urllib.error.HTTPError(request.full_url, 409, "conflict", {}, io.BytesIO(b""))
        return {"success": True}

    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), patch.object(kibana, "OBJECTS", str(OBJECTS)):
        kibana.ensure_session_view("logs-2-*", "waf", send)

    assert sent[1] == ("PUT", "http://kibana:5601/kibana/api/spaces/space/soc-logs-2")
    assert len(sent) == 4, "the view and the route are still written"


def test_a_refused_session_view_does_not_stop_the_session():
    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), patch.object(kibana, "OBJECTS", str(OBJECTS)):
        assert kibana.ensure_session_view("logs-2-*", "waf", FakeKibana(success=False)) is None


def http_error(code, body=b""):
    import io
    import urllib.error

    return urllib.error.HTTPError("http://kibana:5601/kibana/api/saved_objects/_import", code, "x", {}, io.BytesIO(body))


def test_kibana_starting_up_is_waited_for_and_named_as_not_ready_rather_than_unreachable():
    paused = []

    def send(request):
        raise http_error(503, b"Kibana server is not ready yet")

    kibana.bring_up("http://kibana:5601/kibana", b"{}", send, paused.append)

    assert len(paused) == kibana.ATTEMPTS


def test_nothing_is_imported_until_kibana_reports_itself_available():
    sent = []

    def send(request):
        sent.append(request.full_url)
        if len(sent) == 1:
            raise http_error(503, b"Kibana server is not ready yet")
        return {"success": True, "successCount": 7}

    said = kibana.bring_up("http://kibana:5601/kibana", b"{}", send, lambda seconds: None)

    assert said == "kibana: 7 saved objects imported, default route set"
    assert sent[:2] == ["http://kibana:5601/kibana/api/status"] * 2, (
        "a starting Kibana answers a multipart import 415, not 503, and bring-up gave up on the objects"
    )


def test_a_connection_failure_is_retried_then_called_unreachable():
    import urllib.error

    calls = []

    def send(request):
        calls.append(request)
        if len(calls) < 3:
            raise urllib.error.URLError("refused")
        return {"success": True, "successCount": 7}

    said = kibana.bring_up("http://kibana:5601/kibana", b"{}", send, lambda seconds: None)

    assert said == "kibana: 7 saved objects imported, default route set"


def test_nothing_a_learner_can_open_in_kibana_names_the_platform():
    view = a_session_view()
    visible = json.dumps(view["attributes"]).lower() + kibana.SESSION_VIEW_NAME.lower()

    assert not re.search(r"\bcr[-_.]", visible) and "slot" not in visible, (
        "the JSON tab, Inspect and the data view page print the index, the field names, the source filters and the scripts"
    )
    assert not re.search(r"\bcr[-_.]", json.dumps(kibana.session_search(view)).lower())
    assert kibana.SPACE_NAME == "SOC" and kibana.session_view_id("logs-2-*") == "soc-logs-2"
