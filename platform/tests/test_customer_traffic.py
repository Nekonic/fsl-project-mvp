import importlib.util
import json
import random
import re
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

import attacker
import traffic
from range.ports import Node, Segment, Shape

REPO = Path(__file__).resolve().parents[2]
MIX_PATH = REPO / "wargames" / "board" / "traffic.yaml"
KALI = "fsl-kali"

def mix():
    return traffic.checked(yaml.safe_load(MIX_PATH.read_text(encoding="utf-8")), MIX_PATH)

def offered(*origins):
    return [{"id": origin, "label": origin, "target_url": "http://board.com",
             "addresses": [f"10.9.{index}.{n}" for n in (10, 11)]}
            for index, origin in enumerate(origins)]

def test_most_customers_come_from_korea_and_the_seeded_accounts_sign_in_from_there():
    users = traffic.personas(mix(), offered(*mix()["origins"], "ru"), random.Random("1"))
    homes = Counter(user["origin"] for user in users)

    assert len(users) == 12
    assert homes == {"kr": 9, "us": 1, "jp": 1, "cn": 1}, homes
    assert [user["account"]["username"] for user in users if user["account"]] == ["jiwoo", "minseo"]
    assert all(user["origin"] == "kr" for user in users if user["account"])
    assert all(user["language"].startswith("ko-KR") for user in users if user["origin"] == "kr")

def test_customers_spread_over_an_origins_addresses_and_carry_its_way_in():
    users = traffic.personas(mix(), offered("kr"), random.Random("1"))

    assert {user["bind"] for user in users} == {"10.9.0.10", "10.9.0.11"}
    assert {user["target"] for user in users} == {"http://board.com"}

def test_an_origin_the_mix_does_not_name_is_not_used_and_none_left_is_refused():
    users = traffic.personas(mix(), offered("us", "ru"), random.Random("1"))

    assert {user["origin"] for user in users} == {"us"}
    with pytest.raises(traffic.NoOrigin, match="none of the origins"):
        traffic.personas(mix(), offered("ru"), random.Random("1"))

def test_largest_remainder_keeps_the_declared_shares():
    assert traffic.allocated({"c": 20, "a": 50, "b": 30}, 7) == ["a"] * 4 + ["b"] * 2 + ["c"]
    assert traffic.allocated({"us": 8, "hk": 3, "br": 2}, 12) == ["us"] * 7 + ["hk"] * 3 + ["br"] * 2

def test_a_profile_renders_only_its_actions_and_the_plain_one_searches_nothing_unusual():
    users = traffic.personas(mix(), offered("kr", "us"), random.Random("1"))
    community = traffic.flows(mix(), "community", users, random.Random("1"), count=3000)
    plain = traffic.flows(mix(), "plain", users, random.Random("1"), count=3000)

    assert {flow["action"] for flow in community} == set(traffic.ACTIONS)
    assert "search-unusual" not in {flow["action"] for flow in plain}
    assert all(users[flow["user"]]["account"] for flow in community if flow["action"] == "login")

def test_the_rendering_is_the_same_for_the_same_seed():
    users = traffic.personas(mix(), offered("kr"), random.Random("7"))

    assert traffic.plan(mix(), "community", 2, users, "board.com", "7", count=50) == \
        traffic.plan(mix(), "community", 2, users, "board.com", "7", count=50)

def test_searches_are_sent_the_way_the_boards_search_form_encodes_them():
    korean = {"id": "u01", "origin": "kr", "account": None}
    rng = random.Random("3")
    paths = {traffic.steps(mix(), "search-korean", korean, rng)[0]["path"] for _ in range(200)}
    unusual = {traffic.steps(mix(), "search-unusual", korean, rng)[0]["path"] for _ in range(200)}

    assert "/search/?q=%EC%84%9C%EC%9A%B8+%EB%A7%9B%EC%A7%91+%EC%B6%94%EC%B2%9C" in paths
    assert {parse_qs(urlsplit(path).query)["q"][0] for path in unusual} == set(mix()["searches"]["unusual"])
    assert "/search/?q=C%2B%2B+%26+C%23" in unusual

