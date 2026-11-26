import pytest

from tests.training.round.conftest import pvp
from training.round import allocation as allocations
from training.round import lifecycle as service
from users import vpn
from users.models import VpnProfile


def ends_by_operator(found):
    service.end_round(found, "ended_by_operator")


def closes_the_allocation(found):
    allocations.close_allocation(found.allocation)


@pytest.mark.parametrize("ending", [ends_by_operator, closes_the_allocation])
def test_the_profile_is_attached_only_to_the_human_attack_seat_at_start_and_detached_when_the_round_ends(
        cloud, allocation, problem, learner, other, monkeypatch, tmp_path, ending):
    monkeypatch.setenv("CR_VPN_DIR", str(tmp_path / "vpn"))
    attacker, defender = (vpn.issue(user, "192.0.2.10").profile for user in (other, learner))
    found = pvp(allocation, problem, other, learner)
    box = cloud.in_slot(allocation.slot).box

    assert box.matching("set-peer") == []
    service.start_round(found)

    attached = box.matching("set-peer")
    assert [one.argv[2:4] for one in attached] == [[attacker.public_key, f"{attacker.address}/32"]]
    assert attached[0].stdin == VpnProfile.objects.get(pk=attacker.pk).server_private_key
    assert VpnProfile.objects.get(pk=attacker.pk).attached_round == found.pk
    assert VpnProfile.objects.get(pk=defender.pk).attached_round is None

    ending(found)

    assert box.matching("set-peer")[-1].argv == ["sudo", "/usr/local/sbin/set-peer"]
    assert VpnProfile.objects.get(pk=attacker.pk).attached_round is None
    assert len(box.matching("set-peer")) == 2


def test_an_attached_profile_lists_only_its_round_s_wargame_target(cloud, allocation, problem, learner, other,
                                                                   monkeypatch, tmp_path):
    monkeypatch.setenv("CR_VPN_DIR", str(tmp_path / "vpn"))
    attacker = vpn.issue(other, "192.0.2.10").profile
    service.start_round(pvp(allocation, problem, other, learner))

    assert vpn.targets(VpnProfile.objects.get(pk=attacker.pk)) == (("board", "http://121.134.88.42/"),)
