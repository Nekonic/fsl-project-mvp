import json
import pathlib
import re

import pytest
import yaml

from cr import config
from cr.errors import EngineRefused
from sandbox import suricata
from sandbox.runner import Ran, RangeUnavailable
from testing.fakes import FakeRunner, eve

ROOT = pathlib.Path(__file__).resolve().parents[3]
RELOAD = ("suricatasc", "-c", "reload-rules")
RELOADED = '{"message":"done","return":"OK"}\n'
BUSY = '{"message":"Reload already in progress","return":"NOK"}\n'
NO_SOCKET = "Unable to connect socket to /var/run/suricata/suricata-command.socket\n"
BEFORE = 'alert http any any -> any any (msg:"before"; sid:9000910; rev:1;)\n'
AFTER = 'alert http any any -> any any (msg:"after"; sid:9000911; rev:1;)\n'
SENSOR = config.SensorConfig(name="cr-ids", reload=RELOAD)


class Sensor:
    def __init__(self, reload_answer=Ran(0, RELOADED), check_answer=Ran(0, ""), unreachable=False,
                 write_fails=False, rules=SENSOR.rules):
        self.files = {rules: BEFORE}
        self.writes = []
        self.checks = []
        self.reloads = 0
        self.reload_answer = reload_answer
        self.check_answer = check_answer
        self.unreachable = unreachable
        self.write_fails = write_fails

    def __call__(self, argv, stdin=None, timeout=60.0):
        if self.unreachable:
            raise RangeUnavailable("the sensor is not there")
        joined = " ".join(argv)
        if "suricata -T" in joined:
            self.checks.append((joined, stdin))
            return self.check_answer
        if argv[0] == "sh" and stdin is not None:
            if self.write_fails:
                return Ran(1, "sh: can't create: No space left on device")
            self.writes.append(stdin)
            self.files[argv[-1].split(">")[-1].strip()] = stdin
            return Ran(0, "")
        if argv[0] == "cat":
            return Ran(0, self.files.get(argv[1], ""))
        if tuple(argv) == RELOAD:
            self.reloads += 1
            return self.reload_answer
        return Ran(0, "")


def test_the_sensors_come_from_the_topologies_watches():
    sensors = config.build({}, ROOT).sensors

    assert [(one.name, one.role) for one in sensors] == [("cr-ids", "sensor")]
    assert sensors[0].reload == RELOAD
    shipped = (ROOT / "deploy/suricata/suricata.yaml").read_text()
    loaded = yaml.safe_load(shipped.split("\n", 2)[2])
    assert sensors[0].rules == f"{loaded['default-rule-path']}/{loaded['rule-files'][0]}", (
        "the editor must write the file the sensor's Suricata loads")


def test_the_shipped_sensor_opens_the_socket_it_is_reloaded_through():
    shipped = yaml.safe_load((ROOT / "deploy/suricata/suricata.yaml").read_text())

    assert (shipped.get("unix-command") or {}).get("enabled") is True


@pytest.mark.parametrize("reply", [RELOADED, '{"message": "done", "return": "OK"}\n'], ids=["rust", "python"])
def test_an_ok_reply_from_either_suricatasc_leaves_the_new_rules_in_place(reply):
    sensor = Sensor(reload_answer=Ran(0, reply))

    suricata.apply(AFTER, sensor, SENSOR)

    assert sensor.reloads == 1
    assert suricata.current(sensor, SENSOR) == AFTER


@pytest.mark.parametrize("answer, said", [
    (Ran(0, BUSY), "Reload already in progress"),
    (Ran(1, NO_SOCKET), "Unable to connect socket"),
    (Ran(0, ""), "rolled back"),
], ids=["nok-exit-0", "no-socket", "no-reply"])
def test_a_reload_the_sensor_did_not_confirm_fails_and_writes_the_old_rules_back(answer, said):
    sensor = Sensor(reload_answer=answer)

    with pytest.raises(suricata.RuleApplyError, match=said):
        suricata.apply(AFTER, sensor, SENSOR)

    assert sensor.writes == [AFTER, BEFORE]


