import os
import pathlib
import subprocess
import sys

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOCKERFILE = ROOT / "platform/Dockerfile"
ENTRYPOINT = ROOT / "platform/entrypoint.sh"

def setting(name, **env):
    given = {**os.environ, "DJANGO_SETTINGS_MODULE": "fsl.settings", **env}
    done = subprocess.run(
        [sys.executable, "-c",
         f"import fsl.settings as s; print(repr(s.{name}))"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={key: value for key, value in given.items() if value is not None},
    )
    assert done.returncode == 0, done.stderr[-400:]
    return eval(done.stdout.strip())

def test_debug_is_off_unless_someone_asks_for_it():
    assert setting("DEBUG", DJANGO_DEBUG="") is False, (
        "DEBUG defaulted on, so a stack brought up without the lab's compose "
        "file serves tracebacks to whoever asks"
    )

def test_the_lab_can_still_turn_debug_on():
    assert setting("DEBUG", DJANGO_DEBUG="1") is True

def test_the_hosts_it_answers_for_are_configurable():
    hosts = setting("ALLOWED_HOSTS", DJANGO_ALLOWED_HOSTS="range.example,10.0.0.5")

    assert hosts == ["range.example", "10.0.0.5"]

def test_unless_told_otherwise_it_answers_only_to_the_names_of_this_machine():
    hosts = setting("ALLOWED_HOSTS", DJANGO_ALLOWED_HOSTS=None)

    assert hosts == ["localhost", "127.0.0.1", "[::1]"], (
        f"{hosts}: any Host was accepted, so a page on another name re-resolved "
        f"to 127.0.0.1 passes as the platform's own origin"
    )

def test_serving_without_a_secret_is_refused_when_debug_is_off():
    done = subprocess.run(
        [sys.executable, "-c", "import fsl.wsgi"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={**os.environ, "DJANGO_DEBUG": "", "DJANGO_SECRET_KEY": "",
             "DJANGO_SETTINGS_MODULE": "fsl.settings"},
    )

    assert done.returncode != 0, "it would have served with a shipped secret key"
    assert "SECRET_KEY" in done.stderr

def test_the_lab_serves_without_one():
    done = subprocess.run(
        [sys.executable, "-c", "import fsl.wsgi"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={**os.environ, "DJANGO_DEBUG": "1", "DJANGO_SECRET_KEY": "",
             "DJANGO_SETTINGS_MODULE": "fsl.settings"},
    )

    assert done.returncode == 0, done.stderr[-400:]

def test_the_container_does_not_run_djangos_development_server():
    assert "runserver" not in DOCKERFILE.read_text(), (
        "manage.py runserver is single-threaded, unsupervised and documented as "
        "unfit for anything but development"
    )

def test_the_platform_serves_as_a_non_root_user():
    steps = ENTRYPOINT.read_text()

    assert "gosu fsl" in steps and "waitress-serve" in steps, steps
    assert steps.index("gosu fsl") < steps.index("waitress-serve"), (
        "the platform mounts the docker socket; serving as root makes a "
        "container escape a root escape. It drops to fsl before waitress"
    )
    assert "USER root" not in DOCKERFILE.read_text()

def test_socket_access_is_granted_by_group_resolved_at_start():
    steps = ENTRYPOINT.read_text()

    assert "/var/run/docker.sock" in steps and "stat -c %g" in steps, (
        "the socket's group differs per host; the platform reads it at start "
        "rather than being handed it, so a plain `docker compose up` works"
    )
    assert "usermod" in steps and "gosu fsl" in steps, (
        "granting the socket by running as root makes a container escape a "
        "root escape; fsl joins the socket's group instead"
    )

def test_an_existing_socket_group_does_not_break_start():
    assert "getent group" in ENTRYPOINT.read_text(), (
        "groupadd fails when the gid is already a group, and on some hosts the "
        "socket gid is one the image already uses; guard it with getent first"
    )

def test_the_build_needs_no_argument_from_the_operator():
    assert "DOCKER_GID" not in DOCKERFILE.read_text(), (
        "a required build argument breaks `docker compose up` on a fresh host; "
        "the platform resolves the socket group at start instead"
    )

def test_the_entrypoint_is_executable():
    assert os.access(ENTRYPOINT, os.X_OK), (
        "compose runs /app/entrypoint.sh directly; without the executable bit "
        "the platform container never starts"
    )

def test_the_entrypoint_migrates_before_it_serves():
    steps = ENTRYPOINT.read_text()

    assert "migrate" in steps and steps.index("migrate") < steps.index("waitress-serve"), (
        "serving before the database is migrated answers every request with a "
        "500 until the first migrate lands"
    )

def test_the_platform_registers_the_geoip_pipeline_by_name():
    import register_pipeline

    assert register_pipeline.endpoint("http://elasticsearch:9200/") == (
        "http://elasticsearch:9200/_ingest/pipeline/fsl-geoip"
    ), "ingest reads through fsl-geoip; a different name geolocates nothing"

def test_the_pipeline_the_platform_registers_is_a_geoip_pipeline():
    import json

    pipeline = json.loads((ROOT / "deploy/elastic/ingest-pipeline.json").read_text())
    processors = [next(iter(step)) for step in pipeline.get("processors", [])]

    assert "geoip" in processors, (
        f"the file the platform PUTs as fsl-geoip has no geoip processor: {processors}"
    )

def test_the_image_carries_the_docker_cli_for_the_runner():
    text = DOCKERFILE.read_text()

    assert "docker:" in text and "/usr/local/bin/docker" in text, (
        "the Docker substrate shells out to `docker`; without the cli in the "
        "image every runner and launcher call fails"
    )

def test_the_documented_bring_up_is_a_single_compose_up():
    places = [
        *ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md"),
        *(ROOT / "test").iterdir(), *(ROOT / "bin").iterdir(),
    ]
    stale = [
        f"{path.relative_to(ROOT)}: {line.strip()}"
        for path in places if path.is_file()
        for line in path.read_text(errors="ignore").splitlines()
        if "DOCKER_GID" in line or "docker-gid" in line
    ]

    assert not stale, (
        f"bring-up is a plain `docker compose up`; these still name the old "
        f"socket-group step: {stale}"
    )

def test_no_setting_is_read_by_nothing():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    declared = {
        line.split("=")[0].strip()
        for line in (root / "fsl/settings.py").read_text().splitlines()
        if line[:1].isupper() and "=" in line and not line.startswith("_")
    }
    used = "\n".join(
        path.read_text() for path in root.rglob("*.py")
        if path.name != "settings.py" and path.parent.name != "tests"
    ) + composed.text()

    unread = sorted(
        name for name in declared
        if name.startswith(("FSL_", "ATTACKER_", "TOOL_", "TARGET_", "PUBLIC_"))
        and f"settings.{name}" not in used
    )

    assert unread == [], (
        f"{unread} is set in settings and in compose and read by nobody, so it "
        f"reads as configuration somebody could change to an effect"
    )

def test_nothing_the_stack_does_to_itself_trips_the_rules_it_is_scored_on():
    import re

    compose = composed.document()
    check = " ".join(compose["services"]["waf"]["healthcheck"]["test"])
    host = re.search(r"https?://([^/\s\"]+)", check)

    assert host and not re.fullmatch(r"[\d.]+(:\d+)?", host.group(1)), (
        f"the WAF's own health check asks {host and host.group(1)!r}, and a "
        f"numeric Host header trips CRS 920350. It runs every ten seconds, so "
        f"the platform files a false positive against the defence it is "
        f"scoring, forever, in every session"
    )

def test_acceptance_does_not_run_against_a_target_that_is_not_up_yet():
    verify = (ROOT / "bin/verify").read_text()
    opened = verify.find('post("/api/sessions/"')

    assert 0 <= opened < verify.index('section "acceptance'), (
        "attacks fired at a target that is still starting hit nothing, and the "
        "run reports TP 0 - which the session protocol answers with git reset "
        "--hard. A flaky red is worse than a slow verify"
    )

def test_the_image_carries_the_ssh_client_the_openstack_runner_calls():
    assert "openssh-client" in DOCKERFILE.read_text(), (
        "python:3.13-slim has no ssh, so on OpenStack every runner and "
        "launcher call from this image fails with FileNotFoundError"
    )
