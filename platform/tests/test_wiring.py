import pathlib

from range import declared, openstack, sandbox, wiring
from tests import fakecloud

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()
PARAMETERS = {"key_name": "cr-platform", "control_network": "net-mgmt", "control_group": "g-cr-mgmt",
              "senders_group": "g-cr-senders",
              **{f"{kind}_{role}": f"{kind}-{role}" for kind in ("image", "flavor") for role in sandbox.ROLES},
              **{f"group_{lan}": f"g-lan-{lan}" for lan in ("internet", "dmz", "web-outer", "web-inner", "mgmt")}}


def neutron(wargame="board", slot=1):
    cloud = fakecloud.Cloud()
    plan = sandbox.plan(sandbox.read(ROOT, wargame), slot, DECLARED.origins, DECLARED.default_origin, "10.31.0.2")
    cloud.create_stack(openstack.stack_body(plan, openstack.template(plan), PARAMETERS, "digest", 30))
    tag = f"cr.slot={slot}"
    return ([one for one in cloud.networks if tag in one["tags"]], cloud.subnets,
            [one for one in cloud.ports if tag in one["tags"]])


def wired(wargame="board", slot=1, without=()):
    networks, subnets, ports = neutron(wargame, slot)
    kept = [port for port in ports if not {f"cr.device={device}" for device in without} & set(port["tags"])]
    placed = sandbox.addressed(sandbox.read(ROOT, wargame).ports, DECLARED.origins, DECLARED.default_origin)
    return wiring.from_neutron(networks, subnets, kept, {port.device: port.extra for port in placed if port.extra})


def read_slot():
    return wired().interfaces()


def test_neutron_s_ports_give_every_device_its_lans_and_addresses_and_leave_out_the_control_network():
    found = {(one.host, one.name, one.address, one.segment) for one in read_slot()}

    assert {("cr-kali", "internet", "5.188.10.10/24", "internet"), ("cr-kali", "internet", "73.0.0.10/24", "internet"),
            ("cr-edge", "internet", "121.134.88.42/29", "internet"), ("cr-edge", "dmz", "10.30.0.1/24", "dmz"),
            ("cr-waf", "dmz", "10.30.0.247/24", "dmz"), ("cr-waf", "web-outer", "10.30.128.247/24", "web-outer"),
            ("cr-waf", "mgmt", "172.29.0.12/24", "mgmt"), ("board", "web-inner", "10.30.128.59/24", "web-inner"),
            ("log-server", "mgmt", "172.29.0.10/24", "mgmt")} <= found
    assert not [one for one in found if one[2].startswith("10.31.")], "the platform's control network is not drawn"


def test_a_slot_s_wiring_is_read_from_neutron_over_http(monkeypatch):
    cloud = fakecloud.Cloud()
    fakecloud.serving(cloud)
    openstack.forget()
    runner = fakecloud.Runner()
    monkeypatch.setattr(openstack, "execute", runner)
    runner.answer(sandbox.READY, "ready\n")
    adapter = fakecloud.adapter(cloud, slots=1)
    adapter.ensure_slot()

    assert {(one.host, one.address) for one in adapter.wiring().interfaces()} == {
        (one.host, one.address) for one in read_slot()}
    openstack.forget()


