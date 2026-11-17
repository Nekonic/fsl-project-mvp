import ipaddress
import pathlib

import pytest
import yaml

from range import declared, sandbox

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()
COLLECTOR = "10.31.0.2"


def planned(wargame="board", slot=2):
    return sandbox.plan(sandbox.read(ROOT, wargame), slot, DECLARED.origins, DECLARED.default_origin,
                        COLLECTOR, 5140, "abc")


def cloud_config(node):
    assert node.user_data.startswith("#cloud-config\n")
    return yaml.safe_load(node.user_data)


def written(node, path):
    return next(entry["content"] for entry in cloud_config(node)["write_files"] if entry["path"] == path)


def boot(node):
    return written(node, sandbox.BOOT)


def port(plan, device, lan):
    return next(one for one in plan.ports if one.device == device and one.lan == lan)


def test_every_wargame_has_a_topology_and_each_plans_four_nodes_on_its_own_lans():
    assert sandbox.wargames(ROOT) == ("board", "corp")
    for wargame in sandbox.wargames(ROOT):
        plan = planned(wargame)
        assert {node.role for node in plan.nodes} == set(sandbox.ROLES)
        assert [lan.name for lan in plan.lans] == ["internet", "dmz", "web-outer", "web-inner", "mgmt"]


def test_every_slot_stands_on_the_same_addresses_and_differs_only_by_its_networks():
    assert planned(slot=1).ports == planned(slot=7).ports, (
        "slots are told apart by their Neutron networks, not by per-slot address arithmetic")


def test_kali_has_one_internet_port_on_the_default_origin_and_takes_the_other_origins_at_boot():
    plan = planned()
    [kali] = [one for one in plan.ports if one.node == "cr-kali"]
    default = next(origin for origin in DECLARED.origins if origin.id == DECLARED.default_origin)

    assert kali.address == sandbox.origin_addresses(default.subnet, 1)[0] == "5.188.10.10"
    assert kali.pairs == ("0.0.0.0/0",), (
        "max_allowed_address_pair is 10 on this cloud and the origins are 30 /24s; the slot's internet has "
        "no router, so the one pair reaches nothing outside the slot")
    assert len(kali.extra) == sum(origin.addresses for origin in DECLARED.origins) - 1
    assert default.subnet in next(lan.cidrs for lan in plan.lans if lan.name == "internet")
    lines = written(plan.node("cr-kali"), sandbox.KALI_ADDRESSES).splitlines()
    assert lines[-1] == "route replace default via 121.134.88.42 dev @dev@ onlink src 5.188.10.10"
    assert "73.0.0.10/24" in "".join(lines) and "5.188.10.10/24" not in "".join(lines), (
        "Neutron puts the fixed IP on the NIC first, so ip addr lists the default source first")


def test_the_ids_legs_have_port_security_off_and_dummy_addresses_the_boot_flushes_before_bridging():
    plan = planned()
    legs = [one for one in plan.ports if one.ids]
    web = ipaddress.ip_network("10.30.128.0/24")

    assert {(one.node, one.lan) for one in legs} == {("cr-infra", "web-outer"), ("cr-infra", "web-inner")}
    assert not [one for one in legs if one.secured]
    assert [one for one in plan.ports if not one.secured] == legs, "port security is off on the two legs only"
    assert all(ipaddress.ip_address(one.address) in web for one in legs), "Nova boots no port without a fixed IP"
    script = boot(plan.node("cr-infra"))
    for at in range(2):
        assert script.index(f'ip addr flush dev "$leg{at}"') < script.index(f'ip link set "$leg{at}" master br-ids up')
    [sniffed] = [one for one in legs if one.sniffed]
    assert sniffed.lan == "web-inner" and port(plan, "board", "web-inner").lan == sniffed.lan
    assert f"$leg{legs.index(sniffed)}/g" in script and "> /etc/suricata/suricata.yaml" in script


def test_the_sensor_sniffs_one_leg_and_keeps_the_x_forwarded_for_view():
    config = yaml.safe_load(written(planned().node("cr-infra"), sandbox.SENSOR_TEMPLATE)
                            .removeprefix(sandbox.YAML_HEADER))

    assert [capture["interface"] for capture in config["af-packet"]] == [sandbox.SNIFFED]
    assert config["outputs"][0]["eve-log"]["xff"] == {
        "enabled": True, "mode": "extra-data", "deployment": "reverse", "header": "X-Forwarded-For"}
    rules = sandbox.read(ROOT, "board").filling("sensor").rules
    assert written(planned().node("cr-infra"), rules) == (ROOT / sandbox.BASELINE_RULES).read_text()


