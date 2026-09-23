import ipaddress
import struct

import pytest

from range import ATTACKER, WIKI, run

PUBLISHED = {8000: "the scoring API", 9200: "Elasticsearch", 7681: "the attacker's shell", 8080: "the front door"}


def gateway_of(role: str) -> str:
    table = run(role, ["cat", "/proc/net/route"]).stdout.splitlines()[1:]
    for line in table:
        fields = line.split()
        if fields[1] == "00000000":
            return str(ipaddress.IPv4Address(struct.pack("<I", int(fields[2], 16))))
    pytest.fail(f"{role} has no default route: {table}")


def reached(role: str, url: str) -> bool:
    answer = run(role, [
        "sh", "-c",
        f"env -u http_proxy -u HTTP_PROXY -u https_proxy -u HTTPS_PROXY "
        f"wget -q -O /dev/null -T 4 {url} && echo reached || echo refused",
    ])
    return answer.stdout.strip().endswith("reached")


@pytest.mark.parametrize("role", [ATTACKER, WIKI])
@pytest.mark.parametrize("port", sorted(PUBLISHED))
def test_a_host_in_the_range_cannot_reach_what_is_published_for_the_operator(stack_is_up, role, port):
    gateway = gateway_of(role)

    assert not reached(role, f"http://{gateway}:{port}/"), (
        f"{role} reached {PUBLISHED[port]} at its own gateway {gateway}:{port}. "
        f"A port published on every address hairpins back into the range, so "
        f"the side being scored can rewrite the rules or the alerts it is scored on"
    )
