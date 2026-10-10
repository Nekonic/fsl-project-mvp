import json
import pathlib
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

import kibana
from api.models import Session
from tests.browser import open_page

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
        "http://kibana:5601/kibana/api/saved_objects/_import?overwrite=true",
        "http://kibana:5601/kibana/api/kibana/settings",
    ] * 2, "running bring-up twice repeats the same overwrite import, never a second copy"
    assert all(request.get_header("Kbn-xsrf") for request in fake.sent), (
        "Kibana refuses a write without the kbn-xsrf header"
    )
    imported, settings = fake.sent[0], fake.sent[1]
    assert payload in imported.data
    assert json.loads(settings.data) == {
        "changes": {"defaultRoute": "/app/discover#/view/fsl-alerts"}
    }, "opening /kibana/ lands on the alert search, not on Home"


def test_a_refused_import_stops_bring_up_before_the_settings():
    fake = FakeKibana(success=False)

    with pytest.raises(kibana.Refused):
        kibana.settle("http://kibana:5601/kibana", OBJECTS.read_bytes(), fake)

    assert len(fake.sent) == 1


def test_the_entrypoint_sets_kibana_up_in_the_background():
    text = ENTRYPOINT.read_text()

    assert "python kibana.py &" in text, (
        "Kibana answers a minute after Elasticsearch; waiting for it in the "
        "foreground would hold the platform back that long"
    )


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
    assert [item["attributes"]["title"] for item in by_type["dashboard"]] == ["FSL overview"]


def test_the_alert_search_matches_what_the_console_links_to():
    (search,) = [item for item in saved_objects() if item["type"] == "search"]
    source = json.loads(search["attributes"]["kibanaSavedObjectMeta"]["searchSourceJSON"])
    runtime = json.loads(next(
        item for item in saved_objects() if item["type"] == "index-pattern"
    )["attributes"]["runtimeFieldMap"])

    assert search["id"] == kibana.ALERT_SEARCH
    assert search["attributes"]["title"] == "FSL alerts"
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


@pytest.mark.django_db
def test_the_blue_console_opens_kibana_on_the_session_s_alerts(client):
    seen = open_page(client, "/blue/1/", setup="""
      browser.serve((request) => {
        if (request.route === "/api/sessions/1/") {
          return {body: {id: 1, lesson: null, discover: "/kibana/app/discover#/view/fsl-alerts?_a=x"}};
        }
        return {status: 404, body: {detail: "not served"}};
      });
    """, scenario="""
      return browser.element('pane-frame').getAttribute('src');
    """)

    assert seen["errors"] == []
    assert seen["result"] == "/kibana/app/discover#/view/fsl-alerts?_a=x"
