import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"
DECLARATION = ROOT / "platform" / "range" / "declaration.yaml"

def built(compose):
    return {
        name: {
            "name": (network.get("labels") or {}).get("fsl.segment", ""),
            "origin": (network.get("labels") or {}).get("fsl.origin", ""),
        }
        for name, network in (compose.get("networks") or {}).items()
    }

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
        "labels": {"fsl.segment": "Internet", "fsl.origin": "Shanghai, China"}
    }

    assert drift(compose, declaration) == [
        "compose builds the network 'edge-cn' and the declaration says nothing "
        "about it, so the console would show a segment with no name and no origin"
    ]

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
