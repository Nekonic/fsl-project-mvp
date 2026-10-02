from range import declared, fabric, pfsense

OS = declared.read(flavor="openstack")
RULES = "alert http any any -> any any (sid:9000001;)\n"

def test_home_net_holds_every_origin_subnet_and_the_inside_networks():
    home = pfsense.home_net(OS)

    assert home.startswith("[") and home.endswith("]")
    members = home[1:-1].split(",")
    for origin in OS.origins:
        assert origin.subnet in members, origin.id
    assert fabric.INSIDE["estate"] in members
    assert fabric.INSIDE[fabric.MANAGEMENT] in members

def test_home_net_counts_the_origins_so_the_attacker_side_is_not_external():
    members = pfsense.home_net(OS)[1:-1].split(",")

    assert len([m for m in members if m in {o.subnet for o in OS.origins}]) == 30, (
        "the edge sensor watches traffic whose source is an origin subnet; if "
        "those were external, a rule reading EXTERNAL_NET->HOME_NET would still "
        "match, but the home side has to name where the defended hosts are"
    )
    assert members[-2:] == [fabric.INSIDE["estate"], fabric.INSIDE[fabric.MANAGEMENT]]

def test_home_net_is_one_line_with_no_spaces_for_a_suricata_variable():
    assert " " not in pfsense.home_net(OS)

def _origin_segments():
    from range.ports import Segment

    return tuple(
        Segment(id=origin.id, name=origin.label, origin=origin.label, subnet=origin.subnet,
                gateway=origin.subnet.replace("0/24", "1"))
        for origin in OS.origins
    ) + (Segment(id="estate", name="Estate", subnet="10.30.0.0/24", gateway="10.30.0.1"),)

def test_the_wan_holds_the_first_origin_gateway_and_aliases_the_other_twenty_nine():
    wanted = pfsense.settings(_origin_segments(), OS, RULES)

    first = OS.origins[0]
    assert wanted["wan"] == {"id": first.id, "address": first.subnet.replace("0/24", "1"), "bits": "24"}
    assert [alias["id"] for alias in wanted["aliases"]] == [o.id for o in OS.origins[1:]]
    assert len(wanted["aliases"]) == 29
    assert all(alias["bits"] == "24" for alias in wanted["aliases"])
    assert "10.30.0.1" not in {alias["address"] for alias in wanted["aliases"]}, (
        "the estate gateway sits on the LAN, which Neutron's DHCP already gives pfSense"
    )

def test_an_origin_with_no_gateway_cannot_be_held_by_the_edge():
    from dataclasses import replace

    import pytest
    from range.ports import RangeUnavailable

    segments = list(_origin_segments())
    segments[3] = replace(segments[3], gateway="")

    with pytest.raises(RangeUnavailable, match=segments[3].id):
        pfsense.settings(tuple(segments), OS, RULES)

def test_the_playback_carries_its_settings_as_data_ahead_of_the_static_script():
    import base64
    import json
    import re

    wanted = pfsense.settings(_origin_segments(), OS, RULES)
    script = pfsense.playback(wanted, "config_read_file(true);\n")

    first, rest = script.split("\n", 1)
    blob = re.fullmatch(r"\$fsl = json_decode\(base64_decode\('([A-Za-z0-9+/=]+)'\), true\);", first)
    assert blob, "settings travel as base64 so no address or name is ever PHP syntax"
    assert json.loads(base64.b64decode(blob[1])) == wanted
    assert rest == "config_read_file(true);\n"

def test_the_playback_is_saved_as_a_shell_session_and_played_back():
    command = pfsense.command()

    assert command[:2] == ["sh", "-c"]
    assert f"/etc/phpshellsessions/{pfsense.SESSION}" in command[2]
    assert f"pfSsh.php playback {pfsense.SESSION}" in command[2]

def test_the_held_addresses_are_read_back_from_what_the_playback_printed():
    printed = "noise\nfsl-edge wan 73.0.0.1 120.96.0.1\nmore\n"

    assert pfsense.held(printed) == {"73.0.0.1", "120.96.0.1"}
    assert pfsense.held("PHP ERROR: nothing printed\n") == set()

def test_the_static_script_exists_where_the_platform_reads_it():
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / pfsense.TEMPLATE
    text = script.read_text()
    assert "$fsl['wan']" in text and "$fsl['aliases']" in text
    assert "<?php" not in text, "pfSsh.php plays back bare statements"

def test_the_sensor_is_told_its_home_is_every_origin_the_estate_and_management():
    wanted = pfsense.settings(_origin_segments(), OS, RULES)

    assert wanted["home"] == pfsense.home_net(OS)[1:-1].split(",")

def test_the_sensor_starts_from_the_shipped_rules():
    assert pfsense.settings(_origin_segments(), OS, RULES)["rules"] == RULES

def test_the_static_script_names_the_sensor_settings_it_reads():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / pfsense.TEMPLATE).read_text()
    assert "$fsl['home']" in text and "$fsl['rules']" in text

def test_a_running_sensor_is_read_back_from_what_the_playback_printed():
    assert pfsense.sensing("x\nfsl-edge sensor vtnet0 running\n")
    assert not pfsense.sensing("fsl-edge sensor vtnet0 stopped\n")
    assert not pfsense.sensing("PHP ERROR\n")
