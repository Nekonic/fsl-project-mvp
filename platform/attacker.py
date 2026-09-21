from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

from range import declared

from range.ports import RangeUnavailable

class AttackerUnavailable(RangeUnavailable):
    pass

class UnknownOrigin(ValueError):
    pass

def _target_url(address: str) -> str:
    parts = urlsplit(settings.TARGET_URL)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{address}{port}"

def origins(described) -> list[dict]:
    box = settings.ATTACKER_SOURCE_CONTAINER
    terminal = settings.ATTACKER_CONTAINER
    way_in = settings.RANGE.roles["gateway"]

    standing = [
        (segment, {node.name: node.address for node in segment.nodes})
        for segment in described.segments
        if any(node.name == box for node in segment.nodes)
    ]
    if not standing:
        raise AttackerUnavailable(f"{box} is on no network at all")

    found = [
        {
            "id": segment.id,
            "network": segment.network,
            "label": segment.origin,
            "subnet": segment.subnet,
            "source_ip": addresses[box],
            "direct_ip": addresses.get(terminal, ""),
            "address": addresses[way_in],
            "target_url": _target_url(addresses[way_in]),
            "default": segment.id == declared.read().default_origin,
        }
        for segment, addresses in standing
        if segment.origin and addresses[box] and addresses.get(way_in)
    ]
    return sorted(found, key=lambda origin: origin["id"])

def find(described, origin_id: str | None) -> dict:
    available = origins(described)
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

def set_origin(address: str | None, proxy) -> None:
    _write(proxy, settings.ATTACKER_ORIGIN_FILE, address)

def set_label(case_id: str | None, proxy) -> None:
    _write(proxy, settings.ATTACKER_LABEL_FILE, case_id)

def _write(proxy, where: str, value: str | None) -> None:
    proxy(["sh", "-c", f"cat > {where}"], stdin=value or "")
