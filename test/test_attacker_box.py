import ipaddress

import pytest

PUBLIC_HOST = "board.com"

@pytest.fixture(scope="module")
def box(terminal_session):
    return dict(terminal_session["box"], addresses=terminal_session["box_addresses"])

def test_the_console_reports_the_box_s_own_direct_address_and_a_proxied_one_apart_from_it(box):
    assert box["source_ip"] and box["direct_ip"], box
    assert box["direct_ip"] in box["addresses"], (
        f"the console says raw TCP leaves from {box['direct_ip']}, but the "
        f"box's own addresses are {box['addresses']}"
    )
    assert box["source_ip"] not in box["addresses"], (
        "the proxied and direct addresses are the same, so one of them is "
        "wrong and every raw-TCP window would be attributed to the proxy"
    )

def test_choosing_an_origin_moves_the_source_without_renaming_the_site(terminal_session):
    elsewhere = terminal_session["elsewhere"]
    assert elsewhere, "the stack offers only one origin"
    token, alerts = terminal_session["moved"]
    assert alerts, f"nothing alerted on the probe {token}"

    subnet = ipaddress.ip_network(elsewhere["subnet"])
    sources = {a["src_ip"] for a in alerts}

    assert any(ipaddress.ip_address(ip) in subnet for ip in sources), (
        f"asked the shell to leave by {elsewhere['label']} ({subnet}) and the "
        f"alerts came from {sorted(sources)}"
    )
    assert {a["http"].get("hostname") for a in alerts} == {PUBLIC_HOST}, (
        "an alert naming a routing host records a name nobody dialled"
    )
