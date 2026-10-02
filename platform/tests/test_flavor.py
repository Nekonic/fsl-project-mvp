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
    assert "fsl-pfsense" not in d.hosts

def test_the_openstack_flavor_puts_pfsense_at_the_edge_as_the_sensor():
    d = openstack()

    assert d.roles["edge"] == "fsl-pfsense"
    assert d.roles["sensor"] == "fsl-pfsense"
    assert d.roles["gateway"] == "fsl-waf", (
        "the attacker still addresses the WAF by name; pfSense only routes and "
        "watches, so what fills 'gateway' does not change"
    )
    assert d.watches == {"sensor": "edge"}

def test_the_openstack_flavor_adds_pfsense_and_kali_and_takes_the_waf_off_the_internet():
    d = openstack()

    assert d.hosts["fsl-pfsense"].segments == ("internet", "estate", "mgmt")
    assert d.hosts["fsl-pfsense"].image == "fsl-pfsense-edge", (
        "the slot boots the configured edge image (Suricata + sshd + the "
        "platform key + MTU 1450 + OPT1 mgmt), not the bare CE install"
    )
    assert d.hosts["fsl-pfsense"].setup == ""
    assert d.hosts["fsl-pfsense"].ssh_user == "admin", (
        "pfSense's shell account over ssh is admin, not the Ubuntu-image ubuntu"
    )
    assert d.hosts["fsl-kali"].segments == ("internet", "mgmt")
    assert d.hosts["fsl-kali"].setup == "deploy/kali/setup.sh"
    assert d.hosts["fsl-kali"].base == "kali-rolling", (
        "the attacker is a real Kali image, not the estate's Ubuntu builder base"
    )
    assert d.hosts["fsl-waf"].segments == ("estate", "mgmt"), (
        "the WAF stands behind pfSense now, on the estate only"
    )
    assert set(d.hosts["fsl-waf"].names) == {"shop.com", "board.com"}, (
        "the attacker reaches the targets by name through the WAF, so the WAF "
        "carries their names on the estate"
    )

def test_an_unknown_flavor_is_just_the_base():
    assert declared.read(DECLARATION, flavor="nope").roles == base().roles

def test_the_openstack_substrate_selects_the_openstack_flavor():
    assert declared.flavor_for("range.openstack.connect") == "openstack"
    assert declared.flavor_for("range.docker.Docker") == ""

def test_a_prebuilt_image_host_needs_no_setup_script():
    d = openstack()

    pfsense = d.hosts["fsl-pfsense"]
    assert pfsense.image and not pfsense.setup

def test_a_host_that_declares_neither_a_setup_script_nor_an_image_is_refused():
    with pytest.raises(ValueError, match="fsl-x"):
        Declaration(roles={"edge": "fsl-x"}, hosts={"fsl-x": Host()}).check()

def test_a_host_that_declares_both_a_setup_script_and_an_image_is_refused():
    with pytest.raises(ValueError, match="fsl-x"):
        Declaration(
            roles={"edge": "fsl-x"},
            hosts={"fsl-x": Host(setup="s.sh", image="img")},
        ).check()
