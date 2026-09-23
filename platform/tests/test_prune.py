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
        "operators": set(operators),
        "run_open": set(run[:3]),
        "run_closed": set(run[3:]),
    }


def test_only_the_closed_sessions_of_the_run_are_chosen(prune, an_acceptance_run):
    namespace = {}
    exec(prune.module.script(after=an_acceptance_run["before"]), namespace)

    chosen = set(namespace["doomed"].values_list("id", flat=True))

    assert chosen == an_acceptance_run["run_closed"], (
        f"one acceptance run makes about 20 sessions, so keeping the newest 20 "
        f"deleted every session a person had made, open ones included. Chosen "
        f"{sorted(chosen)}, operators were {sorted(an_acceptance_run['operators'])}"
    )


def test_what_verify_runs_leaves_the_operators_and_every_open_session(
    prune, an_acceptance_run
):
    prune("--after", str(an_acceptance_run["before"]), "--apply")

    left = set(Session.objects.values_list("id", flat=True))

    assert left == an_acceptance_run["operators"] | an_acceptance_run["run_open"]


def test_verify_bounds_the_prune_by_the_newest_session_before_acceptance():
    verify = (ROOT / "bin/verify").read_text()

    recorded = verify.find('NEWEST_BEFORE="$(./bin/prune --newest')
    acceptance = verify.find("pytest test/")
    pruned = verify.find('./bin/prune --after "$NEWEST_BEFORE" --apply')

    assert "--keep" not in verify and -1 < recorded < acceptance < pruned, (
        "verify pruned by count, and a count cannot tell the run's own sessions "
        "from the ones a person was still using"
    )
