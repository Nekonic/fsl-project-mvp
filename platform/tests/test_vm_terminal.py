import os
import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "vm-terminal.sh"
KALI_SHELL = "10.31.0.180 cr-srv-1 kali"
WAF_SHELL = "10.31.0.181 cr-srv-2 analyst"


def fakes(tmp_path, **bodies):
    for name, body in {"sleep": "exit 0", **bodies}.items():
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


def test_the_attack_seat_gets_a_login_shell_as_the_kali_learner_account_on_the_address_its_grant_names(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-kali", "attack", "3")

    assert asked.read_text().split("\n")[1:4] == ["terminal_shell", "attack", "3"]
    argv = seen.read_text().split("\n")
    assert "ubuntu@10.31.0.180" in argv and "HostKeyAlias=cr-srv-1" in argv
    assert remote_command(seen).startswith("sudo -i -u kali ") and remote_command(seen).endswith(" bash -l")


def test_the_defence_seat_gets_the_waf_as_analyst_and_never_as_root(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-waf", "defence", "3", lookup=WAF_SHELL)

    assert asked.read_text().split("\n")[1:4] == ["terminal_shell", "defence", "3"]
    assert "ubuntu@10.31.0.181" in seen.read_text().split("\n")
    shell = remote_command(seen)
    assert shell.startswith("sudo -i -u analyst ") and shell.endswith(" bash -l")
    assert not shell.startswith("sudo -i env"), "a plain sudo -i is a root shell on the WAF"


def test_the_lookup_is_the_platform_s_manage_py_beside_the_script(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-kali", "attack", "3")

    assert asked.read_text().split("\n")[0] == str(SCRIPT.parent / "manage.py")


def test_a_refused_lookup_ends_the_shell_without_ssh_and_tells_the_learner_one_plain_line(tmp_path):
    reached = tmp_path / "ssh-reached"
    env = fakes(tmp_path, python="echo 'round 7 gives the defence seat no terminal: not_seated' >&2; exit 1",
                ssh=f"touch {reached}")

    ran = subprocess.run(["sh", str(SCRIPT), "cr-waf", "defence", "7"], capture_output=True, text=True, env=env)

    assert ran.returncode != 0 and not reached.exists()
    assert ran.stdout.strip() == "Connection to waf failed. Reopen the terminal in a moment."
    assert ran.stderr == ""
    assert "not_seated" in (tmp_path / "terminal.log").read_text(), "the cause went nowhere"


def test_a_terminal_without_a_seat_side_or_a_round_opens_nothing(tmp_path):
    for given in (("cr-kali",), ("cr-kali", "attack"), ("cr-kali", "attack", "3;id"), ("cr-kali", "root", "3")):
        ran, asked, seen = opened(tmp_path, *given)

        assert ran.returncode == 1, given
        assert not asked.exists() and not seen.exists(), given


def test_an_account_the_lookup_did_not_name_cleanly_opens_nothing(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-waf", "defence", "3", lookup="10.31.0.181 cr-srv-2 analyst;id")

    assert ran.returncode == 1 and not seen.exists()


def test_an_ssh_that_cannot_connect_ends_in_the_same_plain_line(tmp_path):
    env = fakes(tmp_path, python=f"echo '{KALI_SHELL}'",
                ssh="echo 'ssh: connect to host 10.31.0.180 port 22: Connection timed out' >&2; exit 255")

    ran = subprocess.run(["sh", str(SCRIPT), "cr-kali", "attack", "3"], capture_output=True, text=True, env=env)

    assert ran.returncode == 1
    assert ran.stdout.strip() == "Connection to kali failed. Reopen the terminal in a moment."
    assert "Connection timed out" not in ran.stdout + ran.stderr
    assert "Connection timed out" in (tmp_path / "terminal.log").read_text()


def test_a_kept_terminal_reattaches_to_one_tmux_session_per_seat_so_a_reload_keeps_the_run(tmp_path):
    seen = tmp_path / "tmux-argv"
    env = {**fakes(tmp_path, tmux=f'printf "%s\\n" "$@" > {seen}', ssh="exit 0"), "TERMINAL_KEEP": "1"}
    env.pop("TMUX", None)

    subprocess.run(["sh", str(SCRIPT), "cr-waf", "defence", "3"], capture_output=True, text=True, env=env)

    assert seen.read_text().split("\n")[:-1] == [
        "-f", str(SCRIPT.parent / "tmux.conf"), "new-session", "-A", "-s", "defence-3",
        str(SCRIPT), "cr-waf", "defence", "3"]


def test_the_shell_s_clock_is_korean_time_even_in_a_box_without_a_time_zone_database(tmp_path):
    ran, asked, seen = opened(tmp_path, "cr-waf", "defence", "3", lookup=WAF_SHELL)
    zone = next(word.removeprefix("TZ=") for word in remote_command(seen).split() if word.startswith("TZ="))
    offset = subprocess.run(["date", "+%z"], capture_output=True, text=True,
                            env={"TZ": zone, "TZDIR": str(tmp_path / "no-zoneinfo")}).stdout.strip()

    assert "/" not in zone and offset == "+0900", "the WAF image has no tzdata, so TZ=Asia/Seoul read as UTC"
