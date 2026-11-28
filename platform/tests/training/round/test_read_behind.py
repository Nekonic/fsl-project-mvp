from types import SimpleNamespace

from training.round import views_catch_up


class HeldThread:
    started: list = []

    def __init__(self, target, args, daemon):
        self.target, self.args = target, args

    def start(self):
        HeldThread.started.append(self)


def test_a_request_reads_the_logs_apart_once_per_round_and_does_not_wait_for_the_read(monkeypatch, settings):
    settings.READ_IN_BACKGROUND = True
    HeldThread.started = []
    read = []
    monkeypatch.setattr(views_catch_up.threading, "Thread", HeldThread)
    monkeypatch.setattr(views_catch_up, "read_apart", lambda key: read.append(key))
    request = SimpleNamespace(round=SimpleNamespace(pk=7, allocation=SimpleNamespace(pk=3)), allocation=None)

    views_catch_up.catch_up(request)
    views_catch_up.catch_up(request)

    assert len(HeldThread.started) == 1 and read == []
    HeldThread.started[0].target(*HeldThread.started[0].args)
    views_catch_up._reading.discard((7, 3))
    assert read == [(7, 3)]
