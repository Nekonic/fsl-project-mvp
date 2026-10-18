import json
import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest
import yaml
from django.test import override_settings

from api import views
from api.models import Session
from range import declared
from range.docker import Docker
from range.ports import RangeUnavailable

ROOT = pathlib.Path(__file__).resolve().parents[2]

RUNNING = {
    "kali": [("fsl-3-kali-1", "fsl-3"), ("fsl-7-kali-1", "fsl-7")],
    "suricata": [("fsl-3-suricata-1", "fsl-3"), ("fsl-7-suricata-1", "fsl-7")],
    "waf": [("fsl-3-waf-1", "fsl-3"), ("fsl-7-waf-1", "fsl-7")],
    "board": [("fsl-3-board-1", "fsl-3"), ("fsl-7-board-1", "fsl-7")],
    "proxy": [("fsl-3-proxy-1", "fsl-3"), ("fsl-7-proxy-1", "fsl-7")],
}

NETWORKS = [
    {"Name": "fsl_edge", "Labels": {"fsl.segment.id": "ru",
                                    "com.docker.compose.project": "fsl"},
     "IPAM": {"Config": [{"Subnet": "5.188.10.0/24", "Gateway": "5.188.10.1"}]},
     "Containers": {
         "w3": {"Name": "fsl-3-waf-1", "IPv4Address": "5.188.10.13/24"},
         "w7": {"Name": "fsl-7-waf-1", "IPv4Address": "5.188.10.17/24"},
         "p7": {"Name": "fsl-7-proxy-1", "IPv4Address": "5.188.10.27/24"},
     }},
    {"Name": "fsl-3_estate", "Labels": {"fsl.segment.id": "estate",
                                        "com.docker.compose.project": "fsl-3"},
     "IPAM": {"Config": [{"Subnet": "192.168.3.0/24", "Gateway": "192.168.3.1"}]},
     "Containers": {"b3": {"Name": "fsl-3-board-1", "IPv4Address": "192.168.3.2/24"}}},
    {"Name": "fsl-7_estate", "Labels": {"fsl.segment.id": "estate",
                                        "com.docker.compose.project": "fsl-7"},
     "IPAM": {"Config": [{"Subnet": "192.168.7.0/24", "Gateway": "192.168.7.1"}]},
     "Containers": {
         "b7": {"Name": "fsl-7-board-1", "IPv4Address": "192.168.7.2/24"},
         "w7": {"Name": "fsl-7-waf-1", "IPv4Address": "192.168.7.3/24"},
     }},
    {"Name": "fsl_mgmt", "Labels": {"fsl.segment.id": "mgmt",
                                    "com.docker.compose.project": "fsl"},
     "IPAM": {"Config": [{"Subnet": "172.31.0.0/24", "Gateway": "172.31.0.1"}]},
     "Containers": {}},
]

ATTACHED = [
    (attached["Name"], network["Name"], attached["IPv4Address"].split("/")[0])
    for network in NETWORKS
    for attached in network["Containers"].values()
]


class Range:
    def __init__(self, networks=NETWORKS):
        self.argv = []
        self.networks = networks

    def __call__(self, argv, **kwargs):
        self.argv.append(argv)
        out = ""
        if argv[1] == "ps":
            service = next(a for a in argv if a.startswith("label=com.docker.compose.service="))
            out = "\n".join(f"{n} {p}" for n, p in RUNNING.get(service.rpartition("=")[2], []))
        elif argv[1:3] == ["network", "ls"]:
            wanted = next(a for a in argv if a.startswith("label=fsl.segment.id"))
            segment = wanted.partition("fsl.segment.id")[2].lstrip("=")
            out = "\n".join(
                f"{n['Name']} {n['Labels']['com.docker.compose.project']} "
                f"{n['Labels']['fsl.segment.id']}" for n in self.networks
                if not segment or n["Labels"]["fsl.segment.id"] == segment
            )
        elif argv[1:3] == ["network", "inspect"]:
            out = "\n".join(json.dumps(n) for n in self.networks if n["Name"] in argv)
        elif argv[1:3] == ["container", "inspect"]:
            out = "".join(f"/{name} container:w{name[4]}\n" for name in argv[5:])
        elif argv[1] == "inspect":
            out = json.dumps({
                network: {"IPAddress": address}
                for name, network, address in ATTACHED if name == argv[2]
            })
        return type("Done", (), {"returncode": 0, "stdout": out, "stderr": ""})()