def test_the_rules_go_to_the_path_the_sensor_reads_and_roll_back_there():
    elsewhere = config.SensorConfig(name="edge-ids", rules="/usr/local/etc/suricata/rules/cr.rules", reload=RELOAD)
    sensor = Sensor(reload_answer=Ran(0, BUSY), rules=elsewhere.rules)

    with pytest.raises(suricata.RuleApplyError):
        suricata.apply(AFTER, sensor, elsewhere)

    assert sensor.files[elsewhere.rules] == BEFORE


def test_a_rule_set_the_sensor_refuses_is_never_written_or_reloaded():
    sensor = Sensor(check_answer=Ran(1, 'E: detect: error parsing signature "alert x" from file '
                                        '/tmp/cr-rule-check-1/candidate.rules at line 2'))

    with pytest.raises(suricata.RuleSyntax) as refused:
        suricata.apply(AFTER, sensor, SENSOR)

    assert sensor.writes == [] and sensor.reloads == 0
    assert isinstance(refused.value, EngineRefused) and refused.value.code == "suricata_syntax"
    assert refused.value.errors[0].line == 2 and refused.value.errors[0].path == "text"


def test_checking_runs_the_self_test_on_a_scratch_copy_of_exactly_the_given_rules():
    sensor = Sensor()

    assert suricata.checked(AFTER, sensor, SENSOR) == []
    [(script, given)] = sensor.checks
    assert given == AFTER
    scratch = re.search(r"-S (\S+)", script)[1]
    assert scratch.startswith(suricata.CHECK_SCRATCH) and scratch != SENSOR.rules
    assert "rm -rf" in script, "the scratch copy is removed after the self-test"
    assert sensor.writes == []


def test_two_checks_never_share_a_scratch_copy():
    sensor = Sensor()

    suricata.checked(AFTER, sensor, SENSOR)
    suricata.checked(BEFORE, sensor, SENSOR)

    first, second = (re.search(r"-S (\S+)", script)[1] for script, _ in sensor.checks)
    assert first != second


def test_suricata_errors_are_read_into_lines_and_messages():
    output = ("i: suricata: This is Suricata version 7.0.8\n"
              'E: detect-parse: unknown rule keyword \'nosuch\'.\n'
              'E: detect: error parsing signature "alert http x" from file /tmp/c.rules at line 3\n')

    assert [error.shown() for error in suricata.parsed_errors(output)] == [
        {"line": None, "message": "E: detect-parse: unknown rule keyword 'nosuch'."},
        {"line": 3, "message": 'E: detect: error parsing signature "alert http x" from file /tmp/c.rules at line 3'},
    ]


def test_a_failed_self_test_with_no_error_line_still_reports_why():
    errors = suricata.checked(AFTER, Sensor(check_answer=Ran(1, "Segmentation fault")), SENSOR)

    assert [error.message for error in errors] == ["Segmentation fault"]


def test_a_sensor_that_cannot_be_reached_is_not_a_bad_rule_set():
    with pytest.raises(RangeUnavailable):
        suricata.checked(AFTER, Sensor(unreachable=True), SENSOR)


def test_a_write_that_fails_is_reported_as_a_rule_apply_error():
    with pytest.raises(suricata.RuleApplyError, match="could not write"):
        suricata.apply(AFTER, Sensor(write_fails=True), SENSOR)


def test_seeding_writes_the_baseline_and_needs_the_sensor_to_confirm():
    sensor = Sensor()
    suricata.seed(AFTER, sensor, SENSOR)
    assert sensor.files[SENSOR.rules] == AFTER and sensor.checks == []

    with pytest.raises(suricata.RuleApplyError, match="starting rule set"):
        suricata.seed(AFTER, Sensor(reload_answer=Ran(0, BUSY)), SENSOR)


