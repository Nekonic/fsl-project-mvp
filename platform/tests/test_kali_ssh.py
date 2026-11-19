import subprocess
from pathlib import Path

import pytest

import jump
from range.ports import Ran, RangeUnavailable

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


