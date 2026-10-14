import pathlib
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from api import site, views
from api.models import Detection, Session
from tests.browser import open_page

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

def test_the_site_route_strips_cookies_both_ways():
    block = site_block()

    assert 'proxy_set_header Cookie "";' in block and "proxy_hide_header Set-Cookie;" in block, (
        "the platform's cookies never reach the target and the target's Set-Cookie headers are dropped"
    )

def test_the_site_stays_inside_its_prefix_and_cannot_script_the_console():
    block = site_block()

    assert "proxy_redirect ~^(/.*)$ /site/$session/$site$1;" in block
    assert "proxy_redirect ~^https?://[^/]+(/.*)?$ /site/$session/$site$1;" in block
    for attribute in ("href", "src", "action"):
        assert f"sub_filter '{attribute}=\"/' '{attribute}=\"/site/$session/$site/';" in block
    assert "sub_filter 'http://$site/' '/site/$session/$site/';" in block
    assert "sub_filter 'http://$site\"' '/site/$session/$site/\"';" in block, "WordPress links home as http://corp.com"
    assert 'proxy_set_header Accept-Encoding "";' in block, "sub_filter cannot rewrite a compressed body"
    assert 'add_header Content-Security-Policy "sandbox allow-forms allow-scripts allow-same-origin" always;' in block
    assert "proxy_hide_header X-Frame-Options;" in block

def test_the_site_is_served_from_an_origin_of_its_own_so_its_scripts_cannot_reach_the_console():
    server = site_server()

    assert "location ~ ^/site/" in server and "location /kibana/" not in server
    assert "location / {\n            return 404;" in server, "the site's port serves the site and nothing else"
    assert NGINX.index("listen 8002;") < NGINX.index("location ~ ^/site/"), (
        "the console's own port 8000 has no site route"
    )
    assert "absolute_redirect off;" in server, "a redirect keeps whatever port the browser used"

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
    assert "browse" in response.json()["detail"]

SITE = """
browser.serve((request) => {
  if (request.route === "/api/sessions/1/") {
    return {body: {id: 1, guidance: false, lesson: null, site: SITE_URL}};
  }
  return {status: 404, body: {detail: "not served"}};
});
"""

def served(site='{port: 8002, path: "/site/1/board.com/"}'):
    return SITE.replace("SITE_URL", site)

SUBMIT = "browser.element('site-bar').dispatchEvent({type: 'submit', preventDefault() {}}); await browser.settle();"

