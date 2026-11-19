import os
import pathlib
import subprocess
import sys


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "vm-terminal.sh"


def _finder():
    text = SCRIPT.read_text()
    return text.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


class Slot:
    def __init__(self, cloud, number):
        self.cloud, self.number = cloud, number

    def terminal(self, host):
        return f"10.31.0.{self.number}", f"cr-srv-{self.number}", host


class Cloud:
    def __init__(self, slots):
        self.slots = slots

    def in_slot(self, number):
        return Slot(self, number)


def _found(monkeypatch, capsys, slots, session):
    monkeypatch.setattr("range.substrate", lambda: Cloud(slots))
    monkeypatch.setattr(sys, "argv", ["-", "cr-waf", session])
    try:
        exec(compile(_finder(), str(SCRIPT), "exec"), {"__name__": "__main__"})
    except SystemExit as stopped:
        code = stopped.code
    else:
        code = None
    said = capsys.readouterr()
    return code, said.out.strip(), said.err


def _fakes(tmp_path, **bodies):
    for name, body in {"sleep": "exit 0", **bodies}.items():
        (tmp_path / name).write_text(f"#!/bin/sh\n{body}\n")
        (tmp_path / name).chmod(0o755)
    return {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TERMINAL_LOG": str(tmp_path / "terminal.log")}


def test_a_refused_lookup_ends_the_shell_without_ssh_and_tells_the_learner_one_plain_line(tmp_path):
    reached = tmp_path / "ssh-reached"
    env = _fakes(tmp_path, python="cat >/dev/null; echo 'no open session 7' >&2; exit 2", ssh=f"touch {reached}")

    ran = subprocess.run(["sh", str(SCRIPT), "cr-waf", "7"], capture_output=True, text=True, env=env)

    assert ran.returncode != 0 and not reached.exists()
    assert ran.stdout.strip() == "Connection to waf failed. Reopen the terminal in a moment."
    assert ran.stderr == ""
    assert "no open session 7" in (tmp_path / "terminal.log").read_text(), "the cause went nowhere"


def test_each_pane_is_a_root_login_shell_on_its_slot_s_vm(tmp_path):
    seen = tmp_path / "ssh-argv"
    env = _fakes(tmp_path, python="cat >/dev/null; echo '10.31.0.180 cr-srv-1 cr-kali'",
                 ssh=f'printf "%s\\n" "$@" > {seen}')

    subprocess.run(["sh", str(SCRIPT), "cr-kali", "3"], capture_output=True, text=True, env=env)
    kali = seen.read_text().split("\n")

    assert "ubuntu@10.31.0.180" in kali and "HostKeyAlias=cr-srv-1" in kali
    assert kali[-2].startswith("sudo -i ") and kali[-2].endswith(" bash -l"), (
        "the shell must be a root login shell on the slot's own Kali VM, with its own prompt"
    )


def test_an_ssh_that_cannot_connect_ends_in_the_same_plain_line(tmp_path):
    env = _fakes(tmp_path, python="cat >/dev/null; echo '10.31.0.180 cr-srv-1 cr-kali'",
                 ssh="echo 'ssh: connect to host 10.31.0.180 port 22: Connection timed out' >&2; exit 255")

    ran = subprocess.run(["sh", str(SCRIPT), "cr-kali", "3"], capture_output=True, text=True, env=env)

    assert ran.returncode == 1
    assert ran.stdout.strip() == "Connection to kali failed. Reopen the terminal in a moment."
    assert "Connection timed out" not in ran.stdout + ran.stderr
    assert "Connection timed out" in (tmp_path / "terminal.log").read_text()


def test_a_kept_terminal_reattaches_to_one_tmux_session_per_learner_session_so_a_reload_keeps_the_run(tmp_path):
    seen = tmp_path / "tmux-argv"
    env = {**_fakes(tmp_path, tmux=f'printf "%s\\n" "$@" > {seen}', ssh="exit 0"), "TERMINAL_KEEP": "1"}
    env.pop("TMUX", None)

    subprocess.run(["sh", str(SCRIPT), "cr-kali", "3"], capture_output=True, text=True, env=env)

    assert seen.read_text().split("\n")[:-1] == [
        "-f", "/app/tmux.conf", "new-session", "-A", "-s", "kali-3", str(SCRIPT), "cr-kali", "3"]


def test_the_shell_s_clock_is_korean_time_even_in_a_box_without_a_time_zone_database(tmp_path):
    seen = tmp_path / "ssh-argv"
    env = _fakes(tmp_path, python="cat >/dev/null; echo '10.31.0.180 cr-range-1 s3-waf'",
                 ssh=f'printf "%s\\n" "$@" > {seen}')

    subprocess.run(["sh", str(SCRIPT), "cr-waf", "3"], capture_output=True, text=True, env=env)
    zone = next(word.removeprefix("TZ=") for word in seen.read_text().split("\n")[-2].split() if word.startswith("TZ="))
    offset = subprocess.run(["date", "+%z"], capture_output=True, text=True,
                            env={"TZ": zone, "TZDIR": str(tmp_path / "no-zoneinfo")}).stdout.strip()

    assert "/" not in zone and offset == "+0900", "the WAF image has no tzdata, so TZ=Asia/Seoul read as UTC with the zone name 'Asia'"
