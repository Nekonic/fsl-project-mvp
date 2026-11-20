import json
import pathlib
import re
import urllib.parse

import pytest
from django.conf import settings
from django.urls import Resolver404, resolve

from cr import config as config_module
from cr import errors
from match import views as match_views
from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONT = ROOT / "platform/nginx.conf"
ENTRYPOINT = ROOT / "platform/entrypoint.sh"
TERMINAL_PORTS = {"attack": "7691", "defence": "7692"}
TERMINAL_HOSTS = {"attack": "cr-kali", "defence": "cr-waf"}
TOKEN = re.compile(r"""\s+|#[^\n]*|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|[{};]|(?:\$\{\w+\}|[^\s{};'"])+""")


class Directive:
    def __init__(self, name, args, block=None):
        self.name, self.args, self.block = name, args, block

    def children(self, name, *args):
        return [one for one in self.block or () if one.name == name and tuple(one.args[:len(args)]) == args]

    def child(self, name, *args):
        [found] = self.children(name, *args)
        return found

    def values(self, name):
        return [one.args for one in self.children(name)]

    def text(self):
        return "\n".join(" ".join([one.name, *one.args]) for one in self.block or ())


def unquoted(word):
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"" else word


def parsed(text):
    words = [word for word in TOKEN.findall(text) if word.strip() and not word.startswith("#")]
    position = 0

    def block():
        nonlocal position
        held = []
        while position < len(words) and words[position] != "}":
            statement = []
            while words[position] not in ("{", ";", "}"):
                statement.append(unquoted(words[position]))
                position += 1
            assert statement, f"an empty statement before word {position}"
            if words[position] == "}":
                raise AssertionError(f"{statement[0]} ends without a semicolon")
            ender = words[position]
            position += 1
            if ender == "{":
                inner = block()
                assert position < len(words) and words[position] == "}", f"{statement[0]} block is never closed"
                position += 1
                held.append(Directive(statement[0], statement[1:], inner))
            else:
                held.append(Directive(statement[0], statement[1:]))
        return held

    top = block()
    assert position == len(words), f"a stray closing brace at word {position}"
    return Directive("main", [], top)


def config():
    return parsed(FRONT.read_text())


def http():
    return config().child("http")


def server(port):
    return next(one for one in http().children("server") if one.values("listen")[0][0] == port)


def console():
    return server("8000")


def site_listener():
    return server("8002")


def location(where, *args):
    return where.child("location", *args)


def regex_location(where, matching):
    found = [one for one in where.children("location", "~") + where.children("location", "~*")
             if pattern(one).match(matching)]
    assert found, f"no regex location takes {matching}"
    return found[0]


def pattern(found):
    flags = re.I if found.args[0] == "~*" else 0
    return re.compile(found.args[1].replace("(?<", "(?P<"), flags)


def django_route(path):
    try:
        return resolve(path).func.view_class.__name__
    except Resolver404:
        return None


def test_the_config_is_one_well_formed_nginx_file_with_the_two_listeners():
    whole = config()

    assert [one.name for one in whole.block] == ["worker_processes", "pid", "error_log", "events", "http"]
    assert sorted(one.values("listen")[0][0] for one in http().children("server")) == ["8000", "8002"]


def test_the_well_formedness_check_catches_a_missing_semicolon_and_an_unclosed_block():
    with pytest.raises(AssertionError):
        parsed("http { server { listen 8000 } }")
    with pytest.raises(AssertionError):
        parsed("http { server { listen 8000; }")


@pytest.mark.parametrize("side", ["attack", "defence"])
def test_each_seat_s_terminal_is_its_own_round_path_handed_to_its_ttyd_with_the_round_as_the_only_argument(side):
    found = regex_location(console(), f"/vm-terminal/{side}/12/")
    taken = pattern(found)

    for path in (f"/vm-terminal/{side}/12/", f"/vm-terminal/{side}/12/ws", f"/vm-terminal/{side}/12/token"):
        assert taken.match(path).group("terminal_round") == "12", path
    for path in (f"/vm-terminal/{side}/x/", f"/vm-terminal/{side}/12/../7/ws", f"/vm-terminal/{side}/12"):
        assert not taken.match(path), path
    assert found.values("proxy_pass") == [
        [f"http://127.0.0.1:{TERMINAL_PORTS[side]}/vm-terminal/{side}$terminal_rest?arg=$terminal_round"]]
    assert found.values("auth_request") == [["/seat-terminal"]]
    assert ["401", "=", "@sign-in"] in found.values("error_page")
    assert ["Upgrade", "$http_upgrade"] in found.values("proxy_set_header")


