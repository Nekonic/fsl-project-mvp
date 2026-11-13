import ipaddress
import json
import pathlib

import pytest

from range import declared, rangehost

ROOT = pathlib.Path(__file__).resolve().parents[2]
LEARNER_FACING = ("kali", "waf", "board", "board-db", "corp-wp", "corp-db")
CAPABILITIES = {
    "kali": {"NET_RAW", "NET_ADMIN", "SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "AUDIT_WRITE"},
    "waf": {"NET_BIND_SERVICE", "SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE"},
    "edge": {"NET_ADMIN"},
    "board": {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"},
    "board-db": {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"},
    "corp-wp": {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "NET_BIND_SERVICE"},
    "corp-db": {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"},
}
MOUNTS = {"waf": {"/var/log/modsecurity/audit/audit.log"}}
UNCONFINED = ("seccomp=unconfined", "seccomp:unconfined", "apparmor=unconfined", "apparmor:unconfined",
              "systempaths=unconfined")


def slot_document(number=3):
    stack = declared.read()
    slot = rangehost.Slot(number, rangehost.estate("10.30.0.0/16", number), "abc", 1442)
    return rangehost.compose(ROOT, slot, stack.hosts[stack.range_host].wargames)


def contained():
    services = slot_document()["services"]
    return [(name, services[name]) for name in (*LEARNER_FACING, "edge")]


def test_every_learner_facing_container_is_in_the_slot_and_nothing_else_is_unnamed():
    services = slot_document()["services"]

    assert set(LEARNER_FACING) | {"edge", "edge-sensor", "estate-sensor"} == set(services)


@pytest.mark.parametrize("name, service", contained(), ids=[name for name, _ in contained()])
def test_a_learner_facing_container_holds_no_privilege_it_does_not_need(name, service):
    assert not service.get("privileged"), f"{name} is privileged: root in it is root on the range host"
    assert service.get("cap_drop") == ["ALL"], f"{name} keeps docker's default capabilities"
    assert set(service.get("cap_add") or ()) <= CAPABILITIES[name], (
        f"{name} gains {sorted(set(service.get('cap_add') or ()) - CAPABILITIES[name])}, which nothing in it needs")
    assert "no-new-privileges:true" in (service.get("security_opt") or ()), (
        f"{name} lets a setuid binary or file capability raise a process above what it started with")
    assert not [opt for opt in service.get("security_opt") or () if opt.startswith(UNCONFINED)], (
        f"{name} leaves docker's default seccomp or AppArmor profile")
    for key in ("network_mode", "pid", "ipc", "uts", "userns_mode", "cgroup"):
        assert service.get(key) in (None, ""), f"{name} shares the range host's {key}"
    assert not service.get("devices") and not service.get("device_cgroup_rules"), f"{name} reaches a host device"
    assert not service.get("ports"), f"{name} publishes a port on the range host"
    assert service.get("mem_limit") and service.get("pids_limit"), (
        f"{name} has no memory or process limit, so one slot can starve every other slot")


@pytest.mark.parametrize("name, service", contained(), ids=[name for name, _ in contained()])
def test_a_learner_facing_container_mounts_nothing_of_the_host_beyond_its_own_log(name, service):
    mounts = [volume for volume in service.get("volumes") or ()]
    bound = {str(volume).split(":")[1] for volume in mounts if str(volume).startswith("/")}

    assert not [volume for volume in mounts if "docker.sock" in str(volume)], f"{name} holds the docker socket"
    assert bound <= MOUNTS.get(name, set()), f"{name} mounts {sorted(bound)} from the range host"
    own_logs = {f"{rangehost.LOG_FILES.format(slot=3)}/{log}" for log in rangehost.LOGS.values()}
    for volume in mounts:
        source = str(volume).split(":")[0]
        assert not source.startswith("/") or source in own_logs, (
            f"{name} mounts {source} from the range host; a learner who is root in it can plant a link "
            f"in a mounted directory that a root operation on the host then follows, so it mounts at "
            f"most its own log file")


def test_every_slot_network_is_internal_with_no_host_address_and_no_route_out():
    document = slot_document()

    for key, network in document["networks"].items():
        options = network.get("driver_opts") or {}
        assert network.get("internal") is True, f"{key} gives the slot a way to the Internet"
        assert options.get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated", (
            f"{key} puts a range host address on its bridge, which a container reaches the host's sshd through")


def test_each_slot_s_networks_and_names_are_its_own():
    one, other = slot_document(3), slot_document(4)
    subnets = lambda document: {ipaddress.ip_network(pool["subnet"])
                                for network in document["networks"].values()
                                for pool in (network.get("ipam") or {}).get("config") or []}

    assert not {a for a in subnets(one) for b in subnets(other) if a.overlaps(b)}
    assert not {s["container_name"] for s in one["services"].values()} & {
        s["container_name"] for s in other["services"].values()}
    assert {network.get("name") for network in one["networks"].values()} - {None} == {"s3_internet", "s3_estate"}


def test_the_sensors_watch_the_slot_s_bridges_and_are_no_shell_a_learner_gets():
    services = slot_document()["services"]
    stack = declared.read()

    for name in ("edge-sensor", "estate-sensor"):
        sensor = services[name]
        assert not sensor.get("privileged") and "no-new-privileges:true" in sensor["security_opt"]
        assert set(sensor["cap_add"]) == {"NET_ADMIN", "NET_RAW", "SYS_NICE"}
        assert not [v for v in sensor["volumes"] if "docker.sock" in v]
    terminals = {stack.roles[role] for role in ("attacker", "gateway")}
    assert {stack.compose[role] for role, host in stack.roles.items() if host in terminals} >= {"kali", "waf"}
    assert not {"edge-sensor", "estate-sensor"} & {stack.compose[role] for role in ("attacker", "gateway")}


def test_the_range_host_s_docker_maps_container_root_to_an_unprivileged_host_user():
    stack = declared.read()
    daemon = json.loads(rangehost.bundle(ROOT, stack.hosts[stack.range_host].wargames, "abc", 1442)["daemon.json"])

    assert daemon["userns-remap"] == "default"
    assert ipaddress.ip_network(daemon["default-address-pools"][0]["base"]).overlaps(
        ipaddress.ip_network("10.0.0.0/8")) and not ipaddress.ip_network(
        daemon["default-address-pools"][0]["base"]).overlaps(ipaddress.ip_network("172.30.0.0/16"))
