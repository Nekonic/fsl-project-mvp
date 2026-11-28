import ipaddress
import json
import pathlib

import pytest

from sandbox import declaration
from sandbox import openstack, stack_plan

ROOT = pathlib.Path(__file__).resolve().parents[3]
DECLARED = declaration.read()


def planned(wargame="board", slot=3):
    return stack_plan.plan(stack_plan.read(ROOT, wargame), slot, DECLARED.origins, DECLARED.default_origin,
                        "10.31.0.2")


def rendered(wargame="board", slot=3, zone=""):
    return openstack.template(planned(wargame, slot), zone)


def of_type(document, kind):
    return {name: resource["properties"] for name, resource in document["resources"].items()
            if resource["type"] == kind}


def ports_of(document, node):
    return {name: port for name, port in of_type(document, "OS::Neutron::Port").items()
            if f"cr.node={node}" in port["tags"]}


def lan_of(port):
    return next(tag.split("=", 1)[1] for tag in port["tags"] if tag.startswith("cr.lan="))


@pytest.fixture(params=["board", "corp"])
def stack(request):
    return rendered(request.param)


def test_a_slot_is_one_net_per_lan_and_nothing_routes_or_floats(stack):
    kinds = {resource["type"] for resource in stack["resources"].values()}

    assert kinds == {"OS::Neutron::Net", "OS::Neutron::Subnet", "OS::Neutron::Port", "OS::Nova::Server"}, (
        "no Neutron router, router interface or floating IP: the slot's fake internet has no way out")
    assert sorted(net["name"] for net in of_type(stack, "OS::Neutron::Net").values()) == sorted(
        f"cr-slot-3-{lan}" for lan in ("internet", "dmz", "web-outer", "web-inner", "mgmt"))
    for subnet in of_type(stack, "OS::Neutron::Subnet").values():
        assert subnet["enable_dhcp"] is False and subnet["gateway_ip"] is None, (
            "fixed IPs come from the config drive's network_data.json, and no subnet offers a gateway")


def test_port_security_is_off_only_on_the_two_ids_legs(stack):
    unsecured = {name for name, port in of_type(stack, "OS::Neutron::Port").items()
                 if port.get("port_security_enabled") is False}

    assert unsecured == {"port_cr-infra_web-outer", "port_cr-infra_web-inner"}
    for name, port in of_type(stack, "OS::Neutron::Port").items():
        assert ("security_groups" in port) != (name in unsecured)
        if name not in unsecured and lan_of(port) != "control":
            assert port["security_groups"] == [{"get_param": f"group_{lan_of(port)}"}]


def test_kali_stands_only_on_the_internet_and_the_platform_s_control_network(stack):
    kali = ports_of(stack, "cr-kali")

    assert sorted(lan_of(port) for port in kali.values()) == ["control", "internet"]
    assert kali["port_cr-kali_control"]["security_groups"] == [{"get_param": "control_group"}]
    assert kali["port_cr-kali_internet"]["allowed_address_pairs"] == [{"ip_address": "0.0.0.0/0"}]
    paired = {name for name, port in of_type(stack, "OS::Neutron::Port").items() if "allowed_address_pairs" in port}
    assert paired == {"port_cr-kali_internet", "port_cr-infra_dmz"}, (
        "only Kali, which speaks from every origin, and the router, which forwards them, send from addresses "
        "not their own")


def test_the_waf_and_the_target_have_no_way_to_the_internet_but_through_the_router(stack):
    assert sorted(lan_of(port) for port in ports_of(stack, "cr-waf").values()) == ["control", "dmz", "mgmt",
                                                                                    "web-outer"]
    assert sorted(lan_of(port) for port in ports_of(stack, "cr-target").values()) == ["control", "web-inner"]
    nets = {lan_of(port) for node in ("cr-waf", "cr-target") for port in ports_of(stack, node).values()}
    assert "internet" not in nets


def test_the_web_leg_reaches_the_targets_only_across_the_ids_bridge(stack):
    outer = {node for node in ("cr-waf", "cr-target", "cr-infra", "cr-kali")
             if any(lan_of(port) == "web-outer" for port in ports_of(stack, node).values())}
    inner = {node for node in ("cr-waf", "cr-target", "cr-infra", "cr-kali")
             if any(lan_of(port) == "web-inner" for port in ports_of(stack, node).values())}

    assert outer == {"cr-waf", "cr-infra"} and inner == {"cr-target", "cr-infra"}, (
        "the WAF and the targets share no network, so every packet between them crosses the IDS")