def session_range(session):
    return Docker(declared.read(), session=session)


def test_a_role_runs_in_its_own_session_s_container():
    spy = Range()
    with patch("range.docker.subprocess.run", spy), \
            patch("range.docker.execute", lambda host, command, stdin, timeout: (
                spy.argv.append(command),
                type("Done", (), {"returncode": 0, "stdout": "", "stderr": "fsl.exit=0\n"})(),
            )[1]):
        session_range(3).runner("sensor")(["true"])

    assert spy.argv[-1][:3] == ["docker", "exec", "fsl-3-suricata-1"], (
        "a rule written for session 3 reached the sensor of another session"
    )


def test_a_role_with_no_running_container_in_the_session_is_unavailable():
    with patch("range.docker.subprocess.run", Range()), \
            pytest.raises(RangeUnavailable, match="fsl-9"):
        session_range(9)._container("gateway")


def test_a_session_s_containers_carry_their_declared_host_names():
    with patch("range.docker.subprocess.run", Range()):
        shape = session_range(7).describe()

    names = {segment.id: {node.name for node in segment.nodes} for segment in shape.segments}
    assert names["estate"] == {"fsl-wg-board", "fsl-waf"}
    assert names["ru"] == {"fsl-waf", "fsl-proxy", "fsl-3-waf-1"}, (
        "the attacker box, the topology and the terminals find a host by the "
        "name the declaration gives it, not by its per-session container name"
    )
    assert [(s.name, s.watches) for s in shape.sensors] == [("fsl-suricata", "fsl-waf")]


def test_an_estate_left_by_an_older_control_plane_is_not_a_second_estate():
    left_over = {"Name": "fsl_estate", "Labels": {"fsl.segment.id": "estate",
                                                   "com.docker.compose.project": "fsl"},
                 "IPAM": {"Config": [{"Subnet": "172.30.0.0/24"}]}, "Containers": {}}

    with patch("range.docker.subprocess.run", Range(NETWORKS + [left_over])):
        estate = [s.network for s in session_range(7).segments() if s.id == "estate"]
        sole = session_range(7)._network_of("estate")

    assert (estate, sole) == (["fsl-7_estate"], "fsl-7_estate"), (
        "upgrading the control plane leaves its old estate network behind, and "
        "the range refused to start a tool on two estates"
    )


@pytest.mark.opens_session_stack
def test_the_ground_truth_is_read_on_the_session_s_own_estate():
    with patch("range.docker.subprocess.run", Range()):
        assert session_range(7).address("board") == "192.168.7.2"
        assert session_range(3).address("board") == "192.168.3.2"


def test_a_tool_resolves_the_target_names_to_its_own_session_s_waf():
    spy = Range()
    with patch("range.docker.subprocess.run", spy):
        session_range(7).launcher("ru")("ghcr.io/nekonic/fsl-kali:dev", ["sqlmap"])

    started = spy.argv[-1]
    assert started[:3] == ["docker", "run", "--rm"]
    assert "--add-host=board.com:5.188.10.17" in started
    assert "--add-host=corp.com:5.188.10.17" in started, (
        "board.com is an alias every session's WAF answers to on the shared "
        "edge, so a tool that resolves it by DNS may attack another session"
    )
    assert started[-2:] == ["ghcr.io/nekonic/fsl-kali:dev", "sqlmap"]


