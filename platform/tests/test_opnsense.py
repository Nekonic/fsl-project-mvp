import base64
import pathlib
import subprocess
import xml.etree.ElementTree as ElementTree
from dataclasses import replace

import pytest
import yaml

from range import cloud, declared, opnsense
from range.ports import RangeUnavailable, Segment

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


def test_the_wan_holds_the_first_origin_gateway_and_aliases_the_other_twenty_nine():
    wanted = _wanted()

    first = OS.origins[0]
    assert wanted["wan"] == {"id": first.id, "address": first.subnet.replace("0/24", "1"), "bits": "24"}
    assert [alias["id"] for alias in wanted["aliases"]] == [o.id for o in OS.origins[1:]]
    assert len(wanted["aliases"]) == 29


def test_the_configured_edge_holds_its_management_address_statically_not_by_dhcp():
    wanted = opnsense.settings(_segments(), COLLECTOR, INSIDE, 1450, KEY, management="10.31.0.230")
    root = ElementTree.fromstring(opnsense.render((ROOT / opnsense.CONFIG).read_text(), wanted))

    assert root.findtext("interfaces/opt1/ipaddr") == "10.31.0.230", (
        "OPNsense on this cloud dropped Neutron's DHCP replies after its reconfigure, "
        "so the platform lost the edge; the platform knows the address the port holds"
    )
    assert root.findtext("interfaces/opt1/subnet") == "24"


def test_the_lan_holds_the_estate_gateway_so_the_estate_routes_through_the_edge():
    assert _wanted()["lan"] == {"id": "estate", "address": "10.30.0.1", "bits": "24"}


def test_an_origin_with_no_gateway_cannot_be_held_by_the_edge():
    segments = list(_segments())
    segments[3] = replace(segments[3], gateway="")

    with pytest.raises(RangeUnavailable, match=segments[3].id):
        opnsense.settings(tuple(segments), COLLECTOR, INSIDE, 1450, KEY)


def test_an_edge_without_the_mtu_or_the_platform_key_is_refused_by_what_supplies_it():
    with pytest.raises(RangeUnavailable, match="network.mtu"):
        opnsense.settings(_segments(), COLLECTOR, INSIDE, 0, KEY)
    with pytest.raises(RangeUnavailable, match="fabric"):
        opnsense.settings(_segments(), COLLECTOR, INSIDE, 1450, "")


def test_the_sensor_home_is_the_estate_and_management_so_every_origin_is_external():
    home = _wanted()["home"]

    assert home == [INSIDE["estate"], INSIDE["mgmt"]]
    assert not set(home) & {origin.subnet for origin in OS.origins}, (
        "OPNsense's suricata.yaml sets EXTERNAL_NET to !$HOME_NET, and the "
        "shipped rules match $EXTERNAL_NET -> $HOME_NET; an origin in HOME_NET "
        "would make every attack from it invisible"
    )


def test_the_rendered_config_assigns_wan_lan_and_mgmt_to_the_nics_in_slot_order():
    root = _rendered()

    assert [root.findtext(f"interfaces/{name}/if") for name in ("wan", "lan", "opt1")] == [
        "vtnet0", "vtnet1", "vtnet2"]
    assert root.findtext("interfaces/wan/ipaddr") == OS.origins[0].subnet.replace("0/24", "1")
    assert root.findtext("interfaces/lan/ipaddr") == "10.30.0.1"
    assert root.findtext("interfaces/opt1/ipaddr") == "dhcp"


def test_every_interface_takes_the_tenant_mtu():
    root = _rendered()

    assert {root.findtext(f"interfaces/{name}/mtu") for name in ("wan", "lan", "opt1")} == {"1450"}


def test_the_other_origin_gateways_are_ip_aliases_on_the_wan():
    vips = _rendered().findall("virtualip/vip")

    assert len(vips) == 29
    assert {vip.findtext("interface") for vip in vips} == {"wan"}
    assert {vip.findtext("mode") for vip in vips} == {"ipalias"}
    assert len({vip.get("uuid") for vip in vips}) == 29


