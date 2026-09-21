from __future__ import annotations

import json
import subprocess

from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

_TIMEOUT = 30

                                                                         
                                                                     
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
    return json.loads(
        _docker([
            "inspect", container,
            "--format", "{{json .NetworkSettings.Networks}}",
        ]) or "{}"
    )

def _target_url(origin_id: str) -> str:
    parts = urlsplit(settings.TARGET_URL)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://waf-{origin_id}{port}"

def origins() -> list[dict]:
    attached = _attached(settings.ATTACKER_SOURCE_CONTAINER)
    if not attached:
        raise AttackerUnavailable(
            f"{settings.ATTACKER_SOURCE_CONTAINER} is on no network at all"
        )

                                                                              
                                                                          
                                                                             
                                                                            
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
    return find(origin_id)["source_ip"]

def set_origin(origin_id: str | None) -> None:
    _write(settings.ATTACKER_ORIGIN_FILE, origin_id)

def set_label(case_id: str | None) -> None:
    _write(settings.ATTACKER_LABEL_FILE, case_id)

def _write(where: str, value: str | None) -> None:
    path = Path(where)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value or "")
