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

KOREAN_SEARCH_AT_PL3 = {
    "paranoia": 3,
    "exclusions": [
        {"rule_id": 920272, "target": "REQUEST_URI_RAW", "path": "/search/"},
        {"rule_id": 920272, "target": "ARGS:q", "path": "/search/"},
        {"rule_id": 942460, "target": "ARGS:q", "path": "/search/"},
    ],
    "thresholds": {"inbound": 10000, "outbound": 10000},
}
BODY_UNDER_COMMENTS = {"paranoia": 3, "exclusions": [{"rule_id": 920272, "target": "REQUEST_BODY", "path": "/posts/"}]}
SQLI_FAMILY_OFF_FOR_SORT = {"paranoia": 1, "exclusions": [{"tag": "attack-sqli", "target": "ARGS:sort"}]}
EVERY_RULE_OFF_FOR_SORT = {"paranoia": 1, "exclusions": [{"tag": "OWASP_CRS", "target": "ARGS:sort"}]}

@pytest.mark.parametrize("tuning, line, directive", [
    ({"paranoia": 3}, 0,
     'SecAction "id:10000,phase:1,pass,nolog,'
     'setvar:tx.blocking_paranoia_level=3,setvar:tx.detection_paranoia_level=3"'),
    ({"paranoia": 1, "thresholds": {"outbound": 8, "inbound": 12}}, 0,
     'SecAction "id:10000,phase:1,pass,nolog,'
     'setvar:tx.blocking_paranoia_level=1,setvar:tx.detection_paranoia_level=1,'
     'setvar:tx.inbound_anomaly_score_threshold=12,setvar:tx.outbound_anomaly_score_threshold=8"'),
    ({"paranoia": 4, "exclusions": [{"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}]}, 1,
     'SecRule REQUEST_FILENAME "@beginsWith /search/" '
     '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=920273;ARGS:q"'),
    ({"paranoia": 4, "exclusions": [{"rule_id": 920273}]}, 1,
     'SecAction "id:10001,phase:1,pass,nolog,ctl:ruleRemoveById=920273"'),
    (KOREAN_SEARCH_AT_PL3, 1,
     'SecRule REQUEST_FILENAME "@beginsWith /search/" '
     '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=920272;REQUEST_URI_RAW"'),
    (BODY_UNDER_COMMENTS, 1,
     'SecRule REQUEST_FILENAME "@beginsWith /posts/" '
     '"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=920272;REQUEST_BODY"'),
    (SQLI_FAMILY_OFF_FOR_SORT, 1,
     'SecAction "id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetByTag=attack-sqli;ARGS:sort"'),
], ids=["paranoia", "thresholds", "target-under-path", "rule-everywhere", "raw-uri", "whole-body", "tag-everywhere"])
def test_a_tuning_is_written_as_the_modsecurity_directive_crs_reads(tuning, line, directive):
    assert crs.rendered(crs.checked(tuning)).splitlines()[line] == directive

@pytest.mark.parametrize("tuning", [
    KOREAN_SEARCH_AT_PL3, BODY_UNDER_COMMENTS, {"paranoia": 2, "exclusions": [{"rule_id": 949110}]},
    SQLI_FAMILY_OFF_FOR_SORT, EVERY_RULE_OFF_FOR_SORT,
], ids=["raw-uri-and-thresholds", "whole-body", "no-thresholds", "tag", "every-crs-rule-tag"])
def test_a_written_tuning_reads_back_as_written(tuning):
    checked = crs.checked(tuning)

    assert crs.parsed(crs.rendered(checked)) == checked

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
    {"paranoia": 1, "exclusions": [{"tag": "attack-sqli"}]},
    {"paranoia": 1, "exclusions": [{"tag": "attack-sqli;ARGS:q,ctl:ruleEngine=Off", "target": "ARGS:sort"}]},
    {"paranoia": 1, "exclusions": [{"tag": "", "target": "ARGS:sort"}]},
    *({"paranoia": 1, "exclusions": [{"rule_id": 920272, "target": target}]}
      for target in ("REQUEST_URI_RAW:x", "REQUEST_URI_RAWX", "REQUEST_URI", "REQUEST_BODY:x",
                     "REQUEST_BODYX", "REQUEST_BODY_LENGTH")),
    *({"paranoia": 1, "thresholds": thresholds}
      for thresholds in ("10000", {"inbound": 0}, {"inbound": 100001}, {"inbound": "5"},
                         {"inbound": True}, {"critical": 5}, {"inbound": 5.5})),
])
def test_tuning_that_would_write_anything_but_a_level_exclusions_and_thresholds_is_refused(tuning):
    with pytest.raises(crs.TuningRefused):
        crs.checked(tuning)
