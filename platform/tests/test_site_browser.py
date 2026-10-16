import pathlib
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from api import site, views
from api.models import Detection, Session

ROOT = pathlib.Path(__file__).resolve().parents[2]
NGINX = (ROOT / "platform/nginx.conf").read_text()

pytestmark = pytest.mark.django_db

def site_server():
    start = NGINX.index("listen 8002;")
    return NGINX[start:]

def site_block():
    start = NGINX.index("location ~ ^/site/(?<session>\\d+)/")
    return NGINX[start:NGINX.index("\n        }", start)]

def site_tail(request_uri):
    pattern = re.search(r"map \$request_uri \$site_uri \{\s*~(\S+) \$site_tail;", NGINX).group(1)
    found = re.match(pattern.replace("(?<", "(?P<"), request_uri)
    return found.group("site_tail") if found else "/"

def test_the_site_route_is_guarded_like_the_terminals_and_goes_to_the_session_s_own_waf():
    block = site_block()

    assert "auth_request /terminal-allowed;" in block
    assert "proxy_pass http://127.0.0.1:8001/site-proxy/$session/$site/;" in block, (
        "the platform passes every page on to the WAF and keeps a copy for the Network panel"
    )
    assert "proxy_set_header X-Site-Uri $site_uri;" in block
    assert site.waf_url(7) == "http://fsl-7-waf-1", "the WAF judges every page the learner opens"

def test_the_console_s_own_port_does_not_serve_the_proxy():
    console = NGINX[:NGINX.index("listen 8002;")]

    assert "location /site-proxy/ {\n            return 404;" in console, (
        "on 8000 the target's pages would run with the console's origin"
    )

def test_the_site_route_keeps_the_path_and_query_exactly_as_the_browser_sent_them():
    assert site_tail("/site/7/board.com/search/?q=O%27Brien") == "/search/?q=O%27Brien"
    assert site_tail("/site/7/board.com/") == "/"
    assert site_tail("/site/7/board.com") == "/"
    assert site_tail("/site/7/corp.com/wp-json/?a=/b/") == "/wp-json/?a=/b/"

def test_the_site_is_served_from_an_origin_of_its_own_so_its_scripts_cannot_reach_the_console():
    server = site_server()

    assert "location ~ ^/site/" in server and "location /kibana/" not in server
    assert "location / {\n            return 404;" in server, "the site's port serves the site and nothing else"
    assert NGINX.index("listen 8002;") < NGINX.index("location ~ ^/site/"), (
        "the console's own port 8000 has no site route"
    )

def test_the_session_names_its_site_by_the_scenario_s_host(client):
    board = Session.objects.create(scenario="board", baseline=[])
    corp = Session.objects.create(scenario="corp", baseline=[])

    assert client.get(f"/api/sessions/{board.pk}/").json()["site"] == {
        "port": 8002, "path": f"/site/{board.pk}/board.com/"}
    assert client.get(f"/api/sessions/{corp.pk}/").json()["site"]["path"] == f"/site/{corp.pk}/corp.com/"

def test_alerts_drawn_by_browsing_are_left_out_of_the_score(client):
    session = Session.objects.create(scenario="board", baseline=[])
    Detection.objects.create(session=session, detection_id="b1", source="modsecurity",
                             signature="920273", timestamp=timezone.now(), marker=session.browse_marker)
    client.post_json(f"/api/sessions/{session.pk}/close/")

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert score["unattributed"] == 0 and score["fp"] == 0
    listed = client.get(f"/api/sessions/{session.pk}/detections/").json()
    assert [row["marker"] for row in listed] == [site.MARKER], (
        "the learner still finds the alert in the session's list, labelled browse"
    )

def test_a_forged_browse_header_does_not_hide_an_alert_from_the_score(client):
    session = Session.objects.create(scenario="board", baseline=[])
    other = Session.objects.create(scenario="board", baseline=[])
    for number, marker in enumerate([site.MARKER, other.browse_marker, "browse-0000"]):
        Detection.objects.create(session=session, detection_id=f"f{number}", source="modsecurity",
                                 signature="942100", timestamp=timezone.now(), marker=marker)
    client.post_json(f"/api/sessions/{session.pk}/close/")

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert score["unattributed"] == 3, (
        "only the session's own secret marker, which the platform alone sends, takes an alert out of the score"
    )
    assert session.browse_marker != other.browse_marker and len(session.browse_marker) > 30

