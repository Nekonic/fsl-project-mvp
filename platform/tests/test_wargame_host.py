import io
import json
import pathlib
import shlex
import subprocess
import tarfile
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
import yaml

from range import declared, images, openstack, ports, wargame_host
from range.ports import Drifted, Node, Ran, Segment, Shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
OS = declared.read()
HOST = "cr-wargame-host"
ENTRY = OS.hosts[HOST]
SPEC = openstack.Cloud(
    keystone="http://keystone:5000", neutron="http://neutron:9696",
    nova="http://nova:8774/v2.1", glance="http://glance:9292", project="cr",
    user="cr", ssh_user="ubuntu", ssh_key="/keys/cr",
)

def _adapter(tag="c0ffee", mtu=1450, sideloaded=frozenset()):
    built = openstack.OpenStack(OS, SPEC, get=None, build=openstack.Build(
        source=str(ROOT), image_tag=tag, mtu=mtu, sideloaded=frozenset(sideloaded)))
    built._shape = Shape(segments=(
        Segment(id="estate", name="Estate", subnet="10.30.0.0/24",
                nodes=(Node(HOST, "10.30.0.20"),)),
        Segment(id="mgmt", name="Management", subnet="10.31.0.0/24",
                nodes=(Node(HOST, "10.31.0.20"),)),
    ), sensors=())
    return built

def _shipped(wargame, tag="c0ffee"):
    files = wargame_host.generated(ROOT, HOST, ENTRY.wargames, ENTRY.publish, tag, 1450)
    return yaml.safe_load(files[wargame_host.SHIPPED.format(wargame=wargame)])

def _members(bundle):
    with tarfile.open(fileobj=io.BytesIO(bundle.archive)) as archive:
        return {member.name: archive.extractfile(member).read() for member in archive.getmembers()}

def test_the_host_runs_the_same_ghcr_images_as_docker_at_the_platforms_tag():
    compose = yaml.safe_load((ROOT / "wargames/board/compose.yaml").read_text())

    shipped = _shipped("board")

    assert shipped["services"]["board"]["image"] == "ghcr.io/nekonic/cr-board:c0ffee"
    assert shipped["services"]["board-db"]["image"] == compose["services"]["board-db"]["image"]
    assert set(shipped["services"]) == set(compose["services"])

def test_the_shipped_compose_file_builds_nothing_and_names_each_container_by_its_service():
    for service, entry in _shipped("board")["services"].items():
        assert "build" not in entry, "the range has no Internet and no source tree to build from"
        assert "networks" not in entry, "on the host the project's own default network serves"
        assert entry["container_name"] == service

@pytest.mark.parametrize("wargame, front, port, database", [
    ("board", "board", 8000, "board-db"),
    ("corp", "corp-wp", 80, "corp-db"),
])
def test_only_the_services_the_waf_proxies_to_are_published_on_the_host(wargame, front, port, database):
    services = _shipped(wargame)["services"]

    assert services[front]["ports"] == [f"{ENTRY.publish[front]}:{port}"]
    assert "ports" not in services[database], "the database answers only inside its project"

def test_the_board_is_published_where_the_ground_truth_reader_and_the_waf_expect_it():
    from django.conf import settings

    assert ENTRY.publish["board"] == urlsplit(settings.BOARD_API_URL).port
    assert "proxy_pass http://board:8000;" in (ROOT / "deploy/waf/board.com.conf").read_text()
    assert {"board", OS.compose["corp"]} <= set(ENTRY.names), "the WAF resolves both to the host through /etc/hosts"
    assert {"board.com", "corp.com"} <= set(OS.hosts["cr-waf"].names)

def test_the_containers_networks_take_the_tenant_mtu():
    files = wargame_host.generated(ROOT, HOST, ENTRY.wargames, ENTRY.publish, "c0ffee", 1450)

    daemon = json.loads(files[wargame_host.DAEMON])

    assert daemon["mtu"] == 1450
    assert daemon["default-network-opts"]["bridge"]["com.docker.network.driver.mtu"] == "1450"

