import importlib.util
import json
import re
import sqlite3
import stat
import subprocess
import tarfile
from contextlib import closing
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


def test_the_platform_hands_its_image_tag_to_the_range_it_builds():
    environment = composed.services()["platform"]["environment"]

    assert environment["FSL_IMAGE_TAG"] == "${FSL_IMAGE_TAG:-dev}", (
        "the platform ships the wargame images to the wargame host at this tag; "
        "without it the range would run :dev whatever the VM pulled"
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
    assert "compose.yaml pull" in text and "session.yaml" not in text, text


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
    missing = {"corp-db": "ghcr.io/nekonic/fsl-corp-db is not public, or was never pushed"}

    with pytest.raises(module.Refused, match="fsl-corp-db is not public"):
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


def test_the_first_bring_up_makes_the_range_key_and_a_replace_still_refuses_without_one(tmp_path):
    module = rebuild()
    key = tmp_path / "ssh" / "range-key"
    ran = []

    def keygen(argv, stdin=None, check=True):
        ran.append(argv)
        Path(argv[argv.index("-f") + 1]).write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    module.keep_range_key(key, None, first=True, run=keygen)

    assert ran[0][:2] == ["ssh-keygen", "-q"] and "ed25519" in ran[0] and str(key) in ran[0]
    assert key.is_file()
    module.keep_range_key(key, None, first=True, run=keygen)
    assert len(ran) == 1, "an existing key is never replaced"
    with pytest.raises(module.Refused, match="range's VMs refuse"):
        module.keep_range_key(tmp_path / "absent", None, run=keygen)
    assert len(ran) == 1


def test_the_rebuild_says_what_ssh_answered_when_the_new_vm_never_takes_it(monkeypatch, tmp_path):
    module = rebuild()
    monkeypatch.setattr(module, "SSH_WAIT", -1)
    host = module.Host("ubuntu", "10.0.0.5", tmp_path / "known_hosts", tmp_path / "key")
    monkeypatch.setattr(module, "run", lambda argv, stdin=None, check=True: subprocess.CompletedProcess(
        argv, 255, b"", b"ubuntu@10.0.0.5: Permission denied (publickey)."))

    with pytest.raises(module.Refused, match="Permission denied"):
        host.wait()


def test_the_openstack_cli_beside_the_interpreter_is_found_before_the_path(monkeypatch, tmp_path):
    module = rebuild()
    python = tmp_path / "bin" / "python"
    python.parent.mkdir()
    python.write_text("")
    monkeypatch.setattr(module.sys, "executable", str(python))

    assert module.openstack_cli(lambda name: "/usr/bin/openstack") == "/usr/bin/openstack"
    (python.parent / "openstack").write_text("")
    assert module.openstack_cli(lambda name: "/usr/bin/openstack") == str(python.parent / "openstack")


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

    def settings_fed(self):
        return next(stdin for command, stdin in self.fed.items() if "openstack.env.kept" in command)


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
    assert (built, "platform") in git.compared and (BASE, "wargames/corp/db") in git.compared
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
    [venv] = [command for command in ran if "fsl-venv-checkout" in command]
    assert ran.index(venv) > checkout and "--no-block" in venv and module.VENV_COMMAND in venv.replace("'", ""), (
        "a sideload checkout can change platform/requirements.txt, and the pip install must not hold up the hand-over"
    )
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
    assert platform.settings_fed() == b"FSL_OPENSTACK_PASSWORD=secret\nFSL_SIDELOADED=gns3\n", (
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
    assert platform.settings_fed() == b"FSL_OPENSTACK_PASSWORD=secret\n"


class Probed:
    target = "ubuntu@203.0.113.7"

    def __init__(self, returncode=0, out=b"", err=b""):
        self.answer = subprocess.CompletedProcess([], returncode, out, err)

    def ssh(self, command, stdin=None, check=True):
        return self.answer


def test_a_vm_that_answers_with_nothing_holds_no_store_and_one_that_says_stored_does():
    module = rebuild()

    assert module.holds_store(Probed(0, b"")) is False
    assert module.holds_store(Probed(0, b"stored\n")) is True


@pytest.mark.parametrize("code, said", [(255, "Permission denied"), (3, "")])
def test_a_vm_that_cannot_be_asked_is_never_taken_to_hold_nothing(code, said):
    module = rebuild()

    with pytest.raises(module.Refused, match="cannot tell whether ubuntu@203.0.113.7 holds"):
        module.holds_store(Probed(code, b"", said.encode()))


@pytest.fixture
def probe(tmp_path):
    module = rebuild()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "test").write_text('#!/bin/sh\n[ "$@" ]\n')
    for name in ("sudo", "test"):
        (bin_dir / name).chmod(0o755)
    volume = tmp_path / "volume"
    volume.mkdir()
    script = module.STORE_PROBE.replace(module.STORE_DIRECTORY, str(volume))

    def run(docker=None, stored=False):
        (bin_dir / "docker").unlink(missing_ok=True)
        if docker is not None:
            (bin_dir / "docker").write_text(f"#!/bin/sh\n{docker}\n")
            (bin_dir / "docker").chmod(0o755)
        (volume / "db.sqlite3").unlink(missing_ok=True)
        if stored:
            (volume / "db.sqlite3").write_bytes(b"")
        done = subprocess.run(["/bin/sh", "-c", script], env={"PATH": str(bin_dir)},
                              capture_output=True, text=True)
        return done.returncode, done.stdout.strip()

    return run


def test_the_store_probe_finds_nothing_only_where_docker_is_absent_or_never_ran_the_platform(probe):
    assert probe(docker=None) == (0, ""), "a VM whose cloud-init stopped before Docker has nothing to lose"
    assert probe(docker="exit 0") == (0, ""), "Docker with no platform container and no store file"


@pytest.mark.parametrize("docker, stored", [("echo abc123", False), ("exit 0", True), ("echo abc123", True)])
def test_the_store_probe_reports_a_running_platform_or_a_store_file_as_something_to_keep(probe, docker, stored):
    code, out = probe(docker=docker, stored=stored)

    assert code == 0 and out


def test_the_store_probe_cannot_tell_when_docker_does_not_answer(probe):
    code, out = probe(docker="exit 1", stored=True)

    assert code == 3 and not out


class Unfinished(NewPlatform):
    def ssh(self, command, stdin=None, check=True):
        self.ran.append(command)
        return subprocess.CompletedProcess([], 1, b"", b"")


def test_a_vm_whose_first_boot_did_not_finish_stops_the_hand_over_and_says_how_to_make_it_again(tmp_path):
    module = rebuild()
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = Unfinished()
    platform.target = "ubuntu@203.0.113.7"

    with pytest.raises(module.Refused, match=r"first boot did not finish.*up --replace"):
        module.hand_over(platform, "secret", key, None)
    assert len(platform.ran) == 1


HANDED_OVER = "FSL_OPENSTACK_USER=fsl\nFSL_OPENSTACK_PASSWORD=old\nFSL_SIDELOADED=board,platform\nFSL_OPENSTACK_PLATFORM=srv\n"


def rewritten_settings(monkeypatch, tmp_path, sideload):
    module = rebuild()
    checkout = tmp_path / "fsl"
    checkout.mkdir()
    settings = checkout / "openstack.env"
    settings.write_text(HANDED_OVER)
    settings.chmod(0o600)
    monkeypatch.setattr(module, "CHECKOUT", str(checkout))
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = NewPlatform()
    module.hand_over(platform, "secret", key, None, sideload)
    [rewrite] = [command for command in platform.ran if "openstack.env.kept" in command]
    subprocess.run(["/bin/sh", "-c", rewrite], input=platform.fed[rewrite], check=True)
    assert not (checkout / "openstack.env.kept").exists()
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600
    return module, settings.read_text()


def test_a_second_hand_over_leaves_one_password_line_and_keeps_every_line_it_does_not_own(monkeypatch, tmp_path):
    _, settings = rewritten_settings(monkeypatch, tmp_path, None)

    assert settings == (
        "FSL_OPENSTACK_USER=fsl\nFSL_SIDELOADED=board,platform\nFSL_OPENSTACK_PLATFORM=srv\n"
        "FSL_OPENSTACK_PASSWORD=secret\n"
    ), (
        "plain up redoes the hand-over on a VM that was sideloaded; dropping FSL_SIDELOADED made the "
        "platform pull GHCR's wargame images over the sideloaded ones and rebuild the wargame host"
    )


def test_a_sideloading_hand_over_rewrites_the_sideloaded_line_too(monkeypatch, tmp_path):
    module = rebuild()
    sideload = module.Sideload(HEAD, tmp_path / "head.bundle",
                               {"gns3": module.Tarball(tmp_path / "gns3.tar", "3" * 40)})

    _, settings = rewritten_settings(monkeypatch, tmp_path, sideload)

    assert settings == (
        "FSL_OPENSTACK_USER=fsl\nFSL_OPENSTACK_PLATFORM=srv\n"
        "FSL_OPENSTACK_PASSWORD=secret\nFSL_SIDELOADED=gns3\n"
    )


def test_the_range_key_is_written_into_a_platform_container_that_is_started_first(tmp_path):
    module = rebuild()
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = NewPlatform()

    module.hand_over(platform, "secret", key, None)

    started = next(i for i, command in enumerate(platform.ran) if "up -d platform >/dev/null" in command)
    written = next(i for i, command in enumerate(platform.ran) if "docker exec -i -u fsl fsl-platform" in command)
    assert started < written, (
        "a redone hand-over found the platform container stopped and docker exec refused the key "
        "with 'container ... is not running'"
    )


def test_a_platform_container_that_will_not_start_stops_the_hand_over_before_anything_is_written(tmp_path):
    module = rebuild()

    class Stopped(NewPlatform):
        target = "ubuntu@203.0.113.7"

        def ssh(self, command, stdin=None, check=True):
            self.ran.append(command)
            failing = "up -d platform >/dev/null" in command
            return subprocess.CompletedProcess([], 1 if failing else 0, b"", b"dependency failed" if failing else b"")

    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = Stopped()

    with pytest.raises(module.Refused, match=r"fsl-platform container on ubuntu@203.0.113.7 is not running.*dependency failed"):
        module.hand_over(platform, "secret", key, None)
    assert not [command for command in platform.ran if "docker exec" in command or "openstack.env" in command]


def test_the_password_that_marks_a_finished_hand_over_is_written_after_the_store_is_restored(tmp_path):
    module = rebuild()
    store = tmp_path / "store.sqlite3"
    store.write_bytes(b"")
    key = tmp_path / "range-key"
    key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    platform = NewPlatform()

    module.hand_over(platform, "secret", key, store)

    restore = next(i for i, command in enumerate(platform.ran) if "docker run" in command)
    marked = next(i for i, command in enumerate(platform.ran) if "openstack.env.kept" in command)
    assert restore < marked < len(platform.ran) - 1, (
        "plain up takes a VM with the password line as handed over and restores nothing; a hand-over "
        "that broke before its store was in place must not leave that line behind"
    )


@pytest.mark.parametrize("code, done", [(0, True), (1, False)])
def test_the_hand_over_counts_as_done_only_when_the_password_line_is_found(code, done):
    assert rebuild().hand_over_done(Probed(code)) is done


@pytest.mark.parametrize("code, said", [(255, "Connection timed out"), (2, "Permission denied")])
def test_a_hand_over_that_cannot_be_checked_is_never_redone(code, said):
    module = rebuild()

    with pytest.raises(module.Refused, match="cannot tell whether ubuntu@203.0.113.7 took its hand-over"):
        module.hand_over_done(Probed(code, b"", said.encode()))


def test_the_hand_over_check_reads_a_missing_settings_file_as_not_done(monkeypatch, tmp_path):
    module = rebuild()
    checkout = tmp_path / "fsl"
    checkout.mkdir()
    monkeypatch.setattr(module, "CHECKOUT", str(checkout))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)

    class Shell:
        target = "ubuntu@203.0.113.7"

        def ssh(self, command, stdin=None, check=True):
            return subprocess.run(["/bin/sh", "-c", command], env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
                                  capture_output=True)

    assert module.hand_over_done(Shell()) is False, "cloud-init has not moved openstack.env into place yet"
    (checkout / "openstack.env").write_text("FSL_OPENSTACK_USER=fsl\n")
    assert module.hand_over_done(Shell()) is False
    (checkout / "openstack.env").write_text("FSL_OPENSTACK_USER=fsl\nFSL_OPENSTACK_PASSWORD=secret\n")
    assert module.hand_over_done(Shell()) is True


