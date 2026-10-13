import pathlib
import re

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
GNS3 = ROOT / "deploy" / "gns3"

def service():
    return composed.services()["gns3"]

def test_the_gns3_server_is_the_pinned_release_with_its_mcp_extra():
    dockerfile = (GNS3 / "Dockerfile").read_text()

    assert '"gns3-server[ai-features]==3.1.0a6"' in dockerfile
    assert not re.search(r"qemu|docker\.io|ubridge", dockerfile), (
        "the server only shows the projects; it runs no node"
    )

def test_the_gns3_server_runs_without_privilege_or_the_docker_socket():
    gns3 = service()

    assert not gns3.get("privileged") and not gns3.get("cap_add") and not gns3.get("devices")
    assert not [v for v in gns3["volumes"] if "docker.sock" in v]

def test_the_gns3_server_is_published_like_the_platform_and_reads_the_projects_from_the_repo():
    gns3 = service()

    assert gns3["ports"] == ["${FSL_PUBLISH:-127.0.0.1}:3080:3080"]
    assert "./deploy/topology:/topology:ro" in gns3["volumes"]
    assert gns3["networks"] == ["mgmt"]
    assert composed.services()["platform"]["environment"]["FSL_GNS3_URL"] == "http://gns3:3080"

def test_each_project_is_copied_into_its_own_directory_before_the_server_starts():
    entrypoint = (GNS3 / "entrypoint.sh").read_text()

    assert 'cp "$project" "$DATA/projects/$name/$name.gns3"' in entrypoint, (
        "gns3-server refuses a .gns3 file that sits directly in the projects directory"
    )
    assert entrypoint.index("cp \"$project\"") < entrypoint.index("gns3server --config")
    assert "default_admin_password = $FSL_GNS3_ADMIN_PASSWORD" in entrypoint, (
        "the admin password only takes effect when the controller database is first made"
    )

def test_learners_sign_in_as_a_read_only_auditor_through_the_bundled_web_ui_s_own_storage():
    provision = (GNS3 / "provision.py").read_text()
    page = (GNS3 / "auditor.html").read_text()

    assert 'AUDITOR_ROLE = "Auditor"' in provision
    assert '"path": "/"' in provision
    assert 'localStorage.setItem("controllerIds", "controller-1")' in page
    assert 'location: "bundled"' in page and "authToken: token" in page
