import shlex
import time

import pytest

import plays

SETUP = plays.Setup(wargame="board", title="Acceptance defence shell board")
SITES = "/etc/nginx/conf.d/board.com.conf"
LOGGING_OFF = "access_log off;"
REVERT_WAIT = 120.0


def written(played: plays.Played, line: str, path: str) -> dict:
    return plays.in_shell(played, "defence", f"test -e {path} && printf '%s\\n' {shlex.quote(line)} >> {path}")


def reverted(played: plays.Played) -> dict[str, str]:
    deadline = time.monotonic() + REVERT_WAIT
    while True:
        live = plays.waf_files(played)
        if LOGGING_OFF not in live[plays.SITE_CONF] or time.monotonic() >= deadline:
            return live
        time.sleep(plays.POLL)


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
        seen["live"] = reverted(played)
        seen["refused"] = plays.events(played, {"rule.refused"})
        yield seen


@pytest.mark.parametrize("change", ["log_format", "access_log", "marker"])
def test_the_defence_shell_cannot_write_the_platform_s_logging(shell_round, change):
    assert shell_round[change]["exit_code"] not in (0, None, 255), (
        f"analyst wrote the {change} the platform measures with: {shell_round[change]}")
    assert "Permission denied" in shell_round[change]["stderr"], (
        f"the {change} write failed for a reason other than a permission refusal: {shell_round[change]}")


def test_a_logging_directive_reloaded_from_the_shell_is_put_back(shell_round):
    assert shell_round["reloaded"]["ok"], shell_round["reloaded"]
    assert LOGGING_OFF not in shell_round["live"][plays.SITE_CONF], (
        "access_log off in a defence file, reloaded from the shell, stayed live")
    assert shell_round["refused"], "putting the logging directive back left no rule.refused event"
