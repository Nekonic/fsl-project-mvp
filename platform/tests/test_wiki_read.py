import pathlib
import re
from unittest.mock import patch

import pytest

import objectives
from range.ports import Ran

CONF = pathlib.Path(__file__).resolve().parents[2] / "deploy/wiki/nginx.conf"
SECRET = "/runbooks/deploy.html"
STAMP = "2026-09-24T10:01:02.123+00:00"
MSEC = "1790244062.123"


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
    refused = wiki("cat: can't open '/var/log/nginx/read.log': Permission denied\n", 1)

    with pytest.raises(objectives.ObjectivesUnavailable, match="Permission denied"):
        objectives.wiki_read_at(refused, SECRET)


def test_a_log_that_does_not_exist_yet_means_nobody_has_read_it():
    missing = wiki("cat: can't open '/var/log/nginx/read.log': No such file or directory\n", 1)

    assert objectives.wiki_read_at(missing, SECRET) is None


def test_the_board_reports_an_unreadable_log_instead_of_an_objective_not_taken():
    failed = wiki(written(200, "/") + "cat: read error: I/O error\n", 1)

    with patch("objectives._fetch", return_value=[]):
        found, unreadable = objectives.observe(failed)

    assert found == []
    assert "I/O error" in unreadable


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