def test_the_secret_marker_never_leaves_the_api(client):
    session = Session.objects.create(scenario="board", baseline=[])
    secret = session.browse_marker
    row = Detection.objects.create(
        session=session, detection_id="b1", source="modsecurity", signature="920273", timestamp=timezone.now(),
        marker=secret, raw={"transaction": {"request": {"headers": {"X-FSL-Case": secret}}}})

    listed = client.get(f"/api/sessions/{session.pk}/detections/").content.decode()
    detail = client.get(f"/api/detections/{row.pk}/").json()

    assert secret not in listed
    assert detail["marker"] == site.MARKER
    assert detail["raw"]["transaction"]["request"]["headers"]["X-FSL-Case"] == site.MARKER

@pytest.mark.parametrize("label", ["browse", "browse-1234", "browsewhatever"])
def test_the_attacker_cannot_label_its_traffic_as_browsing(client, label):
    response = client.post_json("/api/attacker/label/", {"case_id": label})

    assert response.status_code == 400

def test_ingest_can_read_only_the_last_minutes_so_a_long_session_still_finds_a_new_alert(client):
    from unittest.mock import patch

    session = Session.objects.create(scenario="board", baseline=[])
    with patch("api.views.elastic.fetch", return_value=([], None)) as fetched:
        client.post_json(f"/api/sessions/{session.pk}/ingest/", {"within": 120})
        client.post_json(f"/api/sessions/{session.pk}/ingest/")
    narrowed, whole = fetched.call_args_list

    assert timezone.now() - narrowed.args[2] < timedelta(seconds=125)
    assert whole.args[2] == session.started_at - timedelta(minutes=1)
    assert (narrowed.kwargs["newest_first"], whole.kwargs["newest_first"]) == (True, False), (
        "a recent read keeps the newest records when there are more than it can take"
    )
    assert client.post_json(f"/api/sessions/{session.pk}/ingest/", {"within": 0}).status_code == 400

def test_the_rule_answer_reads_the_records_of_the_site_browser_s_own_marker():
    import wargames

    rule = next(step for step in wargames.lesson("board", lesson_id="f5")["steps"] if step["id"] == "rule")

    assert rule["check"]["marker"] == views.SITE_BROWSER_MARKER

class Answer:
    def __init__(self, status, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, size):
        for start in range(0, len(self.content), size):
            yield self.content[start:start + size]

    def close(self):
        self.closed = True

def proxied(client, path, answer, method="get", **extra):
    from unittest.mock import patch

    with patch("api.site.requests.request", return_value=answer) as sent:
        response = getattr(client, method)(f"/site-proxy/{path}", HTTP_X_SITE_URI=extra.pop("uri", "/"), **extra)
        if response.streaming:
            response.passed = b"".join(response.streaming_content)
    return response, sent

def test_the_proxy_passes_the_page_to_the_session_s_waf_with_the_site_s_host_and_the_marker(client):
    session = Session.objects.create(scenario="board", baseline=[])
    response, sent = proxied(client, f"{session.pk}/board.com/", Answer(403, b"<html>403 Forbidden</html>",
                             {"Content-Type": "text/html", "Set-Cookie": "a=b", "Server": "nginx"}),
                             uri="/search/?q=O%27Brien", HTTP_COOKIE="sessionid=platform")

    method, url = sent.call_args.args
    headers = sent.call_args.kwargs["headers"]
    assert (method, url) == ("GET", f"http://fsl-{session.pk}-waf-1/search/?q=O%27Brien")
    assert headers["Host"] == "board.com" and headers["X-FSL-Case"] == session.browse_marker
    assert "Cookie" not in headers, "the platform's cookies never reach the target"
    assert sent.call_args.kwargs["allow_redirects"] is False
    assert response.status_code == 403 and response.passed == b"<html>403 Forbidden</html>"
    assert "Set-Cookie" not in response and response["Server"] == "nginx"

