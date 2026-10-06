from pf_prime import mgmt_address, primed_line
from range.ports import Node, Segment

def _segments():
    return (
        Segment(id="estate", name="estate", nodes=(Node(name="fsl-pfsense", address="10.30.0.1"),)),
        Segment(id="mgmt", name="mgmt", nodes=(
            Node(name="fsl-waf", address="10.31.0.9"),
            Node(name="fsl-pfsense", address="10.31.0.158"),
        )),
    )

def test_mgmt_address_finds_the_pfsense_node_on_the_mgmt_segment():
    assert mgmt_address(_segments()) == "10.31.0.158"

def test_mgmt_address_takes_the_mgmt_interface_not_the_estate_one():
    assert mgmt_address(_segments()) != "10.30.0.1"

def test_mgmt_address_is_none_when_the_host_is_absent():
    only_waf = (Segment(id="mgmt", name="mgmt", nodes=(Node(name="fsl-waf", address="10.31.0.9"),)),)
    assert mgmt_address(only_waf) is None

def test_the_primed_line_names_the_upstream_host_and_session():
    assert primed_line("10.31.0.158", "abc123") == "http://10.31.0.158:80 10.31.0.158 abc123"
