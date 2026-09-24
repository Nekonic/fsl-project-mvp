import pytest

import attacker
from range.ports import Node, Segment, Shape

ESTATE = Segment(
    id="estate", name="Application estate", origin="",
    subnet="172.30.0.0/24", network="fsl_estate",
    nodes=(Node("fsl-proxy", "172.30.0.7"), Node("fsl-waf", "172.30.0.9")),
)

def test_a_stack_with_no_origin_does_not_name_one_nobody_asked_for():
    with pytest.raises(attacker.UnknownOrigin) as raised:
        attacker.find(Shape(segments=(ESTATE,), sensors=()), None)

    assert "None" not in str(raised.value), raised.value