def test_root_trusts_only_the_platform_key_and_has_no_password():
    root = _rendered()
    [user] = [u for u in root.findall("system/user") if u.findtext("name") == "root"]

    assert base64.b64decode(user.findtext("authorizedkeys")).decode() == KEY
    assert user.findtext("password") == "*", (
        "the stock image's root password is public (opnsense); this image never has it"
    )
    assert user.findtext("shell") == "/bin/sh", "root's default shell is the console menu"
    assert root.find("system/ssh/passwordauth") is None


def test_the_edge_logs_to_the_collector_and_watches_the_wan_in_ids_mode():
    root = _rendered()
    [destination] = root.findall("OPNsense/Syslog/destinations/destination")

    assert (destination.findtext("hostname"), destination.findtext("port")) == COLLECTOR[:1] + ("5140",)
    assert destination.findtext("transport") == "udp4"
    assert root.findtext("OPNsense/IDS/general/interfaces") == "wan"
    assert root.findtext("OPNsense/IDS/general/ips") == "0", (
        "netmap inline mode is unreliable on VirtIO NICs; the sensor only "
        "watches, as Suricata on pfSense did"
    )
    assert root.findtext("OPNsense/IDS/general/homenet") == ",".join(_wanted()["home"])


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


def test_hardware_offloading_is_off():
    system = _rendered().find("system")

    for name in ("disablechecksumoffloading", "disablesegmentationoffloading",
                 "disablelargereceiveoffloading"):
        assert system.findtext(name) == "1", name


def test_an_image_config_without_slot_values_takes_its_addresses_by_dhcp():
    template = (ROOT / opnsense.CONFIG).read_text()
    root = ElementTree.fromstring(opnsense.render(template, {"mtu": 1450, "key": KEY}))

    assert root.findtext("interfaces/lan/ipaddr") == "dhcp"
    assert not root.findtext("interfaces/wan/ipaddr")
    assert root.find("OPNsense/Syslog/destinations/destination") is None


def test_the_playback_stages_three_files_then_runs_the_static_script(tmp_path):
    config, include, rules = "<opnsense/>\n", "%YAML 1.1\n", "alert ip any any -> any any (sid:1;)\n"
    staged = {name: tmp_path / pathlib.PurePosixPath(path).name
              for name, path in opnsense.STAGED.items()}
    script = opnsense.playback(config, include, rules, "echo staged\n")
    for name, path in opnsense.STAGED.items():
        script = script.replace(path, str(staged[name]))

    done = subprocess.run(["sh"], input=script, capture_output=True, text=True)

    assert done.returncode == 0 and done.stdout == "staged\n", done.stderr
    assert [staged[n].read_text() for n in ("config", "include", "rules")] == [config, include, rules]


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


def test_the_lines_the_edge_printed_are_read_back():
    printed = ("fsl-edge booted 1760000000\nfsl-edge wan 73.0.0.1 120.96.0.1 \n"
               "fsl-edge sensor vtnet0 running\nfsl-edge logs 10.31.0.195:5140\n"
               "fsl-edge wanrule 2\n")

    assert opnsense.booted(printed) == "1760000000"
    assert opnsense.held(printed) == {"73.0.0.1", "120.96.0.1"}
    assert opnsense.sensing(printed)
    assert "logs 10.31.0.195:5140" in opnsense.reported(printed)
    assert opnsense.wan_rule_loaded(printed)


def test_a_stopped_sensor_an_empty_pf_or_no_output_reads_as_not_done():
    assert not opnsense.sensing("fsl-edge sensor vtnet0 stopped\n")
    assert not opnsense.wan_rule_loaded("fsl-edge wanrule 0\n")
    assert opnsense.held("sh: php: not found\n") == set()
    assert opnsense.booted("") == ""
