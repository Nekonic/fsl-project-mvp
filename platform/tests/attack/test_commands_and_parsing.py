from datetime import timedelta

import pytest

from attack import service, tools
from events import log
from events.kinds import Viewer

pytestmark = pytest.mark.django_db


def stamp(at):
    return at.isoformat().replace("+00:00", "Z")


def test_commands_typed_in_the_round_become_command_events_once(attacker, cloud):
    start = attacker.round.started.replace(microsecond=0)
    cloud.box.answer("cat /var/log/commands.log", "\n".join([
        f"{stamp(start - timedelta(minutes=5))}\t\tls before",
        f"{stamp(start + timedelta(seconds=2))}\t\tcurl http://board.com/",
        f"{stamp(start + timedelta(seconds=4))}\t\tsqlmap -u x",
    ]) + "\n")

    first, again = service.read_commands(attacker.round), service.read_commands(attacker.round)

    run = [event["body"]["command"] for event in log.after(attacker.round_id, 0, Viewer(staff=True)).events
           if event["kind"] == "command.run"]
    assert (first, again) == (2, 0)
    assert run == ["curl http://board.com/", "sqlmap -u x"]
    assert [command.line for command in service.commands(attacker.round)] == run


def test_the_answer_parser_splits_status_headers_and_body():
    parsed = tools.answered("HTTP/1.1 302 Found\r\nLocation: /next/\r\nX-Empty:\r\n\r\nline one\r\n\r\nline two"
                            "\ncr.status=302\n")

    assert parsed.status == 302
    assert parsed.headers == (("Location", "/next/"), ("X-Empty", ""))
    assert parsed.body == "line one\r\n\r\nline two"


def test_a_send_that_never_answered_parses_as_no_status():
    assert tools.answered("curl: (28) Operation timed out\ncr.status=000\n").status == 0
    assert tools.answered("").status == 0


def test_the_request_argv_reads_the_body_from_stdin_and_never_from_a_file():
    argv = tools.request_argv("POST", "http://board.com/x", {"Host": "board.com"}, True, 30)

    assert argv[argv.index("--data-binary") + 1] == "@-"
    assert "--path-as-is" in argv and argv[-1] == "http://board.com/x"
    with pytest.raises(ValueError):
        tools.request_argv("TRACE", "http://board.com/", {}, False, 30)