def test_each_session_ships_its_logs_to_its_own_index():
    filebeat = yaml.safe_load((ROOT / "deploy/filebeat/filebeat.yml").read_text())
    stack = yaml.safe_load((ROOT / "session.yaml").read_text())

    assert filebeat["output.elasticsearch"]["index"].startswith("fsl-logs-${FSL_SESSION:shared}-")
    assert stack["services"]["filebeat"]["environment"]["FSL_SESSION"] == "${FSL_SESSION:-shared}"


def test_the_attacker_box_reaches_its_own_session_s_proxy():
    stack = yaml.safe_load((ROOT / "session.yaml").read_text())
    kali, proxy = stack["services"]["kali"], stack["services"]["proxy"]

    assert kali["environment"]["http_proxy"] == "http://fsl-${FSL_SESSION:-}-proxy-1:8081"
    assert "label:/var/lib/session:ro" in kali["volumes"] and "label:/var/lib/session" in proxy["volumes"], (
        "a label directory on the host is shared by every session's proxy"
    )


@pytest.mark.django_db
def test_ingest_reads_only_the_session_s_own_index(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]
    read = []

    def fetch(url, index, start, end, newest_first=False):
        read.append(index)
        return [], None

    with patch("api.views.elastic.fetch", fetch):
        client.post_json(f"/api/sessions/{session_id}/ingest/")
        with override_settings(ELASTIC_SESSION_INDEX=""):
            client.post_json(f"/api/sessions/{session_id}/ingest/")

    assert read == [f"fsl-logs-{session_id}-*", "fsl-logs-*"], (
        "a session scored the alerts another session's attacks drew"
    )


@pytest.mark.django_db
def test_opening_a_session_aims_its_attacker_at_its_own_waf(client):
    aimed = []

    with patch("api.views._aim_attacker", lambda adapter: aimed.append(adapter.session)):
        session_id = client.post_json("/api/sessions/", {}).json()["id"]

    assert aimed == [session_id], (
        "the proxy left with no origin resolves board.com, which every "
        "session's WAF answers to"
    )


@pytest.mark.opens_session_stack
def test_aiming_writes_the_session_s_waf_address_for_the_proxy():
    wrote = []

    class Stub:
        def segments(self):
            with patch("range.docker.subprocess.run", Range()):
                return session_range(7).segments()

        def runner(self, role):
            def run(argv, stdin=None, timeout=60.0):
                wrote.append((role, argv, stdin))
                return type("Ran", (), {"ok": True, "output": ""})()
            return run

    with override_settings(ATTACKER_SOURCE_CONTAINER="fsl-proxy", ATTACKER_ORIGIN_MODE="host-rewrite"):
        views._aim_attacker(Stub())

    assert wrote == [("proxy", ["sh", "-c", "cat > /var/lib/session/origin"], "5.188.10.17")]


@pytest.mark.django_db
def test_range_wide_calls_use_the_newest_session_as_the_range_does():
    Session.objects.create(scenario="board", baseline=[])
    Session.objects.create(scenario="board", baseline=[])
    newest = Session.objects.create(
        scenario="board", baseline=[], ended_at="2026-10-10T00:00:00Z"
    )

    assert views._range().session == newest.pk, (
        "a call with no session named chose an older open session while the "
        "range, asked the same way, answers from the newest stack: the console "
        "reported one session's attacker box and the shell ran in another's"
    )
    with patch("range.docker.subprocess.run", Range()):
        assert session_range(None)._container("attacker") == "fsl-7-kali-1"


class Sensors:
    def __init__(self, rules="alert http any any -> any any (msg:\"x\"; sid:9000001; rev:1;)\n"):
        self.rules = {}
        self.default = rules
        self.ran_in = []

    def install(self):
        sensors = self

        def runner(adapter, role, segment_id=""):
            def run(argv, stdin=None, timeout=60.0):
                sensors.ran_in.append((role, adapter.session))
                return type("Ran", (), {"ok": True, "output": "", "exit_code": 0})()
            return run

        return patch("range.docker.Docker.runner", runner)


