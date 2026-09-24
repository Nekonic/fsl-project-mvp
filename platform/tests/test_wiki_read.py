import pathlib
import re
from unittest.mock import patch

import pytest

import objectives
from range.ports import Ran
from tests.test_docker_runner import RUNS_WHAT_IT_IS_GIVEN, docker_that
from tests.test_openstack_ssh import attacker, host

CONF = pathlib.Path(__file__).resolve().parents[2] / "deploy/wiki/nginx.conf"
SECRET = "/runbooks/deploy.html"
STAMP = "2026-09-24T10:01:02.123+00:00"
MSEC = "1790244062.123"
HEALTHCHECK = '1790244000.000 200 "/index.html" 127.0.0.1 "GET / HTTP/1.1" "Wget"\n'


def written(status, uri, request=None):
    layout = re.search(r"log_format\s+read\s+'([^']*)'", CONF.read_text())[1]
    values = {
        "time_iso8601": "2026-09-24T10:01:02+00:00",
        "msec": MSEC,
        "status": str(status),
        "uri": uri,
        "remote_addr": "172.30.0.2",
        "request": request or f"GET {uri} HTTP/1.1",
        "http_user_agent": "node",
    }
    return re.sub(r"\$(\w+)", lambda variable: values[variable[1]], layout) + "\n"


def wiki(output, exit_code=0):
    return lambda argv, stdin=None, timeout=60.0: Ran(exit_code, output)


@pytest.fixture(params=[
    pytest.param("docker", marks=pytest.mark.stands_in_for_docker),
    "openstack",
])
def runner(request):
    if request.param == "docker":
        return request.getfixturevalue("docker_that")(RUNS_WHAT_IT_IS_GIVEN).runner("wiki")
    return attacker(request.getfixturevalue("host"))


@pytest.fixture
def log(tmp_path, settings):
    kept = tmp_path / "wiki" / "read.log"
    kept.parent.mkdir()
    settings.WIKI_READ_LOG = str(kept)
    return kept


def carried_by(runner, carried):
    def run(argv, stdin=None, timeout=60.0):
        ran = runner(argv, stdin, timeout)
        carried.append(ran.output)
        return ran

    return run


def test_a_read_the_wiki_served_is_taken_at_its_stamp():
    assert objectives.wiki_read_at(wiki(written(200, SECRET)), SECRET) == STAMP


def test_a_request_the_wiki_refused_is_not_a_read():
    assert objectives.wiki_read_at(wiki(written(404, SECRET)), SECRET) is None


def test_a_query_string_on_the_secret_is_still_a_read_of_it():
    line = written(200, SECRET, request=f"GET {SECRET}?x=1 HTTP/1.1")

    assert objectives.wiki_read_at(wiki(line), SECRET) == STAMP


@pytest.mark.parametrize("elsewhere", [f"/x{SECRET}", f"{SECRET}-suffix", f"/x{SECRET}-suffix"])
def test_a_path_that_only_contains_the_secret_is_not_the_secret(elsewhere):
    assert objectives.wiki_read_at(wiki(written(200, elsewhere)), SECRET) is None


def test_a_run_of_nuls_before_a_read_does_not_hide_it():
    log = "\0" * 600 + written(200, SECRET)

    assert objectives.wiki_read_at(wiki(log), SECRET) == STAMP


def test_a_log_that_could_not_be_read_is_unreadable_not_unread():
    refused = wiki("grep: /var/log/nginx/read.log: Permission denied\n", 2)

    with pytest.raises(objectives.ObjectivesUnavailable, match="Permission denied"):
        objectives.wiki_read_at(refused, SECRET)


def test_a_log_that_does_not_exist_yet_means_nobody_has_read_it():
    missing = wiki("grep: /var/log/nginx/read.log: No such file or directory\n", 2)

    assert objectives.wiki_read_at(missing, SECRET) is None


