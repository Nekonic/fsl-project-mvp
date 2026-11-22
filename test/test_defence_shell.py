import shlex

import pytest

import plays

SETUP = plays.Setup(wargame="board", title="Acceptance defence shell board")
SITES = "/etc/nginx/conf.d/board.com.conf"
LOGGING_OFF = "access_log off;"


def written(played: plays.Played, line: str, path: str) -> dict:
    return plays.in_shell(played, "defence", f"test -e {path} && printf '%s\\n' {shlex.quote(line)} >> {path}")


@pytest.fixture(scope="module")
def shell_round():
    with plays.Round("board", SETUP) as played:
        seen = {
            "log_format": written(played, "log_format plain $remote_addr;", SITES),
            "access_log": written(played, LOGGING_OFF, SITES),
            "marker": written(played, "map $http_x_request_id $logged_marker { default \"\"; }", SITES),
        }
        seen["reloaded"] = plays.in_shell(
            played, "defence", plays.appended_and_reloaded(plays.SITE_CONF, LOGGING_OFF + "\n"))
        seen["versions"] = plays.waf_versions(played)
        yield seen


@pytest.mark.parametrize("change", ["log_format", "access_log", "marker"])
def test_the_defence_shell_cannot_write_the_platform_s_logging(shell_round, change):
    assert shell_round[change]["exit_code"] not in (0, None, 255), (
        f"analyst wrote the {change} the platform measures with: {shell_round[change]}")
    assert "Permission denied" in shell_round[change]["stderr"], (
        f"the {change} write failed for a reason other than a permission refusal: {shell_round[change]}")


def test_a_logging_directive_reloaded_from_the_shell_is_refused_before_it_loads(shell_round):
    assert not shell_round["reloaded"]["ok"], shell_round["reloaded"]
    assert "nothing was loaded" in shell_round["reloaded"]["stderr"], shell_round["reloaded"]
    assert all(line["source"] != "terminal" for line in shell_round["versions"]), shell_round["versions"]
