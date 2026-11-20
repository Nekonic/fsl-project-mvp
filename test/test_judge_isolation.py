import ipaddress
import json
import struct

import pytest

import plays
from conftest import STANDING
from range import ATTACKER, BOARD, log_collector, platform_addresses, run, run_side_by_side

PUBLISHED = {
    8000: ("/api/auth/csrf/", "ok", "the platform API"),
    9200: ("/", "cluster_name", "Elasticsearch"),
}
SIDES = ("attack", "defence")
REFUSED = ("302", "403", "409", "503", "000")


@pytest.fixture(scope="module")
def lease(stack_is_up):
    standing = STANDING.lease()
    if standing is not None:
        return standing, STANDING.played
    played = plays.play("board")
    return played.lease, played


@pytest.fixture(scope="module")
def platform(lease):
    held, _ = lease
    found = set(platform_addresses(log_collector(held)))
    assert found, "neither CR_PLATFORM_URL nor the log relay names a platform address a range host could route to"
    return found


def gateways_of(role: str, lease: int) -> set[str]:
    table = run(role, ["cat", "/proc/net/route"], lease=lease).stdout.splitlines()[1:]
    return {str(ipaddress.IPv4Address(struct.pack("<I", int(fields[2], 16))))
            for fields in map(str.split, table) if fields[1] == "00000000"}


def fetch(url: str, *extra: str) -> list[str]:
    return ["curl", "-s", "--max-time", "4", "--noproxy", "*", *extra, url]


def terminal(address: str, side: str, round_id: int) -> list[str]:
    return fetch(f"http://{address}:8000/vm-terminal/{side}/{round_id}/",
                 "-o", "/dev/null", "-w", "%{http_code}", "-H", "Host: localhost:8000")


@pytest.fixture(scope="module")
def answered(lease, platform):
    held, played = lease
    found = {}
    for role in (ATTACKER, BOARD):
        addresses = sorted(gateways_of(role, held) | platform)
        commands = {(address, port): fetch(f"http://{address}:{port}{PUBLISHED[port][0]}")
                    for address in addresses for port in PUBLISHED}
        if role == BOARD:
            commands |= {(address, side): terminal(address, side, played.round)
                         for address in sorted(platform) for side in SIDES}
        ran = run_side_by_side(role, commands, lease=held)
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


def test_a_host_in_the_range_is_refused_the_terminal(answered, platform):
    codes = {(address, side): answered[BOARD][(address, side)].strip()
             for address in platform for side in SIDES}

    assert all(code in REFUSED for code in codes.values()), (
        f"{codes}: the round's own terminal path goes through the seat check, which answers "
        f"302 to sign-in, 403 not_seated, 409 for a round not running or 503; 000 is no route "
        f"to the platform. 2xx or 101 reached the terminal, 404 means the path is out of step "
        f"with nginx.conf, and an empty answer means curl never ran")
