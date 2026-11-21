import os
import pathlib
import subprocess
import sys


from cr import strings
from tests import composed

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOCKERFILE = ROOT / "platform/Dockerfile"
ENTRYPOINT = ROOT / "platform/entrypoint.sh"

def setting(name, **env):
    given = {**os.environ, "DJANGO_SETTINGS_MODULE": "cr.settings", **env}
    done = subprocess.run(
        [sys.executable, "-c",
         f"import cr.settings as s; print(repr(s.{name}))"],
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
        [sys.executable, "-c", "import cr.wsgi"],
        cwd=ROOT / "platform", capture_output=True, text=True,
        env={**os.environ, "DJANGO_DEBUG": "", "DJANGO_SECRET_KEY": "",
             "DJANGO_SETTINGS_MODULE": "cr.settings"},
    )

    assert done.returncode != 0, "it would have served with a shipped secret key"
    assert "SECRET_KEY" in done.stderr

def test_the_platform_serves_as_a_non_root_user():
    steps = ENTRYPOINT.read_text()

    assert "gosu cr" in steps and "waitress-serve" in steps, steps
    assert steps.index("gosu cr") < steps.index("waitress-serve"), (
        "serving as root makes a bug in the platform a root shell in its container; "
        "it drops to cr before waitress"
    )
    assert "USER root" not in DOCKERFILE.read_text()

def test_the_platform_image_carries_no_docker_client_and_joins_no_socket_group():
    assert "docker.sock" not in ENTRYPOINT.read_text() and "docker" not in DOCKERFILE.read_text().lower()

def test_the_platform_compose_service_does_not_turn_debug_on():
    environment = composed.services()["platform"]["environment"]

    assert "DJANGO_DEBUG" not in environment, (
        "a wrong path on the learner's own origin printed the URL routes, and a 500 would print settings"
    )

def test_a_secret_key_is_generated_into_the_data_volume_only_when_none_is_given():
    steps = ENTRYPOINT.read_text()

    assert '[ -z "${DJANGO_SECRET_KEY:-}" ]' in steps and "[ -s /data/secret-key ] ||" in steps, (
        "a key already given or already generated is never replaced"
    )
    assert "umask 077" in steps and steps.index("secret-key") < steps.index("waitress-serve")
    assert "echo" not in steps.split("secret-key", 1)[1].split("waitress-serve", 1)[0], "the key is never printed"



def test_the_image_carries_the_server_string_table_where_cr_strings_reads_it():
    lines = [line.split() for line in DOCKERFILE.read_text().splitlines()]
    workdir = [words[1] for words in lines if words and words[0] == "WORKDIR"][-1]
    read_at = pathlib.PurePosixPath(workdir, "cr", "strings.py").parents[2] / "strings" / strings.TABLE

    assert ["COPY", f"strings/{strings.TABLE}", str(read_at)] in lines, (
        f"cr.strings reads {read_at} in the image, and the Dockerfile does not put the table there")
