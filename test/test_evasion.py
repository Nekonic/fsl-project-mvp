r"""A payload the rules were written for must not escape by changing clothes.

Spaces in a query string can be sent as `%20` or as `+`. Both mean a space to
the application; only one of them looks like whitespace to a `\s` in a pcre,
so the same injection matched the IDS rules one way and slid past them the
other.

The *stack* was never blind to it - ModSecurity catches it by other means, so a
combined verdict says "detected" either way. That is defence in depth doing its
job, and it is also why this went unnoticed for so long. These tests ask which
engine fired, because a rule set that matches an encoding rather than an attack
is worth knowing about while the other engine is still covering for it.
"""

import pytest
import requests

from conftest import PLATFORM_URL, score_when_ready

PLUS = "sqli-or-1-1-plus-encoded"
PERCENT = "sqli-login-bypass"


@pytest.fixture(scope="module")
def fired(stack_is_up):
    """The same class of injection twice, encoded two ways, scored once."""
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={}, timeout=120
    ).json()["id"]
    for case in (PERCENT, PLUS):
        sent = requests.post(
            f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
            json={"case": case}, timeout=300,
        )
        assert sent.status_code == 201, sent.text
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=60)

    # Wait on the control *case*, not on the session. Ingest pulls everything
    # in the session's time window, so a session opened next to another one
    # inherits its alerts - and a readiness check that only asks "have both
    # engines appeared" is satisfied by somebody else's traffic before this
    # session's own has landed.
    def control_seen_by_both(totals):
        control = next(
            (c for c in totals["per_case"] if c["name"] == PERCENT), None
        )
        if not control or not control["detected"]:
            return False
        by_id = {
            d["detection_id"]: d for d in requests.get(
                f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
            ).json()
        }
        sources = {
            by_id[d]["source"] for d in control["detection_ids"] if d in by_id
        }
        return {"suricata", "modsecurity"} <= sources

    score = score_when_ready(session_id, until=control_seen_by_both)
    detections = requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/detections/", timeout=120
    ).json()
    return score, {d["detection_id"]: d for d in detections}


def _case(fired, name):
    score, _ = fired
    return next(c for c in score["per_case"] if c["name"] == name)


def _engines(fired, name):
    _, by_id = fired
    return {
        by_id[d]["source"] for d in _case(fired, name)["detection_ids"] if d in by_id
    }


def test_both_encodings_are_detected_by_the_stack(fired):
    # Neither gets through. The question is what stopped them.
    assert _case(fired, PERCENT)["verdict"] == "TP"
    assert _case(fired, PLUS)["verdict"] == "TP"


def test_the_control_is_caught_by_both_engines(fired):
    # If this narrowed, the test below would pass for the wrong reason.
    assert {"suricata", "modsecurity"} <= _engines(fired, PERCENT)


def test_the_ids_catches_the_plus_encoding_too(fired):
    assert "suricata" in _engines(fired, PLUS), (
        f"only {sorted(_engines(fired, PLUS))} caught the plus-encoded "
        f"injection - the IDS rules match an encoding rather than an attack, "
        f"and the WAF is covering for them"
    )
