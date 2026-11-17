import ipaddress
import pathlib
import shlex
import subprocess

import pytest
import yaml

from range import declared, sandbox

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECLARED = declared.read()
COLLECTOR = "10.31.0.2"


def planned(wargame="board", slot=2):
    return sandbox.plan(sandbox.read(ROOT, wargame), slot, DECLARED.origins, DECLARED.default_origin, COLLECTOR)


def written(node, path):
    assert node.user_data.startswith("#cloud-config\n")
    return next(entry["content"] for entry in yaml.safe_load(node.user_data)["write_files"] if entry["path"] == path)


def slot_env(node):
    return dict(line.split("=", 1) for line in shlex.split(written(node, sandbox.SLOT_ENV), posix=True))


def test_every_wargame_has_a_topology_and_each_plans_four_nodes_on_its_own_lans():
    assert sandbox.wargames(ROOT) == ("board", "corp")
    for wargame in sandbox.wargames(ROOT):
        plan = planned(wargame)
        assert {node.role for node in plan.nodes} == set(sandbox.ROLES)
        assert [lan.name for lan in plan.lans] == ["internet", "dmz", "web-outer", "web-inner", "mgmt"]
        assert plan.logged == "mgmt"


def test_every_slot_stands_on_the_same_addresses_and_differs_only_by_its_networks():
    assert planned(slot=1).ports == planned(slot=7).ports, (
        "slots are told apart by their Neutron networks, not by per-slot address arithmetic")


def test_kali_has_one_internet_port_on_the_default_origin_and_the_origins_default_first():
    plan = planned()
    [kali] = [one for one in plan.ports if one.node == "cr-kali"]
    default = next(origin for origin in DECLARED.origins if origin.id == DECLARED.default_origin)

    assert kali.address == sandbox.origin_addresses(default.subnet, 1)[0] == "5.188.10.10"
    assert kali.pairs == ("0.0.0.0/0",), (
        "max_allowed_address_pair is 10 on this cloud and the origins are 30 /24s; the slot's internet has "
        "no router, so the one pair reaches nothing outside the slot")
    assert default.subnet in next(lan.cidrs for lan in plan.lans if lan.name == "internet")
    env = slot_env(plan.node("cr-kali"))
    origins = env["ORIGINS"].split()
    assert env["INTERNET_ADDRESS"] == "5.188.10.10" and origins[0] == "5.188.10.10/24", (
        "ip addr on Kali lists its default source first")
    assert len(origins) == sum(origin.addresses for origin in DECLARED.origins) and "73.0.0.10/24" in origins


def test_the_ids_legs_have_port_security_off_and_dummy_addresses_in_the_web_lan():
    plan = planned()
    legs = [one for one in plan.ports if one.ids]

    assert {(one.node, one.lan) for one in legs} == {("cr-infra", "web-outer"), ("cr-infra", "web-inner")}
    assert [one for one in plan.ports if not one.secured] == legs, "port security is off on the two legs only"
    assert all(ipaddress.ip_address(one.address) in ipaddress.ip_network("10.30.128.0/24") for one in legs), (
        "Nova boots no port without a fixed IP")
    assert slot_env(plan.node("cr-infra"))["IDS_LEGS"].split() == [one.address for one in legs]


def test_the_infra_is_told_its_slot_the_waf_s_front_its_upstream_and_where_logs_go():
    env = slot_env(planned(slot=2).node("cr-infra"))

    assert env == {"SLOT": "2", "WAF_FRONT": "10.30.0.247", "UPSTREAM": "5.188.10.10",
                   "IDS_LEGS": "10.30.128.251 10.30.128.252", "LOG_SERVER": "172.29.0.10", "COLLECTOR": COLLECTOR}
    assert planned().node("cr-infra").ports[0].address == "121.134.88.42", "the role finds the wan by this address"
    assert next(one for one in planned().ports if one.device == "cr-edge" and one.lan == "dmz").pairs == (
        "0.0.0.0/0",), "the router sends the origins' packets out of its DMZ port, which port security would drop"


def test_the_waf_routes_through_the_router_and_reaches_both_upstreams_and_the_log_server():
    assert slot_env(planned().node("cr-waf")) == {
        "GATEWAY": "10.30.0.1", "LOG_SERVER": "172.29.0.10",
        "BOARD_ADDRESS": "10.30.128.59", "CORP_ADDRESS": "10.30.128.60"}, (
        "nginx resolves every upstream it names at start, so a board slot's WAF knows corp's address too")


@pytest.mark.parametrize("wargame", ["board", "corp"])
def test_the_target_runs_its_own_wargame_on_its_web_address(wargame):
    plan = planned(wargame)
    env = slot_env(plan.node("cr-target"))

    assert env["WARGAMES"] == wargame
    [port] = plan.node("cr-target").ports
    assert port.lan == "web-inner" and port.address == env[f"{wargame.upper()}_ADDRESS"]


