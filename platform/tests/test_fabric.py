import ipaddress
import pathlib

from range import declared, fabric

DECLARED = declared.read()
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPlatformKey fsl@platform"

def built():
    networks, subnets = [], []
    for want in fabric.wanted(DECLARED):
        net_id = f"net-{want.segment}"
        if not any(n["id"] == net_id for n in networks):
            networks.append({
                "id": net_id, "name": f"fsl-{want.segment}",
                "tags": [f"{fabric.TAG}={want.segment}"],
            })
        subnets.append({
            "id": f"sub-{want.name}", "network_id": net_id, "name": want.name,
            "cidr": want.cidr, "enable_dhcp": want.dhcp,
            "gateway_ip": str(next(ipaddress.ip_network(want.cidr).hosts())) if want.gateway else None,
        })
    keypairs = [{"name": fabric.KEYPAIR, "public_key": PUBLIC_KEY + "\n"}]
    return networks, subnets, keypairs

GROUPS = [{"id": "sg-range", "name": fabric.RANGE_GROUP},
          {"id": "sg-reach", "name": fabric.REACH_GROUP}]

def planned(networks=(), subnets=(), keypairs=(), groups=GROUPS, reached=True):
    return fabric.plan(DECLARED, list(networks), list(subnets), list(keypairs),
                       PUBLIC_KEY, list(groups), reached)

def test_an_empty_project_gets_every_network_every_subnet_and_the_key():
    plan = planned()

    assert plan.networks == ("internet", "estate", "mgmt")
    assert len(plan.subnets) == 32
    assert plan.keypair and not plan.clean

def test_the_internet_network_holds_one_subnet_per_origin_with_no_dhcp():
    internet = [s for s in fabric.wanted(DECLARED) if s.segment == "internet"]

    assert [(s.name, s.cidr) for s in internet] == [
        (f"fsl-{o.id}", o.subnet) for o in DECLARED.origins
    ]
    assert not any(s.dhcp for s in internet), (
        "an attack address is set on the attacker's port, so DHCP on thirty "
        "subnets would only hand out addresses nobody asked for"
    )

def test_management_gives_no_default_route():
    [mgmt] = [s for s in fabric.wanted(DECLARED) if s.segment == "mgmt"]

    assert not mgmt.gateway and mgmt.dhcp, (
        "a default route through management would send every range host's "
        "traffic toward a network meant only for the platform to reach them"
    )

def test_a_complete_project_needs_nothing():
    plan = planned(*built())

    assert plan.clean and not plan.leftovers, plan
    assert len(plan.present) == 32

def test_a_subnet_on_its_cidr_but_with_dhcp_on_is_drift_not_a_second_subnet():
    networks, subnets, keypairs = built()
    subnets[0] = dict(subnets[0], enable_dhcp=True)

    plan = planned(networks, subnets, keypairs)

    assert not plan.subnets
    assert plan.drifted == (f"subnet {subnets[0]['name']} {subnets[0]['cidr']}: dhcp is on, declared off",)

def test_a_network_the_declaration_no_longer_names_is_a_leftover():
    networks, subnets, keypairs = built()
    networks.append({"id": "net-edge", "name": "fsl-edge", "tags": [f"{fabric.TAG}=edge"]})

    assert planned(networks, subnets, keypairs).leftovers == (
        "network fsl-edge carries fsl.segment.id=edge, which the declaration does not name",
    )

def test_a_network_left_untagged_by_a_failed_create_is_a_leftover_not_a_duplicate():
    networks, subnets, keypairs = built()
    networks = [n for n in networks if n["id"] != "net-mgmt"] + [
        {"id": "net-half", "name": "fsl-mgmt", "tags": []}
    ]

    plan = planned(networks, subnets, keypairs)

    assert plan.leftovers == ("network fsl-mgmt carries no fsl.segment.id",)
    assert plan.networks == ("mgmt",)

def test_two_networks_carrying_one_tag_are_drift():
    networks, subnets, keypairs = built()
    networks.append({"id": "net-twin", "name": "fsl-estate-2", "tags": [f"{fabric.TAG}=estate"]})

    assert planned(networks, subnets, keypairs).drifted == (
        "networks fsl-estate and fsl-estate-2 both carry fsl.segment.id=estate",
    )

