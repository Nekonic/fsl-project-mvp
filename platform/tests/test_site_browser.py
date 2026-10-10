import pathlib
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from api import views
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
    assert "set $waf http://fsl-$session-waf-1:80;" in block, "the WAF judges every page the learner opens"
    assert "proxy_pass $waf$site_uri;" in block
    assert "proxy_set_header Host $site;" in block, "the WAF picks board.com or corp.com by Host"

def test_the_site_route_keeps_the_path_and_query_exactly_as_the_browser_sent_them():
    assert site_tail("/site/7/board.com/search/?q=O%27Brien") == "/search/?q=O%27Brien"
    assert site_tail("/site/7/board.com/") == "/"
    assert site_tail("/site/7/board.com") == "/"
    assert site_tail("/site/7/corp.com/wp-json/?a=/b/") == "/wp-json/?a=/b/"

def test_browsing_is_marked_so_the_score_never_takes_it_for_a_case():
    block = site_block()

    assert f"proxy_set_header X-FSL-Case {views.SITE_BROWSER_MARKER};" in block, (
        "a learner's own X-FSL-Case is replaced, never passed on"
    )
    assert 'proxy_set_header Cookie "";' in block and "proxy_hide_header Set-Cookie;" in block, (
        "the platform's cookies never reach the target and the target's never land on the platform"
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
                             signature="920273", timestamp=timezone.now(), marker=views.SITE_BROWSER_MARKER)
    client.post_json(f"/api/sessions/{session.pk}/close/")

    score = client.get(f"/api/sessions/{session.pk}/score/").json()

    assert score["unattributed"] == 0 and score["fp"] == 0
    assert len(client.get(f"/api/sessions/{session.pk}/detections/").json()) == 1, (
        "the learner still finds the alert in the session's list and in Kibana"
    )

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
    assert result["home"] == {"src": "http://console.test:8002/site/1/board.com/", "address": "board.com/", "bar": False,
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
    assert result["back"] == ["http://console.test:8002/site/1/board.com/", "board.com/", True, False]
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
    assert result["followed"] == {"address": "board.com/search/?q=O'Brien", "back": False}
    assert (result["address"], result["src"]) == ("board.com/", "http://console.test:8002/site/1/board.com/"), (
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
    session = Session.objects.create(scenario="board", baseline=[], guidance=True)

    steps = {step["id"]: step for step in client.get(f"/api/sessions/{session.pk}/").json()["lesson"]["steps"]}

    assert "Brien" in steps["find"]["discover"] and "403" in steps["find"]["discover"]
    assert f"fsl-logs-{session.pk}" in steps["find"]["discover"]
    assert "discover" not in steps["search"]

def test_the_lesson_s_alert_check_looks_for_the_site_browser_s_own_marker():
    import wargames

    search = wargames.lesson("board")["steps"][0]

    assert search["check"] == {"kind": "alert", "marker": views.SITE_BROWSER_MARKER, "path": "O'Brien"}
