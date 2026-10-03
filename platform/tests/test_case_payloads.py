from pathlib import Path

import yaml

ALLOWED_REQUEST_KEYS = {"method", "path", "headers", "json", "params"}
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