def test_a_subnet_no_origin_declares_is_a_leftover():
    networks, subnets, keypairs = built()
    subnets.append({
        "id": "sub-kp", "network_id": "net-internet", "name": "fsl-kp",
        "cidr": "175.45.176.0/24", "enable_dhcp": False, "gateway_ip": "175.45.176.1",
    })

    assert planned(networks, subnets, keypairs).leftovers == (
        "subnet fsl-kp 175.45.176.0/24 on fsl-internet is declared by nothing",
    )

def test_a_keypair_of_that_name_with_another_key_is_drift():
    networks, subnets, _ = built()
    other = [{"name": fabric.KEYPAIR, "public_key": "ssh-ed25519 AAAAsomeoneelse x"}]

    plan = planned(networks, subnets, other)

    assert not plan.keypair
    assert plan.drifted == ("keypair fsl-platform holds another public key",)

def test_the_inside_networks_overlap_nothing_the_platform_vm_already_routes():
    held = [
        "172.30.0.0/24", "172.31.0.0/24", "172.17.0.0/16",
        "10.20.0.0/24", "192.168.0.0/24",
    ] + [o.subnet for o in DECLARED.origins]
    inside = [ipaddress.ip_network(cidr) for cidr in fabric.INSIDE.values()]

    assert not [
        (str(net), cidr) for net in inside for cidr in held
        if net.overlaps(ipaddress.ip_network(cidr))
    ], (
        "the platform VM runs compose's bridges, sits on 10.20.0.0/24 and "
        "reaches the API across the LAN; an inside network on any of those "
        "would take the route away"
    )

def test_teardown_removes_subnets_before_networks_and_only_what_it_owns():
    networks, subnets, keypairs = built()
    networks.append({"id": "net-other", "name": "tenant-scratch", "tags": []})

    steps = fabric.teardown(DECLARED, networks, subnets, keypairs)
    kinds = [kind for kind, _ in steps]

    assert kinds == ["subnet"] * 32 + ["network"] * 3 + ["keypair"]
    assert ("network", "net-other") not in steps

def test_a_project_without_the_range_groups_gets_both():
    plan = planned(*built(), groups=())

    assert plan.groups == (fabric.RANGE_GROUP, fabric.REACH_GROUP) and not plan.clean

def test_a_platform_not_yet_on_management_is_attached():
    plan = planned(*built(), reached=False)

    assert plan.reach and not plan.clean

def test_two_groups_of_one_name_are_drift():
    plan = planned(*built(), groups=GROUPS + [{"id": "sg-twin", "name": fabric.RANGE_GROUP}])

    assert plan.drifted == (f"2 security groups are called {fabric.RANGE_GROUP}",)

def test_teardown_removes_the_range_groups_last():
    networks, subnets, keypairs = built()

    steps = fabric.teardown(DECLARED, networks, subnets, keypairs,
                            GROUPS + [{"id": "sg-default", "name": "default"}])

    assert steps[-2:] == [("group", "sg-range"), ("group", "sg-reach")]

def test_the_planner_touches_no_cloud_and_no_disk():
    source = pathlib.Path(fabric.__file__).read_text()

    assert not [word for word in ("requests", "urllib", "subprocess", "open(") if word in source]


def _rule(prefix, ident, port=fabric.COLLECTOR_PORT):
    return {"id": ident, "direction": "ingress", "ethertype": "IPv4", "protocol": "udp",
            "port_range_min": port, "port_range_max": port, "remote_ip_prefix": prefix}

def test_the_collector_hears_each_sender_and_nothing_else():
    group = {"id": "sg-reach", "security_group_rules": [
        _rule("10.31.0.63/32", "r-edge"), _rule("10.31.0.201/32", "r-stale"),
        _rule("10.31.0.9/32", "r-other", port=22),
    ]}

    create, delete = fabric.hearing(group, ["10.31.0.63", "10.31.0.198"])

    assert create == [{"security_group_id": "sg-reach", "direction": "ingress",
                       "ethertype": "IPv4", "protocol": "udp",
                       "port_range_min": fabric.COLLECTOR_PORT,
                       "port_range_max": fabric.COLLECTOR_PORT,
                       "remote_ip_prefix": "10.31.0.198/32"}]
    assert delete == ["r-stale"], "a rule for another port is not the collector's to remove"

def test_a_collector_already_hearing_its_senders_changes_nothing():
    group = {"id": "sg-reach", "security_group_rules": [_rule("10.31.0.63/32", "r-edge")]}

    assert fabric.hearing(group, ["10.31.0.63"]) == ([], [])
