import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "redteam/run.py"

def test_the_cli_fires_into_the_stack_of_the_session_it_opened(monkeypatch):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("redteam_cli", CLI)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    fired_on = []

    class Range:
        def __init__(self, session=None):
            self.session = session

        def for_session(self, session):
            return Range(session)

        def launcher(self, segment_id):
            return lambda image, argv, timeout=600.0: fired_on.append(self.session)

    def run(cases, platform_url, launch, tool_target, scenario, announce):
        announce(42)
        launch("fsl-kali", ["curl"])
        return 42

    monkeypatch.setattr(cli, "substrate", Range)
    monkeypatch.setattr(cli.harness, "run", run)
    monkeypatch.setattr(sys, "argv", ["run.py"])

    assert cli.main() == 0
    assert fired_on == [42], (
        "the launcher was built before the session existed, so it found its "
        "network on whichever session stack was newest when it fired"
    )

def test_the_cli_fires_from_the_slot_the_session_was_given(monkeypatch, db):
    import importlib.util
    import sys

    from api.models import Session

    spec = importlib.util.spec_from_file_location("redteam_cli_slots", CLI)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    opened = Session.objects.create(scenario="board", baseline=[], slot=2)
    fired_on = []

    class Slotted:
        def __init__(self, number=None):
            self.number = number

        def in_slot(self, number):
            return Slotted(number)

        def launcher(self, segment_id):
            return lambda image, argv, timeout=600.0: fired_on.append(self.number)

    def run(cases, platform_url, launch, tool_target, scenario, announce):
        announce(opened.pk)
        launch("fsl-kali", ["curl"])
        return opened.pk

    monkeypatch.setattr(cli, "substrate", Slotted)
    monkeypatch.setattr(cli.harness, "run", run)
    monkeypatch.setattr(sys, "argv", ["run.py"])

    assert cli.main() == 0
    assert fired_on == [2], (
        "a session opened on slot 2 fired from slot 1's Kali, which a close had "
        "just sent to be rebuilt, so ssh was refused and the run failed"
    )
