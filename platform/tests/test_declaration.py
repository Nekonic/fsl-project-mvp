import pathlib

import pytest
import yaml

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARATION = ROOT / "platform" / "range" / "declaration.yaml"

MARK = "fsl.segment.id"

def built(compose):
    realised = {}
    for key, network in (compose.get("networks") or {}).items():
        labels = ((network or {}).get("labels") or {})
        if labels.get(MARK):
            pools = ((network or {}).get("ipam") or {}).get("config") or [{}]
            realised[labels[MARK]] = {
                "name": labels.get("fsl.segment", ""),
                "origin": labels.get("fsl.origin", ""),
                "subnet": pools[0].get("subnet", ""),
                "key": key,
            }
    return realised

def carriers(compose):
    found = {}
    for key, network in (compose.get("networks") or {}).items():
        segment_id = ((network or {}).get("labels") or {}).get(MARK)
        if segment_id:
            found.setdefault(segment_id, []).append(key)
    return found

def unmarked(compose):
    return sorted(
        key for key, network in (compose.get("networks") or {}).items()
        if not ((network or {}).get("labels") or {}).get(MARK)
    )

def meant(declaration):
    found = {}
    for entry in declaration.get("segments") or []:
        name = entry.get("name") or entry["id"]
        for origin in entry.get("origins") or []:
            found[origin["id"]] = {
                "name": name, "origin": origin["label"],
                "subnet": origin["subnet"], "optional": True,
            }
        if not entry.get("origins"):
            found[entry["id"]] = {
                "name": name, "origin": entry.get("origin") or "",
                "subnet": "", "optional": False,
            }
    return found

def containers(compose):
    return {
        (service.get("container_name") or name)
        for name, service in (compose.get("services") or {}).items()
    }

def drift(compose, declaration):
    realised, declared = built(compose), meant(declaration)
    complaints = []

    for key in unmarked(compose):
        complaints.append(
            f"the network compose builds from {key!r} carries no {MARK}, so "
            f"nothing on it says which declared segment it realises"
        )
    for segment_id, keys in sorted(carriers(compose).items()):
        if len(keys) > 1:
            complaints.append(
                f"compose builds {len(keys)} networks carrying "
                f"{MARK}={segment_id!r} ({', '.join(sorted(keys))}), so "
                f"nothing says which of them the segment is"
            )

    for segment_id in sorted(set(realised) - set(declared)):
        complaints.append(
            f"compose builds the network {segment_id!r} and the declaration "
            f"says nothing about it, so the console would show a segment with "
            f"no name and no origin"
        )
    for segment_id in sorted(set(declared) - set(realised)):
        if declared[segment_id]["optional"] and segment_id != declaration.get("default_origin"):
            continue
        complaints.append(
            f"the declaration names the segment {segment_id!r} and compose "
            f"builds no such network, so nothing will ever stand on it"
        )
    for segment_id in sorted(set(realised) & set(declared)):
        for field in ("name", "origin"):
            if realised[segment_id][field] != declared[segment_id][field]:
                complaints.append(
                    f"segment {segment_id!r}: compose says the {field} is "
                    f"{realised[segment_id][field]!r} and the declaration says "
                    f"{declared[segment_id][field]!r}"
                )
        placed = declared[segment_id]["subnet"]
        if placed and realised[segment_id]["subnet"] != placed:
            complaints.append(
                f"origin {segment_id!r}: compose builds it on "
                f"{realised[segment_id]['subnet'] or 'no subnet'} and the "
                f"declaration places it on {placed}, where GeoIP put its country"
            )

    services = compose.get("services") or {}
    roles = declaration.get("roles") or {}
    mapped = declaration.get("compose") or {}
    for sensing, sensed in sorted((declaration.get("watches") or {}).items()):
        name = mapped.get(sensing) or (roles.get(sensing) or "").removeprefix("fsl-")
        watched = mapped.get(sensed) or (roles.get(sensed) or "").removeprefix("fsl-")
        if name not in services or watched not in services:
            continue
        mode = (services.get(name) or {}).get("network_mode") or ""
        if mode != f"service:{watched}":
            complaints.append(
                f"the {sensing!r} is declared to watch the {sensed!r} and "
                f"compose gives {name!r} network_mode {mode or 'of its own'!r}, "
                f"so it would see none of that host's traffic"
            )

    defined = containers(compose)
    for role, host in sorted((declaration.get("roles") or {}).items()):
        if role in mapped:
            if mapped[role] not in services:
                complaints.append(
                    f"the role {role!r} is declared to be filled by the compose "
                    f"service {mapped[role]!r} and compose defines no such service"
                )
        elif host not in defined:
            complaints.append(
                f"the role {role!r} is declared to be filled by {host!r} and "
                f"compose defines no such container"
            )
    return complaints

def documents():
    return (
        composed.document(),
        yaml.safe_load(DECLARATION.read_text()),
    )

def test_the_declaration_and_the_stack_that_realises_it_agree():
    assert drift(*documents()) == []


def add_network(key, network):
    def mutate(compose, declaration):
        compose["networks"][key] = network(compose)
    return mutate

def set_label(network, label, value):
    def mutate(compose, declaration):
        if value is None:
            del compose["networks"][network]["labels"][label]
        else:
            compose["networks"][network]["labels"][label] = value
    return mutate

def declare(section, key, value):
    def mutate(compose, declaration):
        declaration[section][key] = value
    return mutate

