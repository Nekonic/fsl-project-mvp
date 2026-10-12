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

def example():
    from range import cloud

    return cloud.read(cloud.EXAMPLE)

def test_the_platform_vm_boots_the_base_image_cloud_yaml_names():
    [server] = resources_of("OS::Nova::Server")

    assert server["image"] == {"get_param": "image"}
    assert example().heat_parameters()["image"] == example().base_image == "ubuntu-24.04"

def test_the_template_holds_no_cloud_value_of_its_own():
    defaulted = [name for name, entry in template()["parameters"].items() if "default" in entry]

    assert not defaulted, (
        f"{defaulted} carry defaults; every cloud value comes from cloud.yaml, "
        f"so a second place to set one would drift from it"
    )
    assert set(template()["parameters"]) == set(example().heat_parameters())

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
               and line.endswith("up -d") for line in lines), lines

def test_its_network_overlaps_nothing_docker_creates_inside_it():
    [subnet] = resources_of("OS::Neutron::Subnet")
    assert subnet["cidr"] == {"get_param": "cidr"}
    platform = ipaddress.ip_network(example().heat_parameters()["cidr"])
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

    assert opened == {
        ("tcp", 22, 22),
        ("tcp", 8000, 8000),
        ("icmp", None, None),
    }, opened

def test_the_vm_publishes_the_platform_on_its_own_address():
    [server] = resources_of("OS::Nova::Server")
    params = server["user_data"]["str_replace"]["params"]
    [fixed] = [k for k, v in params.items() if v == {"get_attr": ["port", "fixed_ips", 0, "ip_address"]}]
    [compose_env] = [e for e in cloud_config()["write_files"] if e["path"].endswith("/compose.env")]
    moved = [" ".join(c) for c in cloud_config()["runcmd"]]

    assert compose_env["content"].splitlines() == [f"FSL_PUBLISH={fixed}", "FSL_SYSLOG_PUBLISH=0.0.0.0"], (
        "the range's VMs reach the collector on the platform's management "
        "address, which the fabric attaches after boot; the stack's group "
        "keeps 5140 shut on the floating IP and fsl-reach opens it per sender"
    )
    assert f"mv {compose_env['path']} /opt/fsl/.env" in moved, moved

FLOATING_ADDRESS = {"if": ["reserved", {"get_param": "floating_address"},
                           {"get_attr": ["floating_ip", "floating_ip_address"]}]}

def test_django_answers_to_the_floating_ip():
    [server] = resources_of("OS::Nova::Server")
    params = server["user_data"]["str_replace"]["params"]
    [floating] = [k for k, v in params.items() if v == FLOATING_ADDRESS]
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
        variable for name, variable in SETTINGS.items()
        if name not in ("password", "platform", "source", "image_tag")
    } | {"FSL_SUBSTRATE", "DJANGO_ALLOWED_HOSTS", "FSL_TOOL_IMAGE"}, names

def test_the_harness_asks_for_the_attacker_the_openstack_range_declares():
    from range import declared

    attacker = declared.read(flavor=declared.flavor_for("range.openstack.connect")).roles["attacker"]
    lines = written_credentials()["content"].splitlines()

    assert f"FSL_TOOL_IMAGE={attacker}" in lines, (
        "the OpenStack launcher runs a tool only on the attacker host the range "
        "declares and refuses any other image; without this the harness asks for "
        "the GHCR Kali image and every case is refused before it is sent"
    )

def test_images_are_built_on_the_platforms_own_network_which_reaches_the_internet():
    [server] = resources_of("OS::Nova::Server")
    bound = server["user_data"]["str_replace"]["params"]
    lines = written_credentials()["content"].splitlines()

    assert f"{SETTINGS['build_network']}=%network%" in lines
    assert bound["%network%"] == {"get_resource": "network"}
    [router] = resources_of("OS::Neutron::Router")
    assert router["external_gateway_info"], (
        "a builder downloads its packages; on a network with no way out its "
        "setup fails at the first apt-get"
    )

def test_the_platform_reads_the_image_sources_it_bundles():
    service = platform_service()
    source = service["environment"]["FSL_SOURCE"]
    mounted = {
        volume.split(":")[1] for volume in service["volumes"] if volume.startswith("./")
    }
    from range import declared

    for host, entry in declared.read().hosts.items():
        for path in (entry.setup, *entry.files):
            assert any(f"{source}/{path}".startswith(f"{m}/") or f"{source}/{path}" == m
                       for m in mounted), (host, path)

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


def test_boot_tells_the_platform_which_server_it_is_before_bringing_it_up():
    commands = [" ".join(map(str, step)) for step in cloud_config()["runcmd"]]
    told = next(i for i, c in enumerate(commands) if f"{SETTINGS['platform']}=" in c)
    started = next(i for i, c in enumerate(commands) if "fsl-platform.service" in c)

    assert "cloud-init query instance_id" in commands[told]
    assert "/opt/fsl/openstack.env" in commands[told]
    assert told < started, (
        "the platform attaches itself to management by its own server id; "
        "read after compose started, it would start without it"
    )

def test_a_network_the_platform_attaches_later_is_configured_by_dhcp():
    [written] = [
        entry for entry in cloud_config()["write_files"]
        if entry["path"].startswith("/etc/systemd/network/")
    ]
    lines = written["content"].splitlines()
    commands = [" ".join(map(str, step)) for step in cloud_config()["runcmd"]]

    assert "Name=en*" in lines and "DHCP=ipv4" in lines
    assert "UseRoutes=false" in lines and "UseDNS=false" in lines, (
        "management has no gateway and no name server of the platform's; "
        "taking either would move the platform's way out"
    )
    assert "networkctl reload" in commands, (
        "networkd reads a file written after it started only on reload, so "
        "the port attached later would come up with no address"
    )


def test_the_platform_vm_installs_everything_it_runs_on_the_stock_image():
    config = cloud_config()
    commands = " ".join(" ".join(map(str, step)) for step in config["runcmd"])

    assert {"docker.io", "docker-compose-v2", "git"} <= set(config["packages"]), (
        "the base image is Canonical's stock noble cloud image, uploaded as is; "
        "whatever the first boot runs beyond it, cloud-init installs"
    )
    assert "git clone" in commands and "docker" in " ".join(
        entry["content"] for entry in config["write_files"] if entry["path"].endswith(".service"))

def test_a_reserved_floating_ip_is_associated_never_owned_so_a_stack_delete_keeps_it():
    resources = template()["resources"]
    conditions = template()["conditions"]

    assert resources["floating_ip"]["condition"] == "allocated"
    assert resources["floating_ip_association"]["condition"] == "reserved"
    assert conditions["reserved"] == {"not": conditions["allocated"]}
    assert conditions["allocated"] == {"equals": [{"get_param": "floating_ip_id"}, ""]}
    [associated] = resources_of("OS::Neutron::FloatingIPAssociation")
    assert associated == {"floatingip_id": {"get_param": "floating_ip_id"},
                          "port_id": {"get_resource": "port"}}
    assert template()["outputs"]["address"]["value"] == FLOATING_ADDRESS

def test_without_an_address_in_cloud_yaml_the_stack_allocates_its_own_floating_ip():
    parameters = example().heat_parameters()

    assert parameters["floating_address"] == parameters["floating_ip_id"] == ""
    assert example().heat_parameters("fip-1")["floating_ip_id"] == "fip-1"

def test_no_parameter_shares_a_name_with_a_resource_because_heat_refuses_the_template():
    assert not set(template()["parameters"]) & set(template()["resources"])