def test_posts_are_the_ones_the_board_seeds_and_nothing_else():
    seed = (REPO / "wargames/board/app/posts/management/commands/seed.py").read_text()
    seeded = len(re.findall(r"^\s+\(\"", seed.split("POSTS = [")[1].split("]")[0], re.MULTILINE))
    users = traffic.personas(mix(), offered("kr"), random.Random("1"))
    paths = {step["path"] for flow in traffic.flows(mix(), "community", users, random.Random("1"), count=2000)
             for step in flow["steps"]}

    assert mix()["posts"] == list(range(1, seeded + 1))
    assert {found[1] for path in paths if (found := re.match(r"/posts/(\d+)/", path))} == \
        {str(post) for post in mix()["posts"]}

def test_sign_in_and_comment_post_the_form_with_the_pages_csrf_token_and_follow_the_redirect():
    persona = {"id": "u01", "origin": "kr", "account": {"username": "jiwoo", "password": "jiwoo1234"}}
    login = traffic.steps(mix(), "login", persona, random.Random("1"))
    comment = traffic.steps(mix(), "comment", persona, random.Random("1"))

    assert [(step["method"], step["path"]) for step in login] == [
        ("GET", "/accounts/login/"), ("POST", "/accounts/login/")]
    assert login[1]["form"] == {"username": "jiwoo", "password": "jiwoo1234", "next": ""}
    assert login[1]["csrf"] and login[1]["follow"]
    assert comment[0]["method"] == "GET" and comment[1]["method"] == "POST"
    assert comment[1]["path"] == comment[0]["path"] + "comments/"
    assert comment[1]["csrf"] and comment[1]["form"]["body"]

@pytest.mark.parametrize("given, kept, expected", [(None, None, 1.0), (None, 4.0, 4.0), (50, None, 50.0), (0.5, 2, 0.5)])
def test_the_rate_defaults_low(given, kept, expected):
    assert traffic.rate_of(given, kept) == expected

@pytest.mark.parametrize("given", [0, -1, 50.5, 1000, "2", True])
def test_the_rate_is_capped_at_what_the_range_was_measured_to_take(given):
    with pytest.raises(ValueError, match="at most 50"):
        traffic.rate_of(given)

def test_records_are_taken_only_up_to_the_last_whole_line():
    whole = json.dumps({"marker": "a", "status": 200}) + "\n" + "not json\n"
    found, used, garbled = traffic.records(whole + '{"marker": "b", "sta')

    assert [record["marker"] for record in found] == ["a"]
    assert used == len(whole.encode()) and garbled == 1

def _openstack_shape():
    kr = Segment(id="kr", name="Internet", origin="South Korea", subnet="175.192.0.0/24",
                 nodes=(Node("fsl-edge", "175.192.0.1"), Node(KALI, "175.192.0.10"), Node(KALI, "175.192.0.11")))
    us = Segment(id="us", name="Internet", origin="United States", subnet="73.0.0.0/24",
                 nodes=(Node("fsl-edge", "73.0.0.1"), Node(KALI, "73.0.0.10"), Node(KALI, "73.0.0.11"),
                        Node(KALI, "73.0.0.12")))
    ru = Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24",
                 nodes=(Node("fsl-edge", "5.188.10.1"), Node(KALI, "5.188.10.10")))
    au = Segment(id="au", name="Internet", origin="Australia", subnet="1.128.0.0/24",
                 nodes=(Node("fsl-edge", "1.128.0.1"), Node(KALI, "1.128.0.10")))
    return Shape(segments=(kr, us, ru, au), sensors=())

@pytest.fixture
def on_openstack(settings):
    from range import declared
    settings.RANGE = declared.read(flavor="openstack")
    settings.ATTACKER_SOURCE_CONTAINER = KALI
    settings.ATTACKER_CONTAINER = KALI
    settings.ATTACKER_ORIGIN_MODE = "snat"
    settings.ATTACKER_TARGET_URL = "http://board.com"

