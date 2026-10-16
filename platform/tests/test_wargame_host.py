import json
import pathlib
import shlex
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
import yaml

from range import declared, openstack, ports, wargame_host
from range.ports import Drifted, Node, Ran, Segment, Shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
OS = declared.read(flavor="openstack")
HOST = "fsl-wargame-host"
ENTRY = OS.hosts[HOST]
SPEC = openstack.Cloud(
    keystone="http://keystone:5000", neutron="http://neutron:9696",
    nova="http://nova:8774/v2.1", glance="http://glance:9292", project="fsl",
    user="fsl", ssh_user="ubuntu", ssh_key="/keys/fsl",
)

def _adapter(tag="c0ffee", mtu=1450):
    built = openstack.OpenStack(OS, SPEC, get=None, build=openstack.Build(
        source=str(ROOT), image_tag=tag, mtu=mtu))
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

def test_the_host_runs_the_same_ghcr_images_as_docker_at_the_platforms_tag():
    compose = yaml.safe_load((ROOT / "wargames/board/compose.yaml").read_text())

    shipped = _shipped("board")

    assert shipped["services"]["board"]["image"] == "ghcr.io/nekonic/fsl-board:c0ffee"
    assert shipped["services"]["board-db"]["image"] == compose["services"]["board-db"]["image"]
    assert set(shipped["services"]) == set(compose["services"])

def test_the_shipped_compose_file_builds_nothing_and_names_each_container_by_its_service():
    for service, entry in _shipped("board")["services"].items():
        assert "build" not in entry, "the range has no Internet and no source tree to build from"
        assert "networks" not in entry, "estate is session.yaml's network; on the host the project's own default serves"
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
    assert "proxy_pass http://board:8000;" in (ROOT / "deploy/waf/range.conf").read_text()
    assert {"board", OS.compose["corp"]} <= set(ENTRY.names), "the WAF resolves both to the host through /etc/hosts"
    assert {"board.com", "corp.com"} <= set(OS.hosts["fsl-waf"].names)

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

def test_a_wargame_starts_from_its_installed_file_with_no_pull():
    argv = wargame_host.up("board")

    assert argv[5:7] == ["-f", "/opt/fsl/wargames/board.yaml"]
    assert argv[-2:] == ["--pull", "never"], "the range has no route to ghcr.io; the images are already on the host"

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

def test_the_vm_waf_reaches_corp_without_a_resolver():
    conf = (ROOT / "deploy/waf/range.conf").read_text()
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
        assert any(f"-p {wargame} -f /opt/fsl/wargames/{wargame}.yaml down -v" in line
                   for line in script), "anonymous volumes keep a session's database"
    assert any("-p sensor" in line and "down -v" in line and "FSL_SENSOR_INTERFACE=lo" in line
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
