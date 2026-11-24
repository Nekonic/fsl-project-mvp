import re
from pathlib import Path

import pytest

from sandbox import definitions as declaration

REPO = Path(__file__).resolve().parents[3]
SCANNED_ROOTS = ("platform", "front/src", "bots", "test", "bin")
SCANNED_SUFFIXES = {".py", ".sh", ".conf", ".yaml", ".html", ".ts", ".tsx", ".js", ".md", ".json", ""}
NOT_SCANNED = re.compile(
    r"^platform/(?:tests|testing|jump)/|^front/src/api/schema\.d\.ts$"
    r"|(?:^|/)(?:\.[^/]+|__pycache__|node_modules)/|\.sqlite3$")

ELASTICSEARCH = "Elasticsearch"
SURICATA = "the Suricata process"
CAPTURE = "packet capture"
CRS = "the CRS and ModSecurity configuration and the nginx reload"
KIBANA = "the Kibana API"
INDEX_PATTERNS = "the log index patterns"
BOX = "the attacker box"
CUSTOMERS = "the customers' box"
NODE_NAMES = "the range's node names"
JUMP = "the platform jump host and the box accounts' keys"
EDGE = "the infra router's nftables sets"
OPENSTACK = "the OpenStack API"
GROUND_TRUTH = "the target's ground truth"
VPN = "WireGuard"

SEAMS = {
    ELASTICSEARCH: (
        {"platform/telemetry/elastic.py"},
        r"/_search\b|\"_search\?|_delete_by_query\b|/_bulk\b|/_ingest/|/_pit\b|/_count\b|/_nodes\b"
        r"|^\s*(?:import|from) elasticsearch"),
    SURICATA: (
        {"platform/sandbox/suricata.py"},
        r'"suricata", "-T"|suricata -T -[cS]\b|suricatasc|reload-rules|"return":"OK"|af-packet'),
    CAPTURE: (
        {"platform/sandbox/suricata.py"},
        r"\btcpdump\b|\bdumpcap\b|\btshark\b"),
    CRS: (
        {"platform/sandbox/crs.py"},
        r"nginx -s reload|REQUEST-9\d\d|modsecurity\.conf|SecRule|/etc/nginx/modsecurity|audit\.log"),
    KIBANA: (
        {"platform/sandbox/kibana.py"},
        r"/api/saved_objects|kbn-xsrf|/api/spaces|/api/data_views|/api/index_patterns|/kibana/(?:api|internal)\b"
        r"|discover:docExplorer\w*Closed|data\.noDataPopover"),
    INDEX_PATTERNS: (
        {"platform/sandbox/kibana.py"},
        r"\blogs-\*|\bfilebeat-\*|\bsuricata-\*|\bindex_patterns?\b"),
    BOX: (
        {"platform/sandbox/attacker.py"},
        r"/usr/local/sbin/set-(?:origin|peer)|/var/lib/session/|ORIGIN-SNAT"),
    CUSTOMERS: (
        {"platform/sandbox/customers.py"},
        r"cr-customers\.service|/var/lib/cr-users|--reuid=|setpriv\b"),
    NODE_NAMES: (
        set(),
        r"\bcr-(?:kali|waf|infra|target)\b"),
    JUMP: (
        {"platform/sandbox/access.py"},
        r"\bauthorized_keys\b|cr-session-"),
    EDGE: (
        {"platform/sandbox/edge.py"},
        r'\["nft"|\bnft (?:add|delete|flush|list|-f|-j)\b|\bconntrack\b'),
    OPENSTACK: (
        {"platform/sandbox/openstack.py"},
        r"/v2\.0/|/servers/detail|/v3/auth/tokens|os-keypairs|\{heat\}/stacks"),
    VPN: (
        {"platform/sandbox/vpn.py"},
        r"\bAllowedIPs\b|\bPersistentKeepalive\b|\bwg (?:genkey|pubkey|set|show)\b"
        r"|\bwireguard\b"),
    GROUND_TRUTH: (
        {"platform/scoring/loot.py", "platform/scoring/effect.py"},
        r"\bread_path\b|binlog|/internal/auth-users|\bwp_(?:usermeta|options|posts)\b|\bMYSQL_PWD\b"),
}

EXCEPTIONS = {
    "platform/cr/config.py": {CRS, NODE_NAMES, INDEX_PATTERNS},
    "platform/nginx.conf": {KIBANA},
    "platform/entrypoint.sh": {NODE_NAMES, JUMP},
    "front/src/panes/Kibana.tsx": {KIBANA},
    "test/plays.py": {CRS},
    "test/shared_sessions.py": {GROUND_TRUTH},
    "test/test_board_exfil.py": {GROUND_TRUTH},
    "test/test_event_time.py": {ELASTICSEARCH, INDEX_PATTERNS},
    "test/test_geoip_durable.py": {ELASTICSEARCH},
    "test/test_origin_placement.py": {ELASTICSEARCH},
    "test/test_waf_geolocation.py": {ELASTICSEARCH},
}
OUTSIDE_THE_SCAN = {"wargames/<id>/topology.yaml", "deploy/roles/infra/edge.nft"}
NOT_WRITTEN_YET: set[str] = set()

