import re

import pytest

from users.models import VpnProfile


@pytest.fixture(autouse=True)
def tunnels(monkeypatch, tmp_path):
    monkeypatch.setenv("CR_VPN_DIR", str(tmp_path / "vpn"))


def private_key(text: str) -> str:
    return re.search(r"^PrivateKey = (\S+)$", text, re.M)[1]


def test_an_issue_returns_the_private_key_once_stores_only_public_keys_and_a_reissue_replaces_it(as_learner, learner):
    first = as_learner.post("/api/vpn/profile/")
    assert first.status_code == 201, first.content
    key = private_key(first.json()["profile"])
    stored = VpnProfile.objects.get(user=learner)
    read = as_learner.get("/api/vpn/profile/").json()

    assert key not in {stored.public_key, stored.server_public_key, stored.server_private_key}
    assert "profile" not in read and key not in str(read)
    assert read["public_key"] == stored.public_key and read["attached_round"] is None

    second = as_learner.post("/api/vpn/profile/").json()
    again = VpnProfile.objects.get(user=learner)

    assert private_key(second["profile"]) != key
    assert (again.public_key, again.server_public_key) != (stored.public_key, stored.server_public_key)
    assert (again.pk, again.port, again.address) == (stored.pk, stored.port, stored.address)
    assert VpnProfile.objects.count() == 1


def test_the_profile_gives_each_wargames_target_as_an_address_url_and_no_hosts_line(as_learner):
    as_learner.post("/api/vpn/profile/")
    read = as_learner.get("/api/vpn/profile/").json()

    assert "hosts" not in read
    assert read["targets"] == [{"wargame": "board", "url": "http://121.134.88.42/"},
                               {"wargame": "corp", "url": "http://121.134.88.42/"}]
