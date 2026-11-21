import os
import pathlib
import re
import subprocess
from datetime import datetime, timezone

import pytest

from cr.config import BoxConfig
from cr.errors import NotFound
from sandbox import attacker as box
from sandbox.runner import Node, Segment, Shape
from testing.fakes import FakeLauncher, FakeRunner

DEPLOY = pathlib.Path(__file__).resolve().parents[3] / "deploy"
KALI = "cr-kali"
EDGE = "cr-edge"
CONFIG = BoxConfig(attacker=KALI, proxy=KALI, way_in=EDGE, target_url="http://board.com", default_origin="ru")

RU = Segment(id="ru", name="Internet", origin="Russia", subnet="5.188.10.0/24", network="cr-internet",
             gateway="5.188.10.1", nodes=(Node(EDGE, "5.188.10.1"), Node(KALI, "5.188.10.10")))
HK = Segment(id="hk", name="Internet", origin="Hong Kong", subnet="103.152.220.0/24", network="cr-internet",
             gateway="103.152.220.1", nodes=(Node(EDGE, "103.152.220.1"), Node(KALI, "103.152.220.10"),
                                             Node(KALI, "103.152.220.11"), Node(KALI, "103.152.220.12")))
MGMT = Segment(id="mgmt", name="Management", subnet="172.29.0.0/24", nodes=(Node("cr-waf", "172.29.0.12"),))
SHAPE = Shape(segments=(RU, HK, MGMT), sensors=())


def test_the_box_never_names_the_substrate():
    assert "docker" not in pathlib.Path(box.__file__).read_text().lower()


def test_nothing_in_the_set_origin_script_a_learner_can_list_carries_the_platform_s_name():
    script = (DEPLOY / "roles/kali/set-origin").read_text()

    assert not re.search(r"\bcr[-_.]", script), "ps and iptables on Kali print these names"
    assert "ORIGIN-SNAT" in script


def test_each_outside_segment_the_box_stands_on_is_an_origin_and_the_declared_default_is_marked():
    found = box.origins(SHAPE, CONFIG)

    assert [(one["id"], one["source_ip"], one["address"], one["default"]) for one in found] == [
        ("hk", "103.152.220.12", "103.152.220.1", False),
        ("ru", "5.188.10.10", "5.188.10.1", True),
    ]
    assert box.find(SHAPE, None, CONFIG)["id"] == "ru"
    assert box.find(SHAPE, "hk", CONFIG)["id"] == "hk"


def test_an_unknown_origin_is_a_not_found_error():
    with pytest.raises(box.UnknownOrigin) as refused:
        box.find(SHAPE, "zz", CONFIG)

    assert isinstance(refused.value, NotFound) and refused.value.code == "unknown_origin"


def test_a_box_on_no_network_is_unavailable():
    with pytest.raises(box.AttackerUnavailable) as refused:
        box.origins(Shape(segments=(MGMT,), sensors=()), CONFIG)

    assert refused.value.code == "attacker_unavailable"


def test_wearing_an_origin_runs_set_origin_with_its_address():
    kali = FakeRunner()

    box.wear_origin(box.find(SHAPE, "hk", CONFIG), kali)

    assert kali.sent[0].argv == ["sudo", "/usr/local/sbin/set-origin", "103.152.220.12"]
    with pytest.raises(box.AttackerUnavailable):
        box.wear_origin(box.find(SHAPE, "hk", CONFIG), FakeRunner().answer("set-origin", "no", 1))


@pytest.mark.parametrize("value, sent", [("c0ffee", "c0ffee"), (None, "")])
def test_the_live_case_reaches_the_proxy_through_its_label_file(value, sent):
    proxy = FakeRunner()

    box.set_label(value, proxy, CONFIG)

    assert proxy.sent[0].stdin == sent, "a cleared case must not label the shell's traffic with the word None"
    assert CONFIG.label_file in proxy.sent[0].text


def test_a_write_the_proxy_could_not_make_is_not_a_silent_success():
    with pytest.raises(box.AttackerUnavailable):
        box.set_label("c0ffee", FakeRunner().answer("cat >", "Read-only file system", 1), CONFIG)


def test_the_launch_runs_on_the_tool_image_the_config_names():
    launcher = FakeLauncher()

    box.launch_with(launcher, CONFIG)(["curl", "-s", "http://board.com/"], timeout=5)

    assert launcher.images == [CONFIG.tool_image]
    assert launcher.runner.sent[0].argv == ["curl", "-s", "http://board.com/"]


