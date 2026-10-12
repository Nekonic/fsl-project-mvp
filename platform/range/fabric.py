from __future__ import annotations

from dataclasses import dataclass

from range.declared import Declaration
from range.ports import RangeUnavailable

TAG = "fsl.segment.id"
SLOT_TAG = "fsl.slot"
KEYPAIR = "fsl-platform"
MANAGEMENT = "mgmt"
NO_DEFAULT_ROUTE = {MANAGEMENT}
SHARED = {MANAGEMENT}
RANGE_GROUP = "fsl-range"
REACH_GROUP = "fsl-reach"
MANAGEMENT_GROUP = "fsl-mgmt"
GROUPS = (RANGE_GROUP, REACH_GROUP, MANAGEMENT_GROUP)
COLLECTOR_PORT = 5140

@dataclass(frozen=True)
class Subnet:
    segment: str
    name: str
    cidr: str
    dhcp: bool
    gateway: bool
    slot: int = 1

    @property
    def carrier(self) -> str:
        return carrier(self.segment, self.slot)

@dataclass(frozen=True)
class Plan:
    networks: tuple[str, ...] = ()
    subnets: tuple[Subnet, ...] = ()
    keypair: bool = False
    groups: tuple[str, ...] = ()
    reach: bool = False
    present: tuple[str, ...] = ()
    drifted: tuple[str, ...] = ()
    leftovers: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.networks or self.subnets or self.keypair or self.groups
                    or self.reach or self.drifted)

def suffixed(name: str, slot: int = 1) -> str:
    return name if slot == 1 else f"{name}-{slot}"

def carrier(segment: str, slot: int = 1) -> str:
    return suffixed(segment, slot)

def network_name(segment: str, slot: int = 1) -> str:
    return f"fsl-{carrier(segment, slot)}"

def network_tags(segment: str, slot: int = 1) -> list[str]:
    return [f"{TAG}={segment}"] + ([f"{SLOT_TAG}={slot}"] if slot > 1 else [])

def owner(segment: str, slot: int) -> int:
    return 1 if segment in SHARED else slot

def slot_of(network: dict) -> int:
    for tag in network.get("tags") or []:
        if tag.startswith(f"{SLOT_TAG}="):
            value = tag.split("=", 1)[1]
            return int(value) if value.isdigit() else 0
    return 1

def _inside(declaration: Declaration) -> list[str]:
    origins = {origin.id for origin in declaration.origins}
    return [segment.id for segment in declaration.segments if segment.id not in origins]

def wanted(declaration: Declaration, inside: dict[str, str], slot: int = 1) -> tuple[Subnet, ...]:
    unplaced = [segment for segment in _inside(declaration) if segment not in inside]
    if unplaced:
        raise RangeUnavailable(
            f"the declaration names {unplaced} and the fabric has no subnet for them; "
            f"set network.{', network.'.join(unplaced)} in cloud.yaml"
        )
    return tuple(
        Subnet(origin.segment, suffixed(f"fsl-{origin.id}", slot), origin.subnet, dhcp=False,
               gateway=True, slot=slot)
        for origin in declaration.origins
    ) + tuple(
        Subnet(segment, suffixed(f"fsl-{segment}", slot), inside[segment], dhcp=True,
               gateway=segment not in NO_DEFAULT_ROUTE, slot=slot)
        for segment in _inside(declaration) if owner(segment, slot) == slot
    )

def _segment_of(network: dict) -> str | None:
    for tag in network.get("tags") or []:
        if tag.startswith(f"{TAG}="):
            return tag.split("=", 1)[1]
    return None

def _same_key(one: str, other: str) -> bool:
    return one.split()[:2] == other.split()[:2]

def _segments(declaration) -> list[str]:
    return list(dict.fromkeys(
        [origin.segment for origin in declaration.origins] + _inside(declaration)
    ))

def _bound(declaration, networks, slot: int = 1):
    segments = _segments(declaration)
    bound: dict[str, dict] = {}
    drifted, leftovers = [], []
    for network in networks:
        segment = _segment_of(network)
        if segment is None:
            if slot == 1 and network["name"] in {network_name(s) for s in segments}:
                leftovers.append(f"network {network['name']} carries no {TAG}")
        elif segment not in segments:
            if slot == 1:
                leftovers.append(
                    f"network {network['name']} carries {TAG}={segment}, which the "
                    f"declaration does not name"
                )
        elif slot_of(network) != owner(segment, slot):
            continue
        elif segment in bound:
            drifted.append(
                f"networks {bound[segment]['name']} and {network['name']} both "
                f"carry {TAG}={segment}"
            )
        else:
            bound[segment] = network
    return segments, bound, drifted, leftovers

def bound(declaration: Declaration, networks: list, slot: int = 1) -> dict[str, dict]:
    return _bound(declaration, networks, slot)[1]

def _beyond(declaration: Declaration, networks: list, slots: int) -> list[str]:
    segments = set(_segments(declaration))
    return [
        f"network {network['name']} carries {SLOT_TAG}={slot_of(network) or '?'}, "
        f"beyond the {slots} slot(s) the cloud settings ask for"
        for network in networks
        if _segment_of(network) in segments
        and not 1 <= slot_of(network) <= (1 if _segment_of(network) in SHARED else slots)
    ]

