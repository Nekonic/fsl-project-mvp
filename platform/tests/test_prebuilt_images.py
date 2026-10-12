import importlib.util
import re
import subprocess
import sys
from argparse import Namespace
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import yaml

from tests import composed
from wargames import WARGAMES

ROOT = composed.ROOT
WORKFLOW = ROOT / ".github/workflows/images.yml"
REBUILD = ROOT / "bin/platform-rebuild"
NAME = re.compile(r"ghcr\.io/nekonic/fsl-([a-z0-9-]+):\$\{FSL_IMAGE_TAG:-dev\}")


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def matrix():
    [job] = workflow()["jobs"].values()
    return job["strategy"]["matrix"]["include"]


def steps():
    [job] = workflow()["jobs"].values()
    return job["steps"]


def built_by_compose():
    found = set()
    for path in composed.files():
        for service in (yaml.safe_load(path.read_text()).get("services") or {}).values():
            if "build" in service:
                build = service["build"]
                context = build if isinstance(build, str) else build["context"]
                name = NAME.fullmatch(service["image"]).group(1)
                found.add((name, str((path.parent / context).resolve().relative_to(ROOT))))
    return found


def rebuild():
    loader = SourceFileLoader("platform_rebuild", str(REBUILD))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("platform_rebuild", loader)
    )
    loader.exec_module(module)
    return module


def written_cloud(tmp_path, **changed):
    document = yaml.safe_load((ROOT / "deploy/openstack/cloud.example.yaml").read_text())
    password = tmp_path / "password"
    password.write_text("secret\n")
    document["identity"]["password_file"] = str(password)
    for dotted, value in changed.items():
        section, key = dotted.split("__")
        document[section][key] = value
    written = tmp_path / "cloud.yaml"
    written.write_text(yaml.safe_dump(document))
    return Namespace(cloud=written, ref=None)


def test_ci_publishes_exactly_the_images_compose_builds():
    published = {(entry["name"], entry["context"]) for entry in matrix()}

    assert published == built_by_compose(), (
        f"the workflow publishes {sorted(published)} and compose builds "
        f"{sorted(built_by_compose())}: a VM that only pulls would miss one, "
        f"or CI would publish an image nothing runs"
    )


