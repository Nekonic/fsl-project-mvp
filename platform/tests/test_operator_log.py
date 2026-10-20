import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import operator_log
from range.ports import Ran

LOG = (
    "2026-09-22T05:00:01Z\tabc-123\tnmap -sS -p 80,443 shop.com\n"
    "2026-09-22T05:00:09Z\t\tls /root\n"
    "2026-09-22T05:00:20Z\tabc-123\tnc shop.com 80\n"
)

def reader(output="", exit_code=0):
    def run(argv, stdin=None, timeout=60.0):
        run.argv = argv
        return Ran(exit_code=exit_code, output=output)

    return run

def test_what_was_typed_comes_back_with_when_and_under_which_case():
    typed = operator_log.commands(reader(LOG))

    assert [(c.at.isoformat(), c.marker, c.text) for c in typed] == [
        ("2026-09-22T05:00:01+00:00", "abc-123", "nmap -sS -p 80,443 shop.com"),
        ("2026-09-22T05:00:09+00:00", "", "ls /root"),
        ("2026-09-22T05:00:20+00:00", "abc-123", "nc shop.com 80"),
    ]

def test_nothing_typed_yet_is_no_commands_and_not_an_error():
    missing = reader("cat: /var/log/fsl/commands.log: No such file", exit_code=1)

    assert operator_log.commands(missing) == []

def at(second, micro=0):
    return datetime(2026, 9, 22, 5, 0, second, micro, tzinfo=timezone.utc)

@pytest.mark.parametrize("start, end, kept", [
    (at(5), at(30), ["ls /root", "nc shop.com 80"]),
    (at(5), None, ["ls /root", "nc shop.com 80"]),
    (at(1, 900000), None, ["nmap -sS -p 80,443 shop.com", "ls /root", "nc shop.com 80"]),
    (at(0), at(20, 100000), ["nmap -sS -p 80,443 shop.com", "ls /root", "nc shop.com 80"]),
    (at(0), at(9), ["nmap -sS -p 80,443 shop.com", "ls /root"]),
], ids=["before-start", "still-open", "same-second-as-start", "same-second-as-end", "after-end"])
def test_a_session_owns_what_was_typed_inside_its_window_to_the_second(start, end, kept):
    window = operator_log.within(operator_log.commands(reader(LOG)), start, end)

    assert [c.text for c in window] == kept, (
        "the log keeps whole seconds and the session microseconds; a session must "
        "neither claim what was typed outside it nor drop what was typed in its "
        "first or last second"
    )

pytestmark = pytest.mark.django_db

def session_with(client, commands_output, exit_code=0):
    from unittest.mock import patch

    from api.models import Session

    session = Session.objects.create()
    Session.objects.filter(pk=session.pk).update(
        started_at=datetime(2026, 9, 22, 5, 0, 5, tzinfo=timezone.utc)
    )

    class Stub:
        def runner(self, role, segment_id=""):
            assert role == "attacker", role
            return reader(commands_output, exit_code)

    with patch("api.views.substrate", Stub):
        return session, client.get(f"/api/sessions/{session.id}/commands/")

def test_the_console_can_ask_what_was_typed_during_a_session(client):
    _, response = session_with(client, LOG)

    assert response.status_code == 200
    assert response.json()["commands"] == [
        {"at": "2026-09-22T05:00:09Z", "case_id": "", "text": "ls /root"},
        {"at": "2026-09-22T05:00:20Z", "case_id": "abc-123", "text": "nc shop.com 80"},
    ], (
        "what was typed before the session opened came back as part of it, so "
        "two sessions run back to back each claim the other's commands"
    )

def test_a_log_that_cannot_be_read_is_503_and_not_an_empty_list(client):
    _, response = session_with(
        client, "cat: /var/log/fsl/commands.log: Permission denied", exit_code=1
    )

    assert response.status_code == 503, (
        "a log the box refused to show came back as nobody having typed "
        "anything, so the window case scores an attack nobody can see"
    )
    assert "Permission denied" in response.json()["detail"]

SHELL = Path(__file__).resolve().parents[2] / "deploy/kali/operator-log.sh"

def test_the_shell_hook_records_what_is_typed_where_the_platform_reads_it_and_not_the_last_shell_s_command(tmp_path):
    (tmp_path / "active").write_text("case-1\n")
    hook = tmp_path / "hook.sh"
    hook.write_text(
        SHELL.read_text()
        .replace(operator_log.LOG_PATH, str(tmp_path / "commands.log"))
        .replace(MARKER_PATH, str(tmp_path / "active"))
    )
    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c",
         'history -s "the old shell typed this"; source "$1"; '
         '__log_command; history -s "nmap --version"; __log_command; __log_command',
         "bash", str(hook)],
        capture_output=True, text=True, timeout=30,
    )

    assert shell.returncode == 0, shell
    typed = operator_log.commands(reader((tmp_path / "commands.log").read_text()))
    assert [(c.marker, c.text) for c in typed] == [("case-1", "nmap --version")], (
        "the first prompt of a shell logged the last command of the previous one, "
        "attributed to whichever case was open now"
    )

def test_the_hook_leaves_a_blank_line_before_every_prompt_but_the_first_as_kali_s_shell_does(tmp_path):
    hook = tmp_path / "hook.sh"
    hook.write_text(
        SHELL.read_text()
        .replace(operator_log.LOG_PATH, str(tmp_path / "commands.log"))
        .replace(MARKER_PATH, str(tmp_path / "active"))
    )

    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", 'source "$1"; __log_command; __log_command; __log_command', "bash", str(hook)],
        capture_output=True, text=True, timeout=30,
    )

    assert shell.stdout == "\n\n"

MARKER_PATH = "/var/lib/session/active"

KALI_SETUP = Path(__file__).resolve().parents[2] / "deploy/kali/setup.sh"
KALI_BASHRC = Path(__file__).resolve().parents[2] / "deploy/kali/bashrc"

def test_the_kali_vm_records_the_terminal_s_ssh_user_and_not_only_root():
    setup = KALI_SETUP.read_text()

    assert "echo '. /usr/local/lib/shell-hook.sh' >> /etc/bash.bashrc" in setup, (
        "on OpenStack the terminal is an ssh login as the kali user, whose shell "
        "never read root's .bashrc, so nothing it typed reached the operator log"
    )
    assert f"install -m 0622 -o ubuntu -g ubuntu /dev/null {operator_log.LOG_PATH}" in setup, (
        "the log must exist, take the kali user's appends, and be read by the account the platform logs in as"
    )

def test_the_attacker_shell_is_kali_s_own():
    setup = KALI_SETUP.read_text()

    assert "useradd --create-home --shell /bin/bash --groups sudo --comment Kali kali" in setup
    assert 'echo "kali ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-kali' in setup
    assert "echo kali > /etc/hostname" in setup and "127.0.1.1 kali" in setup
    assert "preserve_hostname: true" in setup, "cloud-init renamed the machine to the Nova server name again"
    assert ": > /etc/motd" in setup

def test_the_attacker_prompt_is_kali_s_two_line_prompt_and_ends_in_a_dollar_and_a_space():
    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-ic", 'source "$1"; printf "%s" "$PS1"', "bash", str(KALI_BASHRC)],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    prompt = shell.stdout

    assert "┌──" in prompt and "\\u㉿\\h" in prompt and "\\n" in prompt and "└─" in prompt, prompt
    assert re.sub(r"\\\[.*?\\\]", "", prompt).endswith("└─\\$ "), (
        "the terminal steps wait for the prompt with the pattern '\\$ $'"
    )
