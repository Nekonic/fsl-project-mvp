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

def test_the_terminal_has_no_port_of_its_own():
    assert not composed.services()["kali"].get("ports"), (
        "everything a person uses is on the platform's one port"
    )

def test_the_terminal_is_handed_over_only_after_the_platform_agrees():
    terminal = location("/terminal/")

    assert "auth_request" in terminal, (
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
    found = re.search(rf"location ~ (\^/kibana/{re.escape(first_group)}\S*) \{{(.*?)\n        \}}", FRONT.read_text(), re.S)
    return re.compile(found[1].replace("(?<", "(?P<")), found[2]

DISCOVER_CALLS = (
    "/kibana/s/soc-logs-1/app/discover",
    "/kibana/s/soc-logs-1/internal/security/me",
    "/kibana/s/soc-logs-1/internal/security/session",
    "/kibana/s/soc-logs-1/internal/security/user_profile",
    "/kibana/s/soc-logs-1/internal/security/security_checkup/state",
    "/kibana/s/soc-logs-1/api/core/capabilities",
    "/kibana/s/soc-logs-1/api/licensing/info",
    "/kibana/s/soc-logs-1/internal/licensing/feature_usage/register",
    "/kibana/s/soc-logs-1/api/banners/info",
    "/kibana/s/soc-logs-1/api/saved_objects_tagging/tags",
    "/kibana/s/soc-logs-1/internal/spaces/_active_space",
    "/kibana/s/soc-logs-1/internal/telemetry/config",
    "/kibana/s/soc-logs-1/internal/data_views/has_data_views",
    "/kibana/s/soc-logs-1/internal/data_views/fields",
    "/kibana/s/soc-logs-1/internal/data_views/_fields_for_wildcard",
    "/kibana/s/soc-logs-1/internal/index-pattern-management/resolve_index/logs-*",
    "/kibana/s/soc-logs-1/api/content_management/rpc/search",
    "/kibana/s/soc-logs-1/api/content_management/rpc/get",
    "/kibana/s/soc-logs-1/api/content_management/rpc/mSearch",
    "/kibana/s/soc-logs-1/api/index_patterns/has_user_index_pattern",
    "/kibana/s/soc-logs-1/internal/saved_query/_count",
    "/kibana/s/soc-logs-1/internal/bsearch",
    "/kibana/s/soc-logs-1/api/ui_counters/_report",
    "/kibana/8aa0b59da12c/bundles/plugin/discover/8.15.0/discover.plugin.js",
    "/kibana/v8.15.0.json",
)

def test_the_learner_facing_kibana_refuses_what_is_not_discover_and_answers_what_discover_asks():
    refused, block = kibana_location("(?:s/")
    for path in DISCOVER_CALLS:
        assert not refused.match(path), f"{path} is a call Discover makes in a learner space"
    for path in (
        "/kibana/api/console/proxy", "/kibana/s/soc-logs-1/api/console/proxy",
        "/kibana/s/soc-logs-1/api/ingest_pipelines", "/kibana/api/index_management/indices",
        "/kibana/internal/index_management/indices", "/kibana/api/snapshot_restore/repositories",
        "/kibana/api/transform/transforms", "/kibana/api/license", "/kibana/api/upgrade_assistant/status",
        "/kibana/api/index_lifecycle_management/policies", "/kibana/api/spaces/space",
        "/kibana/s/soc-logs-1/api/spaces/space/soc-logs-1", "/kibana/s/soc-logs-1/internal/spaces/space/x/copy_to_space",
        "/kibana/api/saved_objects/_import", "/kibana/api/saved_objects/_export",
        "/kibana/s/soc-logs-1/api/data_views/data_view", "/kibana/api/kibana/settings",
        "/kibana/s/soc-logs-1/api/kibana/settings/defaultIndex", "/kibana/api/rollup/indices",
        "/kibana/api/index_patterns/index_pattern/logs", "/kibana/s/soc-logs-1/api/index_patterns/index_pattern/soc-logs-1",
    ):
        assert refused.match(path), f"{path} reaches Elasticsearch or Kibana administration"
    assert "return 403" in block

def test_the_default_space_is_refused_and_the_one_internal_settings_call_is_read_only():
    default_space, block = kibana_location("(?:(?:app|spaces|api|internal)")
    for path in (
        "/kibana/app/discover", "/kibana/app", "/kibana/spaces/space_selector",
        "/kibana/api/saved_objects/_find", "/kibana/internal/kibana/settings",
        "/kibana/s/default/app/discover", "/kibana/s/default/spaces/space_selector",
        "/kibana/s/default/api/saved_objects/_find", "/kibana/s/default",
    ):
        assert default_space.match(path), f"{path} opens the Default space, which has every feature on"
    assert not default_space.match("/kibana/s/soc-logs-1/app/discover")
    for path in DISCOVER_CALLS:
        assert not default_space.match(path), f"{path} is a call Discover makes in a learner space"
    assert "return 403" in block

    settings, block = kibana_location("s/[^/]+/internal/kibana/settings")
    assert settings.match("/kibana/s/soc-logs-1/internal/kibana/settings")
    assert not settings.match("/kibana/internal/kibana/settings")
    assert "limit_except GET" in block and "deny all" in block, "the UI writes advanced settings through this route"


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