def test_a_new_platform_tag_is_a_new_host_image():
    def bundle(tag):
        return _adapter(tag=tag)._bundle(HOST, ENTRY)

    assert bundle("c0ffee").digest != bundle("decaf").digest, (
        "the images are pulled into the host image at build time; a platform on "
        "a new tag needs a host image holding that tag's images"
    )
    assert bundle("c0ffee").digest == bundle("c0ffee").digest

def test_an_image_sideloaded_for_the_platform_alone_leaves_the_host_image_as_ghcr_builds_it(monkeypatch):
    monkeypatch.setattr(wargame_host, "local_image_id", lambda image: pytest.fail("asked docker"))
    plain = _adapter()._bundle(HOST, ENTRY)

    for sideloaded in ({"platform"}, {"platform", "kali", "gns3"}):
        bundle = _adapter(sideloaded=sideloaded)._bundle(HOST, ENTRY)
        assert (bundle.digest, _members(bundle)) == (plain.digest, _members(plain)), (
            "no wargame image was sideloaded, so the host pulls every image from GHCR as before")
    assert wargame_host.LOADED not in wargame_host.generated(
        ROOT, HOST, ENTRY.wargames, ENTRY.publish, "c0ffee", 1450)

def test_a_sideloaded_board_reaches_the_host_image_from_the_platform_and_its_image_id_is_in_the_digest(monkeypatch):
    held = {"ghcr.io/nekonic/cr-board:c0ffee": "sha256:" + "a" * 64}
    monkeypatch.setattr(wargame_host, "local_image_id", lambda image: held[image])
    monkeypatch.setattr(openstack.OpenStack, "_platform_address", lambda self, why: "10.0.0.5")
    built = _adapter(sideloaded={"board", "platform"})

    first = built._bundle(HOST, ENTRY)
    loaded = _members(first)[wargame_host.LOADED].decode()
    served = _members(first)[wargame_host.SERVED_FROM].decode()
    held["ghcr.io/nekonic/cr-board:c0ffee"] = "sha256:" + "b" * 64

    assert loaded == "ghcr.io/nekonic/cr-board:c0ffee sha256:" + "a" * 64 + " board\n", (
        "GHCR's board at the platform's tag is the pushed one; the host image must hold the board the "
        "platform runs, and setup.sh checks the loaded image is that image")
    assert served == "http://10.0.0.5:8000/api/range/images/sideloaded/\n"
    assert built._bundle(HOST, ENTRY).digest != first.digest, (
        "a slot reset keeps the wargame host's images, so a new board needs a new host image")
    assert built.sideloaded_image("board") == "ghcr.io/nekonic/cr-board:c0ffee"
    assert built.sideloaded_image("platform") == "", "the platform serves only a wargame image it runs"
    assert built.sideloaded_image("corp") == ""

def test_a_platform_at_a_new_address_reuses_the_host_image_it_sideloaded_into(monkeypatch):
    monkeypatch.setattr(wargame_host, "local_image_id", lambda image: "sha256:" + "a" * 64)
    built = _adapter(sideloaded={"board", "platform"})

    monkeypatch.setattr(openstack.OpenStack, "_platform_address", lambda self, why: "10.20.0.27")
    first = built._bundle(HOST, ENTRY)
    monkeypatch.setattr(openstack.OpenStack, "_platform_address", lambda self, why: "10.20.0.141")
    moved = built._bundle(HOST, ENTRY)

    assert _members(moved)[wargame_host.SERVED_FROM] == b"http://10.20.0.141:8000/api/range/images/sideloaded/\n"
    assert moved.digest == first.digest, (
        "bin/cloud down then up makes a new platform VM whose fixed IP Neutron picks again; setup.sh "
        "checks the image id it fetched, so where it fetched it from is not what the host image holds")

def test_the_host_setup_fetches_each_sideloaded_image_from_the_address_the_platform_gave():
    setup = (ROOT / "deploy/wargame-host/setup.sh").read_text()

    assert "served=$(cat served-from)" in setup
    assert 'while read -r image id name; do' in setup and '"$served$name/"' in setup

