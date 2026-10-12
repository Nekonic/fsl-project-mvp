import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from api.management.commands import run_on_role
from range.ports import Ran, RangeUnavailable


class Range:
    def __init__(self, answer=None, refusal=None):
        self.answer, self.refusal, self.asked = answer, refusal, []

    def runner(self, role):
        def run(argv, timeout=60.0):
            self.asked.append((role, argv, timeout))
            if self.refusal:
                raise RangeUnavailable(self.refusal)
            return self.answer
        return run


def test_the_command_runs_through_the_range_adapter_and_answers_in_one_line(monkeypatch):
    held = Range(answer=Ran(exit_code=3, output="200\nwarn\n"))
    monkeypatch.setattr(run_on_role, "substrate", lambda: held)
    said = io.StringIO()

    call_command("run_on_role", "board", json.dumps(["curl", "x"]), "--timeout", "9", stdout=said)

    assert held.asked == [("board", ["curl", "x"], 9.0)]
    line = next(l for l in said.getvalue().splitlines() if l.startswith(run_on_role.ANSWER))
    assert json.loads(line[len(run_on_role.ANSWER):]) == {"exit_code": 3, "output": "200\nwarn\n"}


def test_a_role_the_range_cannot_reach_is_refused_with_the_adapters_reason(monkeypatch):
    reason = "the host filling 'corp-db' (fsl-wg-corp-db) stands on no segment"
    monkeypatch.setattr(run_on_role, "substrate", lambda: Range(refusal=reason))

    with pytest.raises(CommandError, match="stands on no segment"):
        call_command("run_on_role", "corp-db", json.dumps(["true"]))
