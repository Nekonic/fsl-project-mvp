import pytest

from range.ports import Ran
from rules import crs

class Gateway:
    def __init__(self, live="", reload=Ran(0, "test is successful"), workers=None):
        self.file = live
        self.reload = reload
        self.workers = list(workers or ["11 12", "21 22"])
        self.calls = []

    def __call__(self, argv, stdin=None, timeout=60.0):
        joined = " ".join(argv)
        if joined.endswith(crs.WORKERS):
            return Ran(0, self.workers.pop(0) if len(self.workers) > 1 else self.workers[0])
        self.calls.append(argv)
        if "nginx -t" in joined:
            return self.reload
        if "cat >" in joined:
            self.file = stdin
            return Ran(0, "")
        return Ran(0, self.file)

def test_the_paranoia_level_is_set_for_blocking_and_detection_alike():
    rendered = crs.rendered(crs.checked({"paranoia": 3}))

    assert rendered == (
        'SecAction "id:10000,phase:1,pass,nolog,'
        'setvar:tx.blocking_paranoia_level=3,setvar:tx.detection_paranoia_level=3"\n'
    )

def test_an_exclusion_scoped_to_a_path_removes_one_target_from_one_rule():
    rendered = crs.rendered(crs.checked({
        "paranoia": 4,
        "exclusions": [{"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}],
    }))

    assert rendered.splitlines()[1] == (
        'SecRule REQUEST_FILENAME "@beginsWith /search/" '
        '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=920273;ARGS:q"'
    )

def test_an_exclusion_with_no_target_or_path_removes_the_rule_everywhere():
    rendered = crs.rendered(crs.checked({"paranoia": 4, "exclusions": [{"rule_id": 920273}]}))

    assert rendered.splitlines()[1] == 'SecAction "id:10001,phase:1,pass,nolog,ctl:ruleRemoveById=920273"'

@pytest.mark.parametrize("tuning", [
    None,
    {"paranoia": 0},
    {"paranoia": 5},
    {"paranoia": "4"},
    {"paranoia": True},
    {"paranoia": 1, "exclusions": "920273"},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273}] * 21},
    {"paranoia": 1, "exclusions": [{"rule_id": 1}]},
    {"paranoia": 1, "exclusions": [{"rule_id": "920273"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "target": "ARGS:q\"\nSecRuleEngine Off"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "target": "TX:anomaly"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "target": "ARGS:q;ARGS:p"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "path": "/search/\" \"id:1,ctl:ruleEngine=Off"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "path": "/search/\n"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "path": "search"}]},
    {"paranoia": 1, "exclusions": [{"rule_id": 920273, "target": "ARGS:ı"}]},
])
def test_tuning_that_would_write_anything_but_a_level_and_exclusions_is_refused(tuning):
    with pytest.raises(crs.TuningRefused):
        crs.checked(tuning)

def test_applying_writes_the_exclusion_file_and_reloads_nginx():
    gateway = Gateway()

    applied = crs.apply({"paranoia": 2}, gateway)

    assert applied == {"paranoia": 2, "exclusions": []}
    assert "tx.blocking_paranoia_level=2" in gateway.file
    assert any(crs.EXCLUSIONS in " ".join(argv) for argv in gateway.calls)
    assert gateway.calls[-1] == crs.RELOAD

def test_a_tuning_nginx_refuses_is_rolled_back_to_the_previous_file():
    gateway = Gateway(live="the previous file\n", reload=Ran(1, "nginx: [emerg] Rules error"))

    with pytest.raises(crs.TuningRefused, match="Rules error"):
        crs.apply({"paranoia": 2}, gateway)

    assert gateway.file == "the previous file\n"

def test_a_refused_tuning_never_reaches_the_gateway():
    gateway = Gateway()

    with pytest.raises(crs.TuningRefused):
        crs.apply({"paranoia": 9}, gateway)

    assert gateway.calls == []

def test_applying_returns_once_a_new_nginx_worker_serves_without_waiting_for_old_ones_to_drain(monkeypatch):
    monkeypatch.setattr(crs.time, "sleep", lambda seconds: None)
    settled = Gateway(workers=["11 12", "11 12", "11 12 21 22", "12 21 22"])

    crs.apply({"paranoia": 2}, settled)

    assert settled.workers == ["12 21 22"], (
        "new connections reach a new worker as soon as one is up; an old worker "
        "draining a slow request must not hold the tuning back"
    )

def test_a_reload_that_starts_no_new_worker_is_rolled_back_and_refused(monkeypatch):
    monkeypatch.setattr(crs.time, "sleep", lambda seconds: None)
    stuck = Gateway(live="the previous file\n", workers=["11 12"])

    with pytest.raises(crs.TuningRefused, match="no worker"):
        crs.apply({"paranoia": 2}, stuck)

    assert stuck.file == "the previous file\n"
    assert stuck.calls[-1] == crs.RELOAD, "the previous file is reloaded"