def test_a_log_with_no_line_naming_the_secret_means_nobody_has_read_it():
    assert objectives.wiki_read_at(wiki("", 1), SECRET) is None, (
        "grep exits 1 when 'No lines were selected' (POSIX), which is the "
        "answer, not a failure to read the log"
    )


def test_the_board_reports_an_unreadable_log_instead_of_an_objective_not_taken():
    failed = wiki(written(404, SECRET) + "grep: /var/log/nginx/read.log: I/O error\n", 2)

    with patch("objectives._fetch", return_value=[]):
        found, unreadable = objectives.observe(failed)

    assert found == []
    assert "I/O error" in unreadable


def test_a_runner_that_fails_on_this_host_leaves_the_log_unreadable_not_unread():
    def fails_here(argv, stdin=None, timeout=60.0):
        raise OSError(28, "No space left on device")

    with patch("objectives._fetch", return_value=[]):
        found, unreadable = objectives.observe(fails_here)

    assert found == []
    assert "No space left on device" in unreadable


def test_a_read_is_stamped_to_the_millisecond():
    layout = re.search(r"log_format\s+read\s+'([^']*)'", CONF.read_text())[1]

    assert layout.startswith("$msec "), (
        "nginx's $time_iso8601 is to the second, so a read at .900 was stamped "
        ".000 and could be credited to a case that started within that second "
        "after it; $msec is 'time in seconds with a milliseconds resolution'"
    )
    assert objectives.wiki_read_at(wiki(written(200, SECRET)), SECRET) == STAMP


def test_a_line_logged_before_the_change_is_still_read():
    before = f'2026-09-24T10:01:02+00:00 200 "{SECRET}" 172.30.0.2 "GET {SECRET} HTTP/1.1" "node"\n'

    assert objectives.wiki_read_at(wiki(before), SECRET) == "2026-09-24T10:01:02+00:00"


def test_the_platform_is_handed_only_the_lines_that_name_the_secret(runner, log):
    log.write_text(HEALTHCHECK * 500 + written(200, SECRET) + HEALTHCHECK * 500)
    carried = []

    assert objectives.wiki_read_at(carried_by(runner, carried), SECRET) == STAMP
    assert carried == [written(200, SECRET)], (
        "the wiki's healthcheck appends a line every 10 s to a log nothing "
        "rotates, and the red console asks every 10 s; the whole log was "
        f"carried back each time to find one path in it: {len(carried[0])} bytes"
    )


def test_a_log_that_never_names_the_secret_is_unread_on_either_runner(runner, log):
    log.write_text(HEALTHCHECK * 3)

    assert objectives.wiki_read_at(runner, SECRET) is None


def test_a_log_not_written_yet_is_unread_on_either_runner(runner, log):
    assert objectives.wiki_read_at(runner, SECRET) is None


def test_only_the_path_itself_is_the_secret_on_either_runner(runner, log):
    log.write_text(
        written(200, f"{SECRET}-old")
        + written(200, f"/x{SECRET}")
        + written(200, "/", request=f"GET /?next={SECRET} HTTP/1.1")
    )

    assert objectives.wiki_read_at(runner, SECRET) is None


def test_a_read_after_a_run_of_nuls_is_found_on_either_runner(runner, log):
    log.write_bytes(b"\0" * 1031 + HEALTHCHECK.encode() + written(200, SECRET).encode())

    assert objectives.wiki_read_at(runner, SECRET) == STAMP, (
        "a log truncated under nginx starts with NULs, and GNU grep "
        "'suppresses output after null input binary data is discovered' "
        "unless it is told the file is text"
    )


def test_the_last_read_the_wiki_served_wins_on_either_runner(runner, log):
    log.write_text(
        f'2026-09-24T09:00:00+00:00 200 "{SECRET}" 172.30.0.2 "GET {SECRET} HTTP/1.1" "node"\n'
        + written(200, SECRET)
        + written(404, SECRET)
    )

    assert objectives.wiki_read_at(runner, SECRET) == STAMP