def opened_sessions(n):
    return [Session.objects.create(scenario="board", baseline=[]) for _ in range(n)]


@pytest.mark.django_db
def test_rules_act_on_the_sensor_of_the_session_asked_for(client):
    older, _ = opened_sessions(2)
    sensors = Sensors()

    with sensors.install(), patch("api.views.suricata.apply") as applied, \
            patch("api.views.suricata.current", return_value=sensors.default) as read:
        client.get(f"/api/rules/?session={older.pk}")
        client.post_json("/api/rules/apply/", {"content": sensors.default, "session": older.pk})

    read.call_args.args[0](["true"])
    applied.call_args.args[1](["true"])
    assert sensors.ran_in[-2:] == [("sensor", older.pk), ("sensor", older.pk)], (
        "a rule written for one session's sensor reached the newest session's"
    )


@pytest.mark.django_db
def test_a_suppression_is_lifted_on_the_sensor_it_was_set_on(client):
    older, _ = opened_sessions(2)
    rule = 'alert http any any -> any any (msg:"x"; sid:9000901; rev:1;)\n'
    sensors = Sensors()

    with sensors.install(), patch("api.views.suricata.current", return_value=rule), \
            patch("api.views.suricata.apply") as applied:
        made = client.post_json(
            "/api/rules/suppressions/", {"sid": 9000901, "session": older.pk}
        )
        from api.models import Suppression
        record = Suppression.objects.get()
        with patch("api.views.suricata.current", return_value="") as reread:
            client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert made.status_code == 201, made.content
    assert record.session_id == older.pk
    reread.call_args.args[0](["true"])
    assert sensors.ran_in == [("sensor", older.pk)], (
        "the expiry restored the rule on whichever sensor was newest"
    )


@pytest.mark.django_db
def test_the_red_console_s_calls_act_on_its_own_session(client):
    older, _ = opened_sessions(2)
    sensors = Sensors()

    with sensors.install():
        labelled = client.post_json(
            "/api/attacker/label/", {"case_id": "x", "session": older.pk}
        )

    assert labelled.status_code == 200, labelled.content
    assert sensors.ran_in == [("proxy", older.pk)]
    assert client.post_json("/api/attacker/label/", {"case_id": "x", "session": "nine"}).status_code == 400
    assert client.post_json("/api/attacker/label/", {"case_id": "x", "session": 999}).status_code == 404


@pytest.mark.django_db
def test_the_terminal_is_the_session_s_own_kali(client):
    session, = opened_sessions(1)

    assert views._terminal_url(session) == f"/terminal/{session.pk}/"
    assert client.get(f"/api/sessions/{session.pk}/").json()["kali_terminal"] == f"/terminal/{session.pk}/"
    nginx = (ROOT / "platform/nginx.conf").read_text()
    start = nginx.index("location ~ ^/terminal/(?<session>")
    block = nginx[start:nginx.index("}", start)]
    assert "auth_request /terminal-allowed;" in block
    assert "fsl-$session-kali-1:7681" in block, (
        "the shared name kali resolves to every session's attacker box"
    )


@pytest.mark.django_db
def test_the_waf_terminal_is_a_shell_in_the_session_s_own_waf(client):
    session, = opened_sessions(1)

    assert client.get(f"/api/sessions/{session.pk}/").json()["waf_terminal"] == f"/waf-terminal/{session.pk}/"
    nginx = (ROOT / "platform/nginx.conf").read_text()
    start = nginx.index("location ~ ^/waf-terminal/(?<session>\\d+)/")
    block = nginx[start:nginx.index("}", start)]
    assert "auth_request /terminal-allowed;" in block
    assert "proxy_pass http://127.0.0.1:7693/waf-terminal/$rest?arg=$session;" in block, (
        "the session comes from the path alone; a client's own ?arg= is dropped"
    )
    assert "ttyd -W -a -b /waf-terminal -t disableResizeOverlay=true -i 127.0.0.1 -p 7693 /app/waf-terminal.sh" in (
        ROOT / "platform/entrypoint.sh").read_text()