def test_the_offline_test_replays_every_pcap_in_one_container_of_the_pinned_image_outside_the_live_logs():
    alert = {"alert": {"signature_id": 9000911, "signature": "after"},
             "http": {"request_headers": [{"name": "X-Request-ID", "value": "board-sqli-union"}]}}
    replayed = "\n".join([f"{suricata.CASE_HEAD}board-normal-search", f"{suricata.CASE_HEAD}board-sqli-union",
                          eve(alert)])
    node = FakeRunner().answer("docker run", replayed)

    found = suricata.offline_test(AFTER, node, SENSOR, {
        "board-sqli-union": "/var/lib/cr-probes/board/board-sqli-union.pcap",
        "board-normal-search": "/var/lib/cr-probes/board/board-normal-search.pcap",
    }, "test-7")

    assert found == {"board-sqli-union": [{"rule": "9000911", "signature": "after", "marker": "board-sqli-union"}],
                     "board-normal-search": []}
    [laid_out] = node.matching("candidate.rules")[:1]
    assert laid_out.stdin == AFTER and "-r \"/pcaps/$1\"" in laid_out.argv[-1]
    [replay] = node.matching("docker run")
    assert SENSOR.image in replay.text and "--network none" in replay.text
    assert "/var/log/suricata" not in replay.text.replace("-c /etc/suricata/suricata.yaml", ""), (
        "the replay must never write where rsyslog ships the live eve.json from")
    assert ("-v /var/lib/cr-probes/board:/pcaps:ro -v /var/lib/cr-ruletest/test-7:/scratch" in replay.text
            and "sh /scratch/replay.sh board-normal-search board-normal-search.pcap "
                "board-sqli-union board-sqli-union.pcap" in replay.text)
    assert node.sent[-1].argv == ["rm", "-rf", "/var/lib/cr-ruletest/test-7"]
    assert not any(SENSOR.rules in one.text for one in node.sent), "the live rule file is never touched"
    assert not any("reload-rules" in one.text for one in node.sent), "the live sensor is never reloaded"


@pytest.mark.parametrize("scratch", ["/var/log/suricata", "/var/log/suricata/scratch"])
def test_a_scratch_inside_or_above_the_live_logs_is_refused(scratch):
    with pytest.raises(ValueError, match="outside the live log"):
        suricata.offline_test(AFTER, FakeRunner(), config.SensorConfig(name="cr-ids", scratch=scratch),
                              {"c": "/p/c.pcap"}, "run-1")


@pytest.mark.parametrize("run_id, case", [("../etc", "c"), ("ok", "c; rm -rf /")])
def test_run_and_case_names_cannot_escape_the_scratch(run_id, case):
    with pytest.raises(ValueError):
        suricata.offline_test(AFTER, FakeRunner(), SENSOR, {case: "/p/c.pcap"}, run_id)


def test_eve_lines_that_are_not_alerts_are_skipped():
    text = json.dumps({"event_type": "http"}) + "\nnot json\n" + eve({"alert": {"signature_id": 1, "signature": "s"}})

    assert suricata.alerts_in(text) == [{"rule": "1", "signature": "s", "marker": None}]


def test_a_capture_runs_tcpdump_on_the_sensor_interface_in_the_background_and_stops_by_pid():
    node = FakeRunner().answer("tcpdump", "4242\n")

    held = suricata.capture(node, SENSOR, "/var/lib/cr-probes/board/board-sqli-union.pcap", 30)
    suricata.stop_capture(node, held)

    assert held == suricata.Capture(pid=4242, path="/var/lib/cr-probes/board/board-sqli-union.pcap")
    assert "timeout 30 tcpdump -i br0 -Z root -U -s 0 -w /var/lib/cr-probes/board/board-sqli-union.pcap" in node.sent[0].text
    assert "kill -INT 4242" in node.sent[1].text


def test_a_capture_that_did_not_start_says_so():
    with pytest.raises(suricata.RulesUnreadable):
        suricata.capture(FakeRunner().answer("tcpdump", "tcpdump: br0: No such device", 1), SENSOR,
                         "/var/lib/cr-probes/x.pcap", 5)
