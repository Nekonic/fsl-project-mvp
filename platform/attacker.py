from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings

from range.ports import RangeUnavailable

class AttackerUnavailable(RangeUnavailable):
    pass

class UnknownOrigin(ValueError):
    pass

def _target_url(address: str) -> str:
    parts = urlsplit(settings.TARGET_URL)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{address}{port}"

def _way_in() -> str:
    roles = settings.RANGE.roles
    return roles.get("edge") or roles["gateway"]

def origins(described) -> list[dict]:
    box = settings.ATTACKER_SOURCE_CONTAINER
    terminal = settings.ATTACKER_CONTAINER
    way_in = _way_in()
    by_name = "edge" in settings.RANGE.roles

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
            "address": addresses.get(way_in) or segment.gateway,
            "target_url": settings.ATTACKER_TARGET_URL if by_name
            else _target_url(addresses[way_in]),
            "default": segment.id == settings.RANGE.default_origin,
        }
        for segment, addresses in standing
        if segment.origin and addresses.get(box)
        and (by_name or addresses.get(way_in))
    ]
    return sorted(found, key=lambda origin: origin["id"])

def find(described, origin_id: str | None) -> dict:
    available = origins(described)
    if not origin_id:
        if not available:
            raise UnknownOrigin("the stack offers no origin to attack from")
        return next((o for o in available if o["default"]), available[0])
    for origin in available:
        if origin["id"] == origin_id:
            return origin
    raise UnknownOrigin(
        f"no origin {origin_id!r}; the stack offers "
        f"{[o['id'] for o in available]}"
    )

def set_origin(address: str | None, proxy) -> None:
    _write(proxy, settings.ATTACKER_ORIGIN_FILE, address)

def wear_origin(chosen: dict, box) -> None:
    if settings.ATTACKER_ORIGIN_MODE == "snat":
        ran = box(["sudo", "/usr/local/sbin/fsl-origin", chosen["source_ip"]])
        if not ran.ok:
            raise AttackerUnavailable(
                f"the box could not wear {chosen['source_ip']}: {ran.output.strip()[:200]}"
            )
        return
    set_origin(chosen["address"], box)

def set_label(case_id: str | None, proxy) -> None:
    _write(proxy, settings.ATTACKER_LABEL_FILE, case_id)

def _write(proxy, where: str, value: str | None) -> None:
    ran = proxy(["sh", "-c", f"cat > {where}"], stdin=value or "")
    if not ran.ok:
        raise AttackerUnavailable(
            f"the proxy could not write {where}: {ran.output.strip()[:200]}"
        )
