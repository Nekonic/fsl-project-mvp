import pathlib
import re

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONT = ROOT / "platform/nginx.conf"
ENTRYPOINT = ROOT / "platform/entrypoint.sh"

def location(path):
    text = FRONT.read_text()
    start = text.index(f"location {path} {{")
    return text[start:text.index("}", start)]

def test_the_terminal_is_handed_over_only_after_the_platform_agrees():
    for terminal in (location("/vm-terminal/kali/"), location("/vm-terminal/waf/")):
        assert "auth_request /signed-in;" in terminal, (
            "the terminal path would skip the platform's refusal of range addresses"
        )

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

def kibana_location(first_group):
    found = re.search(rf"location ~(\*?) (\^/kibana/{re.escape(first_group)}\S*) \{{(.*?)\n        \}}",
                      FRONT.read_text(), re.S)
    return re.compile(found[2].replace("(?<", "(?P<"), re.I if found[1] else 0), found[3]

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

def test_every_kibana_api_call_in_a_space_goes_through_the_platform_s_gate_and_pages_do_not():
    gated, block = kibana_location("s/[^/]+/(?:api|internal)")
    for path in DISCOVER_CALLS + NOT_DISCOVER:
        assert gated.match(path), f"{path} would reach Kibana without the platform's check of its index"
    for path in KIBANA_PAGES:
        assert not gated.match(path), f"{path} is a page or a bundle, which reads no index"
    assert "set $kibana_gate http://127.0.0.1:8001/kibana-gate/;" in block and "proxy_pass $kibana_gate;" in block
    assert "proxy_set_header X-Kibana-Uri $request_uri;" in block, "the gate checks the URI exactly as Kibana gets it"
    assert "kibana:5601" not in block and "return 404;" in location("/kibana-gate/")

def test_the_default_space_and_a_space_inside_a_space_are_refused():
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
    assert "return 403" in block

def test_a_kibana_path_that_hides_a_dot_segment_or_an_escape_is_refused_before_kibana_decodes_it():
    pages = block_after("location /kibana/ {")
    guard = re.search(r'if \(\$request_uri ~ "(.*?)"\) \{\s+return 403;', pages)
    assert guard
    refused = re.compile(guard[1])
    for uri in ("/kibana/s/soc-logs-1/app/%2e%2e/internal/search/es", "/kibana/s/soc-logs-1/app/../internal/search",
                "/kibana/s/soc-logs-1/app/discover/..%2finternal", "/kibana/s/soc-logs-1/app\\..\\internal"):
        assert refused.search(uri), uri
    for uri in KIBANA_PAGES + ("/kibana/s/soc-logs-1/app/discover?_g=(time:(from:'2026-11-16T07:49:59%2B00:00'))",):
        assert not refused.search(uri), uri

def test_the_space_switcher_lists_only_the_current_space_and_a_lookup_across_spaces_is_refused():
    listing, block = kibana_location("s/(?<kibana_current>")
    assert listing.match("/kibana/s/soc-logs-1/api/spaces/space").group("kibana_current") == "soc-logs-1"
    assert not listing.match("/kibana/s/soc-logs-1/api/spaces/space/soc-logs-2")
    assert "$request_method != GET" in block and '"name":"SOC"' in block

    text = FRONT.read_text()
    assert re.search(r'location /kibana/ \{\s+if \(\$args ~\* "\(\^\|&\)namespaces="\) \{\s+return 403;', text)


def test_the_pages_that_open_administration_send_the_learner_back_to_discover():
    pages, block = kibana_location("(?<kibana_space>")

    for path in ("/kibana/s/soc-logs-1/app/management/data/index_management", "/kibana/s/soc-logs-1/app/home",
                 "/kibana/s/soc-logs-1/app/dev_tools", "/kibana/s/soc-logs-1/app/observability/overview",
                 "/kibana/s/soc-logs-1/app/security", "/kibana/s/soc-logs-1/app/kibana_overview"):
        assert pages.match(path).group("kibana_space") == "s/soc-logs-1/", path
    assert not pages.match("/kibana/s/soc-logs-1/app/discover")
    assert "absolute_redirect off" in block and "return 302 /kibana/${kibana_space}app/discover" in block

def test_kibana_is_published_on_the_platform_host_s_loopback_only_for_the_operator():
    ports = composed.services()["kibana"].get("ports")

    assert ports == ["127.0.0.1:5601:5601"], (
        "the learner-facing /kibana/ refuses administration; an operator reaches Kibana whole through an ssh tunnel"
    )

def block_after(marker):
    return FRONT.read_text().split(marker, 1)[1].split("\n        }", 1)[0]

SITE = "(?<site>[a-z0-9.-]+)(/.*)?$ {"

def test_every_web_surface_beside_the_console_asks_the_platform_for_a_signed_in_session_first():
    gated = {
        "the Kali terminal": location("/vm-terminal/kali/"),
        "the WAF terminal": location("/vm-terminal/waf/"),
        "Kibana": block_after("location /kibana/ {"),
        "the site port": block_after(SITE),
    }

    for name, block in gated.items():
        assert "auth_request /signed-in;" in block, f"{name} skips the sign-in"
        assert "error_page 401 = @sign-in;" in block, f"{name} shows a bare 401 instead of the login page"

def test_the_front_s_checks_reach_the_platform_s_session_check_and_the_world_does_not():
    text = FRONT.read_text()
    checks = re.findall(r"location = /signed-in \{(.*?)\}", text, re.S)

    assert len(checks) == 2
    assert all("internal;" in check and "proxy_pass http://127.0.0.1:8001/auth-check/" in check for check in checks)
    assert "return 404;" in location("/auth-check/")
    assert "/api/attacker/" not in text

def test_the_front_keeps_the_session_check_s_answer_per_cookie_address_and_session_asked():
    text = FRONT.read_text()
    checks = re.findall(r"location = /signed-in \{(.*?)\}", text, re.S)

    assert "keys_zone=signed_in:" in text
    for check in checks:
        assert "proxy_cache signed_in;" in check
        assert 'proxy_cache_key "$cookie_cr_session|$remote_addr|$session_asked";' in check, (
            "a key without the address lets a cached yes skip the platform's refusal of range "
            "addresses; a key without the session lets one session's yes open another's"
        )
        assert "proxy_set_header X-Original-URI $request_uri;" in check
        assert re.search(r"proxy_cache_valid 204 401 [1-9]s;", check), (
            "Kibana's first load is over a hundred requests, each one a session check in Django"
        )

def test_the_site_port_forwards_none_of_the_console_s_cookies_and_keeps_none_of_the_target_s():
    site = block_after(SITE)

    assert 'proxy_set_header Cookie "";' in site
    assert "proxy_hide_header Set-Cookie;" in site
    assert "Access-Control" not in FRONT.read_text()