def test_the_proxy_answers_only_for_an_open_session(client):
    closed = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    missing, sent_missing = proxied(client, "999999/board.com/", Answer(200, b"ok"))
    refused, sent_closed = proxied(client, f"{closed.pk}/board.com/", Answer(200, b"ok"))

    assert (missing.status_code, refused.status_code) == (404, 409)
    assert not sent_missing.called and not sent_closed.called
    assert client.get(f"/api/sessions/{closed.pk}/site/requests/").status_code == 409, (
        "the Network panel stops polling a closed session"
    )

def test_the_site_s_requests_are_listed_per_session_with_what_the_waf_did(client):
    session = Session.objects.create(scenario="board", baseline=[])
    other = Session.objects.create(scenario="board", baseline=[])
    proxied(client, f"{session.pk}/board.com/", Answer(200, b"ok"), uri="/")
    proxied(client, f"{session.pk}/board.com/", Answer(403, b"no"), uri="/search/?q=O%27Brien")
    proxied(client, f"{other.pk}/board.com/", Answer(200, b"elsewhere"), uri="/")

    listed = client.get(f"/api/sessions/{session.pk}/site/requests/").json()
    newer = client.get(f"/api/sessions/{session.pk}/site/requests/?after={listed[0]['id']}").json()

    assert [(r["method"], r["url"], r["status"], r["blocked"]) for r in listed] == [
        ("GET", "http://board.com/", 200, False), ("GET", "http://board.com/search/?q=O%27Brien", 403, True),
    ]
    assert set(listed[0]) == {"id", "at", "method", "url", "status", "blocked", "ms"}
    assert [r["status"] for r in newer] == [403]
    assert client.get(f"/api/sessions/{session.pk}/site/requests/?after=x").status_code == 400

def test_one_request_s_detail_carries_both_sets_of_headers_and_bodies_bounded_to_64_kb(client):
    session = Session.objects.create(scenario="board", baseline=[])
    big = b"a" * (site.BODY_LIMIT + 10)
    proxied(client, f"{session.pk}/board.com/", Answer(200, big, {"Content-Type": "text/html"}), method="post",
            uri="/posts/1/comments/", data="body=hello", content_type="application/x-www-form-urlencoded")
    row, = client.get(f"/api/sessions/{session.pk}/site/requests/").json()

    detail = client.get(f"/api/sessions/{session.pk}/site/requests/{row['id']}/").json()

    assert detail["request_headers"]["Host"] == "board.com"
    assert detail["request_headers"]["X-FSL-Case"] == site.MARKER, "the secret marker stays on the server"
    assert detail["response_headers"] == {"Content-Type": "text/html"}
    assert detail["request_body"] == {"text": "body=hello", "size": 10, "truncated": False}
    assert detail["response_body"]["size"] == site.BODY_LIMIT + 10
    assert len(detail["response_body"]["text"]) == site.BODY_LIMIT and detail["response_body"]["truncated"]
    assert client.get(f"/api/sessions/{session.pk}/site/requests/999999/").status_code == 404

def test_on_a_cloud_range_the_proxy_reaches_the_waf_of_the_session_s_own_slot(client, monkeypatch):
    class Slot:
        def __init__(self, number):
            self.number = number

        def address(self, role):
            return f"10.31.0.{self.number}0"

    class Cloud:
        def in_slot(self, number):
            return Slot(number)

    monkeypatch.setattr(site, "substrate", Cloud)
    session = Session.objects.create(scenario="board", baseline=[], slot=2)
    try:
        _, first = proxied(client, f"{session.pk}/board.com/", Answer(200, b"ok"), uri="/search/?q=a")
        _, second = proxied(client, f"{session.pk}/board.com/", Answer(200, b"ok"), uri="/posts/")
    finally:
        site.forget(session.pk)

    assert first.call_args.args == ("GET", "http://10.31.0.20/search/?q=a")
    assert second.call_args.args == ("GET", "http://10.31.0.20/posts/")
    assert client.get(f"/api/sessions/{session.pk}/").json()["site"]["port"] == 8002, (
        "on OpenStack the Website pane is offered too, or a lesson's first step cannot be done"
    )
