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

def test_the_site_route_is_guarded_like_the_terminals_and_passes_every_page_through_the_platform():
    block = site_block()

    assert "auth_request /terminal-allowed;" in block
    assert "proxy_pass http://127.0.0.1:8001/site-proxy/$session/$site/;" in block, (
        "the platform sends every page from the customers side and keeps a copy for the Network panel"
    )
    assert "proxy_set_header X-Site-Uri $site_uri;" in block

def test_the_script_injected_into_site_pages_answers_only_its_parent_console_and_adds_no_request():
    injected = re.search(r"sub_filter '</body>' '<script>(.*?)</script></body>';", site_block()).group(1)

    assert "m.source!==p" in injected and "own(m.origin)" in injected, (
        "a page framing the site, or a script inside it, gets no rect back"
    )
    assert "fslLocated:id" in injected and "},at)" in injected, "the rect goes back to the asking console only"
    assert "src=" not in injected and "fetch(" not in injected and "XMLHttpRequest" not in injected, (
        "the highlight helper loads nothing, so the WAF, Kibana and the Network panel never see it"
    )

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

    read = [step["check"]["marker"] for unit in ("f4", "f5", "f6")
            for step in wargames.lesson("board", lesson_id=unit)["steps"]
            if step["check"].get("of") == "rule" and step["check"].get("path")]

    assert read and set(read) == {views.SITE_BROWSER_MARKER}, (
        "a rule question about the learner's own search reads the Website pane's records"
    )

class Answer:
    def __init__(self, status, content=b"", headers=None, reason=None):
        self.status = status
        self.reason = reason if reason is not None else site.phrase_of(status)
        self.content = content
        self.headers = list((headers or {}).items())
        self.at = 0

    def getheaders(self):
        return self.headers

    def getheader(self, name, default=None):
        return next((value for key, value in self.headers if key.lower() == name.lower()), default)

    def read(self, size):
        chunk = self.content[self.at:self.at + size]
        self.at += len(chunk)
        return chunk

class Line:
    closed = False

    def settimeout(self, seconds):
        self.timeout = seconds

    def close(self):
        self.closed = True

ON_CUSTOMERS = site.Egress(source="73.0.0.4", address="73.0.0.9", port=80, boxed=False)

def proxied(client, path, answer, method="get", **extra):
    from unittest.mock import patch

    with patch("api.site.egress_of", return_value=(ON_CUSTOMERS, None)), \
            patch("api.site.exchange", return_value=(Line(), answer)) as sent:
        response = getattr(client, method)(f"/site-proxy/{path}", HTTP_X_SITE_URI=extra.pop("uri", "/"), **extra)
        if response.streaming:
            response.passed = b"".join(response.streaming_content)
    return response, sent

def test_the_proxy_sends_the_page_with_the_site_s_host_and_the_marker_and_keeps_the_platform_s_cookies(client):
    session = Session.objects.create(scenario="board", baseline=[])
    response, sent = proxied(client, f"{session.pk}/board.com/", Answer(403, b"<html>403 Forbidden</html>",
                             {"Content-Type": "text/html", "Set-Cookie": "a=b", "Server": "nginx"}),
                             uri="/search/?q=O%27Brien", HTTP_COOKIE="sessionid=platform")

    egress, _, method, target, headers, _ = sent.call_args.args
    assert (egress, method, target) == (ON_CUSTOMERS, "GET", "/search/?q=O%27Brien")
    assert headers["Host"] == "board.com" and headers["X-FSL-Case"] == session.browse_marker
    assert "Cookie" not in headers, "the platform's cookies never reach the target"
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

