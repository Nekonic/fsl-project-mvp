import ipaddress
import re

from range import ATTACKER, run

SERVICE_PORTS = "22,80,443,3306,5601,8000,8080,9200"
OPEN_PORT = re.compile(r"^(\d+)/tcp\s+open\b", re.M)
SCANNED_HOST = re.compile(r"^Nmap scan report for (\S+)", re.M)
PAST_THE_WAF = ("http://board:8000/", "http://corp-wp/")

def _side_ports() -> list[ipaddress.IPv4Interface]:
    said = run(ATTACKER, ["sh", "-c", "ip -o -4 addr show; echo --; ip -o -4 route show default"]).stdout
    addresses, defaults = said.split("--", 1)
    routed = {fields[fields.index("dev") + 1] for fields in map(str.split, defaults.splitlines())
              if "dev" in fields}
    held = [line.split() for line in addresses.splitlines()]
    return [
        ipaddress.IPv4Interface(fields[3]) for fields in held
        if len(fields) >= 4 and fields[2] == "inet" and fields[1] != "lo" and fields[1] not in routed
    ]

def _open_on(side: ipaddress.IPv4Interface) -> dict[str, list[str]]:
    scan = run(
        ATTACKER,
        ["sh", "-c",
         f"$(command -v sudo >/dev/null && echo sudo -n) nmap -n -sT --open -T4 "
         f"--max-retries 1 -p {SERVICE_PORTS} --exclude {side.ip} {side.network}"],
        timeout=600,
    ).stdout
    reports = SCANNED_HOST.split(scan)
    return {
        host: OPEN_PORT.findall(body)
        for host, body in zip(reports[1::2], reports[2::2])
        if OPEN_PORT.findall(body)
    }

def test_the_attacker_reaches_no_service_over_a_port_off_its_route_out():
    reached = {str(side.network): _open_on(side) for side in _side_ports()}

    assert not any(reached.values()), (
        f"from Kali's management port the attacker reaches {reached}; a "
        f"management segment that lets the attacker in hands it the edge's web "
        f"GUI and the wargames' published ports without crossing the edge or the WAF"
    )

def test_the_attacker_cannot_reach_a_target_past_the_waf():
    reached = {
        url: run(ATTACKER, ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "--max-time", "8", "--noproxy", "*", url]).stdout.strip()
        for url in PAST_THE_WAF
    }

    assert all(code in ("", "000") for code in reached.values()), (
        f"the attacker reached a target directly ({reached}), so the WAF is optional"
    )
