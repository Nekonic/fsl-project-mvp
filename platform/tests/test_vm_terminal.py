import os
import pathlib
import shlex
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "vm-terminal.sh"
KALI_SHELL = "10.31.0.180 cr-srv-1 kali"
WAF_SHELL = "10.31.0.181 cr-srv-2 analyst"


def fakes(tmp_path, **bodies):
    for name, body in {"sleep": '[ "$1" != 3 ] || exit 0; exec /bin/sleep "$@"', **bodies}.items():
        (tmp_path / name).write_text(f"#!/bin/sh\n{body}\n")
        (tmp_path / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TERMINAL_LOG": str(tmp_path / "terminal.log")}
    env.pop("TERMINAL_KEEP", None)
    return env


def opened(tmp_path, *given, lookup=KALI_SHELL, **bodies):
    asked, seen = tmp_path / "python-argv", tmp_path / "ssh-argv"
    env = fakes(tmp_path, python=f'printf "%s\\n" "$@" > {asked}; echo "{lookup}"',
                ssh=f'printf "%s\\n" "$@" > {seen}', **bodies)
    ran = subprocess.run(["sh", str(SCRIPT), *given], capture_output=True, text=True, env=env)
    return ran, asked, seen


def remote_command(seen):
    return seen.read_text().split("\n")[-2]


def test_the_attack_player_gets_a_login_shell_as_the_kali_learner_account_on_the_address_its_grant_names(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-kali", "attack", "3")

    assert asked.read_text().split("\n")[1:4] == ["terminal_shell", "attack", "3"]
    argv = seen.read_text().split("\n")
    assert "ubuntu@10.31.0.180" in argv and "HostKeyAlias=cr-srv-1" in argv
    assert remote_command(seen).startswith("sudo -i -u kali ") and remote_command(seen).endswith(" bash -l")


def test_the_defence_player_gets_the_waf_as_analyst_and_never_as_root(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-waf", "defence", "3", lookup=WAF_SHELL)

    assert asked.read_text().split("\n")[1:4] == ["terminal_shell", "defence", "3"]
    assert "ubuntu@10.31.0.181" in seen.read_text().split("\n")
    shell = remote_command(seen)
    assert shell.startswith("sudo -i -u analyst ") and shell.endswith(" bash -l")
    assert not shell.startswith("sudo -i env"), "a plain sudo -i is a root shell on the WAF"


def test_the_defence_player_s_ids_terminal_looks_up_the_sensor_grant_and_opens_as_analyst(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-infra", "ids", "3", lookup="10.31.0.182 cr-srv-3 analyst")

    assert asked.read_text().split("\n")[1:4] == ["terminal_shell", "ids", "3"]
    assert "ubuntu@10.31.0.182" in seen.read_text().split("\n")
    assert remote_command(seen).startswith("sudo -i -u analyst ")


def test_the_lookup_is_the_platform_s_manage_py_beside_the_script(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-kali", "attack", "3")

    assert asked.read_text().split("\n")[0] == str(SCRIPT.parent / "manage.py")


def test_a_refused_lookup_ends_the_shell_without_ssh_and_tells_the_learner_one_plain_line(tmp_path):
    reached = tmp_path / "ssh-reached"
    env = fakes(tmp_path, python="echo 'round 7 gives the defence player no terminal: not_a_player' >&2; exit 1",
                ssh=f"touch {reached}")

    ran = subprocess.run(["sh", str(SCRIPT), "cr-waf", "defence", "7"], capture_output=True, text=True, env=env)

    assert ran.returncode != 0 and not reached.exists()
    assert len(ran.stdout.splitlines()) == 1 and ran.stdout.strip()
    assert "not_a_player" not in ran.stdout and ran.stderr == ""
    assert "not_a_player" in (tmp_path / "terminal.log").read_text(), "the cause went nowhere"


def test_a_terminal_without_a_player_side_or_a_round_opens_nothing(tmp_path):
    for given in (("cr-kali",), ("cr-kali", "attack"), ("cr-kali", "attack", "3;id"), ("cr-kali", "root", "3")):
        ran, asked, seen = opened(tmp_path, *given)

        assert ran.returncode == 1, given
        assert not asked.exists() and not seen.exists(), given


def test_an_account_the_lookup_did_not_name_cleanly_opens_nothing(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-waf", "defence", "3", lookup="10.31.0.181 cr-srv-2 analyst;id")

    assert ran.returncode == 1 and not seen.exists()


def test_an_ssh_that_cannot_connect_ends_in_one_plain_line_without_its_cause(tmp_path):
    env = fakes(tmp_path, python=f"echo '{KALI_SHELL}'",
                ssh="echo 'ssh: connect to host 10.31.0.180 port 22: Connection timed out' >&2; exit 255")

    ran = subprocess.run(["sh", str(SCRIPT), "cr-kali", "attack", "3"], capture_output=True, text=True, env=env)

    assert ran.returncode == 1
    assert len(ran.stdout.splitlines()) == 1 and ran.stdout.strip()
    assert "Connection timed out" not in ran.stdout + ran.stderr
    assert "Connection timed out" in (tmp_path / "terminal.log").read_text()


def test_a_kept_terminal_reattaches_to_one_tmux_session_per_player_so_a_reload_keeps_the_run(tmp_path):
    seen = tmp_path / "tmux-argv"
    env = {**fakes(tmp_path, tmux=f'printf "%s\\n" "$@" > {seen}', ssh="exit 0"), "TERMINAL_KEEP": "1"}
    env.pop("TMUX", None)

    subprocess.run(["sh", str(SCRIPT), "cr-waf", "defence", "3"], capture_output=True, text=True, env=env)

    assert seen.read_text().split("\n")[:-1] == [
        "-f", str(SCRIPT.parent / "tmux.conf"), "new-session", "-A", "-s", "defence-3",
        str(SCRIPT), "cr-waf", "defence", "3"]


def test_the_shell_s_clock_is_korean_time_even_in_a_box_without_a_time_zone_database(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-waf", "defence", "3", lookup=WAF_SHELL)
    zone = next(word.removeprefix("TZ=") for word in shlex.split(remote_command(seen)) if word.startswith("TZ="))
    offset = subprocess.run(["date", "+%z"], capture_output=True, text=True,
                            env={"TZ": zone, "TZDIR": str(tmp_path / "no-zoneinfo")}).stdout.strip()
    shown = subprocess.run(["date", "+%Z"], capture_output=True, text=True,
                           env={"TZ": zone, "TZDIR": str(tmp_path / "no-zoneinfo")}).stdout.strip()

    assert "/" not in zone and offset == "+0900" and shown == "+09", "the WAF image has no tzdata, so TZ=Asia/Seoul read as UTC"


def test_an_open_shell_is_closed_once_the_round_no_longer_gives_the_player_a_terminal(tmp_path):
    checks, ended = tmp_path / "checks", tmp_path / "ssh-ended"
    revoked_on_second_check = (f'echo x >> {checks}; [ "$(wc -l < {checks})" -lt 2 ] || exit 1; '
                               f'echo "{KALI_SHELL}"')
    env = {**fakes(tmp_path, python=revoked_on_second_check,
                   ssh=f"/bin/sleep 30 >/dev/null 2>&1 & trap 'kill $!; touch {ended}; exit 255' TERM; wait"),
           "TERMINAL_RECHECK": "0.2"}

    ran = subprocess.run(["sh", str(SCRIPT), "cr-kali", "attack", "3"], capture_output=True, text=True, env=env,
                         timeout=10)

    assert ended.exists(), "the shell outlived the round's grant"
    assert ran.returncode == 0 and ran.stdout == ""
    assert "no longer gives the attack player a terminal" in (tmp_path / "terminal.log").read_text()


def test_a_shell_whose_grant_holds_is_left_open_and_the_check_stops_with_it(tmp_path):
    checks = tmp_path / "checks"
    env = {**fakes(tmp_path, python=f'echo x >> {checks}; echo "{KALI_SHELL}"', ssh="/bin/sleep 1"),
           "TERMINAL_RECHECK": "0.2"}

    ran = subprocess.run(["sh", str(SCRIPT), "cr-kali", "attack", "3"], capture_output=True, text=True, env=env,
                         timeout=10)
    seen = len(checks.read_text().splitlines())
    subprocess.run(["/bin/sleep", "0.6"])

    assert ran.returncode == 0
    assert seen >= 3, "the grant was never checked again while the shell was open"
    assert len(checks.read_text().splitlines()) == seen, "the check outlived the shell"