def test_typing_a_path_in_the_address_bar_opens_it_through_the_site_route(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      await browser.click('[data-pane="site"]');
      const home = {{src: browser.element('site-frame').getAttribute('src'),
                    address: browser.element('site-address').value,
                    bar: browser.element('site-bar').classList.contains('hidden'),
                    sandbox: browser.element('site-frame').getAttribute('sandbox')}};
      browser.element('site-address').value = "board.com/search/?q=O'Brien";
      {SUBMIT}
      const typed = browser.element('site-frame').getAttribute('src');
      browser.element('site-address').value = "http://board.com/posts/1/";
      {SUBMIT}
      const absolute = browser.element('site-frame').getAttribute('src');
      browser.element('site-address').value = "search/?q=release";
      {SUBMIT}
      return {{home, typed, absolute, bare: browser.element('site-frame').getAttribute('src')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["home"] == {"src": "http://console.test:8002/site/1/board.com/", "address": "http://board.com/", "bar": False,
                              "sandbox": None}, (
        "the response's CSP sandbox isolates the page; a sandbox attribute without "
        "allow-same-origin makes some browsers refuse the frame outright"
    )
    assert result["typed"] == "http://console.test:8002/site/1/board.com/search/?q=O'Brien"
    assert result["absolute"] == "http://console.test:8002/site/1/board.com/posts/1/"
    assert result["bare"] == "http://console.test:8002/site/1/board.com/search/?q=release"

def test_back_and_forward_walk_the_site_history(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario=f"""
      await browser.click('[data-pane="site"]');
      browser.element('site-address').value = "/search/?q=release";
      {SUBMIT}
      const src = () => browser.element('site-frame').getAttribute('src');
      const disabled = () => [browser.element('site-back').disabled, browser.element('site-forward').disabled];
      const atSearch = disabled();
      await browser.click('site-back');
      const back = [src(), browser.element('site-address').value, ...disabled()];
      await browser.click('site-forward');
      const forward = [src(), ...disabled()];
      await browser.click('site-back');
      browser.element('site-address').value = "/posts/2/";
      {SUBMIT}
      return {{atSearch, back, forward, branched: disabled()}};
    """)
    result = seen["result"]

    assert result["atSearch"] == [False, True]
    assert result["back"] == ["http://console.test:8002/site/1/board.com/", "http://board.com/", True, False]
    assert result["forward"] == ["http://console.test:8002/site/1/board.com/search/?q=release", False, True]
    assert result["branched"] == [False, True], "a new page after going back drops the forward history"

def test_a_link_followed_inside_the_page_updates_the_address_bar_and_the_history(client):
    seen = open_page(client, "/blue/1/", setup=served(), scenario="""
      await browser.click('[data-pane="site"]');
      dispatchEvent({type: 'message', data: {fslSite: '/site/1/board.com/'}});
      dispatchEvent({type: 'message', data: {fslSite: '/site/1/board.com/search/?q=O%27Brien'}});
      const followed = {address: browser.element('site-address').value,
                        back: browser.element('site-back').disabled};
      dispatchEvent({type: 'message', data: {fslSite: '/kibana/app/discover'}});
      dispatchEvent({type: 'message', data: {other: 1}});
      await browser.click('site-back');
      return {followed, address: browser.element('site-address').value,
              src: browser.element('site-frame').getAttribute('src')};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["followed"] == {"address": "http://board.com/search/?q=O'Brien", "back": False}
    assert (result["address"], result["src"]) == ("http://board.com/", "http://console.test:8002/site/1/board.com/"), (
        "a message that is not the site's own location changes nothing"
    )

def test_a_session_with_no_site_offers_no_website_pane(client):
    seen = open_page(client, "/blue/1/", setup=served("null"), scenario="""
      return document.querySelector('[data-pane="site"]').classList.contains('hidden');
    """)

    assert seen["result"] is True

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

def test_a_lesson_step_with_a_query_carries_a_discover_link_narrowed_to_it(client):
    session = Session.objects.create(scenario="board", baseline=[], guidance=True, lesson="f4")

    steps = {step["id"]: step for step in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert "script" in steps["find"]["discover"] and "403" in steps["find"]["discover"]
    assert f"fsl-logs-{session.pk}" in steps["find"]["discover"]
    assert "discover" not in steps["search"]

def test_the_rule_answer_reads_the_records_of_the_site_browser_s_own_marker():
    import wargames

    rule = next(step for step in wargames.lesson("board", lesson_id="f5")["steps"] if step["id"] == "rule")

    assert rule["check"] == {"kind": "answer", "of": "rule", "marker": views.SITE_BROWSER_MARKER, "path": "1=1",
                             "known": ["949110"]}

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

def test_a_form_posted_on_the_site_is_passed_on_although_the_platform_refuses_foreign_posts(client):
    session = Session.objects.create(scenario="board", baseline=[])
    response, sent = proxied(client, f"{session.pk}/board.com/", Answer(302, b"", {"Location": "/"}), method="post",
                             uri="/accounts/login/", data="username=a&password=b",
                             content_type="application/x-www-form-urlencoded", HTTP_ORIGIN="http://elsewhere:8002")

    assert response.status_code == 302
    assert sent.call_args.kwargs["data"] == b"username=a&password=b"

def test_the_learner_s_own_address_is_not_passed_to_the_target(client):
    session = Session.objects.create(scenario="board", baseline=[])
    _, sent = proxied(client, f"{session.pk}/board.com/", Answer(200, b"ok"),
                      HTTP_X_FORWARDED_FOR="192.168.0.57", HTTP_X_REAL_IP="192.168.0.57")

    assert not {"X-Forwarded-For", "X-Real-Ip"} & set(sent.call_args.kwargs["headers"]), (
        "the target and its audit log see the platform, never the learner's LAN address"
    )

def test_the_proxy_answers_only_for_an_open_session(client):
    closed = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    missing, sent_missing = proxied(client, "999999/board.com/", Answer(200, b"ok"))
    refused, sent_closed = proxied(client, f"{closed.pk}/board.com/", Answer(200, b"ok"))

    assert (missing.status_code, refused.status_code) == (404, 409)
    assert not sent_missing.called and not sent_closed.called
    assert client.get(f"/api/sessions/{closed.pk}/site/requests/").status_code == 409, (
        "the Network panel stops polling a closed session"
    )

def test_a_waf_that_does_not_answer_is_a_502_that_names_no_internal_host(client):
    from unittest.mock import patch

    import requests

    session = Session.objects.create(scenario="board", baseline=[])
    failure = requests.ConnectionError(f"HTTPConnectionPool(host='fsl-{session.pk}-waf-1', port=80)")
    with patch("api.site.requests.request", side_effect=failure) as sent:
        response = client.get(f"/site-proxy/{session.pk}/board.com/", HTTP_X_SITE_URI="/")

    assert response.status_code == 502
    assert b"fsl-" not in response.content and b"HTTPConnectionPool" not in response.content
    connect, read = sent.call_args.kwargs["timeout"]
    assert connect <= 5 and read <= 30, "a WAF that hangs holds a server thread no longer than this"

def test_closing_a_session_forgets_its_site_requests(client):
    session = Session.objects.create(scenario="board", baseline=[])
    proxied(client, f"{session.pk}/board.com/", Answer(200, b"ok"))

    client.post_json(f"/api/sessions/{session.pk}/close/")

    assert site.kept(session.pk) == [] and session.pk not in site._records

def test_the_page_is_streamed_and_only_its_first_64_kb_are_kept(client):
    session = Session.objects.create(scenario="board", baseline=[])
    answer = Answer(200, b"b" * (site.BODY_LIMIT * 3))
    response, sent = proxied(client, f"{session.pk}/board.com/", answer)

    record, = site.kept(session.pk)
    assert sent.call_args.kwargs["stream"] is True and response.streaming
    assert len(response.passed) == site.BODY_LIMIT * 3, "the browser still gets the whole page"
    assert len(record["response_body"]["text"]) == site.BODY_LIMIT and record["response_body"]["size"] == len(response.passed)
    assert answer.closed

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

def test_a_session_keeps_only_its_latest_requests(client):
    session = Session.objects.create(scenario="board", baseline=[])
    for _ in range(site.KEPT_PER_SESSION + 5):
        proxied(client, f"{session.pk}/board.com/", Answer(200, b""), uri="/")

    assert len(client.get(f"/api/sessions/{session.pk}/site/requests/").json()) == site.KEPT_PER_SESSION

def test_on_a_cloud_range_the_proxy_reaches_the_waf_of_the_session_s_own_slot(client, monkeypatch):
    asked = []

    class Slot:
        def __init__(self, number):
            self.number = number

        def address(self, role):
            asked.append((self.number, role))
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
    assert asked == [(2, "gateway")], (
        "the WAF's address is looked up once per session, not on every page the learner opens"
    )
    assert client.get(f"/api/sessions/{session.pk}/").json()["site"]["port"] == 8002, (
        "on OpenStack the Website pane is offered too, or a lesson's first step cannot be done"
    )