def test_the_network_panel_lists_each_session_s_requests_with_chrome_s_columns(client):
    session = Session.objects.create(scenario="board", baseline=[])
    other = Session.objects.create(scenario="board", baseline=[])
    proxied(client, f"{session.pk}/board.com/", Answer(200, b"ok", {"Content-Type": "text/html"}), uri="/",
            HTTP_SEC_FETCH_DEST="iframe")
    proxied(client, f"{session.pk}/board.com/", Answer(403, b"no", {"Content-Type": "text/html"}),
            uri="/search/?q=O%27Brien", HTTP_SEC_FETCH_DEST="iframe")
    proxied(client, f"{session.pk}/board.com/", Answer(200, b"body{}", {"Content-Type": "text/css"}),
            uri="/static/vendor/bootstrap.min.css", HTTP_SEC_FETCH_DEST="style",
            HTTP_REFERER=f"http://192.168.0.210:8002/site/{session.pk}/board.com/search/?q=O%27Brien")
    proxied(client, f"{other.pk}/board.com/", Answer(200, b"elsewhere"), uri="/")

    listed = client.get(f"/api/sessions/{session.pk}/site/requests/").json()
    newer = client.get(f"/api/sessions/{session.pk}/site/requests/?after={listed[0]['id']}").json()

    assert [(r["url"], r["status"], r["status_text"], r["type"], r["category"]) for r in listed] == [
        ("http://board.com/", 200, "OK", "document", "doc"),
        ("http://board.com/search/?q=O%27Brien", 403, "Forbidden", "document", "doc"),
        ("http://board.com/static/vendor/bootstrap.min.css", 200, "OK", "stylesheet", "css"),
    ]
    assert [r["initiator"] for r in listed] == [{"type": "other"}, {"type": "other"},
                                               {"type": "parser", "url": "http://board.com/search/?q=O%27Brien"}]
    assert set(listed[0]) == set(site.SUMMARY) and "blocked" not in listed[0], "nothing in the panel names the WAF"
    assert listed[2]["size"] > len(b"body{}"), "Size counts the response headers as Chrome's transferred size does"
    assert [r["status"] for r in newer] == [403, 200]
    assert client.get(f"/api/sessions/{session.pk}/site/requests/?after=x").status_code == 400

def test_one_request_s_detail_shows_what_the_browser_sent_without_the_marker_and_with_board_com_as_referer(client):
    session = Session.objects.create(scenario="board", baseline=[])
    big = b"a" * (site.BODY_LIMIT + 10)
    _, sent = proxied(client, f"{session.pk}/board.com/",
                      Answer(200, big, {"Content-Type": "text/html", "Referrer-Policy": "same-origin"}), method="post",
                      uri="/posts/1/comments/", data="body=hello", content_type="application/x-www-form-urlencoded",
                      HTTP_ORIGIN="http://192.168.0.210:8002",
                      HTTP_REFERER=f"http://192.168.0.210:8002/site/{session.pk}/board.com/posts/1/")
    row, = client.get(f"/api/sessions/{session.pk}/site/requests/").json()

    detail = client.get(f"/api/sessions/{session.pk}/site/requests/{row['id']}/").json()

    on_the_wire = sent.call_args.args[4]
    assert on_the_wire["Referer"] == "http://board.com/posts/1/" and on_the_wire["Origin"] == "http://board.com", (
        "the board, the WAF and Kibana see the Referer a browser on board.com sends, not the platform's address"
    )
    shown = dict(detail["request_headers"])
    assert shown["Host"] == "board.com" and shown["Referer"] == "http://board.com/posts/1/"
    assert "X-FSL-Case" not in shown, "the marker stays on the wire for correlation and out of the panel"
    assert detail["response_headers"] == [["Content-Type", "text/html"], ["Referrer-Policy", "same-origin"]]
    assert (detail["remote_address"], detail["egress"]) == ("73.0.0.9:80", "73.0.0.4"), (
        "Remote address is what the browser connected to; the record keeps the customers address it left from"
    )
    assert detail["request_body"] == {"text": "body=hello", "size": 10, "truncated": False}
    assert detail["response_body"]["size"] == site.BODY_LIMIT + 10
    assert len(detail["response_body"]["text"]) == site.BODY_LIMIT and detail["response_body"]["truncated"]
    assert client.get(f"/api/sessions/{session.pk}/site/requests/999999/").status_code == 404

def test_a_page_s_own_referrer_policy_is_shown_for_the_requests_it_makes(client):
    session = Session.objects.create(scenario="board", baseline=[])
    proxied(client, f"{session.pk}/board.com/", Answer(200, b"<html>", {"Content-Type": "text/html",
            "Referrer-Policy": "same-origin"}), uri="/", HTTP_SEC_FETCH_DEST="iframe")
    proxied(client, f"{session.pk}/board.com/", Answer(200, b"x", {"Content-Type": "text/css"}), uri="/a.css",
            HTTP_SEC_FETCH_DEST="style", HTTP_REFERER=f"http://h:8002/site/{session.pk}/board.com/")

    typed, linked = (client.get(f"/api/sessions/{session.pk}/site/requests/{row['id']}/").json()
                     for row in client.get(f"/api/sessions/{session.pk}/site/requests/").json())

    assert typed["referrer_policy"] == "strict-origin-when-cross-origin", "an address typed in the bar has Chrome's default"
    assert linked["referrer_policy"] == "same-origin"

