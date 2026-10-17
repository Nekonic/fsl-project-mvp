import os
import pathlib
import subprocess
import sys

import pytest

from api.models import Session
from range.ports import Node, Segment, Shape

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "vm-terminal.sh"


def _finder():
    text = SCRIPT.read_text()
    return text.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


class Slot:
    def __init__(self, cloud, number):
        self.cloud, self.number = cloud, number

    def describe(self):
        return Shape(segments=(Segment(id="mgmt", name="Management", subnet="10.31.0.0/16",
                                       nodes=(Node("fsl-waf", f"10.31.{self.number}.9"),)),),
                     sensors=())

    def host_key_alias(self, address):
        return f"fsl-server-{self.number}"


class Cloud:
    def __init__(self, slots):
        self.slots = slots

    def in_slot(self, number):
        return Slot(self, number)


def _found(monkeypatch, capsys, slots, session):
    monkeypatch.setattr("range.substrate", lambda: Cloud(slots))
    monkeypatch.setattr(sys, "argv", ["-", "fsl-waf", session])
    try:
        exec(compile(_finder(), str(SCRIPT), "exec"), {"__name__": "__main__"})
    except SystemExit as stopped:
        code = stopped.code
    else:
        code = None
    said = capsys.readouterr()
    return code, said.out.strip(), said.err


@pytest.mark.django_db
def test_the_shell_opens_on_the_slot_the_named_session_holds(monkeypatch, capsys):
    held = Session.objects.create(scenario="board", baseline=[], slot=2)

    assert _found(monkeypatch, capsys, 2, str(held.pk))[:2] == (None, "10.31.2.9 fsl-server-2")


@pytest.mark.django_db
@pytest.mark.parametrize("named", ["", "999", "closed"])
def test_with_two_slots_a_closed_unknown_or_missing_session_is_refused(monkeypatch, capsys, named):
    if named == "closed":
        named = str(Session.objects.create(scenario="board", baseline=[], slot=2,
                                           ended_at="2026-10-10T00:00:00Z").pk)

    code, address, complaint = _found(monkeypatch, capsys, 2, named)

    assert code not in (None, 0) and address == "", (
        "slot 1 is another session's range; a shell there edits someone else's WAF"
    )
    assert "which slot" in complaint


def test_a_refused_lookup_ends_the_shell_without_ssh(tmp_path):
    reached = tmp_path / "ssh-reached"
    for name, body in {
        "python": "cat >/dev/null; echo 'no open session 7' >&2; exit 2",
        "sleep": "exit 0",
        "ssh": f"touch {reached}",
    }.items():
        (tmp_path / name).write_text(f"#!/bin/sh\n{body}\n")
        (tmp_path / name).chmod(0o755)

    ran = subprocess.run(["sh", str(SCRIPT), "fsl-waf", "7"], capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"})

    assert ran.returncode != 0 and not reached.exists()
    assert "no open session 7" in ran.stderr
