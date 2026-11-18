import io
import json

from django.core.management import call_command

from api.management.commands import run_on_role
from range.ports import Ran


class Range:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def runner(self, role):
        def run(argv, timeout=60.0):
            self.asked.append((role, argv, timeout))
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
