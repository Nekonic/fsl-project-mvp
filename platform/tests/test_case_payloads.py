import re
from pathlib import Path

import yaml

ALLOWED_REQUEST_KEYS = {"method", "path", "headers", "json", "data", "params", "prefetch"}
CASES_DIR = Path(__file__).resolve().parents[2] / "cases"


def _request_specs():
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            spec = case.get("request")
            if spec:
                yield path.name, case.get("name"), spec


def test_every_request_case_is_one_the_harness_can_send_as_written():
    offenders = [
        (file, name, sorted(set(spec) - ALLOWED_REQUEST_KEYS))
        for file, name, spec in _request_specs()
        if set(spec) - ALLOWED_REQUEST_KEYS
    ]
    assert offenders == [], offenders

    for file, name, spec in _request_specs():
        pre = spec.get("prefetch")
        if not pre:
            continue
        assert set(pre) <= {"from", "pattern"}, (file, name, sorted(pre))
        assert pre.get("from", "").startswith("/"), (file, name)
        assert re.compile(pre["pattern"]).groups >= 1, (
            f"{file}:{name} prefetch pattern must have a capturing group for the token"
        )


def test_every_attack_case_names_what_its_alert_must_mention_and_every_case_name_is_unique_across_files():
    cases = [case for path in sorted(CASES_DIR.glob("*.yaml"))
             for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []]
    names = [case["name"] for case in cases]

    assert [case["name"] for case in cases if case["malicious"] and not case.get("expect")] == [], (
        "a true positive is corroborated only against the case's expect")
    assert [case["name"] for case in cases if not case["malicious"] and "expect" in case] == []
    assert sorted(name for name in set(names) if names.count(name) > 1) == []


def test_every_case_carries_a_korean_title_for_the_learner():
    cases = [case for path in sorted(CASES_DIR.glob("*.yaml"))
             for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []]

    assert [case["name"] for case in cases
            if not re.search("[가-힣]", str(case.get("title") or ""))] == []
