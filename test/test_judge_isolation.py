import ipaddress
import json
import socket
import struct
from urllib.parse import urlsplit

import pytest
import requests

from conftest import PLATFORM_URL
from range import ATTACKER, BOARD, declared_roles, run

PLATFORM = declared_roles()["scorer"]
PUBLISHED = {
    8000: ("/api/range/ready/", "substrate", "the scoring API"),
    9200: ("/", "cluster_name", "Elasticsearch"),
}


@pytest.fixture(scope="module")
def session(stack_is_up):
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


def fetched(role: str, url: str, session: int, *extra: str) -> str:
    return run(role, [
        "curl", "-s", "--max-time", "4", "--noproxy", "*", *extra, url,
    ], session=session).stdout


def answered_by(body: str, key: str) -> bool:
    try:
        return key in json.loads(body)
    except (ValueError, TypeError):
        return False


@pytest.mark.parametrize("role", [ATTACKER, BOARD])
@pytest.mark.parametrize("port", sorted(PUBLISHED))
def test_a_host_in_the_range_cannot_reach_what_is_published_for_the_operator(
    session, platform_addresses, role, port,
):
    path, key, what = PUBLISHED[port]
    addresses = {gateway_of(role, session)} | platform_addresses
    reached = sorted(
        address for address in addresses
        if answered_by(fetched(role, f"http://{address}:{port}{path}", session), key)
    )

    assert not reached, (
        f"{role} reached {what} at {reached}:{port}. A port published on an "
        f"address a range host can route to lets the side being scored rewrite "
        f"the rules or the alerts it is scored on"
    )


def test_a_host_in_the_range_is_refused_the_terminal(session, platform_addresses):
    answered = {
        (address, pane): fetched(
            BOARD, f"http://{address}:8000/vm-terminal/{pane}/", session,
            "-o", "/dev/null", "-w", "%{http_code}", "-H", "Host: localhost:8000",
        ).strip()
        for address in platform_addresses
        for pane in ("kali", "waf")
    }

    assert all(code in ("403", "000") for code in answered.values()), (
        f"{answered}: 403 is the terminal's auth_request refusing a range host and 000 is "
        f"no route to the platform; an empty answer means curl never ran")
