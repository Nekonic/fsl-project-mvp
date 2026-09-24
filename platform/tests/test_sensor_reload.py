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

def test_an_ok_reply_leaves_the_new_rules_in_place():
    sensor = Sensor(Ran(0, RELOADED))

    suricata.apply(AFTER, sensor, RELOAD)

    assert sensor.reloads == 1
    assert suricata.current(sensor) == AFTER

def test_a_nok_reply_is_a_failed_reload_although_suricatasc_exits_0():
    sensor = Sensor(Ran(0, BUSY))

    with pytest.raises(suricata.RuleApplyError, match="Reload already in progress"):
        suricata.apply(AFTER, sensor, RELOAD)

    assert suricata.current(sensor) == BEFORE, (
        "the Rust suricatasc of Suricata 8 prints a NOK reply and exits 0, "
        "so an exit status alone reported this refused reload as done"
    )

def test_a_socket_that_cannot_be_reached_is_a_failed_reload():
    sensor = Sensor(Ran(1, NO_SOCKET))

    with pytest.raises(suricata.RuleApplyError, match="Unable to connect socket"):
        suricata.apply(AFTER, sensor, RELOAD)

    assert suricata.current(sensor) == BEFORE

def test_a_reload_that_answers_nothing_is_not_taken_for_one():
    sensor = Sensor(Ran(0, ""))

    with pytest.raises(suricata.RuleApplyError, match="rolled back"):
        suricata.apply(AFTER, sensor, RELOAD)

    assert suricata.current(sensor) == BEFORE, (
        "a signal exits 0 whether or not anything reloaded; only the "
        "sensor's own reply says the rules loaded"
    )

def test_a_refused_reload_writes_back_the_rules_it_replaced():
    sensor = Sensor(Ran(0, BUSY))

    with pytest.raises(suricata.RuleApplyError, match="rolled back"):
        suricata.apply(AFTER, sensor, RELOAD)

    assert sensor.writes == [AFTER, BEFORE]

def test_the_reply_of_the_python_client_suricata_7_ships_is_understood():
    sensor = Sensor(Ran(0, '{"message": "done", "return": "OK"}\n'))

    suricata.apply(AFTER, sensor, RELOAD)

    assert suricata.current(sensor) == AFTER
