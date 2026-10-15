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
    assert "busybox-static" in dockerfile, (
        "gns3-server copies a static busybox into every docker node it starts and refuses to start one without it"
    )

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

def test_every_learner_template_and_its_korean_pair_is_a_file_of_its_own_the_platform_reads():
    copied = sorted(path.name for path in TOPOLOGY.glob("*.gns3"))

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
        return projects if path == "/projects" else [] if path.endswith("/nodes") else None

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
    assert "/topology" not in entrypoint and "topology" not in " ".join(service()["volumes"]), (
        "the server never sees the repo's maps, so the full wiring is never opened where learners read"
    )

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

def test_the_read_only_page_leaves_the_learner_only_the_rendered_map_to_pan_and_zoom():
    page = (GNS3 / "auditor.html").read_text()
    hidden = page[page.index("const VIEW_ONLY"):page.index("const BLOCKED")]
    blocked = page[page.index("const BLOCKED"):page.index("const sleep")]

    for chrome in ["#project-titlebar", "#project-toolbar", "app-project-map-menu", "app-context-menu",
                   "app-context-console-menu", "app-topology-summary", ".cdk-overlay-container",
                   "mat-dialog-container"]:
        assert chrome in hidden, f"{chrome} is editing chrome a learner never sees"
    assert "display: none !important" in hidden
    assert "svg.map * { pointer-events: none !important; }" in hidden, (
        "a press on a node, a link or a label lands on the map itself, so it pans instead of dragging"
    )
    for event in ["contextmenu", "dblclick", "click", "keydown", "keyup", "drop", "touchstart"]:
        assert f'"{event}"' in blocked
    assert "if (!event.isTrusted) return;" in page, "the page's own clicks on the hidden controls still reach them"
    assert "event.stopImmediatePropagation()" in page and "{capture: true, passive: false}" in page
    assert 'event.button === 0 && event.target instanceof map.Element && event.target.matches("svg.map")' in page
    assert page.index("viewOnly(map);") < page.index("await drawn(map)"), "the chrome is hidden before the map draws"
    assert page.count('button(map, "zoom_out_map").click()') == 1, (
        "the moving mode stays on, so a drag on the empty map pans and the wheel zooms"
    )
    assert 'button(map, "adjust").click()' in page and 'event.data === "fsl-fit"' in page
    assert "GNS3" not in page

def test_the_platform_reads_the_gns3_admin_password_it_needs_to_load_a_range_s_own_map():
    platform = composed.services()["platform"]
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert "/var/lib/fsl-gns3:/run/fsl-gns3:ro" in platform["volumes"]
    assert platform["environment"]["FSL_GNS3_ADMIN_PASSWORD"] == "${FSL_GNS3_ADMIN_PASSWORD:-}"
    assert 'chgrp "$gid" "$DATA/admin-password"' in entrypoint and 'chmod 640 "$DATA/admin-password"' in entrypoint, (
        "only the docker socket's group, which the platform's user joins and which is root on the host, reads it"
    )