def test_ci_pushes_x86_64_images_tagged_by_commit_with_the_repository_token():
    [push] = [step for step in steps() if "build-push-action" in step["uses"]]
    login = [step for step in steps() if "login-action" in step["uses"]]

    assert workflow()["permissions"] == {"contents": "read", "packages": "write"}
    assert push["with"]["platforms"] == "linux/amd64"
    assert push["with"]["push"] is True
    assert "${{ github.sha }}" in push["with"]["tags"]
    assert login and login[0]["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"


def test_ci_runs_on_dev_and_by_hand():
    triggers = workflow()[True]

    assert triggers["push"]["branches"] == ["dev"]
    assert "workflow_dispatch" in triggers


def test_every_action_ci_uses_is_pinned_to_a_commit():
    floating = [step["uses"] for step in steps()
                if not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"])]

    assert not floating, f"a tag can be moved to other code under the same name: {floating}"


def test_the_rebuild_checks_every_image_ci_publishes():
    assert set(rebuild().IMAGES) == {entry["name"] for entry in matrix()}


def test_each_wargame_names_the_image_its_service_runs():
    repositories = {
        NAME.fullmatch(service["image"]).group(1)
        for service in composed.services().values() if "build" in service
    }

    for wargame in WARGAMES.values():
        image = wargame["image"]
        assert image.startswith("ghcr.io/nekonic/fsl-"), image
        assert image.removeprefix("ghcr.io/nekonic/fsl-") in repositories, image


def test_tool_cases_run_the_kali_image_the_session_pulls():
    from redteam.tools import TOOL_IMAGE

    kali = composed.services()["kali"]["image"]

    assert TOOL_IMAGE == kali.replace("${FSL_IMAGE_TAG:-dev}", "dev")


def test_the_platform_hands_its_image_tag_to_the_sessions_it_starts():
    environment = composed.services()["platform"]["environment"]

    assert environment["FSL_IMAGE_TAG"] == "${FSL_IMAGE_TAG:-dev}", (
        "the platform runs session.yaml itself; without the tag it would "
        "start sessions from :dev whatever the VM pulled"
    )


def platform_vm_config():
    template = yaml.safe_load((ROOT / "deploy/openstack/platform.yaml").read_text())
    [server] = [r["properties"] for r in template["resources"].values()
                if r["type"] == "OS::Nova::Server"]
    return template, yaml.safe_load(server["user_data"]["str_replace"]["template"])


def test_the_platform_vm_pulls_and_never_builds():
    _, config = platform_vm_config()
    [unit] = [e for e in config["write_files"] if e["path"].startswith("/etc/systemd/system/")]
    text = unit["content"] + "\n".join(" ".join(map(str, c)) for c in config["runcmd"])

    assert "build" not in re.sub(r"--no-build", "", text), text
    assert "compose.yaml pull" in text and "session.yaml pull" in text, text


def test_the_platform_vm_runs_the_images_built_from_its_own_checkout():
    _, config = platform_vm_config()
    commands = [" ".join(map(str, c)) for c in config["runcmd"]]
    tagged = next(i for i, c in enumerate(commands) if "FSL_IMAGE_TAG=" in c)
    started = next(i for i, c in enumerate(commands) if "fsl-platform.service" in c)

    assert "git -C /opt/fsl rev-parse HEAD" in commands[tagged]
    assert "/opt/fsl/.env" in commands[tagged]
    assert tagged < started


def test_the_platform_vm_fetches_its_geoip_database_before_starting():
    _, config = platform_vm_config()
    commands = [" ".join(map(str, c)) for c in config["runcmd"]]

    fetched = commands.index("python3 /opt/fsl/bin/fetch-geoip")
    started = next(i for i, c in enumerate(commands) if "fsl-platform.service" in c)
    assert fetched < started


def test_the_platform_vm_flavor_in_the_example_is_eight_gigabytes():
    template, _ = platform_vm_config()
    [server] = [r["properties"] for r in template["resources"].values()
                if r["type"] == "OS::Nova::Server"]
    example = yaml.safe_load((ROOT / "deploy/openstack/cloud.example.yaml").read_text())

    assert server["flavor"] == {"get_param": "flavor"}
    assert example["compute"]["flavors"]["platform"] == "m1.large"


def test_the_range_key_never_enters_the_user_data():
    template, config = platform_vm_config()

    assert not [name for name in template["parameters"]
                if "key" in name and name not in ("key_name", "keystone")]
    assert "PRIVATE KEY" not in yaml.safe_dump(config)


def test_the_rebuild_refuses_without_a_cloud_file(tmp_path):
    done = subprocess.run([sys.executable, str(REBUILD), "--cloud", str(tmp_path / "absent.yaml")],
                          capture_output=True, text=True)

    assert done.returncode != 0
    assert "absent.yaml does not exist" in done.stderr and "cloud.example.yaml" in done.stderr


@pytest.mark.parametrize("changed, which, said", [
    ({"identity__password_file": "/nonexistent"}, "/bin/openstack", "/nonexistent, which does not exist"),
    ({"identity__keystone": "http://keystone:5000/v3"}, "/bin/openstack", "without /v3"),
    ({"network__estate": "10.20.0.0/24"}, "/bin/openstack", "overlaps"),
    ({}, None, "openstack CLI"),
])
def test_the_rebuild_refuses_before_touching_the_cloud(tmp_path, changed, which, said):
    module = rebuild()

    with pytest.raises(module.Refused, match=said):
        module.load(written_cloud(tmp_path, **changed), {}, lambda _: which)


def test_the_openstack_cli_is_driven_by_cloud_yaml_not_an_openrc(tmp_path):
    module = rebuild()

    cloud, environment = module.load(written_cloud(tmp_path), {}, lambda _: "/bin/openstack")

    assert environment["OS_AUTH_URL"] == "http://192.168.0.110:5000/v3"
    assert environment["OS_PASSWORD"] == "secret"
    assert environment["OS_PROJECT_NAME"] == cloud.project
    parameters = module.stack_arguments(cloud)
    assert "flavor=m1.large" in parameters and "image=ubuntu-24.04" in parameters


def test_the_rebuild_refuses_while_an_image_cannot_be_pulled():
    module = rebuild()
    missing = {"kali": "ghcr.io/nekonic/fsl-kali is not public, or was never pushed"}

    with pytest.raises(module.Refused, match="fsl-kali is not public"):
        module.refuse_unless_published("abc", lambda name, tag: missing.get(name))
    module.refuse_unless_published("abc", lambda name, tag: None)


def test_the_rebuild_refuses_to_lose_the_range_key(tmp_path):
    module = rebuild()

    with pytest.raises(module.Refused, match="range's VMs refuse"):
        module.keep_range_key(tmp_path / "absent", None)


def test_the_rebuild_keeps_a_range_key_it_already_has(tmp_path):
    module = rebuild()
    key = tmp_path / "range-key"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")

    module.keep_range_key(key, None)

    assert key.read_text().startswith("-----BEGIN OPENSSH PRIVATE KEY-----")


def test_the_rebuild_takes_the_range_key_from_the_running_platform_once(tmp_path):
    module = rebuild()

    class Old:
        def ssh(self, command):
            assert "/data/ssh/id_ed25519" in command
            return subprocess.CompletedProcess([], 0, b"-----BEGIN OPENSSH PRIVATE KEY-----\nx\n")

    key = tmp_path / "ssh" / "range-key"
    module.keep_range_key(key, Old())

    assert key.read_bytes().startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
    assert key.stat().st_mode & 0o777 == 0o600


class FloatingIps:
    def __init__(self, held):
        self.held, self.ran = held, []

    def __call__(self, argv, stdin=None, check=True):
        self.ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=self.held)


def test_the_reserved_floating_ip_is_found_by_its_address(tmp_path):
    module = rebuild()
    cloud, _ = module.load(written_cloud(tmp_path, network__address="192.168.0.210"), {},
                           lambda _: "/bin/openstack")
    cli = FloatingIps(b"fip-210\n")

    parameters = module.stack_arguments(cloud, cli)

    assert cli.ran == [["openstack", "floating", "ip", "list", "--floating-ip-address",
                        "192.168.0.210", "-f", "value", "-c", "ID"]]
    assert "floating_address=192.168.0.210" in parameters and "floating_ip_id=fip-210" in parameters


def test_an_address_the_project_does_not_hold_stops_the_rebuild(tmp_path):
    module = rebuild()
    cloud, _ = module.load(written_cloud(tmp_path, network__address="192.168.0.210"), {},
                           lambda _: "/bin/openstack")

    with pytest.raises(module.Refused, match="holds no floating IP at"):
        module.stack_arguments(cloud, FloatingIps(b""))


def test_without_an_address_no_floating_ip_is_looked_up(tmp_path):
    module = rebuild()
    cloud, _ = module.load(written_cloud(tmp_path), {}, lambda _: "/bin/openstack")
    cli = FloatingIps(b"")

    assert "floating_ip_id=" in module.stack_arguments(cloud, cli)
    assert cli.ran == []


class NewPlatform:
    def __init__(self):
        self.ran = []

    def ssh(self, command, stdin=None, check=True):
        self.ran.append(command)
        return subprocess.CompletedProcess([], 0, b"")

    def copy(self, source, destination):
        self.ran.append(f"copy {source} {destination}")


COMPOSE_2_40_DOCKER = """#!/bin/sh
case "$*" in
  *"config --images platform"*) printf 'docker.elastic.co/elasticsearch/elasticsearch:8\\nghcr.io/nekonic/fsl-platform:dev\\n' ;;
  "inspect --format {{.Config.Image}} fsl-platform") echo ghcr.io/nekonic/fsl-platform:dev ;;
  *) exit 1 ;;
esac
"""


def test_the_store_restore_runs_exactly_the_platform_image(tmp_path):
    module = rebuild()
    store = tmp_path / "store.sqlite3"
    store.write_bytes(b"")
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = NewPlatform()

    module.hand_over(platform, "secret", key, store)

    [restore] = [command for command in platform.ran if "docker run" in command]
    image = re.search(r"\$\((.*?)\) -c ", restore).group(1)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "docker").write_text(COMPOSE_2_40_DOCKER)
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    resolved = subprocess.run(
        ["sh", "-c", f'set -- $({image}); echo "$@"'],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, capture_output=True, text=True, check=True,
    ).stdout.split()

    assert resolved == ["ghcr.io/nekonic/fsl-platform:dev"], (
        f"the restore runs docker run with {resolved}: Compose 2.40 lists the images platform "
        f"depends on too, so anything but the platform image alone breaks bin/cloud up --replace"
    )