def test_customers_never_take_an_address_the_attacker_sends_from(on_openstack):
    shape = _openstack_shape()
    worn = {origin["id"]: origin["source_ip"] for origin in attacker.origins(shape)}

    found = {origin["id"]: origin["addresses"] for origin in attacker.customer_origins(shape, unbound="1.128.0.10")}

    assert "ru" not in found, "the attacker's default origin is not a customer's"
    assert "au" not in found, "the box's unbound source is the attacker's when it wears no origin"
    assert worn["kr"] not in found["kr"] and worn["us"] not in found["us"]
    assert found["kr"] and found["us"]

def test_with_a_per_origin_way_in_customers_get_their_own_container_address(settings):
    settings.ATTACKER_ORIGIN_MODE = "host-rewrite"
    settings.ATTACKER_SOURCE_CONTAINER = "fsl-proxy"
    settings.ATTACKER_CONTAINER = "fsl-kali"
    us = Segment(id="us", name="Internet", origin="United States", subnet="73.0.0.0/24",
                 nodes=(Node("fsl-proxy", "73.0.0.5"), Node("fsl-waf", "73.0.0.9")))
    ru = Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24",
                 nodes=(Node("fsl-proxy", "5.188.10.5"), Node("fsl-waf", "5.188.10.9")))

    found = attacker.customer_origins(Shape(segments=(us, ru), sensors=()))

    assert found == [{"id": "us", "label": "United States", "target_url": "http://73.0.0.9", "addresses": []}]

def test_the_unbound_source_is_read_from_the_boxs_route_to_the_target(on_openstack):
    seen = []

    def box(argv, stdin=None, timeout=60.0):
        from range.ports import Ran
        seen.append(argv)
        return Ran(0, "10.30.0.102 via 1.128.0.1 dev ens3 src 1.128.0.10 uid 0 \\    cache\n")

    assert attacker.unbound_source(box) == "1.128.0.10"
    assert seen[0][:3] == ["sudo", "sh", "-c"] and "board.com" in seen[0][3]

def test_the_customers_run_as_their_own_account_that_the_origin_rewrite_passes_by(on_openstack):
    from range.ports import Ran
    seen = []

    def box(argv, stdin=None, timeout=60.0):
        seen.append((argv, stdin))
        return Ran(0, "fsl.customers=started\n")

    attacker.place_customers(box, "print()")
    assert attacker.run_customers(box, "{}") is True
    placed, ran = seen[0][0][3], seen[1][0][3]

    assert "-m owner --uid-owner fsl-users -j RETURN" in placed and "-I POSTROUTING 1" in placed
    assert seen[0][1] == "print()" and seen[1][1] == "{}"
    assert "setpriv --reuid=fsl-users" in ran and "setsid" in ran

def test_the_attackers_own_rewrite_stays_after_the_customers_exemption():
    setup = (REPO / "deploy/kali/setup.sh").read_text()

    assert "iptables -t nat -C POSTROUTING -o \"$dev\" -j FSL-ORIGIN 2>/dev/null \\\n  || iptables -t nat -A POSTROUTING" \
        in setup, "fsl-origin appends its jump, so an exemption inserted first is passed before the rewrite"

def test_records_are_cut_out_of_whatever_else_the_box_said():
    from range.ports import Ran

    def box(argv, stdin=None, timeout=60.0):
        return Ran(0, 'fsl.records=\n{"marker":"a"}\n{"mar\n=fsl.records\nsudo: unable to resolve host\n')

    assert attacker.customer_records(box, 0, 100) == '{"marker":"a"}\n{"mar'

