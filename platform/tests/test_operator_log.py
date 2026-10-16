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
    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c",
         'history -s "the old shell typed this"; source "$1"; echo "$FSL_COMMAND_LOG"; '
         'FSL_COMMAND_LOG="$2/commands.log" FSL_LABEL="$2/active"; '
         '_fsl_record; history -s "nmap --version"; _fsl_record; _fsl_record',
         "bash", str(SHELL), str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )

    assert shell.stdout.strip() == operator_log.LOG_PATH, shell
    typed = operator_log.commands(reader((tmp_path / "commands.log").read_text()))
    assert [(c.marker, c.text) for c in typed] == [("case-1", "nmap --version")], (
        "the first prompt of a shell logged the last command of the previous one, "
        "attributed to whichever case was open now"
    )
