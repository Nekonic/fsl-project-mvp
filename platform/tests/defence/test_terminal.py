from defence import service
from match import service as match
from range import jump
from testing.fakerange import WAF_MANAGEMENT

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


def test_no_terminal_is_granted_after_the_end(as_defender, board_round, defender):
    board_round.phase = "ended"
    board_round.save(update_fields=["phase"])

    answer = as_defender.get(BASE.format(round=board_round.pk))

    assert answer.status_code == 409
    assert answer.json()["errors"][0]["code"] == "round_closed"
