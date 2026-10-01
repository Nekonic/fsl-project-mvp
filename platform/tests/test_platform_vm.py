import ipaddress
import json
import pathlib
import subprocess

import yaml

from range.openstack import SETTINGS

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATE = ROOT / "deploy/openstack/platform.yaml"
COMPOSE = ROOT / "compose.yaml"
DOCKER_BRIDGE = ipaddress.ip_network("172.17.0.0/16")
REQUIRED_BY_CONNECT = ("keystone", "user", "password", "project", "ssh_user", "ssh_key")

def template():
    return yaml.safe_load(TEMPLATE.read_text())

def resources_of(kind):
    return [
        resource["properties"]
        for resource in template()["resources"].values()
        if resource["type"] == kind
    ]

def cloud_config():
    [server] = resources_of("OS::Nova::Server")
    text = server["user_data"]["str_replace"]["template"]
    assert text.startswith("#cloud-config\n"), text[:40]
    return yaml.safe_load(text)

def platform_service():
    return yaml.safe_load(COMPOSE.read_text())["services"]["platform"]

def credentials_file():
    [entry] = platform_service()["env_file"]
    return entry

def written_credentials():
    [written] = [
        entry for entry in cloud_config()["write_files"]
        if entry["path"].endswith("/openstack.env")
    ]
    return written

def test_the_platform_vm_boots_ubuntu_24_04():
    assert template()["parameters"]["image"]["default"] == "ubuntu-24.04"

def test_every_boot_brings_the_whole_platform_up_with_compose():
    config = cloud_config()
    commands = [" ".join(command) for command in config["runcmd"]]
    [unit] = [
        entry for entry in config["write_files"]
        if entry["path"].startswith("/etc/systemd/system/")
    ]
    name = pathlib.PurePosixPath(unit["path"]).name
    lines = unit["content"].splitlines()

    assert any(command.startswith("git clone") for command in commands), commands
    assert f"systemctl enable --now {name}" in commands, (
        f"the first boot left the platform down, so someone has to log in and "
        f"bring it up by hand: {commands}"
    )
    assert "WantedBy=multi-user.target" in lines, "a reboot would leave it down"
    assert any(line.startswith("ExecStart=") and "docker compose" in line
               and line.endswith("up -d --build") for line in lines), lines

def test_its_network_overlaps_nothing_docker_creates_inside_it():
    [subnet] = resources_of("OS::Neutron::Subnet")
    platform = ipaddress.ip_network(template()["parameters"][
        subnet["cidr"]["get_param"]]["default"])
    inside = [DOCKER_BRIDGE] + [
        ipaddress.ip_network(pool["subnet"])
        for network in yaml.safe_load(COMPOSE.read_text())["networks"].values()
        for pool in network["ipam"]["config"]
    ]

    clashing = [str(network) for network in inside if network.overlaps(platform)]

    assert not clashing, (
        f"{platform} overlaps {clashing}: the compose bridge would take the "
        f"route to the router and the VM would lose the OpenStack API"
    )

def test_docker_inside_it_fits_its_packets_to_the_network():
    [server] = resources_of("OS::Nova::Server")
    params = server["user_data"]["str_replace"]["params"]
    [key] = [name for name, value in params.items()
             if value == {"get_attr": ["network", "mtu"]}]
    [daemon] = [entry for entry in cloud_config()["write_files"]
                if entry["path"] == "/etc/docker/daemon.json"]
    settings = json.loads(daemon["content"].replace(key, "1450"))

    assert settings["mtu"] == 1450
    assert settings["default-network-opts"]["bridge"][
        "com.docker.network.driver.mtu"] == "1450", (
        "compose's networks default to 1500 on a 1450 tenant network, so a "
        "build step's TLS download from GitHub hangs until it times out"
    )

def test_a_browser_reaches_the_platform_at_the_floating_ip():
    [group] = resources_of("OS::Neutron::SecurityGroup")
    opened = {
        (rule["protocol"], rule.get("port_range_min"), rule.get("port_range_max"))
        for rule in group["rules"]
        if rule.get("direction", "ingress") == "ingress"
    }

    assert opened == {("tcp", 22, 22), ("tcp", 8000, 8000), ("icmp", None, None)}, opened

def test_the_vm_publishes_the_platform_on_its_own_address():
    [server] = resources_of("OS::Nova::Server")
    params = server["user_data"]["str_replace"]["params"]
    [fixed] = [k for k, v in params.items() if v == {"get_attr": ["port", "fixed_ips", 0, "ip_address"]}]
    [compose_env] = [e for e in cloud_config()["write_files"] if e["path"].endswith("/compose.env")]
    moved = [" ".join(c) for c in cloud_config()["runcmd"]]

    assert compose_env["content"].splitlines() == [f"FSL_PUBLISH={fixed}"]
    assert f"mv {compose_env['path']} /opt/fsl/.env" in moved, moved

def test_django_answers_to_the_floating_ip():
    [server] = resources_of("OS::Nova::Server")
    params = server["user_data"]["str_replace"]["params"]
    [floating] = [k for k, v in params.items() if v == {"get_attr": ["floating_ip", "floating_ip_address"]}]
    lines = written_credentials()["content"].splitlines()

    assert f"DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1],{floating}" in lines, (
        "Django refuses a Host it was not told about, so the floating IP "
        "would answer 400 to every browser"
    )

def test_the_password_never_enters_the_user_data():
    [server] = resources_of("OS::Nova::Server")

    assert "password" not in template()["parameters"]
    assert SETTINGS["password"] not in server["user_data"]["str_replace"]["template"], (
        "Nova keeps the user data and its metadata service serves it to "
        "whatever runs on the VM, the range's containers included"
    )

def test_boot_writes_every_other_setting_the_adapter_requires():
    content = written_credentials()["content"]
    names = {line.split("=", 1)[0] for line in content.splitlines() if line}

    assert names == {
        SETTINGS[name] for name in REQUIRED_BY_CONNECT if name != "password"
    } | {"FSL_SUBSTRATE", "DJANGO_ALLOWED_HOSTS"}, names

def test_the_platform_on_the_vm_builds_and_reads_the_cloud_range():
    lines = written_credentials()["content"].splitlines()

    assert "FSL_SUBSTRATE=range.openstack.connect" in lines, (
        "the platform VM would keep scoring the Docker range inside itself "
        "and /api/range/fabric/ would answer that compose builds it"
    )

def test_the_credentials_reach_the_platform_as_written():
    entry = credentials_file()

    assert entry["required"] is False, "a checkout without a cloud would not start"
    assert entry["format"] == "raw", (
        "compose interpolates and unquotes an env file, so a password with $ or "
        "a quote would arrive changed"
    )

def test_the_credentials_file_is_only_readable_by_its_owner():
    assert written_credentials()["permissions"] == "0600"

def test_git_never_takes_the_credentials_file():
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", credentials_file()["path"]], cwd=ROOT
    )

    assert ignored.returncode == 0, "the cloud's password would be one commit away"
