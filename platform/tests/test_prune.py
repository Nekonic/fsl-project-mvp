import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from django.utils import timezone

from api.models import Session

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[2]


def load_prune():
    loader = SourceFileLoader("prune", str(ROOT / "bin/prune"))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("prune", loader)
    )
    loader.exec_module(module)
    return module


@pytest.fixture
def prune(monkeypatch, capsys):
    module = load_prune()

    def in_this_process(script):
        exec(script, {})
        return ""

    monkeypatch.setattr(module, "run", in_this_process)

    def invoke(*argv):
        monkeypatch.setattr(sys, "argv", ["prune", *argv])
        module.main()
        return capsys.readouterr().out

    invoke.module = module
    return invoke


def made(count, still_open):
    return [
        Session.objects.create(ended_at=None if n < still_open else timezone.now()).id
        for n in range(count)
    ]


@pytest.fixture
def an_acceptance_run(prune):
    operators = made(5, still_open=2)
    before = int(prune("--newest"))
    run = made(20, still_open=3)
    return {
        "before": before,
        "run": run,
        "operators": set(operators),
        "run_open": set(run[:3]),
        "run_closed": set(run[3:]),
    }


def test_only_the_closed_sessions_of_the_run_are_chosen(prune, an_acceptance_run):
    namespace = {}
    exec(prune.module.script(ids=an_acceptance_run["run"]), namespace)

    chosen = set(namespace["doomed"].values_list("id", flat=True))

    assert chosen == an_acceptance_run["run_closed"], (
        f"one acceptance run makes about 20 sessions, so keeping the newest 20 "
        f"deleted every session a person had made, open ones included. Chosen "
        f"{sorted(chosen)}, operators were {sorted(an_acceptance_run['operators'])}"
    )


def test_what_verify_runs_leaves_the_operators_and_every_open_session(
    prune, an_acceptance_run, tmp_path
):
    listed = tmp_path / "sessions"
    listed.write_text("".join(f"{session_id}\n" for session_id in an_acceptance_run["run"]))
    prune("--ids", str(listed), "--apply")

    left = set(Session.objects.values_list("id", flat=True))

    assert left == an_acceptance_run["operators"] | an_acceptance_run["run_open"]


def test_verify_prunes_only_the_sessions_its_run_listed():
    verify = (ROOT / "bin/verify").read_text()

    listed = verify.find("FSL_ACCEPTANCE_SESSIONS")
    acceptance = verify.find("pytest test/")
    pruned = verify.find('./bin/prune --ids "$FSL_ACCEPTANCE_SESSIONS" --apply')

    assert "--keep" not in verify and "--after" not in verify and -1 < listed < acceptance < pruned, (
        "verify pruned by count, and then by 'newer than the run', and neither "
        "can tell the run's own sessions from one a person opened meanwhile"
    )


def test_a_session_a_person_opened_during_the_run_is_not_the_run_s(prune, tmp_path):
    before_the_run = made(3, still_open=1)
    run = made(10, still_open=0)
    theirs = made(1, still_open=0)
    listed = tmp_path / "sessions"
    listed.write_text("".join(f"{session_id}\n" for session_id in run))

    prune("--ids", str(listed), "--apply")

    left = set(Session.objects.values_list("id", flat=True))
    assert left == set(before_the_run) | set(theirs), (
        f"a session opened by a person while acceptance ran has an id above "
        f"the run's bound, so 'newer than the run' deleted it: left {sorted(left)}"
    )


def test_a_listed_session_still_open_is_not_deleted(prune, tmp_path):
    run = made(4, still_open=1)
    listed = tmp_path / "sessions"
    listed.write_text("".join(f"{session_id}\n" for session_id in run))

    prune("--ids", str(listed), "--apply")

    assert set(Session.objects.values_list("id", flat=True)) == {run[0]}
