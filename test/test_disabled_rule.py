from datetime import datetime, timezone

import pytest

import plays
from conftest import runs_the_declared_rules

SID = 9000001
DISABLED_CASE = "board-sqli-search"


@pytest.fixture(scope="module")
def disabled(stack_is_up):
    with plays.Round("board") as played:
        record = {"baseline": runs_the_declared_rules(played)}
        record["created"] = plays.disable_rule(played, SID, 10, "acceptance test")
        assert record["created"].status == 201, record["created"].text
        record["listed"] = plays.disabled_rules(played)
        record["listed_at"] = datetime.now(timezone.utc)
        record["rules_while_disabled"] = plays.ids_rules(played)["text"]
        marker = plays.fired(played, DISABLED_CASE)["marker"]
        listed = plays.alerts_until(played, lambda found: "waf" in plays.engines(found, marker))
        record["engines"] = plays.engines(listed, marker)
        record["enabled"] = plays.enable_rule(played, SID)
        record["listed_after"] = plays.disabled_rules(played)
        record["rules_after_enabling"] = plays.ids_rules(played)["text"]
    return record


def test_disabling_the_rule_silences_the_ids_on_the_attack_the_waf_still_logs(disabled):
    assert disabled["engines"] == {"waf"}, (
        f"with sid {SID} disabled the IDS behind the WAF still alerted on {DISABLED_CASE}, or the WAF's own "
        f"record of it never landed, so a silent IDS here proves nothing: {disabled['engines']}"
    )


def test_a_disabled_rule_is_on_the_books_with_a_deadline(disabled):
    live = [row for row in disabled["listed"] if row["sid"] == SID]

    assert live, "a disabled rule that nothing records is a rule disabled for good"
    assert live[0]["expires_at"] == disabled["created"].body["expires_at"]
    assert datetime.fromisoformat(live[0]["expires_at"].replace("Z", "+00:00")) > disabled["listed_at"]


def test_enabling_brings_the_rule_back(disabled):
    assert not any(
        line.startswith("alert") and f"sid:{SID};" in line
        for line in disabled["rules_while_disabled"].splitlines()
    )

    assert disabled["enabled"].status == 204, disabled["enabled"].text
    assert not [row for row in disabled["listed_after"] if row["sid"] == SID]
    assert disabled["rules_after_enabling"] == disabled["baseline"]
