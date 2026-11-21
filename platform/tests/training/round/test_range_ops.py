from sandbox import refill, service
from testing import fakerange
from tests.shape import refused


def refill_state(number: int) -> str:
    return refill.standing(service.store(), number).state


def test_staff_build_the_fabric_and_read_what_already_stands(as_staff, cloud):
    built = as_staff.post("/api/staff/range/fabric/").json()

    assert built == {"present": ["cr-attack", "cr-dmz"], "clean": True}


def test_staff_remove_the_fabric(as_staff, cloud):
    gone = as_staff.delete("/api/staff/range/fabric/").json()

    assert cloud.fabric_removed
    assert gone == {"removed": [{"kind": "network", "id": "cr-attack"}, {"kind": "network", "id": "cr-dmz"}]}


def test_staff_remove_what_an_earlier_range_left(as_staff, cloud):
    cloud.leftovers = [("server", "srv-old")]

    assert as_staff.delete("/api/staff/range/leftovers/").json() == {"removed": [{"kind": "server", "id": "srv-old"}]}


def test_filling_the_pool_owes_a_refill_to_every_slot_no_allocation_holds(as_staff, cloud, allocation):
    shown = as_staff.post("/api/staff/range/pool/").json()["slots"]

    assert [(one["slot"], one["refill"]["state"]) for one in shown] == [(1, "idle"), (2, "running")]
    assert refill.standing(service.store(), 2).wargame == "corp"


def test_the_follower_builds_and_configures_a_slot_the_pool_owes(as_staff, cloud):
    as_staff.post("/api/staff/range/pool/")

    service.advance_refills()

    assert [refill_state(number) for number in (1, 2)] == [refill.IDLE, refill.IDLE]
    assert cloud.in_slot(1).configured == 1 and cloud.in_slot(2).ensured == ["corp"]


def test_staff_read_the_servers_each_slot_s_stack_holds(as_staff, cloud):
    shown = as_staff.get("/api/staff/range/pool/").json()["slots"]

    assert [(one["slot"], one["wargame"], [server["status"] for server in one["servers"]]) for one in shown] == [
        (1, "board", ["ACTIVE"]), (2, "corp", ["ACTIVE"])]


def test_emptying_the_pool_drops_owed_refills_and_deletes_every_slot_s_stack(as_staff, cloud):
    as_staff.post("/api/staff/range/pool/")

    gone = as_staff.delete("/api/staff/range/pool/").json()["removed"]

    assert gone == [{"kind": "stack", "id": "stack-1"}, {"kind": "stack", "id": "stack-2"}]
    assert service.advance_refills() == []


def test_a_range_not_built_through_openstack_refuses_the_cloud_operations(as_staff, cloud, monkeypatch):
    monkeypatch.delattr(fakerange.FakeCloud, "ensure_fabric")

    refused(as_staff.post("/api/staff/range/fabric/"), 409, "range_not_cloud")


def test_a_learner_reaches_none_of_the_range_operations(as_learner, cloud):
    for answer in (as_learner.post("/api/staff/range/fabric/"), as_learner.delete("/api/staff/range/pool/"),
                   as_learner.delete("/api/staff/range/leftovers/")):
        refused(answer, 403, "not_staff")
