import pathlib

import pytest

from range import declared
from range.declared import Declaration, Host

DECLARATION = pathlib.Path(declared.__file__).resolve().parent / "declaration.yaml"

def base():
    return declared.read(DECLARATION)

def openstack():
    return declared.read(DECLARATION, flavor="openstack")

def test_the_docker_flavor_names_no_edge_and_keeps_the_waf_as_sensor_vantage():
    d = base()

    assert "edge" not in d.roles
    assert d.roles["sensor"] == "fsl-suricata"
    assert d.roles["gateway"] == "fsl-waf"
    assert d.watches == {"sensor": "gateway"}
    assert "fsl-edge" not in d.hosts

def test_the_openstack_flavor_puts_opnsense_at_the_edge_as_the_sensor():
    d = openstack()

    assert d.roles["edge"] == "fsl-edge"
    assert d.roles["sensor"] == "fsl-edge"
    assert d.roles["gateway"] == "fsl-waf", (
        "the attacker still addresses the WAF by name; the edge only routes and "
        "watches, so what fills 'gateway' does not change"
    )
    assert d.watches == {"sensor": "edge"}

def test_the_openstack_flavor_adds_the_edge_and_kali_and_takes_the_waf_off_the_internet():
    d = openstack()

    assert d.hosts["fsl-edge"].segments == ("internet", "estate", "mgmt"), (
        "the NIC order is the order OPNsense numbers vtnet0, vtnet1, vtnet2 in, "
        "which its configuration assigns to wan, lan and opt1"
    )
    assert d.hosts["fsl-edge"].ssh_user == "root", (
        "the OPNsense image trusts the platform key for root, whose shell it sets to sh"
    )
    assert d.hosts["fsl-kali"].segments == ("internet", "mgmt")
    assert d.hosts["fsl-kali"].setup == "deploy/kali/setup.sh"
    assert "kali-rolling" not in DECLARATION.read_text(), (
        "the cloud holds one uploaded image, Ubuntu 24.04; the attacker is "
        "built from it like every other host"
    )
    assert d.hosts["fsl-waf"].segments == ("estate", "mgmt"), (
        "the WAF stands behind the edge, on the estate only"
    )
    assert set(d.hosts["fsl-waf"].names) == {"board.com", "corp.com"}, (
        "the attacker reaches every wargame by name through the WAF, so the WAF "
        "carries their names on the estate"
    )

def test_an_unknown_flavor_is_just_the_base():
    assert declared.read(DECLARATION, flavor="nope").roles == base().roles

def test_the_openstack_substrate_selects_the_openstack_flavor():
    assert declared.flavor_for("range.openstack.connect") == "openstack"
    assert declared.flavor_for("range.docker.Docker") == ""

def test_a_prebuilt_image_host_needs_no_setup_script():
    Declaration(roles={"edge": "fsl-x"}, hosts={"fsl-x": Host(image="img")}).check()

def test_the_edge_tells_the_rules_editor_where_its_sensor_reads_rules_and_how_to_reload():
    edge = openstack().hosts["fsl-edge"]

    assert edge.rules == "/usr/local/etc/suricata/rules/fsl.rules"
    assert edge.reload.split()[:3] == ["/usr/local/bin/suricatasc", "-c", "reload-rules"], (
        "suricatasc answers {\"return\": \"OK\"} only once the rules are loaded; "
        "configctl ids reload sends USR2 and returns before they are"
    )

def test_a_host_that_declares_neither_a_setup_script_nor_an_image_is_refused():
    with pytest.raises(ValueError, match="fsl-x"):
        Declaration(roles={"edge": "fsl-x"}, hosts={"fsl-x": Host()}).check()

def test_a_host_that_declares_both_a_setup_script_and_an_image_is_refused():
    with pytest.raises(ValueError, match="fsl-x"):
        Declaration(
            roles={"edge": "fsl-x"},
            hosts={"fsl-x": Host(setup="s.sh", image="img")},
        ).check()

def test_the_attacker_built_on_ubuntu_enables_the_archive_components_its_tools_come_from():
    script = (DECLARATION.parents[2] / "deploy/kali/setup.sh").read_text()

    assert "Components: main restricted universe multiverse" in script, (
        "nikto is in multiverse and sqlmap, ffuf and gobuster in universe; the "
        "script says so itself instead of trusting the image's apt sources"
    )
    assert "/usr/share/wordlists/dirb" in script, "the motd's ffuf line reads that list"
