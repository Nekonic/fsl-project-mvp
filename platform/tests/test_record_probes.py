import importlib.util
import itertools
from importlib.machinery import SourceFileLoader
from pathlib import Path

import httpx2
import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/record-probes"


def command():
    loader = SourceFileLoader("cr_record_probes", str(COMMAND))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("cr_record_probes", loader))
    loader.exec_module(module)
    return module


def progress(state, done=(), failed=(), total=3, allocation=7):
    return 200, {"allocation": allocation, "wargame": "board", "state": state, "total": total, "done": list(done),
                 "failed": list(failed)}


class Platform:
    def __init__(self, recorded=(202, {"allocation": 7}), progresses=()):
        self.recorded = recorded
        self.progresses = iter(progresses)
        self.calls = []

    def record(self, wargame):
        self.calls.append(("record", wargame))
        return self.recorded

    def progress(self, allocation):
        self.calls.append(("progress", allocation))
        return next(self.progresses)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def run(platform, *argv):
    said, clock = [], Clock()
    code = command().main(["board", *argv], platform=platform, say=said.append, sleep=clock.sleep, clock=clock)
    return code, said, clock


def test_it_starts_one_recording_and_follows_the_allocation_until_the_platform_says_done():
    platform = Platform(progresses=[progress("recording"), progress("recording", ["a"]),
                                    progress("recording", ["a"]), progress("done", ["a", "b", "c"])])

    code, said, clock = run(platform, "--poll", "5")

    assert code == 0
    assert platform.calls == [("record", "board"), *[("progress", 7)] * 4]
    assert clock.slept == [5.0, 5.0, 5.0]
    assert said[0] == "recording board on probe allocation 7"
    assert said[1:4] == ["board allocation 7: recording, 0/3 recorded", "board allocation 7: recording, 1/3 recorded",
                         "board allocation 7: done, 3/3 recorded"], "an unchanged progress is not printed twice"
    assert "wargames/board/probes/" in said[-1]


def test_a_case_the_platform_could_not_record_fails_the_run_and_is_named():
    platform = Platform(progresses=[progress("done", ["a", "b"], [{"case": "c", "code": "attacker_unavailable"}])])

    code, said, _ = run(platform)

    assert code == 1
    assert "not recorded: c (attacker_unavailable)" in said[1]


def test_an_allocation_the_platform_gave_up_on_fails_the_run():
    code, _, _ = run(Platform(progresses=[progress("failed")]))

    assert code == 1


def test_a_refused_start_records_nothing_and_says_why():
    platform = Platform(recorded=(409, {"errors": [{"path": "", "code": "probe_running"}]}))

    code, said, _ = run(platform)

    assert code == 2 and platform.calls == [("record", "board")]
    assert "409" in said[-1] and "probe_running" in said[-1]


def test_an_unreachable_platform_is_waited_out_but_a_refused_progress_read_stops_the_run():
    platform = Platform(progresses=[(0, {"errors": [{"code": "unreachable"}]}), progress("done", ["a", "b", "c"])])
    assert run(platform)[0] == 0

    refused = Platform(progresses=[(404, {"errors": [{"path": "", "code": "unknown_allocation"}]})])
    code, said, _ = run(refused)
    assert code == 2 and "unknown_allocation" in said[-1]


def test_a_recording_that_outlasts_the_wait_stops_following_and_names_the_route_that_keeps_the_progress():
    platform = Platform(progresses=itertools.repeat(progress("recording")))

    code, said, clock = run(platform, "--wait", "30", "--poll", "10")

    assert code == 2 and clock.now == 30
    assert "/api/staff/probes/7/" in said[-1]


def test_only_a_wargame_of_the_repository_can_be_recorded():
    assert command().wargames() == sorted(path.parent.name for path in (ROOT / "wargames").glob("*/wargame.yaml"))
    with pytest.raises(SystemExit):
        command().arguments(["nowhere"])


def test_the_real_client_signs_in_once_and_calls_the_two_staff_routes_through_the_generated_client():
    from bots.client import Client

    seen = []

    def answer(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/record/"):
            return httpx2.Response(202, json={"allocation": 7})
        return httpx2.Response(200, json=progress("done", ["a", "b", "c"])[1])

    def connect(url, timeout):
        seen.append(("connect", url))
        client = Client(base_url=url)
        return client.set_httpx_client(httpx2.Client(base_url=url, transport=httpx2.MockTransport(answer)))

    platform = command().Platform("http://10.0.0.9:8000/", connect=connect)

    assert platform.record("board") == (202, {"allocation": 7})
    assert platform.progress(7)[1]["state"] == "done"
    assert seen == [("connect", "http://10.0.0.9:8000"), ("POST", "/api/staff/wargames/board/probes/record/"),
                    ("GET", "/api/staff/probes/7/")]


def test_a_dropped_connection_is_reported_as_unreachable_and_signs_in_again_next_time():
    from bots.client import Client

    connected = []

    def gone(request):
        raise httpx2.ConnectError("refused", request=request)

    def connect(url, timeout):
        connected.append(url)
        return Client(base_url=url).set_httpx_client(httpx2.Client(base_url=url, transport=httpx2.MockTransport(gone)))

    platform = command().Platform("http://10.0.0.9:8000", connect=connect)

    status, body = platform.progress(7)
    platform.progress(7)

    assert status == 0 and body["errors"][0]["code"] == "unreachable"
    assert len(connected) == 2

