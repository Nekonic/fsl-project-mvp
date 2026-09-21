"""The attacker's box: where free-form traffic comes from, and what marks it.

Window correlation matches alerts by source IP, so labelling anything typed in
the terminal means knowing the address Suricata will see. That is *not* the
Kali container's address: the terminal's traffic goes through the stamping
proxy, so the WAF - and the IDS inside its namespace - sees the proxy. Ask
Docker for the container whose address the alerts will actually carry.

The same proxy stamps the case marker, which it reads from a file this module
writes. That is what lets one piece of free-form traffic be scored both ways.

It also knows where an attack can come *from*. One subnet is one place on the
map, so every origin is a separate network, and which ones exist is asked of
Docker rather than listed here - compose decides which addresses exist and the
score is read off the addresses.
"""

from __future__ import annotations

import json
import subprocess

from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

_TIMEOUT = 30

# Networks carrying this label are places an attack can come from. Set in
# compose beside the subnet it describes, so the two cannot disagree.
ORIGIN_LABEL = "fsl.origin"


class AttackerUnavailable(RuntimeError):
    """The attacker container is not running, or Docker cannot be reached."""


class UnknownOrigin(ValueError):
    """No such place to attack from."""


def _docker(argv: list[str]) -> str:
    result = subprocess.run(
        ["docker", *argv], capture_output=True, text=True, timeout=_TIMEOUT,
    )
    if result.returncode != 0:
        raise AttackerUnavailable(
            f"docker {' '.join(argv[:2])}: {result.stderr.strip()[:200]} "
            f"Start the stack with: docker compose up -d"
        )
    return result.stdout


def _attached(container: str) -> dict[str, dict]:
    """The networks a box can leave by, and its address on each."""
    return json.loads(
        _docker([
            "inspect", container,
            "--format", "{{json .NetworkSettings.Networks}}",
        ]) or "{}"
    )


def _target_url(origin_id: str) -> str:
    """The way in through that segment.

    Derived from the default target rather than assembled from a port written
    down twice. The host names the segment, not the machine: the WAF is on
    every edge network, so `waf` alone is ambiguous and the source address of
    the attack is decided by which of its addresses is dialled.
    """
    parts = urlsplit(settings.TARGET_URL)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://waf-{origin_id}{port}"


def origins() -> list[dict]:
    """Every place an attack can come from, discovered from the stack itself.

    An origin needs both halves: a network that declares where it pretends to
    be, and an address on it. A declared network the attacker is not attached
    to would offer an attack that cannot be sent.
    """
    attached = _attached(settings.ATTACKER_SOURCE_CONTAINER)
    if not attached:
        raise AttackerUnavailable(
            f"{settings.ATTACKER_SOURCE_CONTAINER} is on no network at all"
        )

    # Where raw TCP leaves from. Anything HTTP goes through the stamping proxy
    # above, so an alert carries the proxy's address - but nmap and netcat
    # ignore http_proxy and leave from the box the shell is on. Both are true
    # at once, and a window recorded against the wrong one matches no alert.
    try:
        direct = _attached(settings.ATTACKER_CONTAINER)
    except AttackerUnavailable:
        direct = {}

    described = {}
    for line in _docker(
        ["network", "inspect", "--format", "{{json .}}", *sorted(attached)]
    ).splitlines():
        network = json.loads(line)
        described[network["Name"]] = network

    found = []
    for name, connection in attached.items():
        network = described.get(name) or {}
        label = (network.get("Labels") or {}).get(ORIGIN_LABEL)
        address = connection.get("IPAddress")
        if not label or not address:
            continue
        # "fsl_edge-hk" is the compose key "edge-hk" under the project name.
        origin_id = name.split("_", 1)[-1]
        config = (network.get("IPAM") or {}).get("Config") or [{}]
        found.append({
            "id": origin_id,
            "network": name,
            "label": label,
            "subnet": config[0].get("Subnet", ""),
            "source_ip": address,
            "direct_ip": (direct.get(name) or {}).get("IPAddress", ""),
            "target_url": _target_url(origin_id),
            "default": name == settings.ATTACKER_NETWORK,
        })
    return sorted(found, key=lambda o: o["id"])


def find(origin_id: str | None) -> dict:
    """The named origin, or the default one. Never a silent fallback."""
    available = origins()
    if not origin_id:
        return next(
            (o for o in available if o["default"]),
            available[0] if available else {},
        ) or _unknown(None, available)
    for origin in available:
        if origin["id"] == origin_id:
            return origin
    return _unknown(origin_id, available)


def _unknown(origin_id, available):
    raise UnknownOrigin(
        f"no origin {origin_id!r}; the stack offers "
        f"{[o['id'] for o in available]}"
    )


def source_ip(origin_id: str | None = None) -> str:
    """The address alerts from the terminal will carry, leaving by that origin.

    Never guessed. A wrong address matches no alert at all, which scores a
    real attack as a miss and blames the defence for it.
    """
    return find(origin_id)["source_ip"]


def set_origin(origin_id: str | None) -> None:
    """Tell the proxy which segment to send the terminal's traffic out of.

    Written as a file for the same reason as the marker: the proxy reads it
    per request, so there is nothing to restart and nothing to keep in sync.
    """
    _write(settings.ATTACKER_ORIGIN_FILE, origin_id)


def set_label(case_id: str | None) -> None:
    """Tell the proxy which marker to stamp, or to stop stamping.

    Written as a file rather than pushed over an API: the proxy reads it per
    request, so it needs no endpoint of its own and nothing to restart.
    """
    _write(settings.ATTACKER_LABEL_FILE, case_id)


def _write(where: str, value: str | None) -> None:
    path = Path(where)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value or "")