def shape(*segments):
    from range.ports import Shape
    return Shape(segments=segments, sensors=())

class Range:
    def __init__(self, segments, opened=None):
        self.given = segments
        self.lines = []

    def segments(self):
        return self.given

    def runner(self, role):
        from range.ports import Ran

        def run(argv, stdin=None, timeout=60.0):
            return Ran(exit_code=0, output="5.188.10.10 via 10.0.0.1 dev ens3 src 1.128.0.10 uid 1000")
        return run

    def opened(self, role, argv):
        self.lines.append((role, argv))
        return Line()

def test_on_docker_the_pane_leaves_from_the_platform_s_address_on_a_customers_network_to_the_waf_there(settings):
    from range.ports import Node, Segment

    settings.ATTACKER_ORIGIN_MODE = "host-rewrite"
    ru = Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24",
                 nodes=(Node("fsl-proxy", "5.188.10.5"), Node("fsl-waf", "5.188.10.9"), Node("fsl-platform", "5.188.10.2")))
    us = Segment(id="us", name="Internet", origin="United States", subnet="73.0.0.0/24",
                 nodes=(Node("fsl-proxy", "73.0.0.5"), Node("fsl-waf", "73.0.0.9"), Node("fsl-platform", "73.0.0.2")))
    hk = Segment(id="hk", name="Internet", origin="Hong Kong", subnet="103.152.220.0/24",
                 nodes=(Node("fsl-proxy", "103.152.220.5"), Node("fsl-waf", "103.152.220.9"),
                        Node("fsl-platform", "103.152.220.2")))
    session = Session.objects.create(scenario="board", baseline=[])

    egress = site.found_egress(session, Range((ru, hk, us)))

    assert egress == site.Egress(source="73.0.0.2", address="73.0.0.9", port=80, boxed=False), (
        "not the attacker's ru network; of the customers' networks the one board's customers come from most"
    )

def test_on_openstack_the_pane_leaves_kali_from_a_customers_address_and_goes_through_the_firewall_to_board_com(
        settings):
    from range import declared
    from range.ports import Node, Segment

    settings.RANGE = declared.read(flavor="openstack")
    settings.ATTACKER_SOURCE_CONTAINER = "fsl-kali"
    settings.ATTACKER_CONTAINER = "fsl-kali"
    settings.ATTACKER_ORIGIN_MODE = "snat"
    settings.ATTACKER_TARGET_URL = "http://board.com"
    kr = Segment(id="kr", name="Internet", origin="South Korea", subnet="175.192.0.0/24",
                 nodes=(Node("fsl-edge", "175.192.0.1"), Node("fsl-kali", "175.192.0.10"),
                        Node("fsl-kali", "175.192.0.11")))
    ru = Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24",
                 nodes=(Node("fsl-edge", "5.188.10.1"), Node("fsl-kali", "5.188.10.10")))
    estate = Segment(id="estate", name="Application estate", subnet="10.30.0.0/24",
                     nodes=(Node("fsl-edge", "10.30.0.1"), Node("fsl-waf", "10.30.0.63")))
    session = Session.objects.create(scenario="board", baseline=[], slot=2)
    cloud = Range((kr, ru, estate))

    egress = site.found_egress(session, cloud)
    worn = {origin["id"]: origin["source_ip"] for origin in __import__("attacker").origins(shape(kr, ru, estate))}

    assert egress.boxed and egress.address == "10.30.0.63" and egress.port == 80, (
        "Kali's /etc/hosts names board.com by the WAF's estate address; Kali's route to it runs through the firewall"
    )
    assert egress.source in {"175.192.0.10", "175.192.0.11"} - {worn["kr"]}, (
        "a customers address on Kali, never the one the attacker sends from"
    )

def test_a_boxed_egress_opens_its_line_on_the_attacker_and_a_local_one_binds_the_customers_address(monkeypatch):
    import attacker

    cloud = Range(())
    monkeypatch.setattr(attacker, "as_customer", lambda source, address, port: ["bridge", source, address, str(port)],
                        raising=False)
    site.opened(site.Egress(source="175.192.0.11", address="10.30.0.63", port=80, boxed=True), cloud)
    bound = []
    monkeypatch.setattr(site.socket, "create_connection", lambda *args: bound.append(args) or Line())
    site.opened(ON_CUSTOMERS, None)

    assert cloud.lines == [("attacker", ["bridge", "175.192.0.11", "10.30.0.63", "80"])]
    assert bound == [(("73.0.0.9", 80), site.TIMEOUT[0], ("73.0.0.4", 0))]
