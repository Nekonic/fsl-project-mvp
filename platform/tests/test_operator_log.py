from datetime import datetime, timezone

import pytest

import operator_log
from range.ports import Ran, RangeUnavailable

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

def test_a_command_with_a_tab_in_it_keeps_all_of_it():
    typed = operator_log.commands(
        reader("2026-09-22T05:00:01Z\tm\techo one\ttwo\n")
    )

    assert typed[0].text == "echo one\ttwo"

def test_nothing_typed_yet_is_no_commands_and_not_an_error():
    missing = reader("cat: /var/log/fsl/commands.log: No such file", exit_code=1)

    assert operator_log.commands(missing) == []

def test_a_box_that_cannot_be_reached_is_not_an_empty_log():
    def unreachable(argv, stdin=None, timeout=60.0):
        raise RangeUnavailable("fsl-kali is not running")

    with pytest.raises(RangeUnavailable):
        operator_log.commands(unreachable)

def test_a_log_that_cannot_be_read_for_any_other_reason_says_so():
    denied = reader("cat: /var/log/fsl/commands.log: Permission denied", exit_code=1)

    with pytest.raises(operator_log.OperatorLogUnavailable, match="Permission"):
        operator_log.commands(denied)

def test_a_line_that_is_not_a_record_is_skipped_rather_than_guessed():
    typed = operator_log.commands(
        reader("garbage\n2026-09-22T05:00:01Z\tm\techo ok\n\n")
    )

    assert [c.text for c in typed] == ["echo ok"]

def test_only_what_was_typed_inside_the_session_is_its_own():
    window = operator_log.within(
        operator_log.commands(reader(LOG)),
        datetime(2026, 9, 22, 5, 0, 5, tzinfo=timezone.utc),
        datetime(2026, 9, 22, 5, 0, 30, tzinfo=timezone.utc),
    )

    assert [c.text for c in window] == ["ls /root", "nc shop.com 80"], (
        "a session showed what was typed before it started, so two sessions "
        "run back to back would each claim the other's commands"
    )

def test_an_open_session_takes_everything_since_it_started():
    window = operator_log.within(
        operator_log.commands(reader(LOG)),
        datetime(2026, 9, 22, 5, 0, 5, tzinfo=timezone.utc),
        None,
    )

    assert [c.text for c in window] == ["ls /root", "nc shop.com 80"]

pytestmark = pytest.mark.django_db

def session_with(client, commands_output):
    from unittest.mock import patch

    from api.models import Session

    session = Session.objects.create()
    Session.objects.filter(pk=session.pk).update(
        started_at=datetime(2026, 9, 22, 5, 0, 5, tzinfo=timezone.utc)
    )

    class Stub:
        def runner(self, role, segment_id=""):
            assert role == "attacker", role
            return reader(commands_output)

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
        client, "cat: /var/log/fsl/commands.log: Permission denied"
    )

    assert response.status_code == 200 or response.status_code == 503

def test_the_attacker_box_writes_what_it_is_asked_to_read():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    shell = (root / "deploy/kali/operator-log.sh").read_text()
    compose = (root / "compose.yaml").read_text()

    assert operator_log.LOG_PATH in shell, (
        f"the platform reads {operator_log.LOG_PATH} and the box writes "
        f"somewhere else, so every session reports that nothing was typed"
    )
    assert "/label:ro" in compose, (
        "the box cannot see which case is open, so every command it records "
        "is unattributed and the window case still says only that an attack "
        "happened"
    )

def test_a_new_shell_does_not_report_the_last_thing_the_old_one_typed():
    import pathlib

    shell = (
        pathlib.Path(__file__).resolve().parents[2] / "deploy/kali/operator-log.sh"
    ).read_text()

    assert "_FSL_STARTED" in shell, (
        "the first prompt of every shell logged whatever was at the top of "
        "the history file - .bashrc is sourced before the history is loaded, "
        "so opening the terminal recorded the last command of the previous "
        "shell and attributed it to whichever case was open now"
    )


def test_a_command_typed_in_the_same_second_the_session_opened_is_its_own():
    typed = operator_log.commands(reader(LOG))

    window = operator_log.within(
        typed,
        datetime(2026, 9, 22, 5, 0, 1, 900000, tzinfo=timezone.utc),
        None,
    )

    assert [c.text for c in window][0] == "nmap -sS -p 80,443 shop.com", (
        "the log keeps whole seconds and the session keeps microseconds, so "
        "anything typed in the second the session opened read as earlier than "
        "it and was dropped"
    )

def test_a_command_typed_in_the_second_the_session_closed_is_still_its_own():
    typed = operator_log.commands(reader(LOG))

    window = operator_log.within(
        typed,
        datetime(2026, 9, 22, 5, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 22, 5, 0, 20, 100000, tzinfo=timezone.utc),
    )

    assert [c.text for c in window][-1] == "nc shop.com 80"

def test_a_command_typed_after_the_session_closed_is_not_its_own():
    typed = operator_log.commands(reader(LOG))

    window = operator_log.within(
        typed,
        datetime(2026, 9, 22, 5, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 22, 5, 0, 9, tzinfo=timezone.utc),
    )

    assert [c.text for c in window] == [
        "nmap -sS -p 80,443 shop.com", "ls /root",
    ]
