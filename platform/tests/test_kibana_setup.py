import json
import pathlib
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import kibana
from api.models import Session

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
    assert view["attributes"]["title"] == "fsl-logs-*"
    assert view["attributes"]["timeFieldName"] == "@timestamp", (
        "the fsl-geoip pipeline writes the event's own time to @timestamp"
    )
    ids = {item["id"] for item in found}
    for item in found:
        for reference in item["references"]:
            assert reference["id"] in ids, f"{item['id']} points at {reference['id']}, which is not imported"
    for item in by_type["search"] + by_type["visualization"]:
        assert any(r["id"] == kibana.DATA_VIEW for r in item["references"]), item["id"]


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


def test_the_discover_link_without_a_session_view_narrows_the_shared_view_to_the_session_index():
    start = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)

    closed = unquoted(kibana.discover_path(kibana.DATA_VIEW, start, end, kibana.query("fsl-logs-15-*"), kibana.ALERT_COLUMNS))
    running = unquoted(kibana.discover_path(kibana.DATA_VIEW, start, None, kibana.query("fsl-logs-15-*")))
    shared = unquoted(kibana.discover_path(kibana.DATA_VIEW, start, None, kibana.query("")))

    assert closed.startswith("/kibana/app/discover#/?"), (
        "a link that overrides the saved search's query marks it 'Unsaved changes'; "
        "the pane opens an unsaved Discover state on the same data view instead"
    )
    assert "dataSource:(dataViewId:'fsl-logs',type:dataView)" in closed
    assert "and _index : fsl-logs-15-*" in closed
    assert "from:'2026-10-10T05:00:00+00:00',to:'2026-10-10T05:30:00+00:00'" in closed
    assert "to:now" in running
    assert "_index" not in shared, "on OpenStack every session writes the shared index"
    assert kibana.ALERTS_QUERY.replace("'", "!'") in shared


SENSORS = {"fsl-edge": "firewall", "fsl-wargame-host": "board.com"}


def a_session_view(pattern="fsl-logs-slot2-*", sensors=SENSORS):
    return kibana.session_view(pattern, sensors, "waf", kibana.shared_runtime(OBJECTS.read_bytes()))


def test_the_session_data_view_shows_its_name_not_its_pattern_and_hides_what_learners_must_not_read():
    view = a_session_view()
    attributes = view["attributes"]
    hidden = {entry["value"] for entry in json.loads(attributes["sourceFilters"])}

    assert attributes["title"] == "fsl-logs-slot2-*" and attributes["name"] == "Session logs"
    assert view["id"] == "session-fsl-logs-slot2", "one view per index pattern, so opening again overwrites it"
    assert {"_index", "fsl_*", "*X-FSL-Case*", "log.*", "message", "http.request_headers*"} <= hidden, (
        "the slot, the step marker and the raw syslog line (which carries the marker) stay out of the table and flyout"
    )


def test_the_session_data_view_keeps_the_shared_columns_and_adds_the_engine_the_sensor_and_the_headers():
    runtime = json.loads(a_session_view()["attributes"]["runtimeFieldMap"])
    observer = runtime["sensor"]["script"]["source"]

    assert {"rule", "rule_id", "source_ip", "destination", "url", "status", "log_source", "sensor",
            "request_headers"} <= set(runtime)
    assert '"fsl-edge": "firewall"' in observer and '"fsl-wargame-host": "board.com"' in observer, (
        "sensor is the map name of the host whose sensor wrote the event"
    )
    assert "emit(\"waf\")" in observer, "a ModSecurity record is written by the WAF"
    assert '"x-fsl-case"' in runtime["request_headers"]["script"]["source"], (
        "the request headers are shown without the step marker"
    )


def test_one_sensor_names_the_events_that_carry_no_sensor_host():
    single = kibana.sensor_script({"fsl-suricata": "waf"}, "waf")
    several = kibana.sensor_script(SENSORS, "waf")

    assert "host == '' ? \"waf\"" in single, "docker's one Suricata writes a file, not syslog, so no host is named"
    assert "host == '' ? \"\"" in several


