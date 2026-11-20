import pytest

from attack import service
from cr import errors
from match import service as match
from range import jump
from tests.attack.conftest import codes, url
from testing.fakerange import KALI_MANAGEMENT

pytestmark = pytest.mark.django_db


def test_the_terminal_grant_names_a_seat_ttyd_path_and_a_jump_key_to_kali(as_attacker, attacker, cloud):
    answer = as_attacker.get(url(attacker.round, "terminal/"))

    body = answer.json()
    assert answer.status_code == 200
    assert body["ws_url"] == f"/vm-terminal/attack/{attacker.round_id}/"
    ssh = body["ssh"]
    assert (ssh["host"], ssh["port"], ssh["user"]) == ("jump.range.test", 2222, "jump")
    assert (ssh["target_host"], ssh["target_user"]) == (KALI_MANAGEMENT, "kali")
    assert "PRIVATE KEY" in ssh["private_key"] and ssh["expires_at"]
    grant = jump.granted(attacker.pk, service.configured().jump)
    assert grant is not None and grant.address == KALI_MANAGEMENT
    [authorized] = cloud.box.matching("authorized_keys")
    assert authorized.stdin == f"{grant.public_key} {grant.name}\n"


def test_the_grant_is_revoked_when_the_round_closes(as_attacker, attacker, cloud):
    as_attacker.get(url(attacker.round, "terminal/"))

    service.close(attacker.round)

    assert jump.granted(attacker.pk, service.configured().jump) is None
    assert len(cloud.box.matching("authorized_keys")) == 2


def test_no_terminal_is_granted_after_the_end(as_attacker, attacker):
    attacker.round.phase = "ended"
    attacker.round.save(update_fields=["phase"])

    answer = as_attacker.get(url(attacker.round, "terminal/"))

    assert codes(answer) == ["round_closed"]


def test_the_kali_shell_opens_as_the_learner_account_on_the_address_the_seat_s_grant_names(
        as_attacker, attacker, cloud, monkeypatch):
    monkeypatch.setattr(match, "slot_range", lambda number: cloud)
    as_attacker.get(url(attacker.round, "terminal/"))

    shell = match.terminal_shell(attacker.round_id, "attack")

    assert (shell.address, shell.alias, shell.account) == (KALI_MANAGEMENT, KALI_MANAGEMENT, "kali")


def test_no_kali_shell_opens_for_a_seat_that_was_never_granted_one(attacker, cloud, monkeypatch):
    monkeypatch.setattr(match, "slot_range", lambda number: cloud)

    with pytest.raises(errors.NotSeated):
        match.terminal_shell(attacker.round_id, "attack")


def test_no_kali_shell_opens_once_the_round_ended(as_attacker, attacker, cloud, monkeypatch):
    monkeypatch.setattr(match, "slot_range", lambda number: cloud)
    as_attacker.get(url(attacker.round, "terminal/"))
    attacker.round.phase = "ended"
    attacker.round.save(update_fields=["phase"])

    with pytest.raises(errors.Conflict) as refused:
        match.terminal_shell(attacker.round_id, "attack")
    assert refused.value.code == "round_closed"


def test_an_attack_seat_opens_no_shell_on_the_defence_side(as_attacker, attacker, cloud, monkeypatch):
    monkeypatch.setattr(match, "slot_range", lambda number: cloud)
    as_attacker.get(url(attacker.round, "terminal/"))

    with pytest.raises(errors.NotSeated):
        match.terminal_shell(attacker.round_id, "defence")
