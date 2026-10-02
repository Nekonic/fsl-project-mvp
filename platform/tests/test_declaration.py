import pathlib

import yaml
import attacker as ATTACKER
import pytest

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
    for sensing, sensed in sorted((declaration.get("watches") or {}).items()):
        name = (roles.get(sensing) or "").removeprefix("fsl-")
        watched = (roles.get(sensed) or "").removeprefix("fsl-")
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
        if host not in defined:
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

def test_a_segment_compose_builds_and_nobody_declared_is_caught():
    compose, declaration = documents()
    compose["networks"]["edge-cn"] = {
        "labels": {MARK: "edge-cn",
                   "fsl.segment": "Internet", "fsl.origin": "Shanghai, China"}
    }

    assert drift(compose, declaration) == [
        "compose builds the network 'edge-cn' and the declaration says nothing "
        "about it, so the console would show a segment with no name and no origin"
    ]

def test_one_segment_marked_on_two_networks_is_caught():
    compose, declaration = documents()
    compose["networks"]["estate-legacy"] = dict(compose["networks"]["estate"])

    assert drift(compose, declaration) == [
        "compose builds 2 networks carrying fsl.segment.id='estate' "
        "(estate, estate-legacy), so nothing says which of them the segment is"
    ], (
        "the second network overwrote the first in the check and both agreed "
        "with the declaration, while the Docker adapter refuses the stack "
        "compose would build from it"
    )

def test_a_segment_declared_and_never_built_is_caught():
    compose, declaration = documents()
    declaration["segments"].append({"id": "dmz", "name": "DMZ"})

    assert drift(compose, declaration) == [
        "the declaration names the segment 'dmz' and compose builds no such "
        "network, so nothing will ever stand on it"
    ]

def test_the_same_segment_named_two_things_is_caught():
    compose, declaration = documents()
    compose["networks"]["estate"]["labels"]["fsl.segment"] = "Production"

    assert drift(compose, declaration) == [
        "segment 'estate': compose says the name is 'Production' and the "
        "declaration says 'Application estate'"
    ]

def test_an_origin_changed_on_one_side_only_is_caught():
    compose, declaration = documents()
    compose["networks"]["edge-us"]["labels"]["fsl.origin"] = "Seattle"

    assert drift(compose, declaration) == [
        "segment 'us': compose says the origin is 'Seattle' and the "
        "declaration says 'United States'"
    ]

def test_an_origin_taken_off_one_side_only_is_caught():
    compose, declaration = documents()
    del compose["networks"]["edge-hk"]["labels"]["fsl.origin"]

    assert drift(compose, declaration) == [
        "segment 'hk': compose says the origin is '' and the declaration "
        "says 'Hong Kong'"
    ]

def test_a_role_no_container_fills_is_caught():
    compose, declaration = documents()
    declaration["roles"]["sensor"] = "fsl-zeek"

    assert drift(compose, declaration) == [
        "the role 'sensor' is declared to be filled by 'fsl-zeek' and compose "
        "defines no such container"
    ]

def test_a_role_whose_container_compose_renamed_is_caught():
    compose, declaration = documents()
    compose["services"]["wiki"]["container_name"] = "fsl-intranet"

    assert drift(compose, declaration) == [
        "the role 'wiki' is declared to be filled by 'fsl-wiki' and compose "
        "defines no such container"
    ]

def test_every_container_is_named_after_the_service_that_builds_it():
    compose, _ = documents()
    odd = {
        name: service.get("container_name")
        for name, service in compose["services"].items()
        if service.get("container_name") != f"fsl-{name}"
    }

    assert odd == {}, (
        f"the acceptance suite recreates a host by stripping 'fsl-' off the "
        f"name the declaration gives it, which stops working here: {odd}"
    )

def test_the_board_and_its_database_are_declared_so_openstack_can_find_them():
    _, declaration = documents()

    assert declaration["roles"].get("board") == "fsl-board"
    assert declaration["roles"].get("board-db") == "fsl-board-db"

