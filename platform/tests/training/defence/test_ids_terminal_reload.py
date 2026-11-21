from cr.config import SensorConfig
from sandbox import suricata
from sandbox.runner import Ran
from telemetry.models import Event
from tests.training.defence.conftest import BASELINE, SEARCH_RULE
from training.defence import rules as service

RULES = "/api/rounds/{round}/defence/ids/rules/"
QUIET = 'alert http any any -> any any (msg:"quiet"; config: logging disable, type tx, scope tx; sid:1003; rev:1;)\n'


def test_a_round_without_posture_rules_records_the_sensor_s_live_rules_as_version_one(board_round, cyber_range):
    service.apply_posture(board_round)

    [first] = service.versions(board_round, "ids")
    assert (first.version, first.source, first.files) == (1, "setup", {"local.rules": BASELINE})


def test_a_rule_reload_done_in_the_ids_terminal_is_recorded_as_the_next_ids_version_on_the_next_read(
        as_defender, board_round, defender, cyber_range):
    service.record_live_ids(board_round, service.SETUP)

    cyber_range.sensors["sensor"].edited(BASELINE + SEARCH_RULE, reloaded=True)

    assert service.record_terminal_reload(board_round) is True
    assert service.record_terminal_reload(board_round) is False, "the same running rules are one version"
    stored = service.versions(board_round, "ids")
    assert [(one.version, one.source) for one in stored] == [(1, "setup"), (2, "terminal")]
    assert stored[-1].files == {"local.rules": BASELINE + SEARCH_RULE} and stored[-1].player == defender
    applied = Event.objects.filter(round_id=board_round.pk, kind="rule.applied").order_by("id").last()
    assert applied.body == {"engine": "ids", "version": 2, "source": "terminal"}
    shown = as_defender.get(RULES.format(round=board_round.pk)).json()
    assert (shown["text"], shown["version"], shown["recorded"]) == (BASELINE + SEARCH_RULE, 2, True)


def test_rules_written_in_the_ids_terminal_and_not_reloaded_are_not_running_and_are_not_recorded(
        as_defender, board_round, cyber_range):
    service.record_live_ids(board_round, service.SETUP)

    cyber_range.sensors["sensor"].edited(BASELINE + SEARCH_RULE, reloaded=False)

    assert service.record_terminal_reload(board_round) is False
    shown = as_defender.get(RULES.format(round=board_round.pk)).json()
    assert (shown["text"], shown["version"], shown["recorded"]) == (BASELINE + SEARCH_RULE, 1, False)


def test_a_terminal_reload_whose_rule_turns_off_the_sensor_s_logging_is_put_back_to_the_head_version(
        board_round, cyber_range):
    service.record_live_ids(board_round, service.SETUP)
    sensor = cyber_range.sensors["sensor"]

    sensor.edited(BASELINE + QUIET, reloaded=True)

    assert service.record_terminal_reload(board_round) is False
    assert sensor.rules == BASELINE and sensor.reloaded_at > sensor.written_at
    assert [one.version for one in service.versions(board_round, "ids")] == [1]
    refused = Event.objects.filter(round_id=board_round.pk, kind="rule.refused").get()
    assert (refused.body["engine"], refused.body["version"], refused.player_side) == ("ids", 1, "defence")
    assert "config: logging" in refused.body["message"]


def test_rules_reloaded_in_the_ids_terminal_and_rewritten_before_the_read_are_put_back_to_the_head_version(
        board_round, cyber_range):
    service.record_live_ids(board_round, service.SETUP)
    sensor = cyber_range.sensors["sensor"]

    sensor.edited(BASELINE + QUIET, reloaded=True)
    sensor.edited(BASELINE + SEARCH_RULE, reloaded=False)

    assert service.record_terminal_reload(board_round) is False
    assert sensor.rules == BASELINE and sensor.reloaded_at > sensor.written_at
    assert [one.version for one in service.versions(board_round, "ids")] == [1]
    refused = Event.objects.filter(round_id=board_round.pk, kind="rule.refused").get()
    assert refused.body["message"] == service.RUNNING_UNKNOWN
    sensor.edited(BASELINE + SEARCH_RULE, reloaded=False)
    assert service.record_terminal_reload(board_round) is False
    assert sensor.rules == BASELINE + SEARCH_RULE, "an edit after a reload the platform knows is left alone"


def test_only_an_active_rule_with_config_logging_turns_off_the_sensor_s_logging():
    found = suricata.refusals("# " + QUIET + SEARCH_RULE + 'alert http any any -> any any (msg:"config: logging"; sid:7;)\n'
                              + QUIET)

    assert [one.line for one in found] == [4]


def test_a_rule_continued_over_lines_with_a_backslash_is_one_rule_and_a_comment_does_not_continue():
    continued = 'alert http any any -> any any (msg:"q"; \\\n' + QUIET.split("; ", 1)[1]
    found = suricata.refusals("# a comment \\\n" + SEARCH_RULE + continued + "#" + continued)

    assert [one.line for one in found] == [3]


def test_a_last_reload_older_than_the_rule_file_or_an_unreadable_reply_is_not_a_reload():
    config = SensorConfig(name="cr-ids")

    def replying(reloaded: str):
        reply = f'1800000200.0\n{{"message": [{{"id": 0, "last_reload": "{reloaded}"}}], "return": "OK"}}'
        return lambda argv, stdin=None, timeout=60.0: Ran(0, reply)

    assert suricata.reloaded_since_written(replying("2027-01-15T08:04:00.000000+0000"), config) is True
    assert suricata.reloaded_since_written(replying("2027-01-15T08:03:00.000000+0000"), config) is False
    assert suricata.reloaded_since_written(lambda *given, **named: Ran(0, "1800000200.0\nno socket"), config) is False
