from __future__ import annotations

from dataclasses import dataclass

from range.declared import Declaration
from range.ports import RangeUnavailable

TAG = "cr.segment.id"
SLOT_TAG = "cr.slot"
KEYPAIR = "cr-platform"
MANAGEMENT = "mgmt"
CARRIED = (MANAGEMENT,)
REACH_GROUP = "cr-reach"
MANAGEMENT_GROUP = "cr-mgmt"
EGRESS_GROUP = "cr-egress"
GROUPS = (REACH_GROUP, MANAGEMENT_GROUP, EGRESS_GROUP)
RETIRED_GROUPS = ("cr-range", "cr-build")
COLLECTOR_PORT = 5140
NTP_PORT = 123


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
    ntp: bool = False
    present: tuple[str, ...] = ()
    drifted: tuple[str, ...] = ()
    leftovers: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.networks or self.subnets or self.keypair or self.groups
                    or self.reach or self.ntp or self.drifted)


def network_name(segment: str) -> str:
    return f"cr-{segment}"


def network_tags(segment: str) -> list[str]:
    return [f"{TAG}={segment}"]


def slot_of(network: dict) -> int:
    for tag in network.get("tags") or []:
        if tag.startswith(f"{SLOT_TAG}="):
            value = tag.split("=", 1)[1]
            return int(value) if value.isdigit() else 0
    return 1


def segment_of(network: dict) -> str | None:
    for tag in network.get("tags") or []:
        if tag.startswith(f"{TAG}="):
            return tag.split("=", 1)[1]
    return None


def carried(declaration: Declaration) -> list[str]:
    declared = {segment.id for segment in declaration.segments}
    return [segment for segment in CARRIED if segment in declared]


def wanted(declaration: Declaration, inside: dict[str, str]) -> tuple[Subnet, ...]:
    unplaced = [segment for segment in carried(declaration) if segment not in inside]
    if unplaced:
        raise RangeUnavailable(
            f"the declaration names {unplaced} and the fabric has no subnet for them; "
            f"set network.{', network.'.join(unplaced)} in cloud.yaml"
        )
    return tuple(Subnet(segment, f"cr-{segment}", inside[segment], dhcp=True, gateway=False)
                 for segment in carried(declaration))


def retired(network: dict) -> bool:
    segment = segment_of(network)
    return segment is not None and (segment not in CARRIED or slot_of(network) != 1)


def bound(declaration: Declaration, networks: list) -> dict[str, dict]:
    segments = carried(declaration)
    return {segment_of(network): network for network in networks
            if segment_of(network) in segments and slot_of(network) == 1}


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


def _same_key(one: str, other: str) -> bool:
    return one.split()[:2] == other.split()[:2]


def plan(declaration: Declaration, networks: list, subnets: list, keypairs: list,
         public_key: str, groups: list = (), reached: bool = True,
         inside: dict[str, str] | None = None) -> Plan:
    want = wanted(declaration, inside or {})
    segments = carried(declaration)
    drifted, leftovers, held = [], [], {}
    for network in networks:
        segment = segment_of(network)
        if segment is None:
            if network["name"] in {network_name(s) for s in segments}:
                leftovers.append(f"network {network['name']} carries no {TAG}")
        elif retired(network):
            leftovers.append(f"network {network['name']} carries {TAG}={segment}, which the "
                             f"range host's slots replaced")
        elif segment in held:
            drifted.append(f"networks {held[segment]['name']} and {network['name']} both "
                           f"carry {TAG}={segment}")
        else:
            held[segment] = network
    missing = [segment for segment in segments if segment not in held]
    create, present = [], []
    for subnet in want:
        network = held.get(subnet.segment)
        found = network and next(
            (s for s in subnets if s["network_id"] == network["id"] and s["cidr"] == subnet.cidr), None)
        if not found:
            create.append(subnet)
            continue
        differences = _differs(found, subnet)
        if differences:
            drifted.append(f"subnet {subnet.name} {subnet.cidr}: {', '.join(differences)}")
        else:
            present.append(subnet.name)
    declared_cidrs = {(held[s.segment]["id"], s.cidr) for s in want if s.segment in held}
    for network in held.values():
        for found in subnets:
            if found["network_id"] == network["id"] and (network["id"], found["cidr"]) not in declared_cidrs:
                leftovers.append(f"subnet {found.get('name') or found['id']} {found['cidr']} on "
                                 f"{network['name']} is declared by nothing")
    key = next((k for k in keypairs if k["name"] == KEYPAIR), None)
    if key and not _same_key(key["public_key"], public_key):
        drifted.append(f"keypair {KEYPAIR} holds another public key")
    named = {name: [g for g in groups if g["name"] == name] for name in GROUPS}
    drifted += [f"{len(found)} security groups are called {name}"
                for name, found in named.items() if len(found) > 1]
    return Plan(
        networks=tuple(missing),
        subnets=tuple(create),
        keypair=key is None,
        groups=tuple(name for name, found in named.items() if not found),
        reach=not reached,
        ntp=not _serves_time(named[REACH_GROUP], named[MANAGEMENT_GROUP]),
        present=tuple(present),
        drifted=tuple(dict.fromkeys(drifted)),
        leftovers=tuple(leftovers),
    )


def teardown(declaration: Declaration, networks: list, subnets: list,
             keypairs: list, groups: list = ()) -> list[tuple[str, str]]:
    owned = [network["id"] for network in networks if segment_of(network) is not None]
    return (
        [("subnet", s["id"]) for s in subnets if s["network_id"] in set(owned)]
        + [("network", network_id) for network_id in owned]
        + [("keypair", k["name"]) for k in keypairs if k["name"] == KEYPAIR]
        + [("group", g["id"]) for name in (*reversed(GROUPS), *RETIRED_GROUPS)
           for g in groups if g["name"] == name]
    )


def ntp_rule(reach: str, management: str) -> dict:
    return {"security_group_id": reach, "direction": "ingress", "ethertype": "IPv4",
            "protocol": "udp", "port_range_min": NTP_PORT, "port_range_max": NTP_PORT,
            "remote_group_id": management}


def _serves_time(reach: list[dict], management: list[dict]) -> bool:
    if len(reach) != 1 or len(management) != 1:
        return False
    wanted_rule = ntp_rule(reach[0]["id"], management[0]["id"])
    return any(all(rule.get(key) == value for key, value in wanted_rule.items())
               for rule in reach[0].get("security_group_rules") or [])


def _collector_rule(rule: dict) -> bool:
    return (rule.get("direction") == "ingress" and rule.get("protocol") == "udp"
            and rule.get("port_range_min") == COLLECTOR_PORT)


def hearing(group: dict, senders: list[str]) -> tuple[list[dict], list[str]]:
    wanted_prefixes = [f"{sender}/32" for sender in senders]
    heard = {
        rule.get("remote_ip_prefix"): rule["id"]
        for rule in group.get("security_group_rules") or [] if _collector_rule(rule)
    }
    create = [
        {"security_group_id": group["id"], "direction": "ingress", "ethertype": "IPv4",
         "protocol": "udp", "port_range_min": COLLECTOR_PORT,
         "port_range_max": COLLECTOR_PORT, "remote_ip_prefix": prefix}
        for prefix in wanted_prefixes if prefix not in heard
    ]
    return create, [rule for prefix, rule in heard.items() if prefix not in wanted_prefixes]
