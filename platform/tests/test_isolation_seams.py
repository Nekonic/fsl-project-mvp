import re
from pathlib import Path

import pytest

from range import declared

PLATFORM = Path(__file__).resolve().parents[1]
SCANNED = {".py", ".sh", ".conf", ".yaml", ".html"}
NOT_CODE = re.compile(r"^(tests|api/migrations|console/static)/|^console/templates/console/strings\.html$")

SEAMS = {
    "Elasticsearch": (
        {"ingest/elastic.py"}, {"register_pipeline.py"},
        r"/_search\b|/_bulk\b|/_ingest/|/_pit\b|/_count\b|^\s*(?:import|from) elasticsearch"),
    "the Suricata process": (
        {"rules/suricata.py"}, set(),
        r'"suricata", "-T"|suricatasc|reload-rules|"return":"OK"|af-packet'),
    "the CRS and ModSecurity configuration and the nginx reload": (
        {"rules/crs.py"}, set(),
        r"nginx -s reload|REQUEST-9\d\d|modsecurity\.conf|SecRule|/etc/nginx/modsecurity|audit\.log"),
    "the Kibana API": (
        {"kibana.py"}, {"nginx.conf", "console/templates/console/blue.html"},
        r"/api/saved_objects|kbn-xsrf|/api/spaces|/api/data_views|/api/index_patterns"),
    "the attacker box": (
        {"attacker.py"}, {"operator_log.py", "entrypoint.sh"},
        r"/usr/local/sbin/set-origin|/var/lib/session/|ORIGIN-SNAT"),
    "the OpenStack API": (
        {"range/openstack.py"}, set(),
        r"/v2\.0/|/servers/detail|/v3/auth/tokens|os-keypairs|\{heat\}/stacks"),
    "the target's ground truth": (
        {"api/loot.py", "api/effect.py"}, set(),
        r'\["secret"\]\["read_path"\]|binlog'),
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
    shape = declared.read()
    sensing = [shape.roles[role] for role in ("sensor", *shape.watches) if role in shape.roles]

    assert sensing and not [host for host in sensing if not (shape.hosts[host].rules and shape.hosts[host].reload)]
