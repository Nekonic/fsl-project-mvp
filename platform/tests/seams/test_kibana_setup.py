import json
import pathlib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone


from cr.config import KibanaConfig
from defence import kibana

ROOT = pathlib.Path(__file__).resolve().parents[3]
OBJECTS = ROOT / "deploy/kibana/objects.ndjson"
CONFIG = KibanaConfig(url="http://kibana:5601/kibana", objects=str(ROOT / "deploy/kibana/objects.ndjson"))


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


def test_the_alert_search_matches_what_the_console_links_to():
    (search,) = [item for item in saved_objects() if item["type"] == "search"]
    source = json.loads(search["attributes"]["kibanaSavedObjectMeta"]["searchSourceJSON"])
    runtime = json.loads(next(
        item for item in saved_objects() if item["type"] == "index-pattern"
    )["attributes"]["runtimeFieldMap"])

    assert search["id"] == kibana.ALERT_SEARCH
    assert tuple(search["attributes"]["columns"]) == kibana.ALERT_COLUMNS, (
        "the console's link replaces the columns, so the two must agree"
    )
    assert source["query"]["query"] == kibana.ALERTS_QUERY
    assert {"rule", "rule_id", "source_ip", "destination", "url", "status"} <= set(runtime), (
        "Suricata and ModSecurity name the same thing differently; the data "
        "view folds each pair into one column"
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


def test_the_session_data_view_shows_its_name_not_its_pattern_and_hides_what_learners_must_not_read():
    view = a_session_view()
    attributes = view["attributes"]
    hidden = {entry["value"] for entry in json.loads(attributes["sourceFilters"])}

    assert attributes["title"] == "logs-2-*" and attributes["name"] == "logs-*"
    assert view["id"] == "soc-logs-2", "one view per index pattern, so opening again overwrites it"
    assert {"_index", "event.*", "log.*", "message", "http.request_headers*"} <= hidden, (
        "the raw syslog line and the request headers (which carry the step marker) stay out of the table and flyout"
    )
    assert {"http.*", "data_stream.*"} <= hidden, (
        "Suricata's own http names sit beside the lesson's url and status, and the data stream names the slot"
    )
    assert {"src_ip", "dest_ip", "alert.signature", "alert.signature_id"} <= hidden, (
        "the Suricata names for what the data view already shows as source_ip, destination, rule_id and rule"
    )
    assert not any(re.search(r"\bcr[-_.]", entry.lower()) or "slot" in entry.lower() for entry in hidden), (
        "Inspect prints the source filters, so none names the platform"
    )


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


def test_a_space_that_exists_is_updated_not_recreated():
    import io
    import urllib.error

    sent = []

    def send(request):
        sent.append((request.get_method(), request.full_url))
        if request.get_method() == "POST" and request.full_url.endswith("/api/spaces/space"):
            raise urllib.error.HTTPError(request.full_url, 409, "conflict", {}, io.BytesIO(b""))
        return {"success": True}

    kibana.ensure_session_view("logs-2-*", "waf", CONFIG, send)

    assert sent[1] == ("PUT", "http://kibana:5601/kibana/api/spaces/space/soc-logs-2")
    assert len(sent) == 4, "the view and the route are still written"


def test_a_refused_session_view_does_not_stop_the_session():
    assert kibana.ensure_session_view("logs-2-*", "waf", CONFIG, FakeKibana(success=False)) is None


def http_error(code, body=b""):
    import io
    import urllib.error

    return urllib.error.HTTPError("http://kibana:5601/kibana/api/saved_objects/_import", code, "x", {}, io.BytesIO(body))


def test_kibana_starting_up_is_waited_for_and_named_as_not_ready_rather_than_unreachable():
    paused = []

    def send(request):
        raise http_error(503, b"Kibana server is not ready yet")

    said = kibana.bring_up("http://kibana:5601/kibana", b"{}", send, paused.append)

    assert len(paused) == kibana.ATTEMPTS
    assert said.startswith("Kibana still answered 503, not ready"), said


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


def test_a_connection_failure_is_retried_until_kibana_answers():
    import urllib.error

    calls = []

    def send(request):
        calls.append(request)
        if len(calls) < 3:
            raise urllib.error.URLError("refused")
        return {"success": True, "successCount": 7}

    said = kibana.bring_up("http://kibana:5601/kibana", b"{}", send, lambda seconds: None)

    assert said == "kibana: 7 saved objects imported, default route set"


def test_a_connection_that_keeps_failing_is_called_unreachable():
    import urllib.error

    paused = []

    def send(request):
        raise urllib.error.URLError("refused")

    said = kibana.bring_up("http://kibana:5601/kibana", b"{}", send, paused.append)

    assert len(paused) == kibana.ATTEMPTS
    assert said.startswith("could not reach Kibana"), said


def test_nothing_a_learner_can_open_in_kibana_names_the_platform():
    view = a_session_view()
    visible = json.dumps(view["attributes"]).lower() + kibana.SESSION_VIEW_NAME.lower()

    assert not re.search(r"\bcr[-_.]", visible) and "slot" not in visible, (
        "the JSON tab, Inspect and the data view page print the index, the field names, the source filters and the scripts"
    )
    assert not re.search(r"\bcr[-_.]", json.dumps(kibana.session_search(view)).lower())
    assert kibana.SPACE_NAME == "SOC" and kibana.session_view_id("logs-2-*") == "soc-logs-2"


def test_set_up_reads_the_configured_objects_and_says_when_they_are_missing(tmp_path):
    fake = FakeKibana()

    assert kibana.set_up(CONFIG, fake, lambda _: None).startswith("kibana: 7 saved objects imported")
    assert kibana.set_up(KibanaConfig(objects=str(tmp_path / "none.ndjson")), fake).startswith("no saved objects at")
