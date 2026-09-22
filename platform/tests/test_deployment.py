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

def test_a_socket_group_the_image_already_has_does_not_break_the_build():
    text = DOCKERFILE.read_text()

    assert "getent group" in text, (
        "groupadd fails when the gid is already taken, and on this host the "
        "socket's group is 991, which the python image already uses. The build "
        "died with GID '991' already exists and the stack could not come up"
    )

def test_finding_the_socket_group_is_not_left_to_the_operator():
    script = ROOT / "bin/docker-gid"

    assert script.exists() and os.access(script, os.X_OK), (
        "the gid has to be read inside the VM the daemon runs in; read off the "
        "host it comes back 1, the build joins the wrong group and the platform "
        "answers 200 with 'permission denied' in the body"
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
    ) + (root.parent / "compose.yaml").read_text()

    unread = sorted(
        name for name in declared
        if name.startswith(("FSL_", "ATTACKER_", "TOOL_", "TARGET_", "PUBLIC_"))
        and f"settings.{name}" not in used
    )

    assert unread == [], (
        f"{unread} is set in settings and in compose and read by nobody, so it "
        f"reads as configuration somebody could change to an effect"
    )

def test_the_wiki_is_checked_on_an_address_it_actually_listens_on():
    import yaml

    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    check = " ".join(compose["services"]["wiki"]["healthcheck"]["test"])

    assert "localhost" not in check, (
        "busybox wget resolves localhost to ::1 first. The nginx entrypoint "
        "adds an IPv6 listener by rewriting its own conf and this conf is "
        "mounted read-only, so the check failed forever while the wiki served "
        "every request it was given"
    )

def test_nothing_the_stack_does_to_itself_trips_the_rules_it_is_scored_on():
    import re

    import yaml

    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
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

    assert "fsl-juice-shop" in verify and "Health" in verify, (
        "attacks fired at a target that is still starting hit nothing, and the "
        "run reports TP 0 - which the session protocol answers with git reset "
        "--hard. A flaky red is worse than a slow verify"
    )
