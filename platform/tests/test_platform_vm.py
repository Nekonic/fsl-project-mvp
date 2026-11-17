import pathlib
import re
import subprocess

import yaml

from range.openstack import SETTINGS

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATE = ROOT / "deploy/openstack/platform.yaml"
COMPOSE = ROOT / "compose.yaml"

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
    import dataclasses

    from range import cloud

    return dataclasses.replace(cloud.read(cloud.EXAMPLE), signed_in=cloud.Identity(
        cloud="fsl-range", file="clouds.yaml", keystone="http://10.10.10.10:5000", user="fsl-range",
        password="secret", project="fsl-range", user_domain="Default", project_domain="Default",
        region="RegionOne", interface="public",
    ))

def test_the_template_takes_exactly_cloud_yaml_s_values_under_names_heat_accepts():
    defaulted = [name for name, entry in template()["parameters"].items() if "default" in entry]

    assert not defaulted, (
        f"{defaulted} carry defaults; every cloud value comes from cloud.yaml, "
        f"so a second place to set one would drift from it"
    )
    assert set(template()["parameters"]) == set(example().heat_parameters())
    assert not set(template()["parameters"]) & set(template()["resources"]), (
        "Heat refuses a template whose parameter shares a name with a resource"
    )

def rules_for(allowed):
    [group] = resources_of("OS::Neutron::SecurityGroup")
    repeated, fixed = group["rules"]["list_concat"]
    loop = repeated["repeat"]
    assert loop["for_each"]["<%cidr%>"] == {"get_param": "allowed"}
    made = [
        {key: value.replace("<%cidr%>", cidr).replace("<%port%>", port) for key, value in loop["template"].items()}
        for cidr in allowed for port in loop["for_each"]["<%port%>"]
    ]
    return made + fixed

def test_a_browser_reaches_the_platform_at_the_floating_ip_from_the_allowed_networks_only():
    rules = rules_for(["203.0.113.0/24", "198.51.100.7/32"])
    opened = {
        (rule["protocol"], int(rule.get("port_range_min") or 0), rule.get("remote_ip_prefix"))
        for rule in rules
        if rule.get("direction", "ingress") == "ingress"
    }

    assert opened == {
        *{("tcp", port, cidr) for port in (22, 2222, 8000, 8002) for cidr in ("203.0.113.0/24", "198.51.100.7/32")},
        ("icmp", 0, None),
    }, opened

def test_the_password_never_enters_the_user_data():
    [server] = resources_of("OS::Nova::Server")

    assert "password" not in template()["parameters"]
    assert SETTINGS["password"] not in server["user_data"]["str_replace"]["template"], (
        "Nova keeps the user data and its metadata service serves it to "
        "whatever runs on the VM, the range's containers included"
    )

def test_boot_writes_every_setting_the_adapter_requires_for_the_cloud_range_and_its_attacker():
    from range import declared

    lines = written_credentials()["content"].splitlines()
    names = {line.split("=", 1)[0] for line in lines if line}
    attacker = declared.read().roles["attacker"]

    assert names == {
        variable for name, variable in SETTINGS.items()
        if name not in ("password", "platform", "source", "image_tag", "sideloaded")
    } | {"CR_SUBSTRATE", "DJANGO_ALLOWED_HOSTS", "CR_TOOL_IMAGE"}, names
    assert "CR_SUBSTRATE=range.openstack.connect" in lines
    assert f"CR_TOOL_IMAGE={attacker}" in lines, (
        "the OpenStack launcher runs a tool only on the attacker host the range "
        "declares and refuses any other image; without this the harness asks for "
        "the GHCR Kali image and every case is refused before it is sent"
    )

def test_the_platform_reads_the_image_sources_it_bundles():
    service = platform_service()
    source = service["environment"]["CR_SOURCE"]
    mounted = {
        volume.split(":")[1] for volume in service["volumes"] if volume.startswith("./")
    }
    from range import rangehost

    for path in (rangehost.SETUP, rangehost.SLOT_SCRIPT, rangehost.TEMPLATE, rangehost.SENSOR_CONFIG,
                 rangehost.BASELINE_RULES, "wargames/board/compose.yaml"):
        assert any(f"{source}/{path}".startswith(f"{m}/") or f"{source}/{path}" == m
                   for m in mounted), path

def test_the_credentials_file_is_private_and_reaches_the_platform_as_written():
    entry = credentials_file()
    ignored = subprocess.run(["git", "check-ignore", "-q", entry["path"]], cwd=ROOT)

    assert written_credentials()["permissions"] == "0600"
    assert ignored.returncode == 0, "the cloud's password would be one commit away"
    assert entry["required"] is False, "a checkout without a cloud would not start"
    assert entry["format"] == "raw", (
        "compose interpolates and unquotes an env file, so a password with $ or "
        "a quote would arrive changed"
    )

FLOATING_ADDRESS = {"if": ["reserved", {"get_param": "floating_address"},
                           {"get_attr": ["floating_ip", "floating_ip_address"]}]}

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

def test_the_platform_vm_serves_ntp_to_the_range_management_network_alone():
    config = cloud_config()
    [served] = [entry for entry in config["write_files"]
                if entry["path"].startswith("/etc/chrony/conf.d/")]

    assert "chrony" in config["runcmd"][0][-1]
    assert served["path"].endswith(".conf"), "chrony reads only *.conf from its confdir"
    assert served["content"].splitlines() == ["allow %management%", "local stratum 10"], (
        "the range has no Internet, so the platform is its clock; it keeps serving its own "
        "time when it loses its upstream, because the scorer compares against it"
    )
    assert example().heat_parameters()["management"] == example().inside["mgmt"] == "10.31.0.0/24"

def test_the_platform_vm_makes_its_own_virtualenv_in_the_background_after_the_platform_is_up():
    import importlib.util
    from importlib.machinery import SourceFileLoader

    config = cloud_config()
    commands = [list(map(str, command)) for command in config["runcmd"]]
    started = next(i for i, c in enumerate(commands) if "cr-platform.service" in c)
    [made] = [i for i, c in enumerate(commands) if c[0] == "systemd-run"]
    command = commands[made]
    loader = SourceFileLoader("platform_rebuild_venv", str(ROOT / "bin/platform-rebuild"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    [fetched] = [i for i, c in enumerate(commands) if "github.com/astral-sh/uv/releases/download/" in " ".join(c)]
    assert started < fetched < made, "uv is installed after the platform is up and before the virtualenv is made"
    assert re.search(r"/download/\d+\.\d+\.\d+/", commands[fetched][-1]), "uv is pinned to one release"
    assert re.search(r"echo '[0-9a-f]{64}  /tmp/uv.tar.gz' \| sha256sum -c -", commands[fetched][-1]), (
        "the release tarball is checked against its published SHA-256 before it is unpacked"
    )
    assert made > started, "the platform service starts first; the virtualenv must not delay it"
    assert "--no-block" in command, "a slow package install would hold up the rest of the first boot"
    assert {"--uid=ubuntu", "--gid=ubuntu"} <= set(command), (
        "bin/verify runs as the ubuntu user and the checkout is owned by it"
    )
    assert command[-3:] == ["sh", "-c", module.VENV_COMMAND], (
        "the first boot and the hand-over after a sideload checkout make the same virtualenv, "
        "one at a time: the hand-over starts while the first boot's install may still run"
    )
    assert module.VENV_COMMAND == (
        "exec 9>/tmp/cr-venv.lock && flock 9 && "
        "/usr/local/bin/uv sync --quiet --frozen --project /opt/cr --python /usr/bin/python3"
    )
