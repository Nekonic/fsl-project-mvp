import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "redteam/run.py"

def test_the_cli_picks_a_substrate_the_same_way_the_platform_does():
    source = CLI.read_text()

    assert "range.docker" not in source and "import Docker" not in source, (
        "redteam/run.py constructs the Docker adapter by name while the "
        "platform resolves FSL_SUBSTRATE. On any other substrate the console "
        "would fire attacks correctly and the command line would not, and "
        "nothing would say why"
    )

def test_the_cli_goes_through_the_one_factory():
    source = CLI.read_text()

    assert "from range import substrate" in source, (
        "the command line built an adapter of its own, so it and the console "
        "could disagree about what the range is"
    )

def test_there_is_exactly_one_place_that_turns_a_name_into_a_substrate():
    hits = sorted(
        str(path.relative_to(ROOT))
        for path in list(ROOT.glob("platform/**/*.py")) + list(ROOT.glob("redteam/*.py"))
        if "import_string" in path.read_text() and "tests/" not in str(path)
    )

    assert hits == ["platform/range/__init__.py"], (
        f"more than one place builds a substrate from a name: {hits}. They "
        f"drift, and the one nobody runs drifts silently"
    )


def test_no_substrate_is_handed_options_another_substrate_needs():
    import os
    import subprocess
    import sys

    read = subprocess.run(
        [sys.executable, "-c",
         "import fsl.settings as s; print(sorted(s.FSL_SUBSTRATE_OPTIONS))"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "fsl.settings",
             "FSL_SUBSTRATE": "range.openstack.OpenStack"},
    )
    assert read.returncode == 0, read.stderr[-300:]

    assert read.stdout.strip() == "['declared']", (
        f"settings handed the OpenStack adapter {read.stdout.strip()}, which "
        f"includes Docker's compose project name. The adapter then fails on "
        f"an unexpected keyword rather than on the credential it actually "
        f"needs, so the deployment error names the wrong thing"
    )

def test_every_substrate_is_given_the_declaration():
    import os
    import subprocess
    import sys

    for name in ("range.docker.Docker", "range.openstack.OpenStack"):
        read = subprocess.run(
            [sys.executable, "-c",
             "import fsl.settings as s; print('declared' in s.FSL_SUBSTRATE_OPTIONS)"],
            cwd=ROOT / "platform", capture_output=True, text=True,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "fsl.settings",
                 "FSL_SUBSTRATE": name},
        )
        assert read.stdout.strip() == "True", name

def test_the_cli_fires_into_the_stack_of_the_session_it_opened(monkeypatch, capsys):
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
    assert "session 42 opened" in capsys.readouterr().out

def test_the_cli_fires_from_the_slot_the_session_was_given(monkeypatch, capsys, db):
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