@pytest.mark.stands_in_for_docker
def test_on_docker_the_customers_get_a_container_of_their_own_on_their_origins(tmp_path, monkeypatch):
    import stat
    from range import declared, docker
    log = tmp_path / "docker.log"
    stand_in = tmp_path / "docker"
    stand_in.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'case "$1" in\n'
        '  network) [ "$2" = ls ] && { seg="${4##*=}"; echo "fsl_edge-$seg fsl $seg"; }; exit 0;;\n'
        '  exec) shift; [ "$1" = -i ] && shift; shift; exec "$@";;\n'
        "esac\nexit 0\n"
    )
    stand_in.chmod(stand_in.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

    box = docker.Docker(declared=declared.read(), project="fsl", session=7).users_box(["us", "hk"], "fsl-kali:dev")
    ran = box(["echo", "inside"])
    said = log.read_text().splitlines()

    assert ran.output.strip() == "inside"
    started = next(line for line in said if line.startswith("run "))
    assert "--name fsl-7-users" in started and "--network fsl_edge-us" in started
    assert "--label fsl.customers=7" in started and started.endswith("fsl-kali:dev infinity")
    assert "network connect fsl_edge-hk fsl-7-users" in said
    assert any(line.startswith("exec fsl-7-users ") for line in said)

def _program():
    spec = importlib.util.spec_from_file_location("customers_program", REPO / "deploy/traffic/users.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Board(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def _answer(self, status, page=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _cookies(self):
        return dict(part.strip().split("=", 1) for part in (self.headers.get("Cookie") or "").split(";") if "=" in part)

    def _form(self):
        return parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())

    def _note(self):
        noted = {"marker": self.headers.get("X-FSL-Case"), "path": self.path, "method": self.command,
                 "cookies": self._cookies(), "source": self.client_address[0],
                 "host": self.headers.get("Host"), "referer": self.headers.get("Referer")}
        Board.seen.append(noted)
        return noted

    def do_GET(self):
        self._note()
        if "%3Cb%3E" in self.path:
            return self._answer(403, b"<html><center>nginx</center></html>")
        token = b'<input type="hidden" name="csrfmiddlewaretoken" value="F1">'
        self._answer(200, token, [("Set-Cookie", "csrftoken=T1; Path=/")])

    def do_POST(self):
        noted = self._note()
        form = self._form()
        if self._cookies().get("csrftoken") != "T1" or form.get("csrfmiddlewaretoken") != ["F1"]:
            return self._answer(403, b"<h1>Forbidden</h1><p>CSRF verification failed. Request aborted.</p>")
        if form.get("body") == ["stale"]:
            return self._answer(403, KOREAN_CSRF_PAGE)
        noted["form"] = form
        if self.path == "/accounts/login/":
            return self._answer(302, headers=[("Location", "/"), ("Set-Cookie", "sessionid=S1; Path=/")])
        return self._answer(302, headers=[("Location", self.path.removesuffix("comments/"))])

KOREAN_CSRF_PAGE = (
    '<div id="summary"><h1>Forbidden <span>(403)</span></h1>'
    "<p>CSRF \uac80\uc99d\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.</p></div>"
).encode()

@pytest.fixture
def board():
    Board.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Board)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()