@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_the_slot_s_mgmt_lan_admits_only_the_waf_s_logs_to_the_log_server(wargame):
    groups = openstack.lan_groups(planned(wargame))

    assert groups["mgmt"][1] == [{"direction": "ingress", "protocol": "tcp", "port_range_min": 514,
                                  "port_range_max": 514, "remote_ip_prefix": "172.29.0.0/24"}]
    assert groups["web-outer"][1] == [{"direction": "ingress", "remote_ip_prefix": "10.30.128.0/24"}]


def test_every_slot_shares_one_security_group_per_rule_set_so_the_pool_fits_the_group_quota():
    named = {(wargame, slot): openstack.lan_groups(planned(wargame, slot))
             for wargame in ("board", "corp") for slot in (1, 4)}

    names = {name for groups in named.values() for name, _ in groups.values()}
    assert len(names) == 3, "everywhere (internet, dmz), the web subnet (both legs), the logs on mgmt"
    assert all(name.startswith("cr-lan-") for name in names)
    assert named[("board", 1)] == named[("board", 4)] == named[("corp", 1)]


def test_every_control_port_is_on_the_platform_s_network_and_only_the_infra_may_send_it_logs(stack):
    control = {name: port for name, port in of_type(stack, "OS::Neutron::Port").items() if lan_of(port) == "control"}

    assert len(control) == 4
    assert all(port["network"] == {"get_param": "control_network"} for port in control.values())
    senders = {name for name, port in control.items() if {"get_param": "senders_group"} in port["security_groups"]}
    assert senders == {"port_cr-infra_control"}


def test_every_server_boots_its_role_s_image_and_flavor_from_parameters_with_a_config_drive(stack):
    servers = of_type(stack, "OS::Nova::Server")

    assert sorted(servers) == ["server_cr-infra", "server_cr-kali", "server_cr-target", "server_cr-waf"]
    for name, server in servers.items():
        role = planned().node(name.removeprefix("server_")).role
        assert server["image"] == {"get_param": f"image_{role}"} and server["flavor"] == {"get_param": f"flavor_{role}"}
        assert server["config_drive"] is True and server["user_data_format"] == "RAW"
        assert server["networks"][0] == {"port": {"get_resource": f"port_{name.removeprefix('server_')}_control"}}
        assert server["metadata"]["cr_slot"] == "3"
    assert set(stack["parameters"]) >= {f"image_{role}" for role in stack_plan.ROLES}


def test_every_port_and_network_carries_its_slot_and_each_lan_port_its_fixed_ip(stack):
    plan = planned(stack["description"].split(": ")[1])
    for resource in (*of_type(stack, "OS::Neutron::Port").values(), *of_type(stack, "OS::Neutron::Net").values()):
        assert "cr.slot=3" in resource["tags"]
    for port in plan.ports:
        held = of_type(stack, "OS::Neutron::Port")[f"port_{port.node}_{port.lan}"]
        [fixed] = held["fixed_ips"]
        subnet = of_type(stack, "OS::Neutron::Subnet")[fixed["subnet"]["get_resource"]]
        assert fixed["ip_address"] == port.address
        assert ipaddress.ip_address(port.address) in ipaddress.ip_network(subnet["cidr"])


def test_a_rendered_stack_is_the_same_for_the_same_inputs_and_another_for_another_slot():
    one, again, other = rendered(slot=2), rendered(slot=2), rendered(slot=4)
    parameters = {"key_name": "cr-platform"}

    assert json.loads(json.dumps(one)) == one
    assert openstack.stack_digest(one, parameters) == openstack.stack_digest(again, parameters)
    assert openstack.stack_digest(one, parameters) != openstack.stack_digest(other, parameters)
    body = openstack.stack_body(planned(slot=2), one, parameters, openstack.stack_digest(one, parameters), 30)
    assert body["stack_name"] == "cr-slot-2" and body["disable_rollback"] is True
    assert body["tags"].split(",")[:3] == ["cr-range", "cr.slot=2", "cr.wargame=board"]


def test_an_availability_zone_is_rendered_only_when_one_is_set():
    assert not [server for server in of_type(rendered(), "OS::Nova::Server").values() if "availability_zone" in server]
    assert {server["availability_zone"] for server in of_type(rendered(zone="nova"), "OS::Nova::Server").values()} == {
        "nova"}
