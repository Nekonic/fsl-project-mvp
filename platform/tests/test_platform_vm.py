import pathlib
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
    from range import cloud

    return cloud.read(cloud.EXAMPLE)

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
        ("tcp", 8002, 8002),
        ("tcp", 3080, 3080),
        ("icmp", None, None),
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
    attacker = declared.read(flavor=declared.flavor_for("range.openstack.connect")).roles["attacker"]

    assert names == {
        variable for name, variable in SETTINGS.items()
        if name not in ("password", "platform", "source", "image_tag", "sideloaded")
    } | {"FSL_SUBSTRATE", "DJANGO_ALLOWED_HOSTS", "FSL_TOOL_IMAGE"}, names
    assert "FSL_SUBSTRATE=range.openstack.connect" in lines
    assert f"FSL_TOOL_IMAGE={attacker}" in lines, (
        "the OpenStack launcher runs a tool only on the attacker host the range "
        "declares and refuses any other image; without this the harness asks for "
        "the GHCR Kali image and every case is refused before it is sent"
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

    assert "chrony" in config["packages"]
    assert served["path"].endswith(".conf"), "chrony reads only *.conf from its confdir"
    assert served["content"].splitlines() == ["allow %management%", "local stratum 10"], (
        "the range has no Internet, so the platform is its clock; it keeps serving its own "
        "time when it loses its upstream, because the scorer compares against it"
    )
    assert example().heat_parameters()["management"] == example().inside["mgmt"] == "10.31.0.0/24"