def rename_service(old, new):
    def mutate(compose, declaration):
        compose["services"][new] = compose["services"].pop(old)
    return mutate

def set_sensor_mode(compose, declaration):
    compose["services"]["suricata"]["network_mode"] = "service:juice-shop"

def declare_unbuilt_segment(compose, declaration):
    declaration["segments"].append({"id": "dmz", "name": "DMZ"})

def move_origin(compose, declaration):
    compose["networks"]["edge-br"]["ipam"]["config"][0]["subnet"] = "177.54.145.0/24"

def drop_networks(*keys):
    def mutate(compose, declaration):
        for key in keys:
            del compose["networks"][key]
    return mutate

DRIFTS = {
    "undeclared-network": (
        add_network("edge-cn", lambda compose: {"labels": {
            MARK: "edge-cn", "fsl.segment": "Internet", "fsl.origin": "Shanghai, China"}}),
        ["compose builds the network 'edge-cn' and the declaration says nothing "
         "about it, so the console would show a segment with no name and no origin"],
    ),
    "one-segment-two-networks": (
        add_network("estate-legacy", lambda compose: dict(compose["networks"]["estate"])),
        ["compose builds 2 networks carrying fsl.segment.id='estate' "
         "(estate, estate-legacy), so nothing says which of them the segment is"],
    ),
    "declared-never-built": (
        declare_unbuilt_segment,
        ["the declaration names the segment 'dmz' and compose builds no such "
         "network, so nothing will ever stand on it"],
    ),
    "unmarked-network": (
        set_label("mgmt", MARK, None),
        ["the network compose builds from 'mgmt' carries no fsl.segment.id, so "
         "nothing on it says which declared segment it realises",
         "the declaration names the segment 'mgmt' and compose builds no such "
         "network, so nothing will ever stand on it"],
    ),
    "renamed-segment": (
        set_label("estate", "fsl.segment", "Production"),
        ["segment 'estate': compose says the name is 'Production' and the "
         "declaration says 'Application estate'"],
    ),
    "changed-origin": (
        set_label("edge-us", "fsl.origin", "Seattle"),
        ["segment 'us': compose says the origin is 'Seattle' and the "
         "declaration says 'United States'"],
    ),
    "origin-on-another-subnet": (
        move_origin,
        ["origin 'br': compose builds it on 177.54.145.0/24 and the declaration "
         "places it on 177.54.144.0/24, where GeoIP put its country"],
    ),
    "optional-origin-not-built": (drop_networks("edge-hk"), []),
    "default-origin-not-built": (
        drop_networks("edge-hk", "edge"),
        ["the declaration names the segment 'ru' and compose builds no such "
         "network, so nothing will ever stand on it"],
    ),
    "sensor-off-the-watched-namespace": (
        set_sensor_mode,
        ["the 'sensor' is declared to watch the 'gateway' and compose gives "
         "'suricata' network_mode 'service:juice-shop', so it would see none of "
         "that host's traffic"],
    ),
    "role-with-no-container": (
        declare("roles", "scorer", "fsl-zeek"),
        ["the role 'scorer' is declared to be filled by 'fsl-zeek' and compose "
         "defines no such container"],
    ),
    "role-with-no-service": (
        declare("compose", "sensor", "zeek"),
        ["the role 'sensor' is declared to be filled by the compose service "
         "'zeek' and compose defines no such service"],
    ),
    "service-renamed": (
        rename_service("board-db", "intranet"),
        ["the role 'board-db' is declared to be filled by the compose service "
         "'board-db' and compose defines no such service"],
    ),
}

@pytest.mark.parametrize("mutate, complaints", DRIFTS.values(), ids=list(DRIFTS))
def test_each_kind_of_drift_is_caught(mutate, complaints):
    compose, declaration = documents()
    mutate(compose, declaration)

    assert drift(compose, declaration) == complaints

def test_every_container_is_named_after_the_service_that_builds_it():
    compose, _ = documents()
    session = set(composed.services()) - set(
        yaml.safe_load(composed.COMPOSE.read_text())["services"]
    )
    pinned = {
        name: compose["services"][name]["container_name"]
        for name in session if compose["services"][name].get("container_name")
    }

    assert pinned == {}, (
        f"a session stack runs once per session, and a container name pinned "
        f"in it clashes with the next session's, so Docker refuses the second "
        f"stack: {pinned}"
    )


def test_the_default_origin_has_to_be_somewhere_an_attack_can_start():
    from range.declared import Declaration, Segment

    inside_only = Declaration(
        segments=(Segment(id="estate", name="Application estate", origin=""),),
        default_origin="estate",
    )

    with pytest.raises(ValueError, match="estate"):
        inside_only.check()


def origins():
    _, declaration = documents()
    return [o for entry in declaration["segments"] for o in entry.get("origins") or []]

def test_each_origin_is_its_own_slash_24_away_from_every_network_the_platform_needs():
    import ipaddress

    nets = [ipaddress.ip_network(o["subnet"]) for o in origins()]
    inside = [ipaddress.ip_network(n) for n in ("172.30.0.0/24", "172.31.0.0/24", "10.20.0.0/24")]

    assert all(net.prefixlen == 24 for net in nets)
    assert not [
        (str(a), str(b)) for i, a in enumerate(nets) for b in nets[i + 1:] + inside if a.overlaps(b)
    ]