def _waf_terminal(tmp_path, session, running):
    reached = tmp_path / "docker-argv"
    for name, body in {
        "docker": f'case "$1" in inspect) echo {running};; exec) printf "%s\\n" "$@" > {reached};; esac',
        "sleep": "exit 0",
    }.items():
        (tmp_path / name).write_text(f"#!/bin/sh\n{body}\n")
        (tmp_path / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TERMINAL_LOG": str(tmp_path / "terminal.log")}
    ran = subprocess.run(["sh", str(ROOT / "platform/waf-terminal.sh"), session], capture_output=True, text=True, env=env)
    return ran, reached

def test_only_a_session_number_reaches_docker_exec_and_a_missing_waf_gets_one_plain_line(tmp_path):
    for session, running in (("5; reboot", "true"), ("", "true"), ("5", "false")):
        ran, reached = _waf_terminal(tmp_path, session, running)

        assert not reached.exists(), session
        assert ran.stdout.strip() == "Connection to waf failed. Reopen the terminal in a moment."
        assert "session" not in ran.stdout and "slot" not in ran.stdout

    ran, reached = _waf_terminal(tmp_path, "5", "true")
    assert "fsl-5-waf-1" in reached.read_text().split()

@pytest.mark.django_db
def test_on_openstack_the_waf_terminal_is_an_ssh_shell_on_the_waf_vm(client):
    with override_settings(WAF_SESSION_TERMINAL_URL=""):
        session, = opened_sessions(1)
        assert client.get(f"/api/sessions/{session.pk}/").json()["waf_terminal"] == "/vm-terminal/fsl-waf/"

    assert "ttyd -W -a -b /vm-terminal/fsl-waf -t disableResizeOverlay=true -i 127.0.0.1 -p 7692 /app/vm-terminal.sh fsl-waf" in (
        ROOT / "platform/entrypoint.sh").read_text()
    assert "mgmt" in declared.read(flavor="openstack").hosts["fsl-waf"].segments
    shell = (ROOT / "platform/vm-terminal.sh").read_text()
    assert 'if seg.id == "mgmt"' in shell and '"ubuntu@${addr}"' in shell and '"kali@${addr}"' in shell, (
        "the shell is the ssh user the platform tunes the WAF as, on the VM's management address"
    )
    assert "StrictHostKeyChecking=accept-new" in shell and '-o HostKeyAlias=$alias' in shell, (
        "a rebuilt server is a new key under a new alias, so the terminal neither warns nor stops checking"
    )

@pytest.mark.django_db
def test_the_attacker_box_asked_for_no_session_is_the_newest_one(client):
    Session.objects.create(scenario="board", baseline=[])
    newest = Session.objects.create(scenario="board", baseline=[], ended_at="2026-10-10T00:00:00Z")
    asked = []

    def standing(session=None):
        asked.append(session.pk)
        raise RangeUnavailable("stand-in")

    with patch("api.views._standing", standing):
        client.get("/api/attacker/")

    assert asked == [newest.pk], (
        "the console's box and the shell the acceptance suite drives were two "
        "different sessions' attacker boxes"
    )


@pytest.mark.django_db
def test_a_suppression_on_a_torn_down_session_is_lifted_not_stuck(client):
    from django.utils import timezone

    from api.models import Suppression

    gone = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())
    record = Suppression.objects.create(
        session=gone, sid=9000004, original="alert x", expires_at=timezone.now(),
    )

    with patch("api.views.suricata.current", side_effect=RangeUnavailable("no sensor")), \
            patch("range.docker.Docker.has_stack", lambda self: False):
        restored = client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")
        listed = client.get("/api/rules/suppressions/").json()

    assert restored.status_code == 200, restored.content
    assert listed["suppressions"] == [], (
        "a suppression on a session whose stack was taken down could never be "
        "restored, and every later run refused to start over it"
    )


