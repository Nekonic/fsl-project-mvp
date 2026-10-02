from __future__ import annotations

from dataclasses import dataclass

from range.declared import Declaration
from range.ports import RangeUnavailable

TAG = "fsl.segment.id"
KEYPAIR = "fsl-platform"
MANAGEMENT = "mgmt"
INSIDE = {"estate": "10.30.0.0/24", MANAGEMENT: "10.31.0.0/24"}
NO_DEFAULT_ROUTE = {MANAGEMENT}
RANGE_GROUP = "fsl-range"
REACH_GROUP = "fsl-reach"
GROUPS = (RANGE_GROUP, REACH_GROUP)
COLLECTOR_PORT = 5140

@dataclass(frozen=True)
class Subnet:
    segment: str
    name: str
    cidr: str
    dhcp: bool
    gateway: bool

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

def wanted(declaration: Declaration) -> tuple[Subnet, ...]:
    origins = {origin.id for origin in declaration.origins}
    inside = [segment.id for segment in declaration.segments if segment.id not in origins]
    unplaced = [segment for segment in inside if segment not in INSIDE]
    if unplaced:
        raise RangeUnavailable(
            f"the declaration names {unplaced} and the fabric has no subnet for them"
        )
    return tuple(
        Subnet(origin.segment, f"fsl-{origin.id}", origin.subnet, dhcp=False, gateway=True)
        for origin in declaration.origins
    ) + tuple(
        Subnet(segment, f"fsl-{segment}", INSIDE[segment], dhcp=True,
               gateway=segment not in NO_DEFAULT_ROUTE)
        for segment in inside
    )

def _segment_of(network: dict) -> str | None:
    for tag in network.get("tags") or []:
        if tag.startswith(f"{TAG}="):
            return tag.split("=", 1)[1]
    return None

def _same_key(one: str, other: str) -> bool:
    return one.split()[:2] == other.split()[:2]

def _bound(declaration, networks):
    want = wanted(declaration)
    segments = list(dict.fromkeys(subnet.segment for subnet in want))
    bound: dict[str, dict] = {}
    drifted, leftovers = [], []
    for network in networks:
        segment = _segment_of(network)
        if segment is None:
            if network["name"] in {f"fsl-{s}" for s in segments}:
                leftovers.append(f"network {network['name']} carries no {TAG}")
        elif segment not in segments:
            leftovers.append(
                f"network {network['name']} carries {TAG}={segment}, which the "
                f"declaration does not name"
            )
        elif segment in bound:
            drifted.append(
                f"networks {bound[segment]['name']} and {network['name']} both "
                f"carry {TAG}={segment}"
            )
        else:
            bound[segment] = network
    return want, segments, bound, drifted, leftovers

def bound(declaration: Declaration, networks: list) -> dict[str, dict]:
    return _bound(declaration, networks)[2]

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
         public_key: str, groups: list = (), reached: bool = True) -> Plan:
    want, segments, bound, drifted, leftovers = _bound(declaration, networks)
    create, present = [], []
    for subnet in want:
        network = bound.get(subnet.segment)
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
    declared_cidrs = {(subnet.segment, subnet.cidr) for subnet in want}
    for segment, network in bound.items():
        for found in subnets:
            if found["network_id"] == network["id"] and (segment, found["cidr"]) not in declared_cidrs:
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
        networks=tuple(segment for segment in segments if segment not in bound),
        subnets=tuple(create),
        keypair=key is None,
        groups=tuple(name for name, found in named.items() if not found),
        reach=not reached,
        present=tuple(present),
        drifted=tuple(drifted),
        leftovers=tuple(leftovers),
    )

def teardown(declaration: Declaration, networks: list, subnets: list,
             keypairs: list, groups: list = ()) -> list[tuple[str, str]]:
    _, _, bound, _, _ = _bound(declaration, networks)
    owned = {network["id"] for network in bound.values()}
    return (
        [("subnet", s["id"]) for s in subnets if s["network_id"] in owned]
        + [("network", network_id) for network_id in owned]
        + [("keypair", k["name"]) for k in keypairs if k["name"] == KEYPAIR]
        + [("group", g["id"]) for name in GROUPS for g in groups if g["name"] == name]
    )

def _collector_rule(rule: dict) -> bool:
    return (rule.get("direction") == "ingress" and rule.get("protocol") == "udp"
            and rule.get("port_range_min") == COLLECTOR_PORT)

def hearing(group: dict, senders: list[str]) -> tuple[list[dict], list[str]]:
    wanted = [f"{sender}/32" for sender in senders]
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
    return create, [rule for prefix, rule in heard.items() if prefix not in wanted]
