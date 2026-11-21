import pytest

from cr.config import BoxConfig
from sandbox import customers
from sandbox.runner import Node, Segment, Shape
from testing.fakes import FakeRunner

KALI = "cr-kali"
CUSTOMERS = "cr-customers"
CONFIG = BoxConfig(attacker=KALI, proxy=KALI, customers=CUSTOMERS, target_url="http://board.com", default_origin="ru")

RU = Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24", network="cr-internet",
             gateway="5.188.10.1", nodes=(Node("cr-edge", "5.188.10.1"), Node(KALI, "5.188.10.10")))
HK = Segment(id="hk", name="Internet", origin="Hong Kong", subnet="103.152.220.0/24", network="cr-internet",
             gateway="103.152.220.1", nodes=(Node("cr-edge", "103.152.220.1"), Node(KALI, "103.152.220.10"),
                                             Node(CUSTOMERS, "103.152.220.12"), Node(CUSTOMERS, "103.152.220.11")))
MGMT = Segment(id="mgmt", name="Management", subnet="172.29.0.0/24", nodes=(Node(CUSTOMERS, "172.29.0.10"),))
SHAPE = Shape(segments=(RU, HK, MGMT), sensors=())


def test_customers_send_only_from_the_customers_box_s_addresses_on_an_origin_never_kali_s():
    assert customers.customer_origins(SHAPE, CONFIG) == [
        {"id": "hk", "label": "Hong Kong", "target_url": "http://board.com",
         "addresses": ["103.152.220.11", "103.152.220.12"]}]


def test_a_customer_command_runs_as_the_customers_account():
    assert customers.as_customer(["curl", "-s", "http://board.com/"]) == [
        "sudo", "setpriv", "--reuid=cr-users", "--regid=cr-users", "--init-groups", "curl", "-s", "http://board.com/"]


def test_starting_writes_the_plan_empties_the_records_and_starts_the_unit():
    box = FakeRunner().answer("systemctl start", "cr.customers=started\n")

    assert customers.run(box, '{"rate": 1}') is True
    [sent] = box.sent
    assert sent.stdin == '{"rate": 1}'
    assert sent.argv[:3] == ["sudo", "sh", "-c"]
    assert f"mv {customers.PLAN}.new {customers.PLAN}" in sent.argv[3]
    assert f": > {customers.RECORDS}" in sent.argv[3]
    assert f"systemctl start {customers.SERVICE}" in sent.argv[3]


def test_a_running_unit_only_takes_the_new_plan():
    box = FakeRunner().answer("systemctl", "cr.customers=changed\n")

    assert customers.run(box, "{}") is False


def test_stopping_removes_the_plan_and_stops_the_unit():
    box = FakeRunner()

    customers.stop(box)

    assert box.sent[0].argv[3] == f"rm -f {customers.PLAN}; systemctl stop {customers.SERVICE}"


def test_records_are_read_between_the_markers_and_a_cut_reply_is_refused():
    box = FakeRunner().answer("tail -c +11", 'cr.records=\n{"marker": "m1"}\n\n=cr.records\n')

    assert customers.records(box, 10, 100) == '{"marker": "m1"}\n'
    with pytest.raises(customers.CustomersUnavailable) as refused:
        customers.records(FakeRunner().answer("tail", "cr.records=\n{\"mar"), 0, 100)
    assert refused.value.code == "range_unavailable"
