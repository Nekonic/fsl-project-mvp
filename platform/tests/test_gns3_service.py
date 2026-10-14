import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import types

import pytest

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
GNS3 = ROOT / "deploy" / "gns3"
TOPOLOGY = ROOT / "deploy" / "topology"

def service():
    return composed.services()["gns3"]

def test_the_gns3_server_is_the_pinned_release_with_its_mcp_extra():
    dockerfile = (GNS3 / "Dockerfile").read_text()

    assert '"gns3-server[ai-features]==3.1.0a6"' in dockerfile

def test_the_image_carries_what_gns3_3_1_needs_to_open_a_project():
    dockerfile = (GNS3 / "Dockerfile").read_text()

    assert "qemu-system-x86" in dockerfile, "a qemu node is created only where qemu-system-x86_64 runs"
    assert "ARG UBRIDGE=1.2.3" in dockerfile and "GNS3/ubridge/archive/refs/tags/v${UBRIDGE}" in dockerfile, (
        "an ethernet_switch needs uBridge >= 1.2.3 with its brctl module; Debian has no package"
    )
    assert "setcap cap_net_admin,cap_net_raw+ep /usr/local/bin/ubridge" in dockerfile

def test_the_gns3_server_gets_net_admin_a_tun_device_and_the_docker_socket_and_nothing_more():
    gns3 = service()

    assert not gns3.get("privileged")
    assert gns3["cap_add"] == ["NET_ADMIN"], "uBridge makes a kernel bridge and TAPs per switch"
    assert gns3["devices"] == ["/dev/net/tun:/dev/net/tun"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in gns3["volumes"], (
        "a docker node is created, never started, on the host's daemon"
    )
    assert not gns3.get("network_mode") and not gns3.get("pid")

def test_the_gns3_data_sits_at_the_same_path_on_the_host_because_the_host_daemon_mounts_it():
    gns3 = service()
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert "/var/lib/fsl-gns3:/var/lib/fsl-gns3" in gns3["volumes"]
    assert 'DATA="${FSL_GNS3_DATA:-/var/lib/fsl-gns3}"' in entrypoint
    assert "resources_path = $DATA/resources" in entrypoint

def test_the_gns3_server_runs_as_gns3_in_the_socket_s_group_like_the_platform():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert "stat -c %g" in entrypoint and "getent group" in entrypoint and "usermod -aG" in entrypoint
    assert "exec gosu gns3" in entrypoint
    assert entrypoint.index("usermod -aG") < entrypoint.index("exec gosu gns3") < entrypoint.index("gns3server --config")

def test_the_docker_nodes_name_the_images_this_platform_runs_so_gns3_pulls_nothing():
    gns3 = service()
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert gns3["environment"]["FSL_IMAGE_TAG"] == "${FSL_IMAGE_TAG:-dev}"
    rewrite = next(line.strip() for line in entrypoint.splitlines() if line.strip().startswith('sed "s#'))
    rewrite = rewrite.split(' "$project"')[0]
    done = subprocess.run(["sh", "-c", f'{rewrite} "$1"', "sh", str(TOPOLOGY / "range-docker.gns3")],
                          env={"TAG": "c0ffee", "PATH": os.environ["PATH"]}, capture_output=True, text=True)
    images = {node["name"]: node["properties"].get("image")
              for node in json.loads(done.stdout)["topology"]["nodes"]}

    assert images["fsl-kali"] == "ghcr.io/nekonic/fsl-kali:c0ffee"
    assert images["fsl-wg-board-db"].startswith("mysql@sha256:")
    assert images["fsl-elasticsearch"] == "docker.elastic.co/elasticsearch/elasticsearch:8.15.0"
    assert not [image for image in images.values() if image and image.endswith(":dev")]

def test_the_gns3_server_is_published_like_the_platform_and_reads_the_projects_from_the_repo():
    gns3 = service()

    assert gns3["ports"] == ["${FSL_PUBLISH:-127.0.0.1}:3080:3080"]
    assert "./deploy/topology:/topology:ro" in gns3["volumes"]
    assert gns3["networks"] == ["mgmt"]
    assert composed.services()["platform"]["environment"]["FSL_GNS3_URL"] == "http://gns3:3080"

def test_each_project_is_copied_into_its_own_directory_before_the_server_starts():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert '"$project" > "$DATA/projects/$name/$name.gns3"' in entrypoint, (
        "gns3-server refuses a .gns3 file that sits directly in the projects directory"
    )
    assert entrypoint.index('"$project" >') < entrypoint.index("gns3server --config")
    assert "default_admin_password = $FSL_GNS3_ADMIN_PASSWORD" in entrypoint, (
        "the admin password only takes effect when the controller database is first made"
    )

def test_every_map_and_its_korean_pair_is_copied_into_a_directory_of_its_own():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()
    copied = sorted(path.name for path in TOPOLOGY.glob("*.gns3"))

    assert "for project in /topology/*.gns3; do" in entrypoint
    assert 'name="$(basename "$project" .gns3)"' in entrypoint
    assert copied == ["range-docker.gns3", "range-docker.ko.gns3",
                      "range-openstack.gns3", "range-openstack.ko.gns3"]
    assert len({name.removesuffix(".gns3") for name in copied}) == len(copied)

def test_learners_sign_in_as_a_read_only_auditor_through_the_bundled_web_ui_s_own_storage():
    provision = (GNS3 / "provision.py").read_text()
    page = (GNS3 / "auditor.html").read_text()

    assert 'AUDITOR_ROLE = "Auditor"' in provision
    assert '"path": "/"' in provision
    assert 'localStorage.setItem("controllerIds", "controller-1")' in page
    assert 'location: "bundled"' in page and "authToken: token" in page
    assert 'localStorage.setItem("showInterfaceLabels", "true")' in page, (
        "each link end of a range's own map names the interface and its address"
    )
    assert 'localStorage.setItem("integrateLinkLabelsToLinks", "false")' in page, (
        "GNS3 3.1 draws the labels at their stored positions only when they are not folded into the links"
    )

@pytest.fixture
def provision(monkeypatch, tmp_path):
    stub = types.ModuleType("gns3server")
    stub.__file__ = str(tmp_path / "gns3server" / "__init__.py")
    monkeypatch.setitem(sys.modules, "gns3server", stub)
    spec = importlib.util.spec_from_file_location("fsl_gns3_provision", GNS3 / "provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_provisioning_opens_every_closed_project_as_admin_and_leaves_an_open_one(provision, monkeypatch):
    calls = []
    projects = [{"project_id": "a", "name": "range-docker", "status": "closed"},
                {"project_id": "b", "name": "range-openstack", "status": "opened"}]

    def call(method, path, body=None, token=""):
        calls.append((method, path, token))
        return projects if path == "/projects" else None

    monkeypatch.setattr(provision, "call", call)
    monkeypatch.setattr(provision, "ready", lambda: None)
    monkeypatch.setattr(provision, "signed_in", lambda username, password: f"token-of-{username}")
    monkeypatch.setattr(provision, "admin_password", lambda: "secret")
    monkeypatch.setattr(provision, "the_auditor", lambda token: calls.append(("auditor", token)))
    monkeypatch.setattr(provision, "symbols", lambda token: calls.append(("symbols", token)))

    provision.provision()

    assert ("POST", "/projects/a/open", "token-of-admin") in calls
    assert not [c for c in calls if c[1] == "/projects/b/open"]
    assert calls.index(("auditor", "token-of-admin")) < calls.index(("POST", "/projects/a/open", "token-of-admin"))

def test_provisioning_uploads_every_fetched_symbol_as_admin_before_it_opens_a_project(provision, monkeypatch, tmp_path):
    (tmp_path / "ubuntu.svg").write_bytes(b"<svg/>")
    (tmp_path / "ubuntu.txt").write_text("licence")
    calls = []
    monkeypatch.setattr(provision, "SYMBOLS", tmp_path)
    monkeypatch.setattr(provision, "call", lambda method, path, body=None, token="", raw=None: calls.append(
        (method, path, token, raw)))

    provision.symbols("token-of-admin")

    assert calls == [("POST", "/symbols/ubuntu.svg/raw", "token-of-admin", b"<svg/>")], (
        "the licence text stays in the image beside the symbol; only the SVG is a symbol"
    )
    assert "COPY --from=ubridge /symbols /opt/fsl-gns3/symbols" in (GNS3 / "Dockerfile").read_text()

def test_the_system_maps_stay_off_the_learners_gns3_server():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()
    system = sorted(path.name for path in (TOPOLOGY / "system").glob("*.gns3"))

    assert system == ["range-docker.gns3", "range-openstack.gns3"]
    assert "for project in /topology/*.gns3; do" in entrypoint, (
        "the glob does not descend into system/, so the full wiring is never opened where learners read"
    )
    assert "/topology/system" not in entrypoint

def test_the_read_only_page_closes_the_node_list_and_fits_the_map_through_the_web_ui_s_own_controls():
    page = (GNS3 / "auditor.html").read_text()

    assert 'button(map, "account_tree").click()' in page, "the topology summary opens over the map on every load"
    assert 'button(map, "zoom_out").click()' in page and "ZOOM_STEP = 0.1" in page, (
        "the zoom-out button steps the scale by 0.1; the project's own zoom field is not read by the web UI"
    )
    assert 'button(map, "zoom_out_map").click()' in page and "movementX: dx" in page, (
        "the web UI pans in its moving mode by each mousemove's movementX/movementY"
    )
    assert 'frame.src = opened' in page and 'location.replace(opened)' in page, (
        "a project opens inside a same-origin frame the page can steer; the project list opens as before"
    )

def test_the_platform_reads_the_gns3_admin_password_it_needs_to_load_a_range_s_own_map():
    platform = composed.services()["platform"]
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert "/var/lib/fsl-gns3:/run/fsl-gns3:ro" in platform["volumes"]
    assert platform["environment"]["FSL_GNS3_ADMIN_PASSWORD"] == "${FSL_GNS3_ADMIN_PASSWORD:-}"
    assert 'chgrp "$gid" "$DATA/admin-password"' in entrypoint and 'chmod 640 "$DATA/admin-password"' in entrypoint, (
        "only the docker socket's group, which the platform's user joins and which is root on the host, reads it"
    )
