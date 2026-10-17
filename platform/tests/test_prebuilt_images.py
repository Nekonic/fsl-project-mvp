import importlib.util
import json
import re
import subprocess
import tarfile
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


def test_ci_pushes_x86_64_images_tagged_by_the_commit_the_vm_pulls():
    [push] = [step for step in steps() if "build-push-action" in step["uses"]]

    assert push["with"]["platforms"] == "linux/amd64"
    assert "${{ github.sha }}" in push["with"]["tags"]


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


def test_the_range_key_never_enters_the_user_data():
    template, config = platform_vm_config()

    assert not [name for name in template["parameters"]
                if "key" in name and name not in ("key_name", "keystone")]
    assert "PRIVATE KEY" not in yaml.safe_dump(config)


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


def test_the_rebuild_keeps_the_range_key_it_has_and_refuses_to_go_on_without_one(tmp_path):
    module = rebuild()
    key = tmp_path / "range-key"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")

    module.keep_range_key(key, None)

    assert key.read_text().startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    with pytest.raises(module.Refused, match="range's VMs refuse"):
        module.keep_range_key(tmp_path / "absent", None)


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


class NewPlatform:
    def __init__(self):
        self.ran = []
        self.fed = {}

    def ssh(self, command, stdin=None, check=True):
        self.ran.append(command)
        self.fed[command] = stdin
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


HEAD = "1" * 40
BASE = "2" * 40


def saved(tmp_path, name, *tags):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"Config": "blobs/sha256/x", "RepoTags": list(tags), "Layers": []}]))
    tarball = tmp_path / name
    with tarfile.open(tarball, "w") as archive:
        archive.add(manifest, arcname="manifest.json")
    return tarball


def test_a_sideloaded_image_is_not_looked_for_on_ghcr_and_the_others_are(tmp_path):
    module = rebuild()
    tarball = saved(tmp_path, "gns3.tar", f"ghcr.io/nekonic/fsl-gns3:{HEAD}")
    asked = []

    tarballs = module.sideloaded([f"gns3={tarball}"])
    module.refuse_unless_published(BASE, lambda name, tag: asked.append((name, tag)), sideloaded=tarballs)

    assert tarballs == {"gns3": module.Tarball(tarball, HEAD)}
    assert asked == [(name, BASE) for name in module.IMAGES if name != "gns3"]


@pytest.mark.parametrize("pair, said", [
    ("gns3={missing}", "does not exist, so nothing was deleted"),
    ("waf={tarball}", "NAME one of"),
    ("gns3", "NAME one of"),
    ("gns3={wrong}", "holds no single ghcr.io/nekonic/fsl-gns3:<commit>"),
    ("gns3={two}", "holds no single ghcr.io/nekonic/fsl-gns3:<commit>"),
    ("gns3={unreadable}", "not a docker save tarball"),
])
def test_the_rebuild_refuses_a_sideload_it_cannot_run_before_deleting_anything(tmp_path, pair, said):
    module = rebuild()
    paths = {
        "missing": tmp_path / "absent.tar",
        "tarball": saved(tmp_path, "gns3.tar", f"ghcr.io/nekonic/fsl-gns3:{HEAD}"),
        "wrong": saved(tmp_path, "platform.tar", f"ghcr.io/nekonic/fsl-platform:{HEAD}",
                       "ghcr.io/nekonic/fsl-gns3:dev"),
        "two": saved(tmp_path, "both.tar", f"ghcr.io/nekonic/fsl-gns3:{HEAD}",
                     f"ghcr.io/nekonic/fsl-gns3:{BASE}"),
        "unreadable": tmp_path / "plain.tar",
    }
    paths["unreadable"].write_text("not a tar")

    with pytest.raises(module.Refused, match=said):
        module.sideloaded([pair.format(**paths)])


