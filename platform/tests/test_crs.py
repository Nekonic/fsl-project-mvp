import pytest

from range.ports import Ran
from rules import crs

RELOAD = ["sh", "-c", crs.Layout().reload]
WORKERS = crs.workers_of(crs.Layout().pid)

class Gateway:
    def __init__(self, live="", reload=Ran(0, "test is successful"), workers=None):
        self.file = live
        self.reload = reload
        self.workers = list(workers or ["11 12", "21 22"])
        self.calls = []

    def __call__(self, argv, stdin=None, timeout=60.0):
        joined = " ".join(argv)
        if joined.endswith(WORKERS):
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
    assert gateway.calls[-1] == RELOAD

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
    assert stuck.calls[-1] == RELOAD, "the previous file is reloaded"

def test_on_openstack_tuning_writes_where_the_waf_vm_reads_and_reloads_it_with_systemd():
    import os
    import pathlib
    import subprocess
    import sys

    read = subprocess.run(
        [sys.executable, "-c", "import fsl.settings as s; print('\\n'.join(s.FSL_WAF))"],
        cwd=pathlib.Path(__file__).resolve().parents[1], capture_output=True, text=True,
        env={**{k: v for k, v in os.environ.items() if not k.startswith("FSL_")},
             "DJANGO_SETTINGS_MODULE": "fsl.settings", "FSL_SUBSTRATE": "range.openstack.connect"},
    )
    assert read.returncode == 0, read.stderr[-300:]
    layout = crs.Layout(*read.stdout.strip().splitlines())
    setup = (pathlib.Path(__file__).resolve().parents[2] / "deploy/waf/setup.sh").read_text()
    assert layout.rules.startswith("/etc/nginx/modsecurity/crs/rules/"), (
        "the VM's modsecurity.conf includes /etc/nginx/modsecurity/crs/rules/*.conf, "
        "not the container's /etc/modsecurity.d"
    )
    assert f"-g adm /dev/null {layout.rules}" in setup, "the ssh user writes the file without root"

    calls = []

    def vm(argv, stdin=None, timeout=60.0):
        calls.append(argv[-1])
        if "/proc/" in argv[-1]:
            return Ran(0, "11" if len(calls) < 3 else "21")
        return Ran(0, "")

    crs.apply({"paranoia": 2}, vm, layout)

    assert f"cat > {layout.rules}" in calls
    assert calls[-1].startswith("m=$(cat /run/nginx.pid)"), "the VM's nginx keeps its pid in /run"
    assert "sudo systemctl reload nginx" in calls[-2]

def test_on_docker_tuning_keeps_the_container_paths_and_reload():
    from django.conf import settings

    assert settings.FSL_WAF == crs.Layout()
    assert crs.Layout() == (crs.EXCLUSIONS, "nginx -t 2>&1 && nginx -s reload 2>&1", "/tmp/nginx.pid")