def test_the_loader_reads_back_exactly_what_the_file_says():
    from range import declared

    document = yaml.safe_load(DECLARATION.read_text())
    loaded = declared.read()

    assert [(s.id, s.name, s.origin) for s in loaded.segments] == [
        row
        for entry in document["segments"]
        for row in (
            [(origin["id"], entry["name"], origin["label"]) for origin in entry["origins"]]
            if entry.get("origins")
            else [(entry["id"], entry.get("name") or entry["id"], entry.get("origin") or "")]
        )
    ]
    assert [o.id for o in loaded.origins] == [
        origin["id"] for entry in document["segments"] for origin in entry.get("origins") or []
    ]
    assert loaded.roles == document["roles"]

def test_the_declaration_carries_nothing_the_substrate_assigns():
    document = yaml.safe_load(DECLARATION.read_text())
    assigned = {"subnet", "gateway", "address", "nodes", "network"}

    stated = {key for entry in document["segments"] for key in entry}

    assert not stated & assigned, (
        f"the declaration states {sorted(stated & assigned)}, which the "
        f"substrate hands out; a declared address that disagrees with the one "
        f"the range actually gave is a lie the console would draw"
    )


def test_the_declaration_says_where_an_attack_starts_from():
    from range import declared

    found = declared.read()

    assert found.default_origin, (
        "which segment an attack leaves from by default is a fact about the "
        "range, not about the substrate; it was decided by comparing a Docker "
        "network name, so no segment was default on any other substrate"
    )
    assert found.default_origin in {s.id for s in found.segments}

def test_the_default_origin_has_to_be_somewhere_an_attack_can_start():
    from range.declared import Declaration, Segment

    inside_only = Declaration(
        segments=(Segment(id="estate", name="Application estate", origin=""),),
        default_origin="estate",
    )

    with pytest.raises(ValueError, match="estate"):
        inside_only.check()

def test_no_substrate_name_decides_where_an_attack_starts():
    import pathlib

    source = pathlib.Path(ATTACKER.__file__).read_text()

    assert "ATTACKER_NETWORK" not in source, (
        "the default origin was chosen by matching settings.ATTACKER_NETWORK, "
        "which is the literal string fsl_edge"
    )


def test_a_renamed_network_is_still_the_segment_it_says_it_is():
    compose, declaration = documents()
    compose["networks"]["estate"]["name"] = "corp-estate"

    assert drift(compose, declaration) == [], (
        "a network is bound to its segment by the mark it carries, so what the "
        "range happens to call it is nobody's business"
    )

def test_a_network_with_nothing_to_bind_it_is_caught():
    compose, declaration = documents()
    del compose["networks"]["mgmt"]["labels"][MARK]

    assert drift(compose, declaration) == [
        "the network compose builds from 'mgmt' carries no fsl.segment.id, so "
        "nothing on it says which declared segment it realises",
        "the declaration names the segment 'mgmt' and compose builds no such "
        "network, so nothing will ever stand on it",
    ]

def test_every_network_the_stack_builds_says_which_segment_it_is():
    found = unmarked(composed.document())

    assert found == [], (
        f"nothing on {found} says which declared segment it realises, so "
        f"the adapter has to guess from the name it happens to have"
    )

def test_the_declaration_says_what_the_sensor_watches():
    from range import declared

    found = declared.read()

    assert found.watches, (
        "which host the sensor sees traffic for was read off Docker's "
        "NetworkMode, and Neutron has no such fact: on Nova the console would "
        "have shown no sensor at all, or the sketch's guess"
    )
    for sensing, sensed in found.watches.items():
        assert sensing in found.roles and sensed in found.roles

def test_a_sensor_watching_a_role_nobody_fills_is_refused():
    from range.declared import Declaration

    with pytest.raises(ValueError, match="gateway"):
        Declaration(roles={"sensor": "fsl-suricata"},
                    watches={"sensor": "gateway"}).check()

