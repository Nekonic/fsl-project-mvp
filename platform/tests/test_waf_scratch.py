import http.client
import importlib.util
import re
import shlex
import subprocess
import threading
from pathlib import Path, PurePosixPath

import pytest
import yaml

from cr import config as settings
from cr.config import SensorConfig, WafConfig
from sandbox import crs, suricata
from testing.fakes import FakeRunner
from training.content import probes as recorder
from training.defence import ruletest

ROOT = Path(__file__).resolve().parents[2]
WAF = ROOT / "deploy/roles/waf"
INFRA = ROOT / "deploy/roles/infra"


def assigned(path: Path) -> dict[str, str]:
    return {name: value.strip('"') for name, value in re.findall(r'^([A-Z_0-9]+)=("[^"]*"|\S+)$', path.read_text(), re.M)}


def expanded(path: Path, value: str) -> str:
    names = assigned(path)
    return re.sub(r"\$(\w+)", lambda found: names[found[1]], value)


def live_waf() -> WafConfig:
    found, _ = settings.devices(ROOT)
    return settings.waf(found)


def rendered_template(scratch: crs.Scratch) -> str:
    return ((WAF / "probe.conf").read_text().replace("@prefix@", scratch.prefix)
            .replace("@port@", str(scratch.port)).replace("@upstream_port@", str(scratch.upstream_port)))


def scratch_commands() -> list[str]:
    gateway = FakeRunner()
    crs.scratch_test({}, gateway, live_waf(), 42, [])
    return [one.argv[2] for one in gateway.sent if one.argv[:2] == ["sh", "-c"]]


def sed_over(target: str, text: str) -> str:
    [segment] = [part for command in scratch_commands() for part in command.split("; ")
                 if part.startswith("sed ") and target in part]
    words = shlex.split(segment)
    expressions = [words[at + 1] for at, word in enumerate(words) if word == "-e"]
    return subprocess.run(["sed", *(f"-e{one}" for one in expressions)], input=text, capture_output=True, text=True,
                          check=True).stdout