def stamped_backup(directory, name, rows):
    directory.mkdir(exist_ok=True)
    path = directory / name
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE api_session (id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO api_session DEFAULT VALUES", [()] * rows)
        db.commit()
    return path


def test_the_newest_backup_that_holds_rows_is_the_one_restored(monkeypatch, tmp_path):
    module = rebuild()
    backups = tmp_path / "backups"
    monkeypatch.setattr(module, "BACKUPS", backups)
    assert module.newest_backup() is None
    stamped_backup(backups, "db-20261001T000000Z.sqlite3", 3)
    wanted = stamped_backup(backups, "db-20261002T000000Z.sqlite3", 2)
    stamped_backup(backups, "db-20261003T000000Z.sqlite3", 0)
    stamped_backup(backups, "db-20261004-pre-p6.sqlite3", 5)
    (backups / "db-20261005T000000Z.sqlite3").write_bytes(b"not a store")

    assert module.newest_backup() == wanted, (
        "an empty backup or one that is not a store is skipped, and a file named by hand is never "
        "picked, as bin/backup never removes it"
    )


class Resumed:
    def __init__(self, module, monkeypatch, tmp_path, answers=False, done=False, holds=False):
        self.module, self.calls = module, []
        self.backups = tmp_path / "backups"
        monkeypatch.setattr(module, "BACKUPS", self.backups)
        self.cloud, self.environment = module.load(
            written_cloud(tmp_path, keys__range=str(tmp_path / "range-key")), {}, lambda _: "/bin/openstack")
        monkeypatch.setattr(module, "api_answers", lambda address: answers)
        monkeypatch.setattr(module.Host, "wait", lambda host: self.calls.append("ssh"))
        monkeypatch.setattr(module, "hand_over_done", lambda host: done)
        monkeypatch.setattr(module, "holds_store", lambda host: holds)
        monkeypatch.setattr(module, "start_platform", lambda host: self.calls.append("start"))
        monkeypatch.setattr(module, "keep_range_key",
                            lambda key, old, first=False, run=None: self.calls.append(("key", old is not None, first)))
        monkeypatch.setattr(module, "hand_over",
                            lambda host, password, key, store, sideload=None: self.calls.append(("hand_over", store)))
        monkeypatch.setattr(module, "wait_for_api", lambda address: self.calls.append("api"))

    def resume(self, sideload=()):
        self.module.resume(self.cloud, self.environment, "203.0.113.7", list(sideload))
        return self.calls


def test_a_platform_that_answers_and_took_its_hand_over_is_left_alone(monkeypatch, tmp_path):
    assert Resumed(rebuild(), monkeypatch, tmp_path, answers=True, done=True).resume() == ["ssh", "api"]


def test_a_platform_that_answers_without_its_password_line_gets_the_hand_over_again(monkeypatch, tmp_path):
    calls = Resumed(rebuild(), monkeypatch, tmp_path, answers=True, done=False, holds=True).resume()

    assert calls == ["ssh", "start", ("key", True, False), ("hand_over", None), "api"], (
        "a container started before the password line went away still answers; the range build "
        "then fails, so the answer alone does not mean the hand-over was taken")


def test_a_stack_whose_platform_never_took_its_hand_over_gets_it_instead_of_a_twenty_minute_wait(
        monkeypatch, tmp_path):
    calls = Resumed(rebuild(), monkeypatch, tmp_path, done=False).resume()

    assert calls == ["ssh", ("key", False, True), ("hand_over", None), "api"]


def test_a_platform_that_took_its_hand_over_and_is_still_booting_is_waited_for(monkeypatch, tmp_path):
    assert Resumed(rebuild(), monkeypatch, tmp_path, done=True).resume() == ["ssh", "api"]


def test_a_hand_over_redone_on_a_vm_that_holds_a_store_takes_the_key_from_it(monkeypatch, tmp_path):
    calls = Resumed(rebuild(), monkeypatch, tmp_path, done=False, holds=True).resume()

    assert calls == ["ssh", "start", ("key", True, False), ("hand_over", None), "api"], (
        "the store's container may be stopped; the key is taken from it with docker exec"
    )


def test_a_hand_over_redone_on_a_vm_that_holds_no_store_restores_the_newest_backup(monkeypatch, tmp_path, capsys):
    resumed = Resumed(rebuild(), monkeypatch, tmp_path, done=False, holds=False)
    newest = stamped_backup(resumed.backups, "db-20261019T033253Z.sqlite3", 4)

    assert ("hand_over", newest) in resumed.resume()
    assert f"restoring {newest}" in capsys.readouterr().out


def test_a_sideload_is_not_silently_dropped_when_the_hand_over_is_redone(monkeypatch, tmp_path):
    module = rebuild()
    resumed = Resumed(module, monkeypatch, tmp_path, done=False)

    with pytest.raises(module.Refused, match="up --replace --sideload"):
        resumed.resume(["platform=x.tar"])
    assert "api" not in resumed.calls and ("hand_over", None) not in resumed.calls


class Replacing:
    def __init__(self, module, monkeypatch, tmp_path, holds, status="CREATE_COMPLETE", kept_rows=1,
                 address="203.0.113.7"):
        self.calls = []
        self.backups = tmp_path / "backups"
        monkeypatch.setattr(module, "BACKUPS", self.backups)
        self.cloud, self.environment = module.load(
            written_cloud(tmp_path, keys__range=str(tmp_path / "range-key")), {}, lambda _: "/bin/openstack")
        monkeypatch.setattr(module, "commit_of", lambda repository, ref: "a" * 40)
        monkeypatch.setattr(module, "refuse_unless_published", lambda *args, **kwargs: None)
        monkeypatch.setattr(module, "stack_status", lambda stack: status)
        monkeypatch.setattr(module, "address_of", lambda stack, run=None: address)
        monkeypatch.setattr(module, "holds_store", lambda old: holds)
        monkeypatch.setattr(module, "start_platform", lambda old: self.calls.append("start"))
        monkeypatch.setattr(module, "keep_range_key",
                            lambda key, old, first=False, run=None: self.calls.append(("key", old is not None, first)))

        def back_up(old, keep):
            self.calls.append("back_up")
            self.kept = stamped_backup(self.backups, "db-20261020T120000Z.sqlite3", kept_rows)
            return self.kept

        monkeypatch.setattr(module, "back_up", back_up)
        monkeypatch.setattr(module, "replace_stack",
                            lambda cloud, existed: self.calls.append("replace_stack") or "203.0.113.8")
        monkeypatch.setattr(module.Host, "wait", lambda host: None)
        monkeypatch.setattr(module, "hand_over",
                            lambda host, password, key, store, sideload=None: self.calls.append(("hand_over", store)))
        monkeypatch.setattr(module, "wait_for_api", lambda address: None)
        self.module = module

    def run(self):
        self.module.rebuild(self.cloud, self.environment)
        return self.calls


def test_replacing_a_platform_that_never_stored_anything_needs_no_backup(monkeypatch, tmp_path, capsys):
    calls = Replacing(rebuild(), monkeypatch, tmp_path, holds=False).run()

    assert calls == [("key", False, True), "replace_stack", ("hand_over", None)]
    assert "starts with an empty store" in capsys.readouterr().out


def test_replacing_a_platform_that_holds_a_store_still_backs_it_up_first(monkeypatch, tmp_path):
    replacing = Replacing(rebuild(), monkeypatch, tmp_path, holds=True)
    calls = replacing.run()

    assert calls == ["start", ("key", True, True), "back_up", "replace_stack", ("hand_over", replacing.kept)]


@pytest.mark.parametrize("status", ["CREATE_COMPLETE", "CREATE_FAILED", None],
                         ids=["vm-that-never-took-its-hand-over", "failed-stack", "no-stack-after-down"])
def test_a_platform_made_where_no_store_stands_gets_the_newest_backup(monkeypatch, tmp_path, capsys, status):
    replacing = Replacing(rebuild(), monkeypatch, tmp_path, holds=False, status=status)
    newest = stamped_backup(replacing.backups, "db-20261019T033253Z.sqlite3", 4)

    calls = replacing.run()

    assert calls[-1] == ("hand_over", newest), (
        "up --replace backed the store up, the new VM's hand-over failed, and the advice is to run "
        "up --replace again: that VM holds no store, so the backup is the only copy and must be restored"
    )
    assert f"restoring {newest}" in capsys.readouterr().out


def test_a_replaced_vm_whose_store_is_empty_hands_on_the_older_backup_that_holds_rows(monkeypatch, tmp_path):
    replacing = Replacing(rebuild(), monkeypatch, tmp_path, holds=True, kept_rows=0)
    older = stamped_backup(replacing.backups, "db-20261019T033253Z.sqlite3", 4)

    calls = replacing.run()

    assert calls[-1] == ("hand_over", older)


def test_a_standing_stack_whose_address_cannot_be_read_is_never_deleted(monkeypatch, tmp_path):
    module = rebuild()
    replacing = Replacing(module, monkeypatch, tmp_path, holds=True, address=None)

    with pytest.raises(module.Refused, match="CREATE_COMPLETE but its address output cannot be read"):
        replacing.run()
    assert replacing.calls == []
