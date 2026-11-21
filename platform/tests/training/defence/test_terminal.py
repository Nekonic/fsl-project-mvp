import io

import pytest
from django.core.management import CommandError, call_command

from cr import config as service
from sandbox import access as jump
from testing.fakerange import WAF_MANAGEMENT
from training.round import lifecycle as match

BASE = "/api/rounds/{round}/defence/terminal/"


def test_the_terminal_is_the_waf_shell_keyed_to_the_round_with_a_jump_key_to_the_analyst_account(
        as_defender, board_round, defender, cyber_range):
    answer = as_defender.get(BASE.format(round=board_round.pk))

    body = answer.json()
    assert answer.status_code == 200
    assert body["ws_url"] == f"/vm-terminal/defence/{board_round.pk}/"
    ssh = body["ssh"]
    assert (ssh["host"], ssh["port"], ssh["user"]) == ("jump.range.test", 2222, jump.JUMP_USER)
    assert (ssh["target_host"], ssh["target_user"]) == (WAF_MANAGEMENT, "analyst")
    assert "PRIVATE KEY" in ssh["private_key"] and ssh["expires_at"]
    grant = jump.granted(defender.pk, service.configured().jump)
    assert grant is not None and grant.address == WAF_MANAGEMENT
    [authorized] = [one for one in cyber_range.gateway.sent if "authorized_keys" in one.text]
    assert authorized.stdin == f"{grant.public_key} {grant.name}\n"
    assert "getent passwd analyst" in authorized.text


def test_the_analyst_grant_is_revoked_when_the_round_ends(as_defender, board_round, defender, cyber_range):
    as_defender.get(BASE.format(round=board_round.pk))

    match.end_round(board_round, "ended_by_operator")

    assert jump.granted(defender.pk, service.configured().jump) is None
    assert len([one for one in cyber_range.gateway.sent if "authorized_keys" in one.text]) == 2


def test_the_round_end_kills_what_analyst_left_running_on_the_waf(as_defender, board_round, defender, cyber_range):
    as_defender.get(BASE.format(round=board_round.pk))

    match.end_round(board_round, "ended_by_operator")

    sent = cyber_range.gateway.sent
    [ended] = [one for one in sent if "pkill -KILL -u analyst" in one.text]
    assert ended.argv[:3] == ["sudo", "sh", "-c"]
    assert "crontab -r -u analyst" in ended.text and "terminate-user analyst" in ended.text
    dropped = [one for one in sent if "authorized_keys" in one.text][-1]
    assert sent.index(ended) > sent.index(dropped), "the key goes first so no new shell opens"


def test_a_round_whose_defender_never_opened_the_terminal_leaves_the_waf_alone(board_round, defender, cyber_range):
    match.end_round(board_round, "ended_by_operator")

    assert not [one for one in cyber_range.gateway.sent if "pkill" in one.text]


def test_no_terminal_is_granted_after_the_end(as_defender, board_round, defender):
    board_round.phase = "ended"
    board_round.save(update_fields=["phase"])

    answer = as_defender.get(BASE.format(round=board_round.pk))

    assert answer.status_code == 409
    assert answer.json()["errors"][0]["code"] == "round_closed"


def test_the_waf_shell_opens_as_analyst_not_root_on_the_address_the_seat_s_grant_names(
        as_defender, board_round, defender):
    as_defender.get(BASE.format(round=board_round.pk))

    shell = match.terminal_shell(board_round.pk, "defence")

    assert (shell.address, shell.account) == (WAF_MANAGEMENT, "analyst")


def test_the_terminal_lookup_prints_the_one_line_the_terminal_script_splits(as_defender, board_round, defender):
    as_defender.get(BASE.format(round=board_round.pk))
    printed = io.StringIO()

    call_command("terminal_shell", "defence", str(board_round.pk), stdout=printed)

    assert printed.getvalue().split() == [WAF_MANAGEMENT, WAF_MANAGEMENT, "analyst"]


def test_the_terminal_lookup_refuses_a_seat_without_a_grant(board_round, defender):
    with pytest.raises(CommandError, match="not_seated"):
        call_command("terminal_shell", "defence", str(board_round.pk))


def test_the_terminal_lookup_refuses_once_the_round_ended_and_the_grant_went(as_defender, board_round, defender):
    as_defender.get(BASE.format(round=board_round.pk))
    match.end_round(board_round, "ended_by_operator")

    with pytest.raises(CommandError, match="round_closed"):
        call_command("terminal_shell", "defence", str(board_round.pk))
