import io
import json
import pathlib
import shlex
import subprocess
import tarfile
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
import yaml

from range import declared, images, openstack, ports, wargame_host
from range.declared import Declaration, Host
from range.ports import Drifted, Node, Ran, RangeUnavailable, Segment, Shape

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

def _sent(monkeypatch, role, stdin=None):
    sent = []

    def execute(host, command, given, timeout):
        sent.append(command)
        return subprocess.CompletedProcess(command, 0, "", f"{ports.EXIT_MARK}0\n")

    monkeypatch.setattr(openstack, "execute", execute)
    _adapter().runner(role)(["mysql", "-e", "SELECT 1"], stdin=stdin)
    [command] = sent
    return command

def test_on_openstack_the_wargames_run_on_one_host_built_from_the_stock_image():
    assert OS.roles[wargame_host.ROLE] == HOST
    assert OS.roles["board"] == OS.roles["board-db"] == HOST
    assert ENTRY.setup == "deploy/wargame-host/setup.sh"
    assert "board" in ENTRY.wargames
    assert ENTRY.segments == ("estate", "mgmt")
    assert not (ROOT / "wargames/board/image").exists(), (
        "a wargame is its GHCR containers on the wargame host, never a VM image of its own"
    )

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

def test_only_the_services_the_waf_proxies_to_are_published_on_the_host():
    services = _shipped("board")["services"]

    assert services["board"]["ports"] == ["8000:8000"]
    assert "ports" not in services["board-db"], "the database answers only inside its project"

def test_the_board_is_published_where_the_ground_truth_reader_and_the_waf_expect_it():
    from django.conf import settings

    assert ENTRY.publish["board"] == urlsplit(settings.BOARD_API_URL).port
    assert "proxy_pass http://board:8000;" in (ROOT / "deploy/waf/range.conf").read_text()
    assert "board" in ENTRY.names, "the WAF resolves board to the host through /etc/hosts"

def test_the_containers_networks_take_the_tenant_mtu():
    files = wargame_host.generated(ROOT, HOST, ENTRY.wargames, ENTRY.publish, "c0ffee", 1450)

    daemon = json.loads(files[wargame_host.DAEMON])

    assert daemon["mtu"] == 1450
    assert daemon["default-network-opts"]["bridge"]["com.docker.network.driver.mtu"] == "1450"

@pytest.mark.parametrize("tag, mtu, setting", [("", 1450, "FSL_IMAGE_TAG"), ("c0ffee", 0, "FSL_OPENSTACK_MTU")])
def test_the_host_image_is_refused_without_the_tag_or_the_mtu(tag, mtu, setting):
    with pytest.raises(RangeUnavailable, match=setting):
        wargame_host.generated(ROOT, HOST, ENTRY.wargames, ENTRY.publish, tag, mtu)

def test_publishing_a_service_no_wargame_runs_is_refused():
    with pytest.raises(RangeUnavailable, match="nowhere"):
        wargame_host.generated(ROOT, HOST, ("board",), {"nowhere": 80}, "c0ffee", 1450)

def test_a_wargame_without_a_compose_file_is_refused():
    with pytest.raises(RangeUnavailable, match="ghost"):
        wargame_host.generated(ROOT, HOST, ("ghost",), {}, "c0ffee", 1450)

def test_a_new_platform_tag_is_a_new_host_image():
    def bundle(tag):
        return _adapter(tag=tag)._bundle(HOST, ENTRY)

    assert bundle("c0ffee").digest != bundle("decaf").digest, (
        "the images are pulled into the host image at build time; a platform on "
        "a new tag needs a host image holding that tag's images"
    )
    assert bundle("c0ffee").digest == bundle("c0ffee").digest

def test_the_host_bundle_carries_the_setup_and_the_shipped_files():
    built = _adapter()._bundle(HOST, ENTRY)

    with tarfile.open(fileobj=io.BytesIO(built.archive)) as archive:
        members = set(archive.getnames())
    assert members == {
        "deploy/wargame-host/setup.sh",
        wargame_host.DAEMON,
        *(wargame_host.SHIPPED.format(wargame=w) for w in ENTRY.wargames),
    }
    images.user_data(built)

def test_the_setup_installs_docker_and_pulls_every_shipped_file_while_the_builder_has_internet():
    script = (ROOT / ENTRY.setup).read_text()

    assert "docker.io" in script and "docker-compose-v2" in script
    assert "universe" in script, "docker-compose-v2 is in universe; the script says so itself"
    assert "/etc/docker/daemon.json" in script
    pulled = script.index("pull")
    assert script.index("wargames/*.yaml") < pulled
    assert "/opt/fsl/wargames" in script and wargame_host.INSTALLED.startswith("/opt/fsl/wargames/")