def upstream_module():
    spec = importlib.util.spec_from_file_location("probe_upstream", WAF / "probe-upstream.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_waf_installs_the_scratch_template_and_stub_where_the_crs_seam_runs_them():
    script = (WAF / "install.sh").read_text()
    config = WafConfig()

    assert f'install -m 0644 probe.conf "$PROBE_SHARE/probe.conf"' in script
    assert f'install -m 0755 probe-upstream.py "$PROBE_SHARE/probe-upstream.py"' in script
    assert expanded(WAF / "install.sh", "$PROBE_SHARE/probe.conf") == config.probe_template
    assert expanded(WAF / "install.sh", "$PROBE_SHARE/probe-upstream.py") == config.probe_upstream
    assert expanded(WAF / "install.sh", "$CRS_TEST_DIR") == config.scratch
    assert 'install -d -m 0700 "$CRS_TEST_DIR"' in script
    assert {"python3", "curl"} <= set(re.search(r"^installed (.+)", script, re.M)[1].split()), (
        "crs.scratch_test starts the stub with python3 and pipes each probe through curl")


def test_the_template_carries_exactly_the_placeholders_the_crs_seam_fills():
    template = (WAF / "probe.conf").read_text()
    scratch = crs.scratch_for(live_waf(), 42)
    filled = sed_over(live_waf().probe_template, template)

    assert set(re.findall(r"@(\w+)@", template)) == {"prefix", "port", "upstream_port"}
    assert not re.findall(r"@\w+@", filled)
    assert f"127.0.0.1:{scratch.port}" in filled and f"127.0.0.1:{scratch.upstream_port}" in filled


def test_the_scratch_instance_listens_on_loopback_only_and_keeps_every_file_under_its_own_prefix():
    config = live_waf()
    scratch = crs.scratch_for(config, 42)
    conf = rendered_template(scratch)

    assert re.findall(r"^\s*listen (.+)$", conf, re.M) == [f"127.0.0.1:{scratch.port} default_server;",
                                                         f"127.0.0.1:{scratch.port};"]
    assert re.findall(r"^\s*include (\S+);", conf, re.M) == [
        f"{scratch.sites}/http.conf", f"{scratch.sites}/board.com.conf", f"{scratch.sites}/corp.com.conf"], (
        "the defence's nginx files load where the live site config loads them")
    assert f"proxy_pass http://127.0.0.1:{scratch.upstream_port};" in conf
    assert f"modsecurity_rules_file {scratch.tree}/modsecurity.conf;" in conf
    for directive in ("pid", "error_log", "client_body_temp_path", "proxy_temp_path"):
        [path] = re.findall(rf"^\s*{directive} (\S+);", conf, re.M)
        assert PurePosixPath(path).is_relative_to(scratch.prefix), directive
    assert "access_log off;" in conf, "the scratch instance writes no access log for the shipper to pick up"
    assert "@" not in conf.replace("$", "")


def test_the_copied_crs_tree_points_at_the_scratch_copy_and_the_scratch_audit_log_only():
    config = live_waf()
    scratch = crs.scratch_for(config, 42)
    copied = sed_over(f"{scratch.tree}/modsecurity.conf", (ROOT / "deploy/waf/modsecurity.conf").read_text())
    audit_log_shipped = re.findall(r'File="([^"]+)"', (WAF / "log-shipper.conf").read_text())

    assert config.tree == "/etc/nginx/modsecurity"
    assert config.tree not in copied
    assert re.findall(r"^SecAuditLog (\S+)$", copied, re.M) == [scratch.audit]
    assert scratch.audit not in audit_log_shipped
    assert re.findall(r"^SecAuditLogFormat (\S+)$", copied, re.M) == ["JSON"], "crs.audit_alerts reads JSON lines"
    assert "B" in re.search(r"^SecAuditLogParts (\S+)$", copied, re.M)[1], (
        "the request headers carry the X-Request-ID the verdict matches on")


def test_the_live_and_scratch_trees_never_meet():
    config = live_waf()

    with pytest.raises(ValueError):
        crs.scratch_for(WafConfig(scratch=f"{config.tree}/scratch"), 1)
    with pytest.raises(ValueError):
        crs.scratch_for(WafConfig(scratch=f"{config.sites}/scratch"), 1)


def test_the_stub_answers_each_probe_with_its_recorded_response_by_marker_on_loopback():
    stub = upstream_module()
    probes = [{"marker": "probe-1", "method": "GET", "path": "/", "response": {"status": 200, "body": "<p>hi</p>"}},
              {"marker": "probe-2", "method": "POST", "path": "/login/", "body": "a=1",
               "response": {"status": 302, "body": ""}},
              {"marker": "probe-3", "method": "GET", "path": "/x", "response": None}]
    with stub.server(0, probes) as serving:
        threading.Thread(target=serving.serve_forever, daemon=True).start()
        host, port = serving.server_address
        try:
            assert host == "127.0.0.1"
            answers = []
            for method, marker, body in (("GET", "probe-1", None), ("POST", "probe-2", "a=1"),
                                         ("GET", "probe-3", None), ("GET", "unknown", None),
                                         ("HEAD", "probe-1", None)):
                connection = http.client.HTTPConnection(host, port, timeout=5)
                connection.request(method, "/", body=body, headers={"X-Request-ID": marker})
                response = connection.getresponse()
                answers.append((response.status, response.read(), response.getheader("Content-Type")))
                connection.close()
        finally:
            serving.shutdown()

    assert answers[0] == (200, b"<p>hi</p>", "text/html; charset=utf-8"), (
        "ModSecurity inspects only the response body types modsecurity.conf names")
    assert answers[1][:2] == (302, b"")
    assert answers[2][:2] == (200, b"")
    assert answers[3][:2] == (404, b"")
    assert answers[4][:2] == (200, b"")


def test_the_stub_takes_the_arguments_the_crs_seam_passes():
    stub = upstream_module()

    scratch = crs.scratch_for(live_waf(), 42)
    [started] = [part for command in scratch_commands() for part in command.split("; ") if "nohup python3" in part]
    words = shlex.split(started.split(" >")[0])

    given = stub.arguments(words[words.index(live_waf().probe_upstream) + 1:])

    assert (given.port, given.probes) == (scratch.upstream_port, f"{scratch.prefix}/probes.json")
    assert (WAF / "probe-upstream.py").read_text().startswith("#!/usr/bin/env python3\n")


def test_the_infra_runs_the_offline_replay_with_the_live_sensor_s_image_and_settings_outside_the_live_logs():
    script = (INFRA / "install.sh").read_text()
    sensor = SensorConfig(name="cr-ids")
    live = yaml.safe_load((ROOT / "wargames/board/topology.yaml").read_text())["devices"]["cr-ids"]

    assert assigned(INFRA / "install.sh")["SENSOR_IMAGE"] == sensor.image == settings.SURICATA_IMAGE
    assert "install -m 0644 suricata.yaml /etc/suricata/suricata.yaml" in script
    assert sensor.settings_file == "/etc/suricata/suricata.yaml"
    assert expanded(INFRA / "install.sh", "$RULE_TEST_DIR") == sensor.scratch
    assert 'install -d -m 0700 "$RULE_TEST_DIR"' in script
    assert expanded(INFRA / "install.sh", "$EVE_DIR") == sensor.live_logs
    assert suricata.scratch_of(sensor, "test-1").startswith(sensor.scratch + "/")
    assert live["node"] == "cr-infra" and sensor.interface == "br0"
    assert {"tcpdump", "docker.io"} <= set(re.search(r"^installed (.+)", script, re.M)[1].split()), (
        "rules.suricata.capture records the probe pcaps on the IDS bridge with tcpdump")


def test_a_recorded_response_written_by_the_probe_recorder_is_what_the_stub_answers(tmp_path):
    stub = upstream_module()
    recorder.written(tmp_path, "board-sqli-union.request.json", {"method": "GET", "path": "/search", "host": "board.com"})
    recorder.written(tmp_path, "board-sqli-union.response.json", {"status": 403, "body": "denied"})
    recording = ruletest.Recording(case="board-sqli-union", malicious=True, tool_case=False, expect=None,
                                   marker="probe-1", in_manifest=True, folder=tmp_path)

    assert stub.answers([ruletest.probe_request(recording)]) == {"probe-1": (403, b"denied", "text/html; charset=utf-8")}