def test_every_node_keeps_time_by_the_platform_and_fits_nova_s_user_data_limit():
    for node in planned().nodes:
        assert written(node, "/etc/systemd/timesyncd.conf.d/60-cr.conf") == f"[Time]\nNTP={COLLECTOR}\n"
        assert len(node.user_data.encode()) * 4 // 3 < sandbox.USER_DATA_LIMIT


def test_every_node_takes_the_platform_s_ssh_as_one_sudo_user_and_keeps_its_image_s_default_user():
    plan = sandbox.plan(sandbox.read(ROOT, "board"), 1, DECLARED.origins, DECLARED.default_origin, COLLECTOR,
                        ("ubuntu", "ssh-ed25519 AAAA cr-platform"))

    for node in plan.nodes:
        users = yaml.safe_load(node.user_data)["users"]
        assert users[0] == "default", f"{node.name}: Kali's learners ssh in as its default user kali"
        assert users[1] == {"name": "ubuntu", "shell": "/bin/bash", "sudo": "ALL=(ALL) NOPASSWD:ALL",
                            "lock_passwd": True, "ssh_authorized_keys": ["ssh-ed25519 AAAA cr-platform"]}
    assert "users" not in yaml.safe_load(planned().node("cr-kali").user_data), "no key, no user"


@pytest.mark.parametrize("role, units", [
    ("kali", "slot-boot.service"), ("waf", "slot-boot.service nginx.service"),
    ("infra", "slot-boot.service sensor.service"), ("target", "wargames.service"),
])
def test_each_node_marks_itself_ready_or_failed_once_its_role_s_boot_has_run(role, units):
    [node] = [one for one in planned().nodes if one.role == role]
    [[shell, flag, script]] = yaml.safe_load(node.user_data)["runcmd"]

    assert (shell, flag) == ("sh", "-c")
    assert script.startswith(f"install -d -m 0755 {sandbox.STATE}; if systemctl start {units}")
    assert f"; then touch {sandbox.READY}; " in script
    assert f"systemctl --no-pager --lines=20 status {units}; }} > {sandbox.FAILED} 2>&1; touch {sandbox.FAILED}; fi" \
        in script


def test_the_infra_is_ready_only_once_suricata_answers_on_its_command_socket():
    [[_, _, script]] = yaml.safe_load(planned().node("cr-infra").user_data)["runcmd"]

    assert ("systemctl start slot-boot.service sensor.service && for _ in $(seq 300); do suricatasc -c uptime "
            ">/dev/null 2>&1 && break; sleep 1; done && suricatasc -c uptime; then") in script, (
        "configure loads the baseline rules through that socket right after the slot is ready")


def test_the_target_is_ready_only_when_its_image_holds_the_wargame_images_at_the_tag_the_slot_asks_for():
    tag = "c" * 40
    plan = sandbox.plan(sandbox.read(ROOT, "board"), 1, DECLARED.origins, DECLARED.default_origin, COLLECTOR,
                        tag=tag)
    [[_, _, script]] = yaml.safe_load(plan.node("cr-target").user_data)["runcmd"]
    [[_, _, kali]] = yaml.safe_load(plan.node("cr-kali").user_data)["runcmd"]

    images = "grep -h ' image: ' /opt/wargames/*/compose.yaml"
    assert (f"if {images} >/dev/null && ! {images} | grep -v -e ':{tag}$' -e '@sha256:[0-9a-f]*$' && "
            f"systemctl start wargames.service;") in script
    assert f"echo 'the slot asks for wargame images at {tag}:'; {images};" in script
    assert tag not in kali


def test_the_tag_check_passes_the_baked_compose_files_and_their_digest_pinned_databases(tmp_path):
    tag = "c" * 40
    (tmp_path / "board").mkdir()
    (tmp_path / "board/compose.yaml").write_text(
        f"services:\n  board:\n    image: ghcr.io/nekonic/cr-board:{tag}\n"
        f"  board-db:\n    image: mysql@sha256:{'0' * 64}\n")
    check = sandbox.booted("target", tag).split("if ", 1)[1].split(" systemctl start", 1)[0].removesuffix(" &&")
    check = check.replace("/opt/wargames/*/compose.yaml", str(tmp_path / "*/compose.yaml"))

    assert subprocess.run(["sh", "-c", check]).returncode == 0
    (tmp_path / "board/compose.yaml").write_text("services:\n  board:\n    image: ghcr.io/nekonic/cr-board:dev\n")
    assert subprocess.run(["sh", "-c", check], capture_output=True).returncode != 0


def test_a_definition_that_puts_a_port_outside_its_lan_or_without_an_address_is_refused(tmp_path):
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
