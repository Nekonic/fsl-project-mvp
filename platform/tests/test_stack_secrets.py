import pathlib
import re

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "platform/cr/settings.py"


def test_elasticsearch_and_kibana_listen_on_the_platform_vm_s_loopback_alone():
    services = composed.services()

    assert services["elasticsearch"]["ports"] == ["127.0.0.1:9200:9200"]
    assert services["kibana"]["ports"] == ["127.0.0.1:5601:5601"]


def test_no_project_secret_is_written_into_the_stack():
    named = [
        (service, variable)
        for service, settings in composed.services().items()
        for variable in (settings.get("environment") or {})
        if re.search(r"OPENSTACK_PASSWORD", variable)
    ]

    assert not named, (
        "compose keeps environment values in the container's configuration, where docker inspect shows them"
    )


def test_the_project_password_is_a_read_only_secret_file_not_an_environment_value():
    platform = composed.services()["platform"]
    secrets = composed.document()["secrets"]

    assert platform["secrets"] == ["openstack_password"]
    assert secrets["openstack_password"] == {"file": "./openstack-password"}
    assert "CR_OPENSTACK_PASSWORD\"" not in SETTINGS.read_text()
    assert '"/run/secrets/openstack_password"' in SETTINGS.read_text()


def test_no_service_holds_the_docker_socket_beside_the_ones_named_here():
    holding = sorted(
        name for name, service in composed.services().items()
        if any("docker.sock" in str(mount) for mount in service.get("volumes") or [])
    )

    assert set(holding) <= {"platform", "gns3"}