@pytest.mark.django_db
def test_a_suppression_on_a_session_whose_close_rebuilt_the_range_is_lifted_without_the_sensors(client):
    from django.utils import timezone

    from api.models import Suppression

    closed = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())
    record = Suppression.objects.create(
        session=closed, sid=9000004, original="alert x", expires_at=timezone.now(),
    )

    class Rebuilding:
        def rebuild_slot(self):
            return []

        def runner(self, role, segment_id=""):
            raise RangeUnavailable(f"{role} is rebuilding")

    with patch("api.views._range", lambda session=None: Rebuilding()):
        restored = client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert restored.status_code == 200, restored.content
    assert Suppression.objects.get(pk=record.pk).restored_at is not None, (
        "on openstack the close rebuilds every sensor from its image, so a "
        "restore sent while the sensors are down stayed in force and every "
        "later session was refused as off baseline"
    )

@pytest.mark.django_db
def test_a_suppression_on_an_open_session_is_not_dropped_when_its_sensor_is_down(client):
    from django.utils import timezone

    from api.models import Suppression

    live = Session.objects.create(scenario="board", baseline=[])
    record = Suppression.objects.create(
        session=live, sid=9000004, original="alert x", expires_at=timezone.now(),
    )

    with patch("api.views.suricata.current", side_effect=RangeUnavailable("no sensor")):
        restored = client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert restored.status_code == 503
    assert Suppression.objects.get(pk=record.pk).restored_at is None


@pytest.mark.django_db
def test_a_suppression_on_an_ended_session_whose_stack_still_runs_stays_pending(client):
    from django.utils import timezone

    from api.models import Suppression

    ended = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())
    record = Suppression.objects.create(
        session=ended, sid=9000004, original="alert x", expires_at=timezone.now(),
    )

    with patch("api.views.suricata.current", side_effect=RangeUnavailable("docker timed out")), \
            patch("range.docker.Docker.has_stack", lambda self: True):
        restored = client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert restored.status_code == 503
    assert Suppression.objects.get(pk=record.pk).restored_at is None, (
        "a passing docker error marked the rule restored while the sensor that "
        "silenced it still runs with it commented out"
    )


def test_a_session_s_stack_is_known_by_its_project_s_containers():
    seen = []

    def ps(argv, **kwargs):
        seen.append(argv)
        out = "abc123\n" if argv[-1].endswith("fsl-7") else ""
        return type("Done", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    with patch("range.docker.subprocess.run", ps):
        assert session_range(7).has_stack() is True
        assert session_range(8).has_stack() is False
    assert seen[0][:4] == ["docker", "ps", "-a", "-q"]


@pytest.mark.django_db
def test_a_write_naming_no_session_goes_to_the_newest_open_one(client):
    from django.utils import timezone

    open_one = Session.objects.create(scenario="board", baseline=[])
    Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())
    sensors = Sensors()

    with sensors.install():
        client.post_json("/api/attacker/label/", {"case_id": "x"})

    assert sensors.ran_in == [("proxy", open_one.pk)], (
        "a write naming no session went to a closed session's stack"
    )


@pytest.mark.django_db
def test_a_write_with_no_session_open_is_refused(client):
    from django.utils import timezone

    Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    answer = client.post_json("/api/rules/apply/", {"content": ""})

    assert answer.status_code == 409


@pytest.mark.django_db
def test_a_write_to_a_closed_session_is_refused(client):
    from django.utils import timezone

    closed = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    for path, body in (("/api/attacker/label/", {"case_id": "x"}),
                       ("/api/attacker/origin/", {"origin": ""}),
                       ("/api/rules/suppressions/", {"sid": 9000001}),
                       ("/api/rules/apply/", {"content": ""}),
                       ("/api/range/canary/", {})):
        answer = client.post_json(path, dict(body, session=closed.pk))
        assert answer.status_code == 409, (path, answer.content)
