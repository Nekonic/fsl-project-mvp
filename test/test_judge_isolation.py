import ipaddress
import json
import socket
import struct
from urllib.parse import urlsplit

import pytest
import requests

from conftest import PLATFORM_URL, STANDING
from range import ATTACKER, BOARD, declared_roles, run, run_side_by_side

PLATFORM = declared_roles()["scorer"]
PUBLISHED = {
    8000: ("/api/range/ready/", "substrate", "the scoring API"),
    9200: ("/", "cluster_name", "Elasticsearch"),
}
PANES = ("kali", "waf")


@pytest.fixture(scope="module")
def session(stack_is_up):
    standing = STANDING.id()
    if standing is not None:
        return standing
    opened = requests.post(f"{PLATFORM_URL}/api/sessions/", json={}, timeout=600)
    assert opened.status_code == 201, opened.text
    return opened.json()["id"]


@pytest.fixture(scope="module")
def platform_addresses(session):
    shape = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session}/topology/", timeout=120
    ).json()
    found = {
        node["address"] for segment in shape["segments"] for node in segment["nodes"]
        if node["name"] == PLATFORM and node["address"]
    }
    published = socket.gethostbyname(urlsplit(PLATFORM_URL).hostname)
    if not ipaddress.ip_address(published).is_loopback:
        found.add(published)
    assert found, f"the range shows no address of {PLATFORM}: {shape['segments']}"
    return found


def gateway_of(role: str, session: int) -> str:
    table = run(role, ["cat", "/proc/net/route"], session=session).stdout.splitlines()[1:]
    for line in table:
        fields = line.split()
        if fields[1] == "00000000":
            return str(ipaddress.IPv4Address(struct.pack("<I", int(fields[2], 16))))
    pytest.fail(f"{role} has no default route: {table}")


def fetch(url: str, *extra: str) -> list[str]:
    return ["curl", "-s", "--max-time", "4", "--noproxy", "*", *extra, url]


def terminal(address: str, pane: str) -> list[str]:
    return fetch(f"http://{address}:8000/vm-terminal/{pane}/",
                 "-o", "/dev/null", "-w", "%{http_code}", "-H", "Host: localhost:8000")


@pytest.fixture(scope="module")
def answered(session, platform_addresses):
    found = {}
    for role in (ATTACKER, BOARD):
        addresses = sorted({gateway_of(role, session)} | platform_addresses)
        commands = {(address, port): fetch(f"http://{address}:{port}{PUBLISHED[port][0]}")
                    for address in addresses for port in PUBLISHED}
        if role == BOARD:
            commands |= {(address, pane): terminal(address, pane)
                         for address in sorted(platform_addresses) for pane in PANES}
        ran = run_side_by_side(role, commands, session=session)
        found[role] = {key: result.stdout for key, result in ran.items()}
    return found


def answered_by(body: str, key: str) -> bool:
    try:
        return key in json.loads(body)
    except (ValueError, TypeError):
        return False


@pytest.mark.parametrize("role", [ATTACKER, BOARD])
@pytest.mark.parametrize("port", sorted(PUBLISHED))
def test_a_host_in_the_range_cannot_reach_what_is_published_for_the_operator(answered, role, port):
    path, key, what = PUBLISHED[port]
    reached = sorted(
        address for (address, asked), body in answered[role].items()
        if asked == port and answered_by(body, key)
    )

    assert not reached, (
        f"{role} reached {what} at {reached}:{port}. A port published on an "
        f"address a range host can route to lets the side being scored rewrite "
        f"the rules or the alerts it is scored on"
    )


def test_a_host_in_the_range_is_refused_the_terminal(answered, platform_addresses):
    codes = {(address, pane): answered[BOARD][(address, pane)].strip()
             for address in platform_addresses for pane in PANES}

    assert all(code in ("403", "000") for code in codes.values()), (
        f"{codes}: 403 is the terminal's auth_request refusing a range host and 000 is "
        f"no route to the platform; an empty answer means curl never ran")
