import subprocess
from pathlib import Path

import pytest

from attack import jump
from cr.config import JumpConfig
from range.runner import RangeUnavailable

KALI = "10.20.0.5"
PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


@pytest.fixture
def config(tmp_path):
    return JumpConfig(directory=str(tmp_path / "jump"), port=2222, host="range.example")


def test_a_key_may_forward_only_to_its_seat_s_kali_ssh_port_and_nothing_else():
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
    sshd = dict(line.split(" ", 1) for line in jump.sshd_config(JumpConfig(directory="/data/jump", port=2222)).splitlines())

    assert sshd["Port"] == "2222"
    assert sshd["AuthorizedKeysFile"] == "none"
    assert sshd["AuthorizedKeysCommand"] == "/usr/bin/cat /data/jump/authorized_keys"
    assert sshd["AllowUsers"] == jump.JUMP_USER
    assert (sshd["AuthenticationMethods"], sshd["PasswordAuthentication"]) == ("publickey", "no")
    assert (sshd["AllowTcpForwarding"], sshd["PermitTTY"], sshd["ForceCommand"]) == ("local", "no", "/usr/sbin/nologin")


@pytest.mark.skipif(not Path("/usr/sbin/sshd").exists(), reason="no sshd here to read the config")
def test_sshd_reads_the_rendered_config(tmp_path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "ssh_host_ed25519_key")],
                   check=True)
    (tmp_path / "sshd_config").write_text(jump.sshd_config(JumpConfig(directory=str(tmp_path), port=2222)))

    read = subprocess.run(["/usr/sbin/sshd", "-t", "-f", str(tmp_path / "sshd_config")], capture_output=True, text=True)

    assert "Bad configuration option" not in read.stderr and "unsupported option" not in read.stderr, read.stderr


def test_a_second_key_for_a_seat_replaces_its_first_and_leaves_other_seats_alone(config):
    first = jump.issue(7, KALI, config)
    other = jump.issue(8, "10.20.1.5", config)
    second = jump.issue(7, KALI, config)

    assert first.grant.public_key != second.grant.public_key
    assert jump.keys_file(config).read_text().splitlines() == [other.grant.line, second.grant.line]
    assert oct(jump.keys_file(config).stat().st_mode & 0o777) == "0o600"
    assert jump.granted(8, config) == other.grant
    assert jump.revoke(7, config) == second.grant
    assert jump.grants(config) == [other.grant]
    assert jump.revoke(7, config) is None


def test_no_keys_file_is_no_grants(config):
    assert jump.grants(config) == []


def test_the_ssh_config_a_seat_is_shown_jumps_through_the_configured_host_and_port(config):
    issued = jump.issue(3, KALI, config)

    shown = jump.shown(issued.grant, "board", config)

    assert shown["host"] == "board-kali"
    assert "HostName range.example\n    Port 2222\n" in shown["config"]
    assert f"HostName {KALI}" in shown["config"] and "ProxyJump board-kali-jump" in shown["config"]
    assert shown["fingerprint"].startswith("SHA256:")
    assert "PRIVATE KEY" in issued.private_key