class ChangedContexts:
    def __init__(self, changed, broken=False):
        self.changed, self.broken, self.compared = changed, broken, []

    def __call__(self, argv, stdin=None, check=True):
        source, context = argv[-4], argv[-1]
        self.compared.append((source, context))
        code = 128 if self.broken else 1 if (source, context) in self.changed else 0
        return subprocess.CompletedProcess(argv, code, b"", b"")


def test_every_image_must_be_built_from_what_head_holds():
    module = rebuild()
    built = "3" * 40
    git = ChangedContexts({(BASE, "platform"), (BASE, "deploy/gns3")})
    platform = {"platform": module.Tarball(Path("p.tar"), built)}

    with pytest.raises(module.Refused, match=rf"sideload them:\n  gns3: deploy/gns3 differs between {BASE} and HEAD$"):
        module.refuse_unless_unchanged(BASE, HEAD, platform, git)
    assert (built, "platform") in git.compared and (BASE, "deploy/kali") in git.compared
    module.refuse_unless_unchanged(
        BASE, HEAD, {**platform, "gns3": module.Tarball(Path("g.tar"), built)}, git)
    with pytest.raises(module.Refused, match=f"platform: platform differs between {built} and HEAD"):
        module.refuse_unless_unchanged(BASE, HEAD, platform, ChangedContexts({(built, "platform")}))
    assert set(module.build_contexts()) == set(module.IMAGES)


def test_a_commit_missing_here_stops_the_sideload():
    module = rebuild()

    with pytest.raises(module.Refused, match="git fetch it first"):
        module.refuse_unless_unchanged(BASE, HEAD, {}, ChangedContexts(set(), broken=True))


def test_a_sideloaded_rebuild_checks_head_out_and_loads_only_the_named_images(tmp_path):
    module = rebuild()
    store = tmp_path / "store.sqlite3"
    store.write_bytes(b"")
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    bundle = tmp_path / f"fsl-{HEAD}.bundle"
    built = "3" * 40
    sideload = module.Sideload(HEAD, bundle, {"gns3": module.Tarball(tmp_path / "gns3.tar", built)})
    platform = NewPlatform()

    module.hand_over(platform, "secret", key, store, sideload)

    ran = platform.ran
    checkout = next(i for i, command in enumerate(ran) if f"checkout -q --detach {HEAD}" in command)
    assert f"fetch -q /tmp/{bundle.name} HEAD" in ran[checkout]
    [load] = [command for command in ran if "docker load" in command]
    assert f"/tmp/gns3.tar" in load
    assert (f"docker tag ghcr.io/nekonic/fsl-gns3:{built} ghcr.io/nekonic/fsl-gns3:"
            "$(sed -n 's/^FSL_IMAGE_TAG=//p' /opt/fsl/.env)") in load
    restore = next(i for i, command in enumerate(ran) if "docker run" in command)
    assert checkout < ran.index(load) < restore
    assert ran[-1] == "cd /opt/fsl && sudo docker compose -f /opt/fsl/compose.yaml up -d --force-recreate", (
        "HEAD's compose file may add services, so every service starts, not only the platform; and a file "
        "bind-mounted into a running container keeps the cloned commit's copy after the checkout, so the "
        "collector ran the old filebeat.yml until each service was recreated"
    )
    assert platform.fed["cat >> /opt/fsl/openstack.env"] == b"FSL_OPENSTACK_PASSWORD=secret\nFSL_SIDELOADED=gns3\n", (
        "the platform ships a sideloaded wargame image to the wargame host's builder instead of GHCR's copy "
        "at the same tag, so it has to know which images were sideloaded"
    )


def test_without_a_sideload_the_rebuild_pulls_everything_and_restarts_only_the_platform(tmp_path):
    module = rebuild()
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = NewPlatform()

    module.hand_over(platform, "secret", key, None)

    assert not [command for command in platform.ran if "docker load" in command or "git " in command]
    assert platform.ran[-1].endswith("up -d platform")
    assert platform.fed["cat >> /opt/fsl/openstack.env"] == b"FSL_OPENSTACK_PASSWORD=secret\n"