def test_a_sensor_compose_takes_out_of_the_namespace_it_watches_is_caught():
    compose, declaration = documents()
    compose["services"]["suricata"]["network_mode"] = "service:juice-shop"

    assert drift(compose, declaration) == [
        "the 'sensor' is declared to watch the 'gateway' and compose gives "
        "'suricata' network_mode 'service:juice-shop', so it would see none of "
        "that host's traffic"
    ]

def test_a_sensor_compose_gives_its_own_stack_is_caught():
    compose, declaration = documents()
    del compose["services"]["suricata"]["network_mode"]

    assert drift(compose, declaration) == [
        "the 'sensor' is declared to watch the 'gateway' and compose gives "
        "'suricata' network_mode 'of its own', so it would see none of that "
        "host's traffic"
    ]

def test_the_declaration_says_where_the_defended_site_is():
    from range import declared

    site = declared.read().defended_site

    assert (site.label, site.lat, site.lon) == ("Seoul, Korea", 37.5665, 126.978), (
        "the target sits on a lab address that geolocates nowhere useful, so "
        "where the map draws it has to be declared"
    )

@pytest.mark.parametrize("lat, lon", [(91.0, 0.0), (-90.5, 0.0), (0.0, 180.5), (0.0, -181.0)])
def test_a_defended_site_off_the_globe_is_refused(lat, lon):
    from range.declared import Declaration, Site

    with pytest.raises(ValueError, match="defended_site"):
        Declaration(defended_site=Site(label="Nowhere", lat=lat, lon=lon)).check()

def test_a_declaration_without_a_defended_site_still_loads(tmp_path):
    from range import declared

    written = tmp_path / "declaration.yaml"
    written.write_text("segments:\n  - id: edge\n    origin: Moscow, Russia\n")

    assert declared.read(written).defended_site is None

def origins():
    _, declaration = documents()
    return [o for entry in declaration["segments"] for o in entry.get("origins") or []]

def test_thirty_countries_are_declared_in_the_order_of_their_traffic():
    found = origins()
    shares = [o["share"] for o in found]

    assert len(found) == 30
    assert shares == sorted(shares, reverse=True)
    assert [o["id"] for o in found] == [o["country"].lower() for o in found]
    assert len({o["id"] for o in found}) == 30

def test_a_hundred_addresses_go_to_the_countries_by_their_share():
    found = origins()

    assert [o["addresses"] for o in found] == [
        35, 6, 5, 5, 5, 4, 4, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2,
        1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    ], (
        "the frozen addresses column is the largest-remainder split of 100 by "
        "the traffic shares, at least one each; it no longer sums to that"
    )

def test_each_origin_is_its_own_slash_24_away_from_every_network_the_platform_needs():
    import ipaddress

    nets = [ipaddress.ip_network(o["subnet"]) for o in origins()]
    inside = [ipaddress.ip_network(n) for n in ("172.30.0.0/24", "172.31.0.0/24", "10.20.0.0/24")]

    assert all(net.prefixlen == 24 for net in nets)
    assert not [
        (str(a), str(b)) for i, a in enumerate(nets) for b in nets[i + 1:] + inside if a.overlaps(b)
    ]

def test_an_origin_states_only_what_places_it():
    stated = {key for o in origins() for key in o}

    assert stated == {"id", "label", "country", "subnet", "share", "addresses"}, stated

def test_an_origin_compose_builds_on_another_subnet_is_caught():
    compose, declaration = documents()
    compose["networks"]["edge-br"]["ipam"]["config"][0]["subnet"] = "177.54.145.0/24"

    assert drift(compose, declaration) == [
        "origin 'br': compose builds it on 177.54.145.0/24 and the declaration "
        "places it on 177.54.144.0/24, where GeoIP put its country"
    ]

def test_compose_may_build_some_origins_but_always_the_default_one():
    compose, declaration = documents()
    del compose["networks"]["edge-hk"]
    without_hk = drift(compose, declaration)
    del compose["networks"]["edge"]

    assert without_hk == []
    assert drift(compose, declaration) == [
        "the declaration names the segment 'ru' and compose builds no such "
        "network, so nothing will ever stand on it"
    ]
