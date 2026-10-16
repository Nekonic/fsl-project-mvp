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

def test_the_platform_serves_as_a_non_root_user():
    steps = ENTRYPOINT.read_text()

    assert "gosu fsl" in steps and "waitress-serve" in steps, steps
    assert steps.index("gosu fsl") < steps.index("waitress-serve"), (
        "the platform mounts the docker socket; serving as root makes a "
        "container escape a root escape. It drops to fsl before waitress"
    )
    assert "USER root" not in DOCKERFILE.read_text()

def test_socket_access_is_granted_by_a_group_resolved_at_start_that_may_already_exist():
    steps = ENTRYPOINT.read_text()

    assert "/var/run/docker.sock" in steps and "stat -c %g" in steps, (
        "the socket's group differs per host; the platform reads it at start "
        "rather than being handed it, so a plain `docker compose up` works"
    )
    assert "usermod" in steps and "gosu fsl" in steps, (
        "granting the socket by running as root makes a container escape a "
        "root escape; fsl joins the socket's group instead"
    )
    assert "getent group" in steps, (
        "groupadd fails when the gid is already a group, and on some hosts the "
        "socket gid is one the image already uses; guard it with getent first"
    )
    assert "DOCKER_GID" not in DOCKERFILE.read_text(), (
        "a required build argument breaks `docker compose up` on a fresh host"
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
