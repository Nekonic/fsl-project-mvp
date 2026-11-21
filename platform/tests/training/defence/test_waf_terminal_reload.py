from datetime import timedelta

from django.utils import timezone

from sandbox.runner import Ran
from telemetry.models import Event
from tests.training.defence.conftest import BASELINE, SEARCH_RULE
from training.defence import rules as service
from training.models import Round

BASE = "/api/rounds/{round}/defence/"
HTTP = "/etc/nginx/defence/http.conf"


def url(found, tail):
    return BASE.format(round=found.pk) + tail


def test_a_reload_done_in_the_terminal_is_recorded_as_the_next_version_on_the_next_read(as_defender, board_round,
                                                                                         defender, cyber_range):
    service.record_live_waf(board_round, service.SETUP)

    cyber_range.gateway.edited(HTTP, "deny 203.0.113.9;\n", reloaded=True)

    assert service.record_terminal_reload(board_round) is True
    assert service.record_terminal_reload(board_round) is False, "the same running files are one version"
    stored = service.versions(board_round, "waf")
    assert [(one.version, one.source) for one in stored] == [(1, "setup"), (2, "terminal")]
    assert stored[-1].files[HTTP] == "deny 203.0.113.9;\n" and stored[-1].player == defender
    applied = Event.objects.filter(round_id=board_round.pk, kind="rule.applied").order_by("id").last()
    assert (applied.body, applied.player_side) == ({"engine": "waf", "version": 2, "source": "terminal"}, "defence")
    shown = as_defender.get(url(board_round, "waf/")).json()
    assert shown["version"] == 2 and shown["recorded"] is True


def test_a_terminal_reload_that_turns_off_the_platform_s_measurement_is_put_back_to_the_head_version(
        board_round, cyber_range):
    service.record_live_waf(board_round, service.SETUP)
    head = cyber_range.gateway.files[HTTP]

    cyber_range.gateway.edited(HTTP, "set_real_ip_from 127.0.0.1;\nreal_ip_header X-Forwarded-For;\n", reloaded=True)

    assert service.record_terminal_reload(board_round) is False
    assert cyber_range.gateway.files[HTTP] == head
    assert [one.version for one in service.versions(board_round, "waf")] == [1]
    refused = Event.objects.filter(round_id=board_round.pk, kind="rule.refused").get()
    assert (refused.body["engine"], refused.body["version"], refused.player_side) == ("waf", 1, "defence")
    assert "set_real_ip_from" in refused.body["message"]


def test_files_edited_but_not_reloaded_are_not_running_and_are_not_recorded(as_defender, board_round, cyber_range):
    service.record_live_waf(board_round, service.SETUP)

    cyber_range.gateway.edited(HTTP, "deny 203.0.113.9;\n", reloaded=False)

    assert service.record_terminal_reload(board_round) is False
    assert [one.version for one in service.versions(board_round, "waf")] == [1]
    shown = as_defender.get(url(board_round, "waf/")).json()
    assert {one["path"]: one["text"] for one in shown["files"]}[HTTP] == "deny 203.0.113.9;\n"
    assert shown["recorded"] is False


def test_a_round_with_no_recorded_version_has_nothing_to_compare_a_reload_with(board_round, cyber_range):
    cyber_range.gateway.edited(HTTP, "deny all;\n", reloaded=True)

    assert service.record_terminal_reload(board_round) is False


def test_a_waf_the_platform_cannot_read_records_nothing(board_round, cyber_range):
    service.record_live_waf(board_round, service.SETUP)

    def unreachable(argv, stdin=None, timeout=60.0):
        return Ran(255, "ssh: connect to host refused")

    cyber_range.gateway = unreachable

    assert service.record_terminal_reload(board_round) is False
    assert [one.version for one in service.versions(board_round, "waf")] == [1]
