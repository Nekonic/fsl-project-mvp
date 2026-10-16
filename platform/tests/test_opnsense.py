import base64
import pathlib
import xml.etree.ElementTree as ElementTree

import yaml

from range import cloud, declared, opnsense
from range.ports import Segment

ROOT = pathlib.Path(__file__).resolve().parents[2]
OS = declared.read(flavor="openstack")
INSIDE = cloud.read(cloud.EXAMPLE).inside
COLLECTOR = ("10.31.0.195", 5140)
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPlatformKey fsl-platform"


def _segments():
    return tuple(
        Segment(id=origin.id, name=origin.label, origin=origin.label, subnet=origin.subnet,
                gateway=origin.subnet.replace("0/24", "1"))
        for origin in OS.origins
    ) + (Segment(id="estate", name="Estate", subnet="10.30.0.0/24", gateway="10.30.0.1"),
         Segment(id="mgmt", name="Management", subnet="10.31.0.0/24"))


def _wanted(**changed):
    return {**opnsense.settings(_segments(), COLLECTOR, INSIDE, 1450, KEY), **changed}


def _rendered(**changed):
    template = (ROOT / opnsense.CONFIG).read_text()
    return ElementTree.fromstring(opnsense.render(template, _wanted(**changed)))


def test_the_configured_edge_holds_its_management_address_statically_not_by_dhcp():
    wanted = opnsense.settings(_segments(), COLLECTOR, INSIDE, 1450, KEY, management="10.31.0.230")
    root = ElementTree.fromstring(opnsense.render((ROOT / opnsense.CONFIG).read_text(), wanted))

    assert root.findtext("interfaces/opt1/ipaddr") == "10.31.0.230", (
        "OPNsense on this cloud dropped Neutron's DHCP replies after its reconfigure, "
        "so the platform lost the edge; the platform knows the address the port holds"
    )
    assert root.findtext("interfaces/opt1/subnet") == "24"


def test_the_configured_edge_keeps_time_by_the_platform_on_management_alone():
    wanted = opnsense.settings(_segments(), COLLECTOR, INSIDE, 1450, KEY, management="10.31.0.230",
                               clock="10.31.0.195")
    root = ElementTree.fromstring(opnsense.render((ROOT / opnsense.CONFIG).read_text(), wanted))

    assert root.findtext("system/timeservers") == "10.31.0.195", (
        "the range has no Internet; the edge's sensor stamps every alert by its own clock"
    )
    assert root.findtext("ntpd/iburst") == "10.31.0.195"
    assert root.findtext("ntpd/interface") == "opt1", (
        "ntpd answers on every address it listens on; bound to management, only the "
        "platform reaches it, past fsl-mgmt"
    )


def test_the_sensor_home_is_the_estate_and_management_so_every_origin_is_external():
    home = _wanted()["home"]

    assert home == [INSIDE["estate"], INSIDE["mgmt"]]
    assert not set(home) & {origin.subnet for origin in OS.origins}, (
        "OPNsense's suricata.yaml sets EXTERNAL_NET to !$HOME_NET, and the "
        "shipped rules match $EXTERNAL_NET -> $HOME_NET; an origin in HOME_NET "
        "would make every attack from it invisible"
    )


def test_every_interface_takes_the_tenant_mtu():
    root = _rendered()

    assert {root.findtext(f"interfaces/{name}/mtu") for name in ("wan", "lan", "opt1")} == {"1450"}


def test_root_trusts_only_the_platform_key_and_has_no_password():
    root = _rendered()
    [user] = [u for u in root.findall("system/user") if u.findtext("name") == "root"]

    assert base64.b64decode(user.findtext("authorizedkeys")).decode() == KEY
    assert user.findtext("password") == "*", (
        "the stock image's root password is public (opnsense); this image never has it"
    )
    assert user.findtext("shell") == "/bin/sh", "root's default shell is the console menu"
    assert root.find("system/ssh/passwordauth") is None


def test_the_edge_routes_without_nat_and_never_answers_the_range_itself():
    root = _rendered()
    rules = [(r.findtext("interface"), r.findtext("type"), r.findtext("destination/network"))
             for r in root.findall("filter/rule")]

    assert root.findtext("nat/outbound/mode") == "disabled"
    assert rules.index(("wan", "block", "(self)")) < rules.index(("wan", "pass", None))
    assert rules.index(("lan", "block", "(self)")) < rules.index(("lan", "pass", None))
    assert ("opt1", "pass", None) in rules


def test_from_the_internet_the_edge_passes_only_http_to_the_waf():
    root = _rendered(front="10.30.0.198")

    [crossing] = [r for r in root.findall("filter/rule")
                  if r.findtext("interface") == "wan" and r.findtext("type") == "pass"]
    assert crossing.findtext("protocol") == "tcp"
    assert crossing.findtext("destination/address") == "10.30.0.198"
    assert crossing.findtext("destination/port") == "80"
    assert crossing.find("destination/any") is None, (
        "a wan pass rule to any let Kali reach the wargame host's estate "
        "address on 8000 and 80 through the edge, past the WAF"
    )


def test_the_static_script_installs_the_rules_where_the_rules_editor_writes_them():
    script = (ROOT / opnsense.SCRIPT).read_text()
    include = yaml.safe_load((ROOT / opnsense.INCLUDE).read_text())
    edge = OS.hosts[OS.roles["sensor"]]

    assert f"{opnsense.STAGED['rules']} {edge.rules}" in script
    assert include["rule-files"] == [edge.rules]
    assert include["unix-command"]["filename"] in edge.reload.split(), (
        "suricatasc must talk to the socket the include opens"
    )
    assert "/conf/config.xml" in script and "shutdown -r now" in script


def test_the_sensor_sends_alerts_and_http_records_to_syslog_as_suricata():
    [output] = yaml.safe_load((ROOT / opnsense.INCLUDE).read_text())["outputs"]
    eve = output["eve-log"]
    kinds = [next(iter(kind)) for kind in eve["types"]]

    assert eve["filetype"] == "syslog" and eve["identity"] == "suricata", (
        "the collector decodes a syslog message as EVE JSON only when its "
        "app name is suricata (deploy/filebeat/filebeat.yml)"
    )
    assert kinds == ["alert", "http"]


def test_the_lines_the_edge_printed_are_read_back_and_a_stopped_sensor_or_empty_pf_is_not_done():
    printed = ("fsl-edge booted 1760000000\nfsl-edge wan 73.0.0.1 120.96.0.1 \n"
               "fsl-edge sensor vtnet0 running\nfsl-edge logs 10.31.0.195:5140\n"
               "fsl-edge wanrule 2\n")

    assert opnsense.booted(printed) == "1760000000"
    assert opnsense.held(printed) == {"73.0.0.1", "120.96.0.1"}
    assert opnsense.sensing(printed)
    assert "logs 10.31.0.195:5140" in opnsense.reported(printed)
    assert opnsense.wan_rule_loaded(printed)
    assert not opnsense.sensing("fsl-edge sensor vtnet0 stopped\n")
    assert not opnsense.wan_rule_loaded("fsl-edge wanrule 0\n")
    assert opnsense.held("sh: php: not found\n") == set()
    assert opnsense.booted("") == ""