def test_the_edge_forwards_port_80_to_the_waf_and_lets_in_only_replies_and_ping_from_the_internet():
    plan = planned()
    rules = written(plan.node("cr-infra"), sandbox.EDGE_RULES)

    assert 'iifname "@wan@" ip daddr 121.134.88.42 tcp dport 80 dnat to 10.30.0.247' in rules
    forward = rules[rules.index("chain forward"):rules.index("chain input")]
    assert [line.strip() for line in forward.splitlines() if "@wan@" in line] == [
        'iifname "@wan@" ct state established,related accept', 'iifname "@wan@" ct status dnat accept',
        'iifname "@wan@" drop']
    inbound = rules[rules.index("chain input"):]
    assert 'icmp type echo-request accept' in inbound, "ping and traceroute from Kali reach the router"
    assert "snat" not in rules and "masquerade" not in rules, "the WAF sees each client's own address"
    assert port(plan, "cr-edge", "dmz").pairs == ("0.0.0.0/0",), (
        "the router sends the origins' packets out of its DMZ port, which port security would drop")
    assert "ip route replace default via 5.188.10.10 dev \"$wan\" onlink" in boot(plan.node("cr-infra"))


def test_the_waf_routes_through_the_router_and_reaches_both_upstreams_by_name():
    script = boot(planned().node("cr-waf"))

    assert 'ip route replace default via 10.30.0.1 dev "$dmz"' in script
    assert "'10.30.128.59 board' '10.30.128.60 corp-wp'" in script, "nginx resolves every upstream it names at start"
    assert "systemctl restart nginx" in script


def test_each_slot_s_logs_reach_the_collector_under_a_name_that_keeps_its_slot():
    one, two = (written(planned(slot=n).node("cr-infra"), sandbox.SHIPPING) for n in (1, 2))

    assert " cr-ids suricata " in one and " cr-waf modsecurity " in one
    assert " cr-ids-2 suricata " in two and " cr-waf-2 nginx " in two
    assert two.count('Target="10.31.0.2" Port="5140" Protocol="udp"') == 3
    assert 'File="/var/log/suricata/eve.json" Tag="suricata"' in two
    assert '$fromhost-ip == "172.29.0.12" and $programname == "modsecurity"' in two, (
        "a sender keeps only the tags its own logs carry, so a learner who is root in the WAF cannot pass "
        "a line off as Suricata's")
    assert '$programname == "suricata"' not in two
    assert 'port="514" address="172.29.0.10"' in two


def test_the_waf_ships_its_audit_and_refused_logs_to_the_log_server_on_the_slot_s_mgmt():
    node = planned().node("cr-waf")
    shipped = written(node, sandbox.SHIPPING)

    assert 'File="/var/log/modsecurity/audit/audit.log" Tag="modsecurity"' in shipped
    assert 'File="/var/log/nginx/refused.log" Tag="nginx"' in shipped
    assert 'Target="172.29.0.10" Port="514" Protocol="tcp"' in shipped
    assert 'freshStartTail="on"' in shipped and 'reopenOnTruncate="on"' in shipped


@pytest.mark.parametrize("wargame,running,published", [
    ("board", {"board", "board-db"}, ["10.30.128.59:8000:8000"]),
    ("corp", {"corp-wp", "corp-db"}, ["10.30.128.60:80:80"]),
])
def test_the_target_runs_its_wargame_alone_published_on_its_web_address(wargame, running, published):
    plan = planned(wargame)
    document = yaml.safe_load(written(plan.node("cr-target"), sandbox.TARGET_COMPOSE))
    front = "board" if wargame == "board" else "corp-wp"

    assert set(document["services"]) == running
    assert document["services"][front]["ports"] == published
    assert all(service["image"].endswith(":abc") or "@sha256:" in service["image"]
               for service in document["services"].values())
    assert {service["container_name"] for service in document["services"].values()} == running, (
        "api/loot.py and api/effect.py reach a target by its service name through docker exec")
    assert not [key for service in document["services"].values() for key in service if key in sandbox.DROPPED]
    assert "--pull never" in boot(plan.node("cr-target"))


def test_every_node_keeps_time_by_the_platform_and_reports_its_boot():
    for node in planned().nodes:
        document = cloud_config(node)
        assert written(node, "/etc/systemd/timesyncd.conf.d/60-cr.conf") == f"[Time]\nNTP={COLLECTOR}\n"
        [[_, _, command]] = document["runcmd"]
        assert sandbox.READY in command and sandbox.FAILED in command
        assert len(node.user_data.encode()) * 4 // 3 < sandbox.USER_DATA_LIMIT


def test_a_definition_that_puts_a_port_outside_its_lan_or_without_an_address_is_refused(tmp_path):
    (tmp_path / "deploy/suricata/rules").mkdir(parents=True)
    for name in (sandbox.SENSOR_CONFIG, sandbox.BASELINE_RULES):
        (tmp_path / name).write_text((ROOT / name).read_text())
    topology = yaml.safe_load((ROOT / sandbox.DEFINITION.format(wargame="board")).read_text())
    (tmp_path / "wargames/odd").mkdir(parents=True)
    topology["nodes"]["cr-waf"]["ports"][0]["address"] = "10.99.0.1"
    (tmp_path / "wargames/odd/topology.yaml").write_text(yaml.safe_dump(topology))
    with pytest.raises(ValueError, match="outside dmz"):
        sandbox.read(tmp_path, "odd")
    del topology["nodes"]["cr-waf"]["ports"][0]["address"]
    (tmp_path / "wargames/odd/topology.yaml").write_text(yaml.safe_dump(topology))
    with pytest.raises(ValueError, match="no fixed IP"):
        sandbox.read(tmp_path, "odd")
