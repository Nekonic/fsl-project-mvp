from pathlib import Path

import yaml

ALLOWED_REQUEST_KEYS = {"method", "path", "headers", "json", "data", "params", "prefetch"}
CASES_DIR = Path(__file__).resolve().parents[2] / "redteam" / "cases"


def _request_specs():
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            spec = case.get("request")
            if spec:
                yield path.name, case.get("name"), spec


def test_every_request_case_uses_only_keys_the_harness_sends():
    offenders = [
        (file, name, sorted(set(spec) - ALLOWED_REQUEST_KEYS))
        for file, name, spec in _request_specs()
        if set(spec) - ALLOWED_REQUEST_KEYS
    ]
    assert offenders == [], offenders


def test_prefetch_specs_name_a_page_and_a_capturing_pattern():
    import re
    for file, name, spec in _request_specs():
        pre = spec.get("prefetch")
        if not pre:
            continue
        assert set(pre) <= {"from", "pattern"}, (file, name, sorted(pre))
        assert pre.get("from", "").startswith("/"), (file, name)
        assert re.compile(pre["pattern"]).groups >= 1, (
            f"{file}:{name} prefetch pattern must have a capturing group for the token"
        )