def test_a_wargame_starts_from_its_installed_file_with_no_pull():
    argv = wargame_host.up("board")

    assert argv[:5] == ["sudo", "docker", "compose", "-p", "board"]
    assert argv[5:7] == ["-f", "/opt/fsl/wargames/board.yaml"]
    assert argv[7:] == ["up", "-d", "--wait", "--pull", "never"], (
        "the range has no route to ghcr.io; the images are already on the host"
    )

def test_a_wargame_role_runs_inside_its_container_on_the_host(monkeypatch):
    command = _sent(monkeypatch, "board-db")

    assert command[-2] == "ubuntu@10.31.0.20"
    remote = shlex.split(command[-1])
    assert remote[:4] == ["sudo", "docker", "exec", "board-db"]
    assert remote[4:6] == ["sh", "-c"] and remote[-3:] == ["mysql", "-e", "SELECT 1"]

def test_input_reaches_the_container_only_when_the_caller_sends_some(monkeypatch):
    remote = shlex.split(_sent(monkeypatch, "board", stdin="body")[-1])

    assert remote[:5] == ["sudo", "docker", "exec", "-i", "board"]

def test_the_wargames_role_runs_on_the_host_itself(monkeypatch):
    remote = shlex.split(_sent(monkeypatch, wargame_host.ROLE)[-1])

    assert remote[0] == "sh" and "docker" not in remote[:3]

def test_a_role_on_a_host_without_wargames_is_not_wrapped(monkeypatch):
    plain = Declaration(roles={"gateway": "fsl-waf"}, compose={"gateway": "waf"},
                        hosts={"fsl-waf": Host(setup="s.sh")})
    built = openstack.OpenStack(plain, SPEC, get=None)

    assert built._container("gateway", "fsl-waf") == ""

class WargameShell:
    def __init__(self, exit_code=0):
        self.exit_code = exit_code
        self.calls = []

    def __call__(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            self.calls.append((role, argv, timeout))
            return Ran(self.exit_code, "container board-db is unhealthy" if self.exit_code else "")
        return run

def test_starting_the_wargames_brings_each_up_on_the_host():
    built, host = _adapter(), WargameShell()
    built.runner = host

    done = built.start_wargames()

    assert host.calls == [(wargame_host.ROLE, wargame_host.up(w), wargame_host.UP_TIMEOUT)
                          for w in ENTRY.wargames]
    assert done == (HOST, tuple(f"runs {w}" for w in ENTRY.wargames))

def test_a_wargame_that_does_not_come_up_healthy_is_drift():
    built = _adapter()
    built.runner = WargameShell(exit_code=1)

    with pytest.raises(Drifted, match="unhealthy"):
        built.start_wargames()

def test_publish_without_a_wargame_is_refused_in_the_declaration():
    with pytest.raises(ValueError, match="publishes"):
        Declaration(roles={"x": "fsl-x"}, hosts={"fsl-x": Host(setup="s.sh", publish={"board": 8000})}).check()

def test_the_wargame_host_boots_on_the_flavor_cloud_yaml_names_for_wargames():
    from range import cloud

    flavors = cloud.read(cloud.EXAMPLE).role_flavors
    listed = {"flavors": [{"id": "f-small", "name": "m1.small"}, {"id": "f-medium", "name": "m1.medium"}]}
    built = openstack.OpenStack(OS, SPEC, get=lambda call, body=None: listed, build=openstack.Build(
        flavor="m1.small", role_flavors=flavors))

    assert built._host_flavor(HOST) == "f-medium"
    assert built._host_flavor("fsl-waf") == "f-small"

def test_corp_and_its_database_stand_on_the_same_host_as_the_board():
    assert OS.roles["corp"] == OS.roles["corp-db"] == HOST
    assert "corp" in ENTRY.wargames
    assert OS.compose["corp"] in ENTRY.names, "the WAF resolves corp-wp to the host through /etc/hosts"
    assert {"board.com", "corp.com"} <= set(OS.hosts["fsl-waf"].names)

def test_corp_is_published_where_the_waf_proxies_corp_com():
    services = _shipped("corp")["services"]

    assert services["corp-wp"]["ports"] == [f"{ENTRY.publish['corp-wp']}:80"]
    assert services["corp-wp"]["image"] == "ghcr.io/nekonic/fsl-corp:c0ffee"
    assert services["corp-db"]["image"] == "ghcr.io/nekonic/fsl-corp-db:c0ffee"
    assert "ports" not in services["corp-db"]

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
        sent.append(shlex.split(command[-1]))
        return subprocess.CompletedProcess(command, 0, "", f"{ports.EXIT_MARK}0\n")

    monkeypatch.setattr(openstack, "execute", execute)
    effect.read_changes(_adapter().runner("corp-db"), datetime(2026, 10, 11, tzinfo=timezone.utc))

    [remote] = sent
    assert remote[:4] == ["sudo", "docker", "exec", "corp-db"]
    assert effect.BINLOG_CMD in remote, "the binary log is corp-db's own, under its /var/lib/mysql"
