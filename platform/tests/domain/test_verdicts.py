from datetime import datetime, timezone

import pytest

from domain.verdicts import Probe, table
from domain.types import DetectionRecord

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
PROBES = [
    Probe("sqli", True, "m-sqli", expect="SQL"),
    Probe("xss", True, "m-xss", expect="XSS"),
    Probe("browse", False, "m-browse"),
    Probe("sqlmap", True, "m-sqlmap", expect="SQL", tool_case=True),
    Probe("traversal", True, "m-trav", recorded=False),
]


def alert(n, marker, signature, rule="1000001"):
    return DetectionRecord(f"a{n}", T0, None, marker, engine="suricata", rule=rule, signature=signature)


def test_an_ids_table_gives_each_recorded_case_one_verdict():
    alerts = [alert(1, "m-sqli", "SQL injection"), alert(2, "m-sqli", "SQL injection"),
              alert(3, "m-sqlmap", "SQL injection")]

    result = table(PROBES, alerts, "ids")

    assert [(c.case, c.verdict, c.corroborated, c.recorded_run) for c in result.cases] == [
        ("sqli", "tp", True, False), ("xss", "fn", False, False), ("browse", "tn", None, False),
        ("sqlmap", "tp", True, True)]
    assert result.cases[0].alerts == (("1000001", "SQL injection"), ("1000001", "SQL injection"))
    assert dict(result.totals) == {"tp": 2, "fn": 1, "fp": 0, "tn": 1}
    assert [(u.case, u.reason) for u in result.untested] == [("traversal", "not_recorded")]


def test_the_waf_cannot_replay_a_tool_case():
    result = table(PROBES, [], "waf")

    assert [(u.case, u.reason) for u in result.untested] == [("sqlmap", "tool_case"), ("traversal", "not_recorded")]
    assert "sqlmap" not in [c.case for c in result.cases]


def test_a_block_everything_rule_shows_its_false_positive_and_corroborates_nothing():
    alerts = [alert(n, marker, "block everything SQL XSS") for n, marker in enumerate(["m-sqli", "m-xss", "m-browse"])]

    result = table(PROBES[:3], alerts, "ids")

    assert result.total("fp") == 1
    assert all(c.corroborated is False for c in result.cases if c.malicious)


def test_against_applied_lists_only_the_cases_whose_verdict_moved():
    applied = table(PROBES[:3], [alert(1, "m-sqli", "SQL injection")], "ids")
    candidate = table(PROBES[:3], [alert(1, "m-sqli", "SQL injection"), alert(2, "m-xss", "XSS script")], "ids", applied)

    assert [(c.case, c.was, c.now) for c in candidate.against_applied] == [("xss", "fn", "tp")]
    assert table(PROBES[:3], [], "ids").against_applied == ()


def test_an_unknown_engine_is_refused():
    with pytest.raises(ValueError):
        table(PROBES, [], "firewall")
