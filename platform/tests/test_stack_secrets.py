import pathlib
import re

import yaml

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "platform/entrypoint.sh"
ELASTIC_START = ROOT / "deploy/elastic/start.sh"
FILEBEAT = ROOT / "deploy/filebeat/filebeat.yml"
SETTINGS = ROOT / "platform/cr/settings.py"


def kept_mounts(service):
    return {
        mount["target"]: mount for mount in composed.services()[service].get("volumes") or []
        if isinstance(mount, dict) and mount.get("source") == "platformdata"
    }


def test_elasticsearch_runs_with_security_on_and_only_on_loopback():
    elastic = composed.services()["elasticsearch"]

    assert elastic["environment"]["xpack.security.enabled"] == "true"
    assert elastic["ports"] == ["127.0.0.1:9200:9200"]
    assert "elastic:" in elastic["healthcheck"]["test"][1] and "curl -K -" in elastic["healthcheck"]["test"][1], (
        "the health check signs in without putting the password on a command line"
    )


def test_no_elasticsearch_or_project_secret_is_written_into_the_stack():
    named = [
        (service, variable)
        for service, settings in composed.services().items()
        for variable in (settings.get("environment") or {})
        if re.search(r"ELASTIC.*(PASSWORD|TOKEN)|OPENSTACK_PASSWORD|SERVICEACCOUNTTOKEN", variable)
    ]

    assert not named, (
        "compose keeps environment values in the container's configuration, where docker inspect shows them"
    )
    assert "ELASTIC_PASSWORD_FILE" in ELASTIC_START.read_text()


def test_the_generated_credentials_sit_on_the_platform_volume_where_each_service_sees_only_its_own():
    assert kept_mounts("elasticsearch")["/run/cr-elastic"]["volume"]["subpath"] == "elastic"
    collector = kept_mounts("collector")["/run/cr-elastic"]
    kibana = kept_mounts("kibana")["/run/cr-kibana"]

    assert collector["volume"]["subpath"] == "elastic" and collector["read_only"] is True
    assert kibana["volume"]["subpath"] == "elastic/kibana" and kibana["read_only"] is True, (
        "Kibana faces learners; it holds its service token and not the elastic password"
    )


def test_the_platform_makes_the_password_once_mode_0600_before_elasticsearch_starts():
    start = ENTRYPOINT.read_text()
    elastic = composed.services()["elasticsearch"]

    assert 'install -d -o "$ELASTIC_UID" -g 0 -m 700 "$ELASTIC_KEPT"' in start
    assert "umask 077" in start and '[ ! -s "$ELASTIC_KEPT/elastic-password" ]' in start
    assert 'install -o cr -m 600 "$ELASTIC_KEPT/elastic-password" /data/elastic-password' in start, (
        "manage.py run by docker exec gets no environment the entrypoint exported, so it reads a copy cr owns"
    )
    assert elastic["depends_on"] == {"platform": {"condition": "service_healthy"}}
    assert composed.services()["platform"]["healthcheck"]["test"][-1] == "/data/elastic/elastic-password"
    assert "depends_on" not in composed.services()["platform"]


def test_kibana_reaches_elasticsearch_with_a_service_account_token():
    kibana = composed.services()["kibana"]
    start = ELASTIC_START.read_text()

    assert "ELASTICSEARCH_SERVICEACCOUNTTOKEN" in " ".join(kibana["entrypoint"])
    assert "elasticsearch-service-tokens create elastic/kibana" in start
    assert "umask 077" in start


def test_the_collector_signs_in_with_the_password_it_reads_at_start():
    output = yaml.safe_load(FILEBEAT.read_text())["output.elasticsearch"]

    assert output["username"] == "elastic" and output["password"] == "${ELASTIC_PASSWORD}"
    assert "cat /run/cr-elastic/elastic-password" in " ".join(composed.services()["collector"]["entrypoint"])


def test_the_project_password_is_a_read_only_secret_file_not_an_environment_value():
    platform = composed.services()["platform"]
    secrets = composed.document()["secrets"]

    assert platform["secrets"] == ["openstack_password"]
    assert secrets["openstack_password"] == {"file": "./openstack-password"}
    assert "CR_OPENSTACK_PASSWORD\"" not in SETTINGS.read_text()
    assert '"/run/secrets/openstack_password"' in SETTINGS.read_text()


def test_the_kibana_viewer_is_made_once_with_a_private_password_and_read_only_rights(tmp_path, monkeypatch):
    import kibana
    import register_pipeline

    kept = tmp_path / "viewer"
    monkeypatch.setattr(kibana, "VIEWER_PASSWORD_FILE", str(kept))
    made = register_pipeline.viewer_password()
    sent = dict(register_pipeline.puts("http://es:9200/", b"{}", made))

    assert made and register_pipeline.viewer_password() == made
    assert oct(kept.stat().st_mode & 0o777) == "0o600"
    assert sent["http://es:9200/_security/user/cr-viewer"] == (
        b'{"password": "' + made.encode() + b'", "roles": ["cr_viewer"]}'
    )
    role = sent["http://es:9200/_security/role/cr_viewer"].decode()
    assert '"privileges": ["read", "view_index_metadata"]' in role and '"names": ["logs-*"]' in role
    assert "_ingest/pipeline/geoip" in next(iter(sent))


def test_no_service_holds_the_docker_socket_beside_the_ones_named_here():
    holding = sorted(
        name for name, service in composed.services().items()
        if any("docker.sock" in str(mount) for mount in service.get("volumes") or [])
    )

    assert set(holding) <= {"platform", "gns3"}
