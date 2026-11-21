from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable

from cr.config import EdgeConfig
from sandbox.runner import RangeUnavailable

NO_ENTRIES = 1


def _addresses(given: Iterable[str]) -> list[str]:
    try:
        return sorted({str(ipaddress.IPv4Address(str(one).strip())) for one in given}, key=ipaddress.IPv4Address)
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"an edge set holds IPv4 addresses only: {exc}") from exc


def _element(config: EdgeConfig, set_name: str, addresses: list[str]) -> str:
    return f"add element {config.family} {config.table} {set_name} {{ {', '.join(addresses)} }}"


def _ran(router, argv: list[str], what: str, stdin: str | None = None):
    ran = router(argv, stdin=stdin)
    if not ran.ok:
        raise RangeUnavailable(f"the edge router could not {what}: {ran.output.strip()[:300]}")
    return ran


def admit(router, addresses: Iterable[str], config: EdgeConfig = EdgeConfig()) -> None:
    refill(router, addresses, (), config)


def _elements(pool: Iterable[str], spent: Iterable[str], config: EdgeConfig) -> list[str]:
    return [_element(config, name, found) for name, found in
            ((config.pool, _addresses(pool)), (config.spent, _addresses(spent))) if found]


def refill(router, pool: Iterable[str], spent: Iterable[str], config: EdgeConfig = EdgeConfig()) -> None:
    lines = _elements(pool, spent, config)
    if lines:
        _ran(router, ["nft", "-f", "-"], "add the round's addresses", stdin="\n".join(lines) + "\n")


def restart(router, pool: Iterable[str], spent: Iterable[str], config: EdgeConfig = EdgeConfig()) -> None:
    lines = [f"flush set {config.family} {config.table} {name}" for name in (config.pool, config.spent)]
    lines += _elements(pool, spent, config)
    _ran(router, ["nft", "-f", "-"], "start the round's addresses afresh", stdin="\n".join(lines) + "\n")


def spend(router, address: str, config: EdgeConfig = EdgeConfig()) -> None:
    [ip] = _addresses([address])
    _ran(router, ["nft", _element(config, config.spent, [ip])], f"mark {ip} spent")
    flushed = router(["conntrack", "-D", "-s", ip])
    if not flushed.ok and flushed.exit_code != NO_ENTRIES:
        raise RangeUnavailable(f"the edge router could not drop {ip}'s connections: {flushed.output.strip()[:300]}")


def listed(router, set_name: str, config: EdgeConfig = EdgeConfig()) -> set[str]:
    ran = _ran(router, ["nft", "-j", "list", "set", config.family, config.table, set_name], f"list {set_name}")
    try:
        document = json.loads(ran.output)
    except ValueError as exc:
        raise RangeUnavailable(f"the edge router listed {set_name} as no JSON: {exc}") from exc
    found: set[str] = set()
    for entry in document.get("nftables") or ():
        for element in (entry.get("set") or {}).get("elem") or ():
            found.add(element if isinstance(element, str) else str((element.get("elem") or {}).get("val", "")))
    return {one for one in found if one}
