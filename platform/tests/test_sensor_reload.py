import pytest

from range.ports import Ran
from rules import suricata

RELOAD = ("suricatasc", "-c", "reload-rules")
BEFORE = 'alert http any any -> any any (msg:"before"; sid:9000910; rev:1;)\n'
AFTER = 'alert http any any -> any any (msg:"after"; sid:9000911; rev:1;)\n'
RELOADED = '{"message":"done","return":"OK"}\n'
BUSY = '{"message":"Reload already in progress","return":"NOK"}\n'
NO_SOCKET = (
    "Unable to connect socket to /var/run/suricata/suricata-command.socket: "
    "ioerror: `No such file or directory (os error 2)`\n"
)

class Sensor:
    def __init__(self, answer):
        self.files = {suricata.RULE_PATH: BEFORE}
        self.writes = []
        self.reloads = 0
        self.answer = answer

    def __call__(self, argv, stdin=None, timeout=60.0):
        if argv[0] == "sh":
            self.writes.append(stdin)
            self.files[argv[-1].split(">")[-1].strip()] = stdin
            return Ran(0, "")
        if argv[0] == "cat":
            return Ran(0, self.files[argv[1]])
        if tuple(argv) == RELOAD:
            self.reloads += 1
            return self.answer
        return Ran(0, "")

def test_the_sensor_is_reloaded_through_its_command_socket_by_default():
    from django.conf import settings

    assert settings.FSL_SENSOR_RELOAD == RELOAD, (
        "kill -USR2 1 signals whatever is pid 1, which is Suricata only in "
        "its container and init on an instance, and it returns before the "
        "new rules have loaded, so the caller never learns whether they did"
    )

def test_the_shipped_sensor_opens_the_socket_it_is_reloaded_through():
    import pathlib

    import yaml

    shipped = pathlib.Path(__file__).resolve().parents[2] / "deploy/suricata/suricata.yaml"
    config = yaml.safe_load(shipped.read_text())

    assert (config.get("unix-command") or {}).get("enabled") is True, (
        "Suricata 8 opens no command socket when unix-command is absent, "
        "so every reload failed and rolled back: measured suricatasc -c "
        "uptime against the live sensor, No such file or directory"
    )

@pytest.mark.parametrize("reply", [RELOADED, '{"message": "done", "return": "OK"}\n'], ids=["rust", "python"])
def test_an_ok_reply_from_either_suricatasc_leaves_the_new_rules_in_place(reply):
    sensor = Sensor(Ran(0, reply))

    suricata.apply(AFTER, sensor, RELOAD)

    assert sensor.reloads == 1
    assert suricata.current(sensor) == AFTER

@pytest.mark.parametrize("answer, said", [
    (Ran(0, BUSY), "Reload already in progress"),
    (Ran(1, NO_SOCKET), "Unable to connect socket"),
    (Ran(0, ""), "rolled back"),
], ids=["nok-exit-0", "no-socket", "no-reply"])
def test_a_reload_the_sensor_did_not_confirm_fails_and_writes_the_old_rules_back(answer, said):
    sensor = Sensor(answer)

    with pytest.raises(suricata.RuleApplyError, match=said):
        suricata.apply(AFTER, sensor, RELOAD)

    assert sensor.writes == [AFTER, BEFORE], (
        "the Rust suricatasc of Suricata 8 prints a NOK reply and exits 0, and a signal "
        "exits 0 whether or not anything reloaded; only the sensor's own reply says the rules loaded"
    )

def test_the_rules_go_to_the_path_the_sensor_reads_and_roll_back_there():
    edge_rules = "/usr/local/etc/suricata/rules/fsl.rules"
    sensor = Sensor(Ran(0, BUSY))
    sensor.files[edge_rules] = BEFORE

    with pytest.raises(suricata.RuleApplyError):
        suricata.apply(AFTER, sensor, RELOAD, edge_rules)

    assert sensor.files[edge_rules] == BEFORE
    assert sensor.files[suricata.RULE_PATH] == BEFORE
    assert sensor.writes == [AFTER, BEFORE]

def test_on_openstack_the_rules_editor_writes_and_reloads_what_the_edge_loads():
    import os
    import pathlib
    import subprocess
    import sys

    read = subprocess.run(
        [sys.executable, "-c",
         "import fsl.settings as s; print(s.FSL_SENSOR_RULES); print(' '.join(s.FSL_SENSOR_RELOAD))"],
        cwd=pathlib.Path(__file__).resolve().parents[1], capture_output=True, text=True,
        env={**{k: v for k, v in os.environ.items() if not k.startswith("FSL_SENSOR")},
             "DJANGO_SETTINGS_MODULE": "fsl.settings", "FSL_SUBSTRATE": "range.openstack.connect"},
    )
    assert read.returncode == 0, read.stderr[-300:]

    rules, reload = read.stdout.strip().splitlines()
    assert rules == "/usr/local/etc/suricata/rules/fsl.rules", (
        "the editor wrote /var/lib/suricata/rules/local.rules on the edge, a "
        "file the edge's Suricata never loads"
    )
    assert reload == "/usr/local/bin/suricatasc -c reload-rules /var/run/suricata-command.socket"