@pytest.mark.parametrize("side", ["attack", "defence"])
def test_the_entrypoint_starts_each_side_s_ttyd_where_nginx_hands_it_with_the_side_and_url_arguments(side):
    started = next(line for line in ENTRYPOINT.read_text().splitlines()
                   if "ttyd" in line and f"-p {TERMINAL_PORTS[side]} " in line)
    words = started.rstrip(" &").split()

    assert words[words.index("-b") + 1] == f"/vm-terminal/{side}"
    assert "-a" in words, "without -a ttyd drops the round nginx passes as ?arg="
    assert words[-3:] == ["/app/vm-terminal.sh", TERMINAL_HOSTS[side], side]
    assert words[words.index("-i") + 1] == "127.0.0.1"


def test_the_kali_shell_is_never_reachable_through_the_defence_path_or_the_waf_through_the_attack_path():
    attack = regex_location(console(), "/vm-terminal/attack/12/")
    defence = regex_location(console(), "/vm-terminal/defence/12/")

    assert TERMINAL_PORTS["defence"] not in attack.values("proxy_pass")[0][0]
    assert TERMINAL_PORTS["attack"] not in defence.values("proxy_pass")[0][0]
    assert location(console(), "/vm-terminal/").values("return") == [["404"]]


def test_the_terminal_check_asks_the_round_s_seat_route_for_the_side_in_the_path():
    seat = next(one for one in http().children("map") if one.args == ["$request_uri", "$terminal_seat"])
    [(given, value), (default, empty)] = [one.args and (one.name, one.args[0]) for one in seat.block]
    mapped = re.compile(given.removeprefix("~").replace("(?<", "(?P<")).match("/vm-terminal/defence/12/ws")
    asked = value.replace("$seat_round", mapped["seat_round"]).replace("$seat_side", mapped["seat_side"])
    check = location(console(), "=", "/seat-terminal")

    assert (default, empty) == ("default", "")
    assert check.values("internal") == [[]]
    assert check.values("proxy_pass") == [["http://127.0.0.1:8001/api/rounds/$terminal_seat/"]]
    assert django_route(f"/api/rounds/{asked}/") == "DefenceTerminalAuth"
    assert django_route("/api/rounds/12/terminal-auth/attack/") == "AttackTerminalAuth"
    assert "proxy_cache" not in check.text(), "a cached yes would outlive the seat's grant"
    assert check.child("if").values("return") == [["403"]], "a path naming no seat is refused, not checked"


def normalized_by_nginx(raw):
    path = re.sub(r"/+", "/", urllib.parse.unquote(raw.partition("?")[0]))
    kept = []
    for part in path.split("/")[1:]:
        if part == "..":
            kept.pop()
        elif part != ".":
            kept.append(part)
    return "/" + "/".join(kept)


def seat_nginx_checks(raw):
    seat = next(one for one in http().children("map") if one.args == ["$request_uri", "$terminal_seat"])
    [given, value] = seat.block[0].name, seat.block[0].args[0]
    mapped = re.compile(given.removeprefix("~").replace("(?<", "(?P<")).match(raw)
    if not mapped:
        return ""
    return value.replace("$seat_round", mapped["seat_round"]).replace("$seat_side", mapped["seat_side"])


def terminal_reached(raw):
    uri = normalized_by_nginx(raw)
    for side in TERMINAL_PORTS:
        found = regex_location(console(), f"/vm-terminal/{side}/12/")
        taken = pattern(found).match(uri)
        if not taken:
            continue
        [guard] = found.children("if")
        [compared, unequal, wanted, closing] = guard.args
        assert (compared, unequal, closing, guard.values("return")) == ("($terminal_seat", "!=", ")", [["404"]])
        if seat_nginx_checks(raw) != wanted.replace("$terminal_round", taken["terminal_round"]):
            return None
        return side, taken["terminal_round"]
    return None


@pytest.mark.parametrize("raw", [
    "/vm-terminal/defence/7/../../attack/5/ws", "/vm-terminal/attack/7/../5/ws", "/vm-terminal/attack/%35/ws",
    "/vm-terminal//attack/5/ws", "/vm-terminal/attack/7/./../5/token", "/vm-terminal/attack/7%2f..%2f5/ws",
])
def test_a_terminal_path_whose_raw_seat_differs_from_the_one_nginx_routes_on_is_refused_before_the_seat_check(raw):
    assert terminal_reached(raw) is None, f"{raw} would check one seat and open another round's shell"


