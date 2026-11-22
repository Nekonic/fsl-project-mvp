import pytest

from telemetry import events as log
from telemetry.events import Viewer
from tests.training.attack.conftest import codes, url
from training.models import Action, ToolRun

pytestmark = pytest.mark.django_db


def tool_events(found):
    return [(event["kind"], event["body"]) for event in
            log.after(found.pk, 0, Viewer(sides=frozenset({"attack"}))).events if event["kind"].startswith("tool.")]


def started(browser, found, tool="curl", args=("-s", "http://board.com/")):
    return browser.post(url(found, "tools/"), {"tool": tool, "args": list(args)}, format="json")


def test_a_free_tool_starts_asynchronously_on_the_box_carrying_the_action_s_marker(as_attacker, attacker, cloud):
    answer = started(as_attacker, attacker.round)

    assert answer.status_code == 202
    run = ToolRun.objects.get(pk=answer.json()["run"])
    action = Action.objects.get(pk=answer.json()["action"])
    assert run.argv == ["curl", "-H", f"X-Request-ID: {action.marker}", "-s", "http://board.com/"]
    assert (action.kind, action.correlation, action.malicious) == ("tool", "marker", None)
    [launched] = cloud.box.matching("setsid nohup")
    assert f"/var/lib/cr-runs/{run.pk}" in launched.text
    assert tool_events(attacker.round) == [("tool.started", {"run": run.pk, "tool": "curl"})]


def test_a_tool_that_cannot_carry_a_marker_correlates_by_window(as_attacker, attacker):
    answer = started(as_attacker, attacker.round, tool="nmap", args=("-p", "80", "board.com"))

    assert Action.objects.get(pk=answer.json()["action"]).correlation == "window"


def test_the_output_is_read_after_an_offset_and_the_end_is_recorded_once(as_attacker, attacker, cloud):
    run = started(as_attacker, attacker.round).json()["run"]
    cloud.box.answer("tail -c +1 ", "cr.output=\nfirst part")
    first = as_attacker.get(url(attacker.round, f"tools/{run}/"))
    cloud.box.answer("tail -c +11 ", "cr.exit=0\ncr.output=\n and the rest")
    second = as_attacker.get(url(attacker.round, f"tools/{run}/?after=10"))
    again = as_attacker.get(url(attacker.round, f"tools/{run}/?after=23"))

    assert (first.json()["output"], first.json()["offset"], first.json()["done"]) == ("first part", 10, False)
    assert (second.json()["output"], second.json()["offset"], second.json()["done"]) == (" and the rest", 23, True)
    assert second.json()["exit_code"] == 0
    assert again.json()["done"] is True
    assert [kind for kind, _ in tool_events(attacker.round)] == ["tool.started", "tool.ended"]
    assert ToolRun.objects.get(pk=run).ended is not None


def test_a_player_stops_its_run_on_the_box(as_attacker, attacker, cloud):
    run = started(as_attacker, attacker.round, tool="nikto", args=("-h", "board.com")).json()["run"]

    answer = as_attacker.delete(url(attacker.round, f"tools/{run}/"))

    assert answer.status_code == 204
    assert cloud.box.matching(f"kill -TERM")
    stopped = ToolRun.objects.get(pk=run)
    assert (stopped.stopped_by, stopped.exit_code) == ("player", 143)
    assert tool_events(attacker.round)[-1] == ("tool.ended", {"run": run, "exit_code": 143, "stopped_by": "player"})


def test_the_tool_list_names_every_tool_with_its_args_schema_and_the_round_s_runs(as_attacker, attacker):
    run = started(as_attacker, attacker.round).json()["run"]

    listed = as_attacker.get(url(attacker.round, "tools/")).json()

    assert {"curl", "nmap", "sqlmap"} <= {tool["tool"] for tool in listed["tools"]}
    assert all(tool["args_schema"]["type"] == "array" for tool in listed["tools"])
    assert [one["run"] for one in listed["runs"]] == [run]


def test_an_unknown_tool_and_an_unknown_run_are_named(as_attacker, attacker):
    unknown_tool = started(as_attacker, attacker.round, tool="telnet")
    unknown_run = as_attacker.get(url(attacker.round, "tools/4242/"))

    assert (unknown_tool.status_code, codes(unknown_tool)) == (404, ["unknown_tool"])
    assert (unknown_run.status_code, codes(unknown_run)) == (404, ["unknown_run"])


def test_too_many_args_are_refused_by_path(as_attacker, attacker):
    answer = started(as_attacker, attacker.round, args=["x"] * 65)

    assert answer.status_code == 400
    assert answer.json()["errors"][0]["path"] == "args"


def test_a_run_of_another_round_is_unknown_here(as_attacker, attacker, make_round, cloud):
    other = make_round()
    from tests import rounds

    player = rounds.playing(other, "attack", attacker.user)
    foreign = started(as_attacker, player.round).json()["run"]

    answer = as_attacker.get(url(attacker.round, f"tools/{foreign}/"))

    assert codes(answer) == ["unknown_run"]


def test_a_round_read_ends_a_run_that_finished_on_the_box_though_the_attacker_never_reads_its_output(
        as_attacker, attacker, cloud):
    from training.round import lifecycle

    run = started(as_attacker, attacker.round).json()["run"]
    cloud.box.answer("head -c 0", "cr.exit=3\ncr.output=\n")

    lifecycle.read_logs(attacker.round)

    ended = ToolRun.objects.get(pk=run)
    assert ended.ended is not None and ended.exit_code == 3
    assert Action.objects.get(pk=ended.action_id).ended == ended.ended
    assert [kind for kind, _ in tool_events(attacker.round)] == ["tool.started", "tool.ended"]
