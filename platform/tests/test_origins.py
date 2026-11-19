import pathlib
from dataclasses import replace

import pytest

import attacker
from range import declared
from range.ports import Node, Segment, Shape

KALI = "cr-kali"
WAF = "cr-waf"
PF = "cr-edge"

EDGE = Segment(
    id="ru", name="Internet", origin="Russia",
    subnet="5.188.10.0/24", network="cr-internet", gateway="5.188.10.1",
    nodes=(Node(PF, "5.188.10.1"), Node(KALI, "5.188.10.10")),
)
HK = Segment(
    id="hk", name="Internet", origin="Hong Kong",
    subnet="103.152.220.0/24", network="cr-internet", gateway="103.152.220.1",
    nodes=(Node(PF, "103.152.220.1"), Node(KALI, "103.152.220.10")),
)
BR = Segment(
    id="br", name="Internet", origin="Brazil",
    subnet="177.54.144.0/24", network="cr-internet", gateway="177.54.144.1",
    nodes=(Node(PF, "177.54.144.1"), Node(KALI, "177.54.144.10")),
)
ESTATE = Segment(
    id="estate", name="Application estate", origin="",
    subnet="10.30.0.0/24", network="cr-estate",
    nodes=(Node(PF, "10.30.0.1"), Node(WAF, "10.30.0.217")),
)

SHAPE = Shape(segments=(EDGE, HK, BR, ESTATE), sensors=())

@pytest.fixture(autouse=True)
def on_the_attacker_box(settings):
    settings.RANGE = declared.read()
    settings.ATTACKER_SOURCE_CONTAINER = KALI
    settings.ATTACKER_CONTAINER = KALI


def origins(described=SHAPE):
    return attacker.origins(described)

def test_every_declared_network_is_an_origin_in_a_stable_order_with_the_default_marked():
    listed = origins()

    assert [o["id"] for o in listed] == ["br", "hk", "ru"], "rotation depends on a stable order"
    assert [o["id"] for o in listed if o["default"]] == ["ru"]


def test_finding_an_origin_never_names_the_substrate():
    source = pathlib.Path(attacker.__file__).read_text()

    assert "docker" not in source.lower()
    assert "subprocess" not in source

def test_the_default_origin_answers_when_none_was_asked_for():
    assert attacker.find(SHAPE, None)["source_ip"] == "5.188.10.10"

pytestmark = pytest.mark.django_db


def _openstack_shape():
    us = Segment(id="us", name="Internet", origin="United States", subnet="73.0.0.0/24",
                 network="cr-internet", gateway="73.0.0.1",
                 nodes=(Node(PF, "73.0.0.1"), Node(KALI, "73.0.0.10")))
    tw = Segment(id="tw", name="Internet", origin="Taiwan", subnet="120.96.0.0/24",
                 network="cr-internet", gateway="120.96.0.1",
                 nodes=(Node(PF, "120.96.0.1"), Node(KALI, "120.96.0.10")))
    estate = Segment(id="estate", name="Estate", origin="", subnet="10.30.0.0/24",
                     network="cr-estate", nodes=(Node("cr-waf", "10.30.0.217"),))
    return Shape(segments=(us, tw, estate), sensors=())

def test_the_edge_is_the_way_in_and_the_target_is_a_name(settings):
    settings.ATTACKER_TARGET_URL = "http://shop.com"

    found = {o["id"]: o for o in attacker.origins(_openstack_shape())}

    assert set(found) == {"us", "tw"}, "the estate is not an origin"
    assert found["us"]["source_ip"] == "73.0.0.10", "the attack comes from the Kali box"
    assert found["us"]["target_url"] == "http://shop.com", (
        "the target is reached by name through the edge, not by a per-origin WAF address"
    )
    assert found["us"]["address"] == "73.0.0.1", "the way in is the edge's gateway"

def test_an_origin_the_attacker_has_no_address_on_is_not_offered():
    shape = _openstack_shape()
    no_kali = tuple(
        replace(s, nodes=tuple(n for n in s.nodes if n.name != KALI)) if s.id == "tw" else s
        for s in shape.segments
    )

    listed = [o["id"] for o in attacker.origins(Shape(segments=no_kali, sensors=()))]
    assert listed == ["us"]


