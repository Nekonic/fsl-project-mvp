import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

import jump
from api.models import Session
from range.ports import Ran, RangeUnavailable
from tests.conftest import ApiClient

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]
KALI = "10.20.0.5"
PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


class OneKali:
    def __init__(self, address=KALI, answer=Ran(0, "")):
        self.kali, self.answer, self.sent = address, answer, []

    def address(self, role):
        return self.kali if role == "attacker" else ""

    def runner(self, role, segment_id=""):
        def run(argv, stdin=None, timeout=60.0):
            if role != "attacker":
                raise RangeUnavailable(f"this test stands up no {role}")
            self.sent.append((argv, stdin))
            return self.answer
        return run


def learner(name, staff=False):
    user = get_user_model().objects.create_user(name, password="range-practice-42", is_staff=staff)
    client = ApiClient()
    client.force_login(user)
    return client, user


@pytest.fixture
def kali():
    standing = OneKali()
    with patch("api.views.substrate", lambda: standing):
        yield standing


@pytest.fixture
def owned():
    client, user = learner("learner1")
    return client, Session.objects.create(scenario="board", baseline=[], owner=user)


def test_a_key_may_forward_only_to_its_session_s_kali_ssh_port_and_nothing_else():
    line = jump.authorized_keys_line(PUBLIC, KALI, 7)

    assert line == f'restrict,port-forwarding,permitopen="{KALI}:22" {PUBLIC} cr-session-7'


@pytest.mark.parametrize("address", ['10.0.0.1:22",permitopen="*:*', "", "kali", "fe80::1"])
def test_an_address_that_is_not_one_ipv4_address_never_reaches_the_keys_file(address):
    with pytest.raises(RangeUnavailable):
        jump.authorized_keys_line(PUBLIC, address, 7)


def test_a_public_key_that_is_not_one_ed25519_key_never_reaches_the_keys_file():
    with pytest.raises(ValueError):
        jump.authorized_keys_line(f'{PUBLIC} x\nrestrict,permitopen="*:*" {PUBLIC}', KALI, 7)


def test_the_jump_accepts_only_keys_from_the_platform_and_forwards_without_a_shell():
    config = dict(line.split(" ", 1) for line in jump.sshd_config(2222, "/data/jump").splitlines())

    assert config["Port"] == "2222"
    assert config["AuthorizedKeysFile"] == "none"
    assert config["AuthorizedKeysCommand"] == "/usr/bin/cat /data/jump/authorized_keys"
    assert config["AllowUsers"] == jump.JUMP_USER
    assert (config["AuthenticationMethods"], config["PasswordAuthentication"],
            config["KbdInteractiveAuthentication"]) == ("publickey", "no", "no")
    assert (config["AllowTcpForwarding"], config["PermitTTY"], config["ForceCommand"]) == (
        "local", "no", "/usr/sbin/nologin")
    assert all(config[name] == "no" for name in (
        "AllowAgentForwarding", "AllowStreamLocalForwarding", "X11Forwarding", "PermitTunnel", "GatewayPorts"))


@pytest.mark.skipif(not Path("/usr/sbin/sshd").exists(), reason="no sshd here to read the config")
def test_sshd_reads_the_rendered_config(tmp_path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "ssh_host_ed25519_key")],
                   check=True)
    (tmp_path / "sshd_config").write_text(jump.sshd_config(2222, str(tmp_path)))

    read = subprocess.run(["/usr/sbin/sshd", "-t", "-f", str(tmp_path / "sshd_config")],
                          capture_output=True, text=True)

    assert "Bad configuration option" not in read.stderr and "unsupported option" not in read.stderr, read.stderr


def test_a_second_key_for_a_session_replaces_its_first_and_leaves_other_sessions_alone():
    first = jump.issue(7, KALI)
    other = jump.issue(8, "10.20.1.5")
    second = jump.issue(7, KALI)

    assert first.grant.public_key != second.grant.public_key
    assert jump.keys_file().read_text().splitlines() == [other.grant.line, second.grant.line]
    assert jump.revoke(7) == second.grant
    assert jump.grants() == [other.grant]
    assert jump.revoke(7) is None


def test_the_owner_gets_a_key_once_and_kali_gets_its_public_half(kali, owned):
    client, session = owned

    issued = client.post_json(f"/api/sessions/{session.pk}/ssh/")
    read = client.get(f"/api/sessions/{session.pk}/ssh/").json()

    assert issued.status_code == 201, issued.content
    body = issued.json()
    assert body["private_key"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert "private_key" not in read and read["issued"] is True
    assert read["fingerprint"] == body["fingerprint"] == jump.granted(session.pk).fingerprint
    assert body["host"] == "board-kali" and body["key_file"] == f"~/.ssh/cr-session-{session.pk}"
    assert "Host board-kali\n" in body["config"] and "    ProxyJump board-kali-jump\n" in body["config"]
    assert f"    HostName {KALI}\n" in body["config"] and "    HostName testserver\n" in body["config"]
    [(argv, stdin)] = kali.sent
    assert argv[:2] == ["sudo", "sh"] and "authorized_keys" in argv[-1]
    assert stdin == f"{jump.granted(session.pk).public_key} cr-session-{session.pk}\n"


def test_another_learner_and_an_admin_who_did_not_open_the_session_get_no_key(kali, owned):
    _, session = owned
    other, _ = learner("learner2")
    admin, _ = learner("admin2", staff=True)

    assert other.post_json(f"/api/sessions/{session.pk}/ssh/").status_code == 404
    assert other.get(f"/api/sessions/{session.pk}/ssh/").status_code == 404
    assert admin.post_json(f"/api/sessions/{session.pk}/ssh/").status_code == 403
    assert jump.grants() == [] and kali.sent == []


def test_closing_the_session_revokes_its_key_on_the_jump_and_on_kali(kali, owned):
    client, session = owned
    client.post_json(f"/api/sessions/{session.pk}/ssh/")

    assert client.post_json(f"/api/sessions/{session.pk}/close/").status_code == 200

    assert jump.granted(session.pk) is None
    assert client.get(f"/api/sessions/{session.pk}/ssh/").json() == {"issued": False}
    dropped = kali.sent[-1]
    assert f"' cr-session-{session.pk}$'" in dropped[0][-1] and "cat >>" not in dropped[0][-1]
    assert client.post_json(f"/api/sessions/{session.pk}/ssh/").status_code == 409


def test_a_kali_that_refuses_the_key_leaves_no_key_on_the_jump(owned):
    client, session = owned
    refusing = OneKali(answer=Ran(1, "no such user kali"))

    with patch("api.views.substrate", lambda: refusing):
        answer = client.post_json(f"/api/sessions/{session.pk}/ssh/")

    assert answer.status_code == 503 and "no such user kali" in answer.json()["detail"]
    assert jump.grants() == []


def test_a_slot_with_no_kali_address_issues_no_key(owned):
    client, session = owned

    with patch("api.views.substrate", lambda: OneKali(address="")):
        assert client.post_json(f"/api/sessions/{session.pk}/ssh/").status_code == 503
    assert jump.grants() == []


def test_the_jump_runs_inside_the_platform_so_the_control_plane_stays_four_services():
    loader = SourceFileLoader("measure", str(ROOT / "bin/measure"))
    measure = importlib.util.module_from_spec(importlib.util.spec_from_loader("measure", loader))
    loader.exec_module(measure)
    entrypoint = (ROOT / "platform/entrypoint.sh").read_text()

    assert measure.services() == 4
    assert "/usr/sbin/sshd -D -e -f /run/sshd-jump.conf" in entrypoint and "python jump.py" in entrypoint