def _run(tmp_path, plan, until):
    program = _program()
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    customers = program.Customers(str(tmp_path / "plan.json"), str(tmp_path / "records.jsonl"))
    worker = threading.Thread(target=customers.run, daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not until():
        time.sleep(0.05)
    (tmp_path / "plan.json").unlink()
    worker.join(5)
    for staff in customers.workers:
        staff.join(5)
    found, _, garbled = traffic.records((tmp_path / "records.jsonl").read_text())
    assert garbled == 0
    return found

def test_every_request_the_customers_send_carries_its_own_marker_and_is_recorded(tmp_path, board):
    member = {"id": "u01", "origin": "kr", "bind": "127.0.0.1", "target": board, "agent": "Mozilla/5.0",
              "language": "ko-KR", "account": {"username": "jiwoo", "password": "jiwoo1234"}}
    reader = dict(member, id="u02", account=None)
    rng = random.Random("1")
    flows = [
        {"user": 0, "action": "comment",
         "steps": traffic.steps(mix(), "login", member, rng) + traffic.steps(mix(), "comment", member, rng)},
        {"user": 1, "action": "search-unusual", "steps": [
            {"step": "search", "method": "GET", "path": "/search/?q=%3Cb%3Ex%3C%2Fb%3E"}]},
        {"user": 1, "action": "home", "steps": traffic.steps(mix(), "home", reader, rng)},
    ]
    plan = {"host": "board.com", "rate": 50, "profile": "community", "users": [member, reader], "flows": flows}

    records = _run(tmp_path, plan, lambda: any(r["path"].endswith("/comments/") for r in Board.seen))
    by_marker = {record["marker"]: record for record in records}
    seen = [dict(request, record=by_marker.get(request["marker"])) for request in Board.seen]

    assert len({request["marker"] for request in seen}) == len(seen), "a marker was reused"
    assert set(by_marker) == {request["marker"] for request in seen}, (
        "a request the board saw is not in the records, or a record was never sent"
    )
    signed_in = [r for r in seen if r["method"] == "POST" and r["path"] == "/accounts/login/"]
    commented = [r for r in seen if r["method"] == "POST" and r["path"].endswith("/comments/")]
    assert signed_in and all(r["form"]["username"] == ["jiwoo"] and r["referer"] for r in signed_in), (
        "the sign-in form was refused for its CSRF token"
    )
    assert commented and all(r["cookies"].get("sessionid") == "S1" and r["form"]["body"] for r in commented), (
        "a comment was refused or not sent signed in"
    )
    assert all(r["record"]["status"] == 302 for r in signed_in + commented)
    assert any(r["record"]["step"] == "redirect" and r["path"] == "/" for r in seen)
    blocked = [r["record"] for r in seen if r["record"]["action"] == "search-unusual"]
    assert blocked and {(r["status"], r["refused_by"]) for r in blocked} == {(403, "")}
    assert all(r["host"] == "board.com" and r["source"] == "127.0.0.1" for r in seen)
    assert {record["source_ip"] for record in records} == {"127.0.0.1"}

def test_a_form_whose_page_carried_no_token_is_not_posted(tmp_path, board):
    persona = {"id": "u01", "origin": "kr", "bind": "", "target": board, "agent": "Mozilla/5.0",
               "language": "ko-KR", "account": None}
    flows = [{"user": 0, "action": "comment", "steps": [
        {"step": "post", "method": "GET", "path": "/search/?q=%3Cb%3E"},
        {"step": "comment", "method": "POST", "path": "/posts/1/comments/", "csrf": True, "form": {"body": "x"}},
    ]}]
    plan = {"host": "board.com", "rate": 50, "profile": "community", "users": [persona], "flows": flows}

    records = _run(tmp_path, plan, lambda: len(Board.seen) >= 4)

    assert {request["method"] for request in Board.seen} == {"GET"}
    assert records and all(record["method"] == "GET" for record in records)

def test_the_board_s_csrf_refusal_in_the_customer_s_language_is_the_app_s_not_the_defence_s(tmp_path, board):
    persona = {"id": "u01", "origin": "kr", "bind": "", "target": board, "agent": "Mozilla/5.0",
               "language": "ko-KR", "account": None}
    flows = [{"user": 0, "action": "comment", "steps": [
        {"step": "post", "method": "GET", "path": "/posts/1/"},
        {"step": "comment", "method": "POST", "path": "/posts/1/comments/", "csrf": True, "form": {"body": "stale"}},
    ]}]
    plan = {"host": "board.com", "rate": 50, "profile": "community", "users": [persona], "flows": flows}

    records = _run(tmp_path, plan, lambda: any(r["method"] == "POST" for r in Board.seen))

    refused = [record for record in records if record["method"] == "POST"]
    assert refused and {(record["status"], record["refused_by"]) for record in refused} == {(403, "app")}