CLAUDE_MD = REPO / "CLAUDE.md"
EXCEPTION_PARAGRAPH = re.compile(r"Known exceptions in code today.*?(?=\n- |\n## )", re.S)
NAMED_FILE = re.compile(r"`([\w<>./-]+\.(?:py|sh|conf|yaml|nft|tsx|ts|js|html))`")
TOP_LEVELS = ("platform/", "front/", "bots/", "test/", "bin/", "deploy/", "wargames/", "docs/")


def is_scanned(name: str, path: Path) -> bool:
    return path.is_file() and path.suffix in SCANNED_SUFFIXES and not NOT_SCANNED.search(name)


def scanned() -> dict[str, str]:
    files = {}
    for root in SCANNED_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            name = str(path.relative_to(REPO))
            if is_scanned(name, path):
                files[name] = path.read_text(errors="ignore")
    return files


def knowing(files: dict[str, str], seam: str) -> set[str]:
    pattern = SEAMS[seam][1]
    return {name for name, text in files.items() if re.search(pattern, text, re.M)}


def owners() -> set[str]:
    return {owner for owned, _ in SEAMS.values() for owner in owned}


def repo_path(named: str) -> str:
    return named if named.startswith(TOP_LEVELS) else f"platform/{named}"


def named_in_claude_md() -> set[str]:
    paragraph = EXCEPTION_PARAGRAPH.search(CLAUDE_MD.read_text())
    assert paragraph, "CLAUDE.md has no 'Known exceptions in code today' paragraph to hold the list against"
    named = {repo_path(found) for found in NAMED_FILE.findall(paragraph.group(0))}
    return {name for name in named if not name.startswith("docs/")} - owners()


@pytest.fixture(scope="module")
def files():
    return scanned()


@pytest.mark.parametrize("seam", sorted(SEAMS))
def test_only_the_seam_s_own_files_and_the_listed_exceptions_know_it(files, seam):
    owned, _ = SEAMS[seam]
    allowed = {name for name, seams in EXCEPTIONS.items() if seam in seams}
    found = knowing(files, seam)

    assert found <= owned | allowed, (
        f"{sorted(found - owned - allowed)} know {seam}; CLAUDE.md keeps that to "
        f"{sorted(owned)} and the exceptions it lists, {sorted(allowed)}")
    assert owned <= found, f"the pattern for {seam} no longer finds {sorted(owned - found)}, so it guards nothing"


def test_every_exception_still_knows_exactly_what_it_is_allowed_to(files):
    stale = {name: sorted(seams - {seam for seam in SEAMS if name in knowing(files, seam)})
             for name, seams in EXCEPTIONS.items() if name in files}

    assert {name: gone for name, gone in stale.items() if gone} == {}


def test_every_listed_exception_exists_or_is_named_as_not_written_yet():
    present = {name for name in EXCEPTIONS if (REPO / name).is_file()}

    assert set(EXCEPTIONS) - present == NOT_WRITTEN_YET
    assert all(is_scanned(name, REPO / name) for name in present)
    assert (REPO / "deploy/roles/infra/edge.nft").is_file()
    assert list(REPO.glob("wargames/*/topology.yaml"))


def test_the_exception_list_is_the_one_claude_md_gives():
    assert named_in_claude_md() == set(EXCEPTIONS) | OUTSIDE_THE_SCAN


def test_the_suricata_pattern_finds_a_config_test_in_a_shell_string_as_well_as_in_an_argv_list():
    pattern = SEAMS[SURICATA][1]

    assert re.search(pattern, 'f"suricata -T -c {settings} -S {rules}"') and re.search(pattern, '["suricata", "-T"]')


def test_the_scan_reaches_every_client_and_skips_the_generated_types(files):
    reached = {name.split("/", 1)[0] if not name.startswith("front/") else "front/src" for name in files}

    assert {"platform", "bots", "test", "bin"} <= reached
    assert {f"platform/{unit}" for unit in ("users", "sandbox", "telemetry", "training", "scoring")} <= {
        "/".join(name.split("/")[:2]) for name in files}
    assert {"bots/prompts/attacker.md", "bots/prompts/defender.md", "bots/README.md"} <= set(files)
    assert "front/src/api/schema.d.ts" not in files


def test_every_sensor_names_the_rule_file_and_the_reload_rules_suricata_py_is_handed():
    shape = declaration.read()
    sensing = [shape.roles[role] for role in ("sensor", *shape.watches) if role in shape.roles]

    assert sensing and not [host for host in sensing if not (shape.hosts[host].rules and shape.hosts[host].reload)]