def test_opening_the_session_view_overwrites_the_one_with_its_id():
    fake = FakeKibana()

    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), patch.object(kibana, "OBJECTS", str(OBJECTS)):
        made = kibana.ensure_session_view("fsl-logs-slot2-*", SENSORS, "waf", fake)

    (sent,) = fake.sent
    assert made == "session-fsl-logs-slot2"
    assert sent.full_url == "http://kibana:5601/kibana/api/saved_objects/_import?overwrite=true"
    assert b'"name": "Session logs"' in sent.data


def test_a_refused_session_view_does_not_stop_the_session():
    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), patch.object(kibana, "OBJECTS", str(OBJECTS)):
        assert kibana.ensure_session_view("fsl-logs-slot2-*", SENSORS, "waf", FakeKibana(success=False)) is None


@pytest.mark.django_db
def test_the_session_api_hands_the_console_its_discover_link(client, settings):
    settings.ELASTIC_SESSION_INDEX = "fsl-logs-{session}-*"
    session = Session.objects.create(scenario="board", baseline=[])

    reply = client.get(f"/api/sessions/{session.pk}/").json()

    assert f"_index : fsl-logs-{session.pk}-*" in unquoted(reply["discover"])
    assert "to:now" in unquoted(reply["discover"])


@pytest.mark.django_db
def test_a_lesson_opens_kibana_on_its_session_view_from_the_lesson_start_with_an_empty_query(client, settings):
    settings.ELASTIC_SESSION_INDEX = "fsl-logs-slot{slot}-*"
    began = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
    session = Session.objects.create(scenario="board", baseline=[], guidance=True, lesson="f2", lessons=[
        {"id": "f1", "started_at": (began - timedelta(minutes=10)).isoformat()},
        {"id": "f2", "started_at": began.isoformat()}])

    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), \
            patch.dict(kibana.VIEWS, {"fsl-logs-slot1-*": (True, 0.0)}):
        link = unquoted(client.get(f"/api/sessions/{session.pk}/").json()["discover"])

    assert "dataViewId:'session-fsl-logs-slot1'" in link
    assert "query:(language:kuery,query:'')" in link, "the learner writes the query; nothing scopes it in the bar"
    assert "from:'2026-10-18T08:59:55+00:00'" in link
    assert "columns:!(log_source,sensor,event_type,source_ip,destination,url,status,rule_id,rule)" in link
    assert "exists:(field:log_source)" in link, "the range VMs' own system log lines are not the session's events"


@pytest.mark.django_db
def test_a_session_view_kibana_refused_links_the_shared_view_narrowed_to_the_session_not_a_view_that_does_not_exist(
        client, settings):
    settings.ELASTIC_SESSION_INDEX = "fsl-logs-slot{slot}-*"
    session = Session.objects.create(scenario="board", baseline=[], guidance=True, lesson="f1")

    with patch.object(kibana, "URL", "http://kibana:5601/kibana"), patch.dict(kibana.VIEWS, {}, clear=True), \
            patch.object(kibana, "ensure_session_view", return_value=None):
        link = unquoted(client.get(f"/api/sessions/{session.pk}/").json()["discover"])

    assert "session-fsl-logs-slot1" not in link
    assert "_index : fsl-logs-slot1-*" in link


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


def test_nothing_that_waits_on_another_service_runs_before_the_platform_serves():
    text = ENTRYPOINT.read_text()
    before_serving = text[text.index("migrate"):text.index("exec waitress-serve")]

    assert "python register_pipeline.py &" in before_serving and "python kibana.py &" in before_serving, (
        "register_pipeline retries Elasticsearch for minutes; in the foreground the platform answers nothing meanwhile"
    )
    threads = int(text.split("--threads=")[1].split()[0])
    assert threads >= 16, "lesson checks, the Network panel and a long verify must not take every thread"