@pytest.mark.parametrize("raw, reached", [
    ("/vm-terminal/attack/7/ws", ("attack", "7")), ("/vm-terminal/defence/7/?x=1", ("defence", "7")),
    ("/vm-terminal/attack/7/x/../ws", ("attack", "7")),
])
def test_a_terminal_path_reaches_the_seat_the_check_asked_about(raw, reached):
    assert terminal_reached(raw) == reached


def test_the_sign_in_checks_reach_the_api_s_own_session_check_and_cache_it_per_cookie_and_address():
    for listener in (console(), site_listener()):
        check = location(listener, "=", "/signed-in")
        [[target]] = check.values("proxy_pass")

        assert check.values("internal") == [[]]
        assert target.startswith("http://127.0.0.1:8001/") and django_route(target.removeprefix("http://127.0.0.1:8001"))
        assert check.values("proxy_cache_key") == [[f"$cookie_{settings.SESSION_COOKIE_NAME}|$remote_addr"]]
        assert check.values("proxy_cache") == [["signed_in"]]
        assert re.fullmatch(r"[1-9]s", check.values("proxy_cache_valid")[0][-1])
    assert "keys_zone=signed_in:1m" in " ".join(http().values("proxy_cache_path")[0])
    assert settings.SESSION_COOKIE_NAME == "cr_session"


def test_the_platform_sees_the_client_not_the_front():
    forwarded = re.findall(r"proxy_set_header\s+X-Forwarded-For\s+(\S+);", FRONT.read_text())

    assert forwarded and set(forwarded) == {"$remote_addr"}, (
        f"{forwarded}: appending keeps whatever the client claimed"
    )


def test_waitress_answers_the_front_alone_and_trusts_only_it():
    text = ENTRYPOINT.read_text()

    assert "--listen=127.0.0.1:8001" in text
    assert "--trusted-proxy=127.0.0.1" in text
    assert "--trusted-proxy-headers=x-forwarded-for" in text
    assert "--clear-untrusted-proxy-headers" in text


@pytest.mark.parametrize(("path", "zone"), [("/api/auth/login/", "sign_in"), ("/api/auth/signup/", "sign_up")])
def test_sign_in_and_sign_up_are_rate_limited_by_their_own_exact_locations(path, zone):
    exact = location(console(), "=", path)

    assert exact.values("limit_req")[0][0] == f"zone={zone}"
    assert django_route(path) is not None
    assert console().values("error_page") == [["429", "=", "@too-many"]]


def test_a_throttled_answer_has_the_api_s_one_error_shape_with_a_code_the_api_knows():
    [[status, body]] = location(console(), "@too-many").values("return")

    assert status == "429"
    assert re.fullmatch(r'\{"errors":\[\{"path":"","code":"(\w+)"\}\]\}', body)[1] in errors.CODES


def test_the_api_is_rate_limited_per_client_and_per_address():
    gateway = location(console(), "/api/")

    assert [one[0] for one in gateway.values("limit_req")] == ["zone=api_client", "zone=api_address"]
    assert gateway.values("proxy_pass") == [["http://127.0.0.1:8001"]]


def test_the_console_is_the_front_build_served_last_with_every_other_path_falling_back_to_its_index():
    last = console().block[-1]

    assert (last.name, last.args) == ("location", ["/"])
    assert last.values("root") == [["/app/front/dist"]]
    assert last.values("try_files") == [["$uri", "/index.html"]]
    assert "proxy_pass" not in last.text(), "Django serves the API, not the console"
    assets = location(console(), "/assets/")
    assert assets.values("root") == [["/app/front/dist"]]
    assert assets.values("try_files") == [["$uri", "=404"]]
    assert http().values("include")[0] == ["/etc/nginx/mime.types"]


@pytest.mark.parametrize("internal_route", ["/site-proxy/", "/kibana-gate/"])
def test_the_django_routes_only_nginx_may_call_are_refused_from_outside(internal_route):
    assert location(console(), internal_route).values("return") == [["404"]]