LOG = ("2026-11-19T10:00:00Z\tboard-sqli\tcurl http://board.com/?q=1\n"
       "garbage line\n"
       "2026-11-19T10:00:05Z\t\tsqlmap -u http://board.com/\n")


def test_the_command_log_is_read_into_timed_commands_and_garbage_is_skipped():
    commands = box.commands(FakeRunner().answer("commands.log", LOG), CONFIG)

    assert [(one.marker, one.text) for one in commands] == [
        ("board-sqli", "curl http://board.com/?q=1"), ("", "sqlmap -u http://board.com/")]
    start = datetime(2026, 11, 19, 10, 0, 1, tzinfo=timezone.utc)
    assert [one.text for one in box.within(commands, start, None)] == ["sqlmap -u http://board.com/"]


def test_a_missing_command_log_is_no_commands_and_an_unreadable_one_is_an_error():
    assert box.commands(FakeRunner().answer("cat", "cat: No such file or directory", 1), CONFIG) == []
    with pytest.raises(box.AttackerUnavailable):
        box.commands(FakeRunner().answer("cat", "Permission denied", 1), CONFIG)


def test_a_run_starts_detached_into_its_own_folder_and_is_read_from_an_offset():
    kali = FakeRunner()
    box.start_run(kali, 12, ["nmap", "-p", "80", "board.com"])

    script = kali.sent[0].argv[-1]
    assert "/var/lib/cr-runs/12" in script and "setsid nohup" in script and "nmap -p 80 board.com" in script

    reading = FakeRunner().answer("cr.output", "cr.exit=0\ncr.output=\nPORT 80 open\n")
    out = box.run_output(reading, 12, offset=3)
    assert out == box.RunOutput(output="PORT 80 open\n", offset=3 + len("PORT 80 open\n"), done=True, exit_code=0)
    assert "tail -c +4" in reading.sent[0].argv[-1]


def test_a_run_still_going_is_not_done_and_an_unknown_run_is_not_found():
    going = box.run_output(FakeRunner().answer("cr.output", "cr.output=\npartial"), 3)
    assert going.done is False and going.exit_code is None and going.output == "partial"

    with pytest.raises(NotFound) as missing:
        box.run_output(FakeRunner().answer("cr.output", "cr.run=missing\n"), 3)
    assert missing.value.code == "unknown_run"


def test_stopping_a_run_kills_its_process_group_and_marks_it_ended():
    kali = FakeRunner()

    box.stop_run(kali, 12)

    script = kali.sent[0].argv[-1]
    assert "kill -TERM -- -$pid" in script and "/var/lib/cr-runs/12/exit" in script


def _hook(tmp_path):
    hook = tmp_path / "hook.sh"
    hook.write_text((DEPLOY / "kali/operator-log.sh").read_text()
                    .replace(BoxConfig.command_log, str(tmp_path / "commands.log"))
                    .replace(BoxConfig.label_file, str(tmp_path / "active")))
    return hook


def test_the_shell_hook_logs_what_is_typed_where_the_box_reads_it_and_not_the_last_shell_s_command(tmp_path):
    (tmp_path / "active").write_text("case-1\n")
    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c",
         'history -s "the old shell typed this"; source "$1"; '
         '__log_command; history -s "nmap --version"; __log_command; __log_command',
         "bash", str(_hook(tmp_path))],
        capture_output=True, text=True, timeout=30,
    )

    assert shell.returncode == 0, shell
    logged = FakeRunner().answer("cat", (tmp_path / "commands.log").read_text())
    assert [(c.marker, c.text) for c in box.commands(logged, CONFIG)] == [("case-1", "nmap --version")]


def test_the_hook_leaves_a_blank_line_before_every_prompt_but_the_first_as_kali_s_shell_does(tmp_path):
    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", 'source "$1"; __log_command; __log_command; __log_command',
         "bash", str(_hook(tmp_path))],
        capture_output=True, text=True, timeout=30,
    )

    assert shell.stdout == "\n\n"


def test_the_attacker_prompt_is_kali_s_two_line_prompt_and_ends_in_a_dollar_and_a_space():
    shell = subprocess.run(
        ["bash", "--noprofile", "--norc", "-ic", 'source "$1"; printf "%s" "$PS1"', "bash",
         str(DEPLOY / "kali/bashrc")],
        capture_output=True, text=True, timeout=30, env={**os.environ, "TERM": "xterm-256color"},
    )
    prompt = re.sub(r"\\\[.*?\\\]", "", shell.stdout)

    assert "\\n" in prompt and prompt.endswith("\\$ "), "the terminal waits for the prompt with '[$#] $'"
