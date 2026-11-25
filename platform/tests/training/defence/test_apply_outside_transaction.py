from django.db import connection

from sandbox import crs, suricata
from training.defence import rules as service
from tests.training.defence.conftest import SEARCH_RULE

EXCLUSIONS = "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf"
EXCLUDE_Q = 'SecRule REQUEST_FILENAME "@beginsWith /search/" "id:10001,phase:1,pass,nolog"\n'


def watched(monkeypatch, module, names):
    depths: list[tuple[str, int]] = []
    for name in names:
        original = getattr(module, name)

        def seen(*args, _name=name, _original=original, **kwargs):
            depths.append((_name, len(connection.atomic_blocks)))
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, seen)
    return depths


def test_an_ids_apply_writes_the_sensor_with_no_transaction_open_and_records_it_after(board_round, monkeypatch):
    outside = len(connection.atomic_blocks)
    depths = watched(monkeypatch, suricata, ("apply", "current", "reloaded"))

    applied = service.apply_ids(board_round, SEARCH_RULE, 0)

    assert applied.rule_set.version == 1
    assert "apply" in {name for name, _ in depths}
    assert all(depth == outside for _, depth in depths), depths


def test_a_waf_apply_writes_the_waf_with_no_transaction_open_and_records_it_after(board_round, monkeypatch):
    outside = len(connection.atomic_blocks)
    depths = watched(monkeypatch, crs, ("apply", "read", "reloaded"))

    applied = service.apply_waf(board_round, {EXCLUSIONS: EXCLUDE_Q}, 0, source=service.SETUP)

    assert applied.rule_set.version == 1
    assert "apply" in {name for name, _ in depths}
    assert all(depth == outside for _, depth in depths), depths
