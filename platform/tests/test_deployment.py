import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOCKERFILE = ROOT / "platform/Dockerfile"

def setting(name, **env):
    done = subprocess.run(
        [sys.executable, "-c",
         f"import fsl.settings as s; print(repr(s.{name}))"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "fsl.settings", **env},
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

def test_the_container_does_not_run_as_root():
    assert "USER " in DOCKERFILE.read_text(), (
        "the platform mounts the docker socket; running it as root makes a "
        "container escape a root escape"
    )


def test_socket_access_is_granted_by_group_not_by_root():
    text = DOCKERFILE.read_text()

    assert "DOCKER_GID" in text, (
        "the platform needs the docker socket, which is group-owned. Granting "
        "it by running as root makes a container escape a root escape; the gid "
        "differs per host so it has to be a build argument"
    )
    assert "USER fsl" in text

def test_the_lab_passes_the_hosts_own_socket_group():
    compose = (ROOT / "compose.yaml").read_text()

    assert "DOCKER_GID" in compose, (
        "the image takes a DOCKER_GID build argument and compose never sets "
        "it, so the platform cannot reach the daemon"
    )
