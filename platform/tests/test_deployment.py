import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOCKERFILE = ROOT / "platform/Dockerfile"

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

def test_the_container_does_not_run_as_root():
    users = [args for keyword, args in dockerfile_instructions() if keyword == "USER"]

    assert users and users[-1].split(":")[0] not in ("root", "0"), (
        f"the image ends as user {users[-1:] or ['root']}. The platform mounts "
        f"the docker socket; running it as root makes a container escape a "
        f"root escape"
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

def socket_group_in_compose():
    import re

    import yaml

    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    value = str(compose["services"]["platform"]["build"]["args"]["DOCKER_GID"])
    return value, re.fullmatch(r"\$\{DOCKER_GID(?:(:?[-?])(.*))?\}", value)

def test_a_build_without_the_socket_group_is_not_handed_one():
    value, reference = socket_group_in_compose()

    assert reference and not (reference.group(2) or ""), (
        f"compose builds the platform with DOCKER_GID={value!r}. On colima the "
        f"socket's group is not 0, and every documented start command omitted "
        f"the variable, so the platform built quietly and every docker call it "
        f"made answered 'permission denied'"
    )

def test_compose_commands_that_build_nothing_run_without_the_socket_group():
    value, reference = socket_group_in_compose()

    assert not (reference and "?" in (reference.group(1) or "")), (
        f"{value!r} makes compose refuse every command, logs and ps included, "
        f"whenever the variable is unset; only the build needs it"
    )

def dockerfile_instructions():
    joined = DOCKERFILE.read_text().replace("\\\n", " ")
    return [
        (keyword, args.strip())
        for keyword, _, args in (line.strip().partition(" ") for line in joined.splitlines())
        if keyword and not keyword.startswith("#")
    ]

def test_the_image_has_no_socket_group_of_its_own_to_fall_back_on():
    declared = [
        args for keyword, args in dockerfile_instructions()
        if keyword == "ARG" and args.split("=")[0] == "DOCKER_GID"
    ]

    assert declared and all(args.split("=", 1)[1:] in ([], [""]) for args in declared), (
        f"the Dockerfile declares {declared}: a plain docker build without the "
        f"argument joins that group and cannot reach the socket"
    )

def test_the_image_refuses_to_build_without_the_socket_group():
    steps = [
        args for keyword, args in dockerfile_instructions()
        if keyword == "RUN" and "DOCKER_GID" in args
    ]
    guard = steps[0] if steps else ""

    assert guard and not any(
        command in guard for command in ("useradd", "groupadd", "usermod")
    ), (
        "no step checks DOCKER_GID before the first one that creates a user or "
        "a group with it, so an empty value builds an image that cannot reach "
        "the socket"
    )

    refused = subprocess.run(
        ["sh", "-c", guard], capture_output=True, text=True,
        env={**os.environ, "DOCKER_GID": ""},
    )
    allowed = subprocess.run(
        ["sh", "-c", guard], capture_output=True, text=True,
        env={**os.environ, "DOCKER_GID": "991"},
    )

    assert refused.returncode != 0 and "bin/docker-gid" in refused.stderr, (
        "an empty DOCKER_GID has to stop the build and say where the value "
        "comes from"
    )
    assert allowed.returncode == 0, allowed.stderr

def test_every_documented_build_passes_the_socket_group():
    import re

    places = [
        *ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md"),
        *(ROOT / "test").iterdir(), *(ROOT / "bin").iterdir(),
    ]
    bare = [
        f"{path.relative_to(ROOT)}: {line.strip()}"
        for path in places if path.is_file()
        for line in path.read_text(errors="ignore").splitlines()
        for build in re.finditer(r"docker compose up\b[^\n\"'`]*--build", line)
        if not line[:build.start()].endswith("DOCKER_GID=$(bin/docker-gid) ")
    ]

    assert not bare, (
        f"these tell the operator to build the platform without the socket's "
        f"group, which the build now refuses: {bare}"
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

def test_the_image_carries_the_ssh_client_the_openstack_runner_calls():
    assert "openssh-client" in DOCKERFILE.read_text(), (
        "python:3.13-slim has no ssh, so on OpenStack every runner and "
        "launcher call from this image fails with FileNotFoundError"
    )
