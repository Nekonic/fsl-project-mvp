import pathlib

import yaml
import attacker as ATTACKER
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"
DECLARATION = ROOT / "platform" / "range" / "declaration.yaml"

MARK = "fsl.segment.id"

def built(compose):
    realised = {}
    for key, network in (compose.get("networks") or {}).items():
        labels = ((network or {}).get("labels") or {})
        if labels.get(MARK):
            realised[labels[MARK]] = {
                "name": labels.get("fsl.segment", ""),
                "origin": labels.get("fsl.origin", ""),
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
    return {
        entry["id"]: {
            "name": entry.get("name") or entry["id"],
            "origin": entry.get("origin") or "",
        }
        for entry in declaration.get("segments") or []
    }

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
        yaml.safe_load(COMPOSE.read_text()),
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
    compose["networks"]["edge-kp"]["labels"]["fsl.origin"] = "Pyongyang"

    assert drift(compose, declaration) == [
        "segment 'edge-kp': compose says the origin is 'Pyongyang' and the "
        "declaration says 'North Korea'"
    ]

def test_an_origin_taken_off_one_side_only_is_caught():
    compose, declaration = documents()
    del compose["networks"]["edge-hk"]["labels"]["fsl.origin"]

    assert drift(compose, declaration) == [
        "segment 'edge-hk': compose says the origin is '' and the declaration "
        "says 'Kwai Chung, Hong Kong'"
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

def test_the_loader_reads_back_exactly_what_the_file_says():
    from range import declared

    document = yaml.safe_load(DECLARATION.read_text())
    loaded = declared.read()

    assert [(s.id, s.name, s.origin) for s in loaded.segments] == [
        (entry["id"], entry.get("name") or entry["id"], entry.get("origin") or "")
        for entry in document["segments"]
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
    found = unmarked(yaml.safe_load(COMPOSE.read_text()))

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
