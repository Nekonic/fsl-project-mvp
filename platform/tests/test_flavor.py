import pathlib

import pytest

from range import declared
from range.declared import Declaration, Host

DECLARATION = pathlib.Path(declared.__file__).resolve().parent / "declaration.yaml"

def read():
    return declared.read(DECLARATION)

def test_opnsense_stands_at_the_edge_as_the_sensor():
    d = read()

    assert d.roles["edge"] == "cr-edge"
    assert d.roles["sensor"] == "cr-edge"
    assert d.roles["gateway"] == "cr-waf", (
        "the attacker still addresses the WAF by name; the edge only routes and "
        "watches, so what fills 'gateway' does not change"
    )
    assert d.watches == {"sensor": "edge", "estate-sensor": "wargames"}

def test_the_wargame_host_watches_the_inside_leg():
    d = read()

    assert d.roles["estate-sensor"] == "cr-wargame-host"
    assert d.compose["estate-sensor"] == "suricata", (
        "the edge sees only the wan, so the wargame host runs a sensor on the WAF's leg to the target"
    )
    host = d.hosts["cr-wargame-host"]
    assert host.rules == "/var/lib/suricata/rules/local.rules"
    assert host.reload == "suricatasc -c reload-rules"
    assert host.logs == {"suricata": "/var/log/suricata/eve.json"}
    edge = d.hosts["cr-edge"]
    assert edge.rules == "/usr/local/etc/suricata/rules/cr.rules"
    assert edge.reload.split()[:3] == ["/usr/local/bin/suricatasc", "-c", "reload-rules"], (
        "suricatasc answers {\"return\": \"OK\"} only once the rules are loaded; "
        "configctl ids reload sends USR2 and returns before they are"
    )

def test_the_edge_and_kali_stand_on_the_internet_and_the_waf_behind_the_edge():
    d = read()

    assert d.hosts["cr-edge"].segments == ("internet", "estate", "mgmt"), (
        "the NIC order is the order OPNsense numbers vtnet0, vtnet1, vtnet2 in, "
        "which its configuration assigns to wan, lan and opt1"
    )
    assert d.hosts["cr-edge"].ssh_user == "root", (
        "the OPNsense image trusts the platform key for root, whose shell it sets to sh"
    )
    assert d.hosts["cr-kali"].segments == ("internet", "mgmt")
    assert d.hosts["cr-kali"].setup == "deploy/kali/setup.sh"
    assert "kali-rolling" not in DECLARATION.read_text(), (
        "the cloud holds one uploaded image, Ubuntu 24.04; the attacker is "
        "built from it like every other host"
    )
    assert d.hosts["cr-waf"].segments == ("estate", "mgmt"), (
        "the WAF stands behind the edge, on the estate only"
    )
    assert set(d.hosts["cr-waf"].names) == {"board.com", "corp.com"}, (
        "the attacker reaches every wargame by name through the WAF, so the WAF "
        "carries their names on the estate"
    )

@pytest.mark.parametrize("host, refused", [
    (Host(image="img"), False),
    (Host(), True),
    (Host(setup="s.sh", image="img"), True),
])
def test_a_prebuilt_image_host_needs_no_setup_script(host, refused):
    declaration = Declaration(roles={"edge": "cr-x"}, hosts={"cr-x": host})
    if refused:
        with pytest.raises(ValueError, match="cr-x"):
            declaration.check()
    else:
        declaration.check()
