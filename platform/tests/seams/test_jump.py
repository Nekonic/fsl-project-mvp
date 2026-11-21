import subprocess
from pathlib import Path

import pytest

from cr.config import JumpConfig
from sandbox import access as jump
from sandbox.runner import Ran, RangeUnavailable
from testing.fakes import FakeRunner

KALI = "10.20.0.5"
PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


@pytest.fixture
def config(tmp_path):
    return JumpConfig(directory=str(tmp_path / "jump"), port=2222, host="range.example")


def test_a_key_may_forward_only_to_its_player_s_box_ssh_port_and_nothing_else():
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


def test_a_second_key_for_a_player_replaces_its_first_and_leaves_other_players_alone(config):
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


def test_a_player_s_grant_on_a_second_box_stands_beside_the_first_and_is_revoked_apart(config):
    waf = jump.issue(7, KALI, config)
    sensor = jump.issue(7, "10.20.1.9", config, "ids")

    assert sensor.grant.line.endswith(" cr-session-7-ids")
    assert jump.grants(config) == [waf.grant, sensor.grant]
    assert jump.granted(7, config) == waf.grant and jump.granted(7, config, "ids") == sensor.grant
    assert jump.revoke(7, config, "ids") == sensor.grant
    assert jump.grants(config) == [waf.grant]


def test_no_keys_file_is_no_grants(config):
    assert jump.grants(config) == []


def test_box_keys_are_named_and_a_bad_name_is_refused():
    box = FakeRunner()

    jump.authorize_key(box, "ssh-ed25519 AAAA", "cr-session-4", "analyst")

    assert box.sent[0].stdin == "ssh-ed25519 AAAA cr-session-4\n"
    assert "getent passwd analyst" in box.sent[0].argv[-1]
    with pytest.raises(ValueError):
        jump.drop_key(box, "x; rm -rf /", "analyst")


def test_a_box_that_refuses_the_key_is_range_unavailable():
    with pytest.raises(RangeUnavailable):
        jump.authorize_key(FakeRunner().answer("authorized_keys", "no such user", 1), "ssh-ed25519 AAAA",
                           "cr-session-4", "analyst")


def test_access_grants_the_jump_and_the_box_account_and_closing_takes_both_back(config):
    box = FakeRunner()

    access = jump.open_access(3, KALI, box, "analyst", config)

    assert (access.host, access.port, access.user) == ("range.example", 2222, jump.JUMP_USER)
    assert (access.target_host, access.target_user) == (KALI, "analyst")
    assert "PRIVATE KEY" in access.private_key
    assert jump.granted(3, config).address == KALI
    assert jump.close_access(3, lambda: box, "analyst", config) is not None
    assert jump.granted(3, config) is None
    assert len(box.matching("authorized_keys")) == 2
    assert jump.close_access(3, lambda: box, "analyst", config) is None


FAKE_TOOLS = {
    "id": 'grep -qx "$2" "$STATE/accounts"',
    "crontab": 'echo "$*" >> "$STATE/crontab"',
    "atq": 'cat "$STATE/atq"',
    "atrm": 'echo "$*" >> "$STATE/atrm"',
    "loginctl": 'echo "$*" >> "$STATE/loginctl"',
    "pkill": ('grep -q "^$3 " "$STATE/processes" || exit 1\n'
              'grep -v "^$3 " "$STATE/processes" > "$STATE/left" || true\n'
              'cat "$STATE/respawn" >> "$STATE/left"; : > "$STATE/respawn"\n'
              'mv "$STATE/left" "$STATE/processes"; echo "$*" >> "$STATE/pkill"'),
    "pgrep": 'grep -q "^$2 " "$STATE/processes"',
    "sleep": ":",
}


@pytest.fixture
def waf_box(tmp_path):
    tools, state = tmp_path / "bin", tmp_path / "state"
    tools.mkdir()
    state.mkdir()
    for name, body in FAKE_TOOLS.items():
        tool = tools / name
        tool.write_text(f"#!/bin/sh\n{body}\n")
        tool.chmod(0o755)
    (state / "accounts").write_text("analyst\nkali\n")
    (state / "atq").write_text("7\tThu Nov 20 10:00:00 2026 a analyst\n8\tThu Nov 20 10:05:00 2026 a kali\n"
                               "9\tThu Nov 20 11:00:00 2026 b analyst\n")
    (state / "processes").write_text("analyst 4100 nohup tail -f\nanalyst 4101 sleep 9999\nkali 5100 bash\n")
    (state / "respawn").write_text("")

    def box(argv, stdin=None, timeout=60.0):
        assert argv[:3] == ["sudo", "sh", "-c"]
        done = subprocess.run(["sh", "-c", argv[3]], input=stdin, capture_output=True, text=True, timeout=timeout,
                              env={"PATH": f"{tools}:/usr/bin:/bin", "STATE": str(state)})
        return Ran(exit_code=done.returncode, output=done.stdout + done.stderr)

    return box, state, tools


def left(state, name):
    found = state / name
    return found.read_text() if found.exists() else ""


def test_ending_the_account_kills_what_it_left_and_clears_its_cron_at_and_user_manager(waf_box):
    box, state, _ = waf_box
    (state / "respawn").write_text("analyst 4200 forked child\n")

    jump.end_account(box, "analyst")

    assert left(state, "processes") == "kali 5100 bash\n"
    assert left(state, "crontab") == "-r -u analyst\n"
    assert left(state, "atrm").split() == ["7", "9"]
    assert left(state, "loginctl").splitlines() == ["disable-linger analyst", "terminate-user analyst"]
    assert left(state, "pkill").splitlines() == ["-KILL -u analyst", "-KILL -u analyst"]


def test_an_account_with_nothing_left_ends_quietly(waf_box):
    box, state, _ = waf_box
    (state / "processes").write_text("kali 5100 bash\n")
    (state / "atq").write_text("")

    jump.end_account(box, "analyst")

    assert left(state, "atrm") == "" and left(state, "pkill") == ""
    assert left(state, "processes") == "kali 5100 bash\n"


def test_a_process_that_outlives_every_kill_is_range_unavailable(waf_box):
    box, state, tools = waf_box
    (tools / "pkill").write_text('#!/bin/sh\necho "$*" >> "$STATE/pkill"\n')

    with pytest.raises(RangeUnavailable, match="end what analyst left running"):
        jump.end_account(box, "analyst")
    assert len(left(state, "pkill").splitlines()) == 3


def test_a_box_without_the_account_has_nothing_to_end(waf_box):
    box, state, _ = waf_box

    jump.end_account(box, "nobody")

    assert left(state, "crontab") == "" and left(state, "pkill") == ""


def test_an_account_name_reaches_the_box_quoted():
    assert "'a b'" in jump.account_ended("a b")
