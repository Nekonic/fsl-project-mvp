import json
import pathlib
import urllib.parse
from datetime import datetime, timedelta, timezone

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


def test_the_discover_link_narrows_to_the_session_index_and_window():
    start = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)

    closed = unquoted(kibana.discover_path("fsl-logs-15-*", start, end))
    running = unquoted(kibana.discover_path("fsl-logs-15-*", start, None))
    shared = unquoted(kibana.discover_path("", start, None))

    assert closed.startswith("/kibana/app/discover#/?"), (
        "a link that overrides the saved search's query marks it 'Unsaved changes'; "
        "the pane opens an unsaved Discover state on the same data view instead"
    )
    assert "dataSource:(dataViewId:fsl-logs,type:dataView)" in closed
    assert f"and _index : fsl-logs-15-*" in closed
    assert "from:'2026-10-10T05:00:00+00:00',to:'2026-10-10T05:30:00+00:00'" in closed
    assert "to:now" in running
    assert "_index" not in shared, "on OpenStack every session writes the shared index"
    assert kibana.ALERTS_QUERY.replace("'", "!'") in shared


@pytest.mark.django_db
def test_the_session_api_hands_the_console_its_discover_link(client, settings):
    settings.ELASTIC_SESSION_INDEX = "fsl-logs-{session}-*"
    session = Session.objects.create(scenario="board", baseline=[])

    reply = client.get(f"/api/sessions/{session.pk}/").json()

    assert f"_index : fsl-logs-{session.pk}-*" in unquoted(reply["discover"])
    assert "to:now" in unquoted(reply["discover"])


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