def test_the_site_pane_is_proxied_per_round_to_the_site_proxy_route_with_the_raw_rest_of_the_path():
    found = regex_location(site_listener(), "/site/12/board.com/posts/1/")
    taken = pattern(found).match("/site/12/board.com/posts/1/")
    site_tail = next(one for one in http().children("map") if one.args == ["$request_uri", "$site_uri"])
    tail = re.compile(site_tail.block[0].name.removeprefix("~").replace("(?<", "(?P<"))

    assert (taken["round"], taken["site"]) == ("12", "board.com")
    assert tail.match("/site/12/board.com/posts/1/?q=%27a")["site_tail"] == "/posts/1/?q=%27a"
    assert found.values("proxy_pass") == [["http://127.0.0.1:8001/site-proxy/$round/$site$site_uri"]]
    assert django_route("/site-proxy/12/board.com/posts/1/") == "SiteProxy"
    assert django_route("/site-proxy/12/board.com/") == "SiteProxy"
    assert found.values("auth_request") == [["/signed-in"]]
    assert ["401", "=", "@sign-in"] in found.values("error_page")


def test_the_site_pane_hands_django_only_the_session_cookie_and_keeps_none_of_the_target_s():
    found = regex_location(site_listener(), "/site/12/board.com/")

    assert ["Cookie", "cr_session=$cookie_cr_session"] in found.values("proxy_set_header")
    assert ["Set-Cookie"] in found.values("proxy_hide_header")
    assert any(args[0] == "Content-Security-Policy" and args[1].startswith("sandbox ")
               for args in found.values("add_header"))
    assert "Access-Control" not in FRONT.read_text()
    assert "$session" not in found.text()


def test_the_site_listener_answers_nothing_else():
    assert location(site_listener(), "/").values("return") == [["404"]]


def test_the_site_listener_sends_a_signed_out_learner_to_the_console_s_sign_in_with_the_site_address_to_come_back_to():
    assert location(site_listener(), "@sign-in").values("return") == [
        ["302", "$console_origin/login/?next=$site_origin$request_uri"]]
    assert location(console(), "@sign-in").values("return") == [["302", "/login/?next=$request_uri"]]
    assert "/tmp/nginx-origins.conf" in [args[0] for args in http().values("include")]
    assert "8000" not in location(site_listener(), "@sign-in").text()


def test_the_entrypoint_renders_the_configured_origins_before_nginx_checks_its_config():
    lines = ENTRYPOINT.read_text().splitlines()
    rendered = lines.index("python -m cr.config > /tmp/nginx-origins.conf")

    assert rendered < next(number for number, line in enumerate(lines) if line.startswith("nginx -t"))


def origin_maps(environ):
    text = config_module.nginx_origins(config_module.origins(environ))
    return {one.args[1]: one.block[0].args[0] for one in parsed(text).children("map")}


def test_unset_origins_keep_the_console_on_8000_and_the_site_on_8002_of_the_host_asked_over_http():
    assert origin_maps({}) == {"$console_origin": "http://$host:8000", "$site_origin": "http://$host:8002"}
    assert config_module.origins({}).site_for("range.example") == "http://range.example:8002"


def test_configured_origins_replace_both_for_a_tls_proxy_or_a_domain():
    environ = {"CR_CONSOLE_ORIGIN": "https://cr.example/", "CR_SITE_ORIGIN": "https://site.cr.example:8443"}

    assert origin_maps(environ) == {"$console_origin": "https://cr.example",
                                    "$site_origin": "https://site.cr.example:8443"}
    assert config_module.origins(environ).site_for("ignored") == "https://site.cr.example:8443"


@pytest.mark.parametrize("given", ["cr.example", "https://cr.example/login", "ftp://cr.example", 'https://a"; }',
                                   "https://cr.example?x=1"])
def test_an_origin_that_is_not_a_scheme_host_and_port_stops_the_start(given):
    with pytest.raises(ValueError):
        config_module.origins({"CR_SITE_ORIGIN": given})


DISCOVER_CALLS = (
    "/kibana/s/soc-logs-1/internal/security/me",
    "/kibana/s/soc-logs-1/api/core/capabilities",
    "/kibana/s/soc-logs-1/internal/data_views/fields",
    "/kibana/s/soc-logs-1/internal/search/ese",
    "/kibana/s/soc-logs-1/internal/kibana/settings",
    "/kibana/s/soc-logs-1/api/content_management/rpc/get",
)
NOT_DISCOVER = (
    "/kibana/s/soc-logs-1/api/console/proxy", "/kibana/s/soc-logs-1/internal/bsearch",
    "/kibana/s/soc-logs-1/api/saved_objects/_import", "/kibana/s/soc-logs-1/internal/search/esql",
    "/kibana/s/soc-logs-2/api/data_views/data_view", "/kibana/s/soc-logs-1/API/console/proxy",
    "/kibana/S/soc-logs-1/internal/search/es",
)
KIBANA_PAGES = (
    "/kibana/s/soc-logs-1/app/discover", "/kibana/s/soc-logs-1/bootstrap.js", "/kibana/s/soc-logs-1/",
    "/kibana/8aa0b59da12c/bundles/plugin/discover/8.15.0/discover.plugin.js", "/kibana/v8.15.0.json",
)


