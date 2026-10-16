import pathlib

import pytest

from range import declared
from range.declared import Declaration, Host

DECLARATION = pathlib.Path(declared.__file__).resolve().parent / "declaration.yaml"

def openstack():
    return declared.read(DECLARATION, flavor="openstack")

def test_the_openstack_flavor_puts_opnsense_at_the_edge_as_the_sensor():
    d = openstack()

    assert d.roles["edge"] == "fsl-edge"
    assert d.roles["sensor"] == "fsl-edge"
    assert d.roles["gateway"] == "fsl-waf", (
        "the attacker still addresses the WAF by name; the edge only routes and "
        "watches, so what fills 'gateway' does not change"
    )
    assert d.watches == {"sensor": "edge", "estate-sensor": "wargames"}

def test_the_openstack_flavor_watches_the_inside_leg_on_the_wargame_host():
    d = openstack()

    assert d.roles["estate-sensor"] == "fsl-wargame-host"
    assert d.compose["estate-sensor"] == "suricata", (
        "docker's sensor sees the WAF's leg to the target too; on openstack the "
        "edge sees only the wan, so the wargame host runs the same sensor image"
    )
    host = d.hosts["fsl-wargame-host"]
    assert host.rules == "/var/lib/suricata/rules/local.rules"
    assert host.reload == "suricatasc -c reload-rules"
    assert host.logs == {"suricata": "/var/log/suricata/eve.json"}
    edge = d.hosts["fsl-edge"]
    assert edge.rules == "/usr/local/etc/suricata/rules/fsl.rules"
    assert edge.reload.split()[:3] == ["/usr/local/bin/suricatasc", "-c", "reload-rules"], (
        "suricatasc answers {\"return\": \"OK\"} only once the rules are loaded; "
        "configctl ids reload sends USR2 and returns before they are"
    )

def test_the_docker_flavor_keeps_one_sensor_and_no_overlay_compose_role():
    d = declared.read()

    assert d.watches == {"sensor": "gateway"}
    assert "estate-sensor" not in d.compose
    assert "edge" not in d.roles and "fsl-edge" not in d.hosts

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

@pytest.mark.parametrize("host, refused", [
    (Host(image="img"), False),
    (Host(), True),
    (Host(setup="s.sh", image="img"), True),
])
def test_a_prebuilt_image_host_needs_no_setup_script(host, refused):
    declaration = Declaration(roles={"edge": "fsl-x"}, hosts={"fsl-x": host})
    if refused:
        with pytest.raises(ValueError, match="fsl-x"):
            declaration.check()
    else:
        declaration.check()
