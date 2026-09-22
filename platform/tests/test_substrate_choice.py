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