def kibana_location(first_group):
    found = next(one for one in console().children("location", "~") + console().children("location", "~*")
                 if one.args[1].startswith(f"^/kibana/{first_group}"))
    return pattern(found), found


def test_every_kibana_api_call_in_a_space_goes_through_the_platform_s_gate_and_pages_do_not():
    gated, block = kibana_location("s/[^/]+/(?:api|internal)")
    for path in DISCOVER_CALLS + NOT_DISCOVER:
        assert gated.match(path), f"{path} would reach Kibana without the platform's check of its index"
    for path in KIBANA_PAGES:
        assert not gated.match(path), f"{path} is a page or a bundle, which reads no index"
    assert block.values("set") == [["$kibana_gate", "http://127.0.0.1:8001/kibana-gate/"]]
    assert block.values("proxy_pass") == [["$kibana_gate"]]
    assert ["X-Kibana-Uri", "$request_uri"] in block.values("proxy_set_header")
    assert django_route("/kibana-gate/") == "KibanaGate"


def test_the_default_space_and_a_space_inside_a_space_are_refused_by_the_gate():
    default_space, block = kibana_location("(?:(?:app|spaces|api|internal)")
    for path in (
        "/kibana/app/discover", "/kibana/app", "/kibana/spaces/space_selector",
        "/kibana/api/saved_objects/_find", "/kibana/internal/kibana/settings", "/kibana/API/console/proxy",
        "/kibana/s/default/app/discover", "/kibana/s/default/spaces/space_selector",
        "/kibana/s/default/api/saved_objects/_find", "/kibana/s/default",
        "/kibana/s/soc-logs-1/s/soc-logs-2/internal/search/ese",
    ):
        assert default_space.match(path), f"{path} opens the Default space, which has every feature on"
    assert not default_space.match("/kibana/s/soc-logs-1/app/discover")
    for path in DISCOVER_CALLS:
        assert not default_space.match(path), f"{path} is a call Discover makes in a learner space"
    assert block.values("return") == [["403"]]
    assert block.values("error_page") == [["403", "=", "@kibana-gate"]], (
        "nginx's own 403 page is English; the gate answers the refusal in Korean")


def test_a_kibana_path_that_hides_a_dot_segment_or_an_escape_is_refused_before_kibana_decodes_it():
    pages = location(console(), "/kibana/")
    guard = next(one for one in pages.children("if") if one.args[0] == "($request_uri")
    refused = re.compile(guard.args[2])
    for uri in ("/kibana/s/soc-logs-1/app/%2e%2e/internal/search/es", "/kibana/s/soc-logs-1/app/../internal/search",
                "/kibana/s/soc-logs-1/app/discover/..%2finternal", "/kibana/s/soc-logs-1/app\\..\\internal"):
        assert refused.search(uri), uri
    for uri in KIBANA_PAGES + ("/kibana/s/soc-logs-1/app/discover?_g=(time:(from:'2026-11-16T07:49:59%2B00:00'))",):
        assert not refused.search(uri), uri
    assert guard.values("return") == [["403"]]
    assert any(one.args[:2] == ["($args", "~*"] and "namespaces=" in one.args[2] for one in pages.children("if"))


def test_kibana_pages_ask_for_a_signed_in_session_and_refusals_go_to_the_gate():
    pages = location(console(), "/kibana/")

    assert pages.values("auth_request") == [["/signed-in"]]
    assert ["401", "=", "@sign-in"] in pages.values("error_page")
    assert ["403", "=", "@kibana-gate"] in pages.values("error_page")
    assert pages.values("set") == [["$kibana", "http://kibana:5601"]]


