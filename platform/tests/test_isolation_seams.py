import re
from pathlib import Path

import pytest

from range import declaration

PLATFORM = Path(__file__).resolve().parents[1]
SCANNED = {".py", ".sh", ".conf", ".yaml", ".html"}
NOT_CODE = re.compile(r"^(tests|testing)/")

SEAMS = {
    "Elasticsearch": (
        {"ingest/elastic.py"}, set(),
        r"/_search\b|\"_search\?|_delete_by_query\b|/_bulk\b|/_ingest/|/_pit\b|/_count\b|^\s*(?:import|from) elasticsearch"),
    "the Suricata process": (
        {"rules/suricata.py"}, set(),
        r'"suricata", "-T"|suricatasc|reload-rules|"return":"OK"|af-packet'),
    "the CRS and ModSecurity configuration and the nginx reload": (
        {"rules/crs.py"}, {"cr/config.py"},
        r"nginx -s reload|REQUEST-9\d\d|modsecurity\.conf|SecRule|/etc/nginx/modsecurity|audit\.log"),
    "the Kibana API": (
        {"defence/kibana.py"}, {"nginx.conf"},
        r"/api/saved_objects|kbn-xsrf|/api/spaces|/api/data_views|/api/index_patterns"),
    "the attacker box": (
        {"attack/box.py"}, {"cr/config.py", "entrypoint.sh"},
        r"/usr/local/sbin/set-origin|/var/lib/session/|ORIGIN-SNAT"),
    "the platform jump host and the box accounts' keys": (
        {"range/jump.py"}, {"entrypoint.sh"},
        r"\bauthorized_keys\b|cr-session-"),
    "the OpenStack API": (
        {"range/openstack.py"}, set(),
        r"/v2\.0/|/servers/detail|/v3/auth/tokens|os-keypairs|\{heat\}/stacks"),
    "the target's ground truth": (
        {"referee/loot.py", "referee/effect.py"}, set(),
        r'\bread_path\b|binlog'),
}


def scanned() -> dict[str, str]:
    return {
        str(path.relative_to(PLATFORM)): path.read_text(errors="ignore")
        for path in sorted(PLATFORM.rglob("*"))
        if path.is_file() and path.suffix in SCANNED and not NOT_CODE.search(str(path.relative_to(PLATFORM)))
    }


@pytest.mark.parametrize("seam", sorted(SEAMS))
def test_only_the_seam_s_own_files_and_the_listed_exceptions_know_it(seam):
    owners, exceptions, knows = SEAMS[seam]
    files = scanned()
    knowing = {name for name, text in files.items() if re.search(knows, text, re.M)}

    assert knowing <= owners | exceptions, (
        f"{sorted(knowing - owners - exceptions)} know {seam}; CLAUDE.md keeps that to "
        f"{sorted(owners)} and the exceptions it lists, {sorted(exceptions)}")
    assert {owner for owner in owners if owner in files} <= knowing, (
        f"the pattern for {seam} no longer finds its own file, so it guards nothing")


def test_every_sensor_names_the_rule_file_and_the_reload_rules_suricata_py_is_handed():
    shape = declaration.read()
    sensing = [shape.roles[role] for role in ("sensor", *shape.watches) if role in shape.roles]

    assert sensing and not [host for host in sensing if not (shape.hosts[host].rules and shape.hosts[host].reload)]