def _differs(found: dict, subnet: Subnet) -> list[str]:
    differences = []
    if bool(found.get("enable_dhcp")) != subnet.dhcp:
        differences.append(
            f"dhcp is {'on' if found.get('enable_dhcp') else 'off'}, declared "
            f"{'on' if subnet.dhcp else 'off'}"
        )
    if (found.get("gateway_ip") is not None) != subnet.gateway:
        differences.append(
            f"gateway is {found.get('gateway_ip')}, declared "
            f"{'one' if subnet.gateway else 'none'}"
        )
    return differences

def plan(declaration: Declaration, networks: list, subnets: list, keypairs: list,
         public_key: str, groups: list = (), reached: bool = True,
         inside: dict[str, str] | None = None, slots: int = 1) -> Plan:
    numbers = range(1, max(1, slots) + 1)
    want = tuple(subnet for n in numbers for subnet in wanted(declaration, inside or {}, n))
    bound_in, missing, drifted, leftovers = {}, [], [], []
    for n in numbers:
        segments, bound_in[n], drifted_n, leftovers_n = _bound(declaration, networks, n)
        drifted += drifted_n
        leftovers += leftovers_n
        missing += [carrier(segment, n) for segment in segments
                    if segment not in bound_in[n] and owner(segment, n) == n]
    leftovers += _beyond(declaration, networks, max(1, slots))
    create, present = [], []
    for subnet in want:
        network = bound_in[subnet.slot].get(subnet.segment)
        found = network and next(
            (s for s in subnets
             if s["network_id"] == network["id"] and s["cidr"] == subnet.cidr),
            None,
        )
        if not found:
            create.append(subnet)
            continue
        differences = _differs(found, subnet)
        if differences:
            drifted.append(f"subnet {subnet.name} {subnet.cidr}: {', '.join(differences)}")
        else:
            present.append(subnet.name)
    declared_cidrs = {
        (bound_in[subnet.slot][subnet.segment]["id"], subnet.cidr)
        for subnet in want if subnet.segment in bound_in[subnet.slot]
    }
    carriers = {network["id"]: network for n in numbers for network in bound_in[n].values()}
    for network in carriers.values():
        for found in subnets:
            if found["network_id"] == network["id"] and (network["id"], found["cidr"]) not in declared_cidrs:
                leftovers.append(
                    f"subnet {found.get('name') or found['id']} {found['cidr']} on "
                    f"{network['name']} is declared by nothing"
                )
    key = next((k for k in keypairs if k["name"] == KEYPAIR), None)
    if key and not _same_key(key["public_key"], public_key):
        drifted.append(f"keypair {KEYPAIR} holds another public key")
    named = {name: [g for g in groups if g["name"] == name] for name in GROUPS}
    drifted += [
        f"{len(found)} security groups are called {name}"
        for name, found in named.items() if len(found) > 1
    ]
    return Plan(
        networks=tuple(missing),
        subnets=tuple(create),
        keypair=key is None,
        groups=tuple(name for name, found in named.items() if not found),
        reach=not reached,
        present=tuple(present),
        drifted=tuple(dict.fromkeys(drifted)),
        leftovers=tuple(leftovers),
    )

def teardown(declaration: Declaration, networks: list, subnets: list,
             keypairs: list, groups: list = ()) -> list[tuple[str, str]]:
    segments = set(_segments(declaration))
    owned = [network["id"] for network in networks if _segment_of(network) in segments]
    return (
        [("subnet", s["id"]) for s in subnets if s["network_id"] in set(owned)]
        + [("network", network_id) for network_id in owned]
        + [("keypair", k["name"]) for k in keypairs if k["name"] == KEYPAIR]
        + [("group", g["id"]) for name in reversed(GROUPS) for g in groups if g["name"] == name]
    )

def group_of(segment: str) -> str:
    return MANAGEMENT_GROUP if segment == MANAGEMENT else RANGE_GROUP

def _collector_rule(rule: dict) -> bool:
    return (rule.get("direction") == "ingress" and rule.get("protocol") == "udp"
            and rule.get("port_range_min") == COLLECTOR_PORT)

def hearing(group: dict, senders: list[str], kept=()) -> tuple[list[dict], list[str]]:
    wanted = [f"{sender}/32" for sender in senders]
    staying = set(wanted) | {f"{address}/32" for address in kept}
    heard = {
        rule.get("remote_ip_prefix"): rule["id"]
        for rule in group.get("security_group_rules") or [] if _collector_rule(rule)
    }
    create = [
        {"security_group_id": group["id"], "direction": "ingress", "ethertype": "IPv4",
         "protocol": "udp", "port_range_min": COLLECTOR_PORT,
         "port_range_max": COLLECTOR_PORT, "remote_ip_prefix": prefix}
        for prefix in wanted if prefix not in heard
    ]
    return create, [rule for prefix, rule in heard.items() if prefix not in staying]
