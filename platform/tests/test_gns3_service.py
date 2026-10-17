import importlib.util
import json
import pathlib
import sys
import types

import pytest

import topology
from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
GNS3 = ROOT / "deploy" / "gns3"
TOPOLOGY = ROOT / "deploy" / "topology"

def service():
    return composed.services()["gns3"]

def test_the_gns3_server_gets_net_admin_a_tun_device_the_docker_socket_and_the_host_s_pids_and_nothing_more():
    gns3 = service()

    assert not gns3.get("privileged")
    assert gns3["cap_add"] == ["NET_ADMIN"], "uBridge makes a kernel bridge and TAPs per switch"
    assert gns3["devices"] == ["/dev/net/tun:/dev/net/tun"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in gns3["volumes"], (
        "a display node runs on the host's daemon"
    )
    assert gns3["pid"] == "host", (
        "uBridge moves a started docker node's interface into the namespace of the container's host pid"
    )
    assert not gns3.get("network_mode")

def test_the_gns3_image_has_the_docker_client_gns3_runs_to_close_a_display_node_and_fetches_no_skills():
    installed = (GNS3 / "Dockerfile").read_text()

    assert "docker-cli" in installed, (
        "GNS3 closes a docker node by running `docker exec`; without the client every close failed, "
        "and each deleted map left its containers running"
    )
    assert '"enabled": False' in installed, (
        "3.1's copilot clones its skills repository at every start; without git it logged two errors, "
        "and the range uses no copilot"
    )

def test_the_gns3_server_runs_as_gns3_in_the_socket_s_group_like_the_platform():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert "stat -c %g" in entrypoint and "getent group" in entrypoint and "usermod -aG" in entrypoint
    assert "exec gosu gns3" in entrypoint
    assert entrypoint.index("usermod -aG") < entrypoint.index("exec gosu gns3") < entrypoint.index("gns3server --config")

def test_the_display_nodes_run_the_one_image_provisioning_starts_and_no_image_tag_is_rewritten():
    gns3 = service()
    entrypoint = (GNS3 / "entrypoint.sh").read_text()
    provision = (GNS3 / "provision.py").read_text()

    assert "FSL_IMAGE_TAG" not in gns3["environment"] and "sed " not in entrypoint
    assert f'DISPLAY_IMAGE = "{topology.DISPLAY_IMAGE}"' in provision
    for path in TOPOLOGY.glob("*.gns3"):
        images = {node["properties"].get("image") for node in json.loads(path.read_text())["topology"]["nodes"]
                  if node["node_type"] == "docker"}
        assert images == {topology.DISPLAY_IMAGE}, path.name

def test_the_gns3_server_is_published_like_the_platform_and_holds_only_the_maps_the_platform_loads():
    gns3 = service()

    assert gns3["ports"] == ["${FSL_PUBLISH:-127.0.0.1}:3080:3080"]
    assert not [volume for volume in gns3["volumes"] if "topology" in volume], (
        "a template draws every wargame; only a session's own map is loaded, by the platform"
    )
    assert gns3["networks"] == ["mgmt"]
    assert composed.services()["platform"]["environment"]["FSL_GNS3_URL"] == "http://gns3:3080"

def test_no_project_is_copied_in_before_the_server_starts_and_the_admin_password_is_set_first():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert ".gns3" not in entrypoint and "/topology" not in entrypoint
    assert "default_admin_password = $FSL_GNS3_ADMIN_PASSWORD" in entrypoint, (
        "the admin password only takes effect when the controller database is first made"
    )
    assert entrypoint.index("default_admin_password") < entrypoint.index("gns3server --config")

def test_learners_sign_in_as_a_read_only_auditor_through_the_bundled_web_ui_s_own_storage():
    provision = (GNS3 / "provision.py").read_text()
    page = (GNS3 / "auditor.html").read_text()

    assert 'AUDITOR_ROLE = "Auditor"' in provision
    assert '"path": "/"' in provision
    assert 'localStorage.setItem("controllerIds", "controller-1")' in page
    assert 'location: "bundled"' in page and "authToken: token" in page

@pytest.fixture
def provision(monkeypatch, tmp_path):
    stub = types.ModuleType("gns3server")
    stub.__file__ = str(tmp_path / "gns3server" / "__init__.py")
    monkeypatch.setitem(sys.modules, "gns3server", stub)
    spec = importlib.util.spec_from_file_location("fsl_gns3_provision", GNS3 / "provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_provisioning_starts_every_stopped_display_node_of_an_open_project_and_nothing_else(provision, monkeypatch):
    calls = []
    projects = [{"project_id": "a", "name": "range-openstack slot 1 board", "status": "opened"}]
    listed = [{"node_id": "n1", "name": "waf", "status": "stopped", "properties": {"image": provision.DISPLAY_IMAGE}},
              {"node_id": "n2", "name": "attacker", "status": "started", "properties": {"image": provision.DISPLAY_IMAGE}},
              {"node_id": "n3", "name": "service-sw", "status": "started", "properties": {}},
              {"node_id": "n4", "name": "fsl-kali", "status": "stopped", "properties": {"image": "kalilinux/kali"}}]

    def call(method, path, body=None, token=""):
        calls.append((method, path))
        return projects if path == "/projects" else listed if path.endswith("/nodes") else None

    monkeypatch.setattr(provision, "call", call)
    provision.opened("token-of-admin")

    assert [c for c in calls if c[0] == "POST"] == [("POST", "/projects/a/nodes/n1/start")], (
        "a node of any other image, as an old map's real images, is never run by the map server"
    )

def test_the_platform_reads_the_gns3_admin_password_it_needs_to_load_a_range_s_own_map():
    platform = composed.services()["platform"]
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert "/var/lib/fsl-gns3:/run/fsl-gns3:ro" in platform["volumes"]
    assert platform["environment"]["FSL_GNS3_ADMIN_PASSWORD"] == "${FSL_GNS3_ADMIN_PASSWORD:-}"
    assert 'chgrp "$gid" "$DATA/admin-password"' in entrypoint and 'chmod 640 "$DATA/admin-password"' in entrypoint, (
        "only the docker socket's group, which the platform's user joins and which is root on the host, reads it"
    )