def test_a_wargame_starts_from_its_installed_file_with_no_pull_on_volumes_filled_from_its_pristine_copy():
    argv = wargame_host.up("board")
    script = argv[3].splitlines()
    compose = "docker compose -p board -f /opt/cr/wargames/board.yaml"

    assert argv[:3] == ["sudo", "sh", "-c"] and script[0] == "set -e"
    created = script.index(f"{compose} up --no-start --pull never")
    restored = next(i for i, line in enumerate(script) if f"sh {wargame_host.PRISTINE} restore board" in line)
    started = script.index(f"{compose} up -d --wait --pull never")
    assert created < restored < started, (
        "the containers' new volumes are filled from the copy kept at image build before any "
        "container starts, so MySQL finds an initialised datadir and skips its initialisation")
    assert all("--pull never" in line for line in script if " up " in line), (
        "the range has no route to ghcr.io; the images are already on the host")

def test_the_pristine_copy_is_made_once_at_image_build_and_never_by_a_reset():
    setup = (ROOT / "deploy/wargame-host/setup.sh").read_text()
    pristine = (ROOT / "deploy/wargame-host/pristine.sh").read_text()
    kept = setup.index('sh /opt/cr/pristine.sh keep "${wargame%.yaml}"')

    assert f"install -m 0755 pristine.sh {wargame_host.PRISTINE}" in setup
    assert kept > setup.index("docker load") and kept > setup.index("pull --quiet"), (
        "the copy is made from the images the host image holds")
    assert "CR_PRISTINE:-/opt/cr/pristine}" in pristine
    assert not "/opt/cr/pristine".startswith(images.WORKDIR), "the builder deletes its workdir after setup"
    reset = [*wargame_host.up("board"), *wargame_host.cleared(["board", "corp"], (), True)]
    assert not any(" keep " in part for part in reset)
    assert not any("pristine" in part for part in wargame_host.cleared(["board", "corp"], (), True)), (
        "down -v removes the containers' volumes and leaves the pristine copy alone")

def _clear(tmp_path, failing):
    (tmp_path / "bin").mkdir(exist_ok=True)
    docker = tmp_path / "bin" / "docker"
    docker.write_text(f"""#!/bin/sh
echo "$*" >> {tmp_path}/downs
case "$*" in *"-p {failing} "*) sleep 1; exit 3 ;; esac
sleep 1
""")
    docker.chmod(0o755)
    script = wargame_host.cleared(["board", "corp"], (), True)[-1]
    started = time.monotonic()
    done = subprocess.run(["sh", "-c", script], env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"},
                          capture_output=True, text=True)
    return done, time.monotonic() - started

def test_the_wargames_and_the_sensor_come_down_at_once_and_one_failure_fails_the_clear(tmp_path):
    done, took = _clear(tmp_path, "none")
    assert done.returncode == 0, done.stderr
    assert len((tmp_path / "downs").read_text().splitlines()) == 3
    assert took < 2.5, "three one-second downs run side by side"

    failed, _ = _clear(tmp_path, "corp")
    assert failed.returncode != 0
    assert len((tmp_path / "downs").read_text().splitlines()) == 6, "the others finish before it reports"

FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE/calls"
case "$1" in
  compose)
    case "$*" in
      *"config --services"*) cat "$FAKE/services" ;;
      *" down -v "*) for volume in "$FAKE"/volumes/*; do rm -rf "$volume"; done ;;
    esac ;;
  inspect)
    case "$3" in
      *State.Status*) cat "$FAKE/$4.status" ;;
      *) cat "$FAKE/$4.mounts" ;;
    esac ;;
esac
"""

def _host(tmp_path, containers):
    fake = tmp_path / "docker-state"
    (fake / "volumes").mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    docker = tmp_path / "bin" / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    (fake / "services").write_text("".join(f"{name}\n" for name in containers))
    for name, (status, path, files) in containers.items():
        volume = fake / "volumes" / name
        volume.mkdir()
        for file, content in files.items():
            (volume / file).write_text(content)
        (fake / f"{name}.status").write_text(f"{status}\n")
        (fake / f"{name}.mounts").write_text(f"{path} {volume}\n\n")
    return fake

def _pristine(tmp_path, fake, verb):
    env = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "FAKE": str(fake),
           "CR_PRISTINE": str(tmp_path / "pristine")}
    return subprocess.run(["sh", str(ROOT / "deploy/wargame-host/pristine.sh"), verb, "board"],
                          env=env, capture_output=True, text=True)

def test_keeping_copies_each_stopped_containers_volumes_before_removing_them(tmp_path):
    fake = _host(tmp_path, {
        "board-db": ("exited", "/var/lib/mysql", {"ibdata1": "initialised", "binlog.000001": "rows"}),
        "board": ("exited", "/srv/static", {}),
    })

    done = _pristine(tmp_path, fake, "keep")

    assert done.returncode == 0, done.stderr
    kept = tmp_path / "pristine" / "board"
    assert (kept / "board-db/var/lib/mysql/ibdata1").read_text() == "initialised"
    assert (kept / "board-db/var/lib/mysql/binlog.000001").read_text() == "rows"
    assert (kept / "board/srv/static").is_dir()
    calls = (fake / "calls").read_text().splitlines()
    order = [next(i for i, call in enumerate(calls) if step in call)
             for step in ("up -d --wait --pull never", "stop --timeout", "down -v")]
    assert order == sorted(order), "MySQL is shut down cleanly before its datadir is copied"

def test_restoring_fills_only_the_new_empty_volumes_of_containers_that_never_ran(tmp_path):
    fake = _host(tmp_path, {
        "board-db": ("created", "/var/lib/mysql", {}),
        "board": ("running", "/srv/static", {"live": "session data"}),
        "cache": ("created", "/data", {"kept-by-compose": "old"}),
    })
    for container, path in (("board-db", "var/lib/mysql"), ("board", "srv/static"), ("cache", "data")):
        kept = tmp_path / "pristine" / "board" / container / path
        kept.mkdir(parents=True)
        (kept / "pristine").write_text(container)

    done = _pristine(tmp_path, fake, "restore")

    assert done.returncode == 0, done.stderr
    volumes = fake / "volumes"
    assert (volumes / "board-db" / "pristine").read_text() == "board-db"
    assert sorted(p.name for p in (volumes / "board").iterdir()) == ["live"], (
        "a running container's datadir is live; writing under it would corrupt it")
    assert sorted(p.name for p in (volumes / "cache").iterdir()) == ["kept-by-compose"], (
        "compose hands a recreated container its old anonymous volume, which holds data already")
    assert not any(" up " in call or " down" in call for call in (fake / "calls").read_text().splitlines())

class WargameShell:
    def __init__(self, exit_code=0):
        self.exit_code = exit_code
        self.calls = []

    def __call__(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            self.calls.append((role, argv, timeout))
            return Ran(self.exit_code, "container board-db is unhealthy" if self.exit_code else "")
        return run

def test_a_wargame_that_does_not_come_up_healthy_is_drift():
    built = _adapter()
    built.runner = WargameShell(exit_code=1)

    with pytest.raises(Drifted, match="unhealthy"):
        built.start_wargames()

def test_the_wargames_start_side_by_side_and_not_one_after_the_other():
    both_running = threading.Barrier(len(ENTRY.wargames), timeout=10)

    def runner(role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            both_running.wait()
            return Ran(0, "")
        return run

    built = _adapter()
    built.runner = runner

    assert built.start_wargames() == (HOST, tuple(f"runs {wargame}" for wargame in ENTRY.wargames)), (
        "each wargame's up waits only for its own containers; a serial start puts one wargame's whole "
        "start on the reset's critical path")

@pytest.mark.parametrize("failing", [("corp",), ("board",), ("board", "corp")])
def test_each_wargame_that_does_not_come_up_healthy_is_named_in_the_drift(failing):
    def runner(role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            wargame = argv[-1].split(" -p ")[1].split()[0]
            return Ran(1, f"container {wargame}-db is unhealthy") if wargame in failing else Ran(0, "")
        return run

    built = _adapter()
    built.runner = runner

    with pytest.raises(Drifted) as raised:
        built.start_wargames()
    for wargame in ENTRY.wargames:
        named = f"did not start {wargame} (exit 1): container {wargame}-db is unhealthy" in str(raised.value)
        assert named == (wargame in failing), str(raised.value)

@pytest.mark.parametrize("wargame", ENTRY.wargames)
def test_every_wargame_healthcheck_probes_each_second_while_it_starts(wargame):
    for service, entry in _shipped(wargame)["services"].items():
        check = entry["healthcheck"]
        assert check["start_interval"] == "1s", (
            f"{service}: --wait sees a container healthy only at its next probe; Docker Engine 25 and "
            f"later probe every start_interval during start_period")
        assert check["interval"] == "10s" and check["start_period"] == "120s", service

def test_the_vm_waf_reaches_corp_without_a_resolver():
    conf = (ROOT / "deploy/waf/board.com.conf").read_text()
    corp = conf[conf.index("server_name corp.com;"):]

    assert "proxy_pass http://corp-wp:80;" in corp, (
        "a proxy_pass through a variable resolves at request time and needs a "
        "resolver directive, which the VM has none of; a literal name is "
        "resolved at start from /etc/hosts, where the slot writes it"
    )
    assert "resolver" not in conf
    assert "127.0.0.1 board corp-wp" in (ROOT / "deploy/waf/setup.sh").read_text(), (
        "nginx -t at build time resolves every literal upstream"
    )

@pytest.mark.reads_target_state
def test_the_effect_reader_reads_corp_db_inside_its_container(monkeypatch):
    from api import effect

    sent = []

    def execute(host, command, given, timeout):
        sent.append(command)
        return subprocess.CompletedProcess(command, 0, "", f"{ports.EXIT_MARK}0\n")

    monkeypatch.setattr(openstack, "execute", execute)
    effect.read_changes(_adapter().runner("corp-db"), datetime(2026, 10, 11, tzinfo=timezone.utc))

    [command] = sent
    assert command[-2] == "ubuntu@10.31.0.20", "the runner reaches the host on its mgmt address"
    remote = shlex.split(command[-1])
    assert remote[:4] == ["sudo", "docker", "exec", "corp-db"]
    assert effect.BINLOG_CMD in remote, "the binary log is corp-db's own, under its /var/lib/mysql"

def test_clearing_the_host_removes_each_wargame_with_its_volumes_and_the_sensor_log():
    argv = wargame_host.cleared(["board", "corp"], ("/var/log/suricata/eve.json",), True)
    script = argv[-1].splitlines()

    assert argv[:3] == ["sudo", "sh", "-c"] and script[0] == "set -e"
    for wargame in ("board", "corp"):
        assert any(f"-p {wargame} -f /opt/cr/wargames/{wargame}.yaml down -v" in line
                   for line in script), "anonymous volumes keep a session's database"
    assert any("-p sensor" in line and "down -v" in line and "CR_SENSOR_INTERFACE=lo" in line
               for line in script)
    assert any(line.startswith("rm -f /var/log/suricata/eve.json") for line in script)
    assert not any("rules" in line for line in script), (
        "the baseline rules reach the sensor through rules/suricata.py once it is up"
    )
    assert not any(" up " in line for line in script), "configure starts them afterwards"

def test_no_wargame_container_holds_a_host_path_or_privilege_a_reset_in_place_would_keep():
    for wargame in ENTRY.wargames:
        services = yaml.safe_load(wargame_host.render(
            yaml.safe_load((ROOT / wargame_host.COMPOSE.format(wargame=wargame)).read_text()),
            "c0ffee", {}))["services"]
        for name, service in services.items():
            assert not service.get("privileged"), name
            assert not service.get("volumes"), (
                f"{name} mounts a host path, so the host is not reset by removing containers"
            )
            assert service.get("network_mode") != "host", name