def test_the_space_switcher_lists_only_the_current_space_and_a_lookup_across_spaces_is_refused():
    listing, block = kibana_location("s/(?<kibana_current>")
    assert listing.match("/kibana/s/soc-logs-1/api/spaces/space").group("kibana_current") == "soc-logs-1"
    assert not listing.match("/kibana/s/soc-logs-1/api/spaces/space/soc-logs-2")
    assert "$request_method != GET" in " ".join(block.child("if").args)
    assert '"name":"SOC"' in block.values("return")[0][1]
    assert block.values("error_page") == [["403", "=", "@kibana-gate"]]
    gate = location(console(), "@kibana-gate")
    assert gate.values("proxy_pass") == [["$kibana_gate"]]
    assert ["X-Kibana-Uri", "$request_uri"] in gate.values("proxy_set_header")


def test_the_pages_that_open_administration_send_the_learner_back_to_discover():
    pages, block = kibana_location("(?<kibana_space>")

    for path in ("/kibana/s/soc-logs-1/app/management/data/index_management", "/kibana/s/soc-logs-1/app/home",
                 "/kibana/s/soc-logs-1/app/dev_tools", "/kibana/s/soc-logs-1/app/observability/overview",
                 "/kibana/s/soc-logs-1/app/security", "/kibana/s/soc-logs-1/app/kibana_overview"):
        assert pages.match(path).group("kibana_space") == "s/soc-logs-1/", path
    assert not pages.match("/kibana/s/soc-logs-1/app/discover")
    assert block.values("absolute_redirect") == [["off"]]
    assert block.values("return") == [["302", "/kibana/${kibana_space}app/discover"]]


def test_kibana_is_published_on_the_platform_host_s_loopback_only_for_the_operator():
    ports = composed.services()["kibana"].get("ports")

    assert ports == ["127.0.0.1:5601:5601"], (
        "the learner-facing /kibana/ refuses administration; an operator reaches Kibana whole through an ssh tunnel"
    )


def test_the_old_session_paths_are_gone():
    text = FRONT.read_text()

    for old in ("/vm-terminal/kali/", "/vm-terminal/waf/", "/auth-check/", "/kibana-refused/", "/static/map/",
                "$session_asked"):
        assert old not in text, old


AUTH_PASSES = {401, 403}


def auth_request_answer(status):
    if 200 <= status < 300:
        return 0
    return status if status in AUTH_PASSES else 500


def refused_terminal(refusal):
    refused = location(console(), "@terminal-refused")
    for guard in refused.children("if"):
        variable, operator, compared = guard.args
        assert (variable, operator) == ("($terminal_refusal", "="), guard.args
        if compared.rstrip(")") == refusal:
            [answer] = guard.values("return")
            return int(answer[0]), json.loads(answer[1])
    [answer] = refused.values("return")
    return int(answer[0]), json.loads(answer[1])


def browser_sees(side, status, refusal):
    found = regex_location(console(), f"/vm-terminal/{side}/12/ws")
    passed = auth_request_answer(status)
    pages = {code: one[-1] for one in found.values("error_page") for code in one[:-2]}
    if pages.get(str(passed)) == "@terminal-refused":
        return refused_terminal(refusal)
    return passed, None


@pytest.mark.parametrize("side", ["attack", "defence"])
def test_the_terminal_check_s_refusal_code_reaches_nginx_beside_its_status(side):
    found = regex_location(console(), f"/vm-terminal/{side}/12/ws")
    header = "$upstream_http_" + match_views.REFUSAL_HEADER.lower().replace("-", "_")

    assert found.values("auth_request_set") == [["$terminal_refusal", header]]
    assert ["429", "=", "@too-many"] in found.values("error_page"), (
        "an error_page in the location drops the server's, so the held_open limit keeps its answer")


@pytest.mark.parametrize("side", ["attack", "defence"])
@pytest.mark.parametrize("refusal", [errors.Conflict(code="round_closed"), errors.Conflict(code="round_not_started"),
                                     errors.NotFound(code="unknown_round"), errors.NotSeated()])
def test_a_refused_terminal_answers_the_api_s_status_and_error_shape_not_nginx_s_500(side, refusal):
    assert browser_sees(side, refusal.status, refusal.code) == (refusal.status, refusal.shown())


@pytest.mark.parametrize("side", ["attack", "defence"])
def test_a_terminal_check_that_answers_nothing_known_is_unavailable_and_a_sign_in_still_redirects(side):
    assert browser_sees(side, 502, "") == (503, errors.Unavailable().shown())
    found = regex_location(console(), f"/vm-terminal/{side}/12/ws")
    assert ["401", "=", "@sign-in"] in found.values("error_page")
