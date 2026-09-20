"""The shipped attack cases have to take something.

Firing payloads that trip an IDS rule and achieve nothing is not an attack,
and a range whose red team achieves nothing cannot teach a blue team anything
about what it failed to stop. Before this, a full twelve-case run scored TP=6
and took zero objectives.

These run against the session the red team fixture already produced, so they
cost one poll rather than a second run.
"""

import pytest
import requests

from conftest import PLATFORM_URL

@pytest.fixture(scope="module")
def must_take(stack_is_up):
    """What the case file claims it takes, read from the case file.

    Repeating the list here would let the two drift, and the one that would
    quietly stop being true is this one.
    """
    catalogue = requests.get(
        f"{PLATFORM_URL}/api/wargames/juice-shop/cases/", timeout=60
    ).json()
    claimed = {case["takes"] for case in catalogue if case.get("takes")}
    assert claimed, "no case in redteam/cases/ claims to take an objective"
    return claimed


@pytest.fixture(scope="module")
def taken(session_id):
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=120)
    return requests.get(
        f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=60
    ).json()


def test_the_red_team_takes_objectives_at_all(taken):
    assert taken, (
        "a full run of redteam/cases/ achieved nothing the target recognises. "
        "The cases are firing payloads, not attacks."
    )


def test_every_objective_a_case_claims_actually_falls(taken, must_take):
    keys = {objective["key"] for objective in taken}

    assert must_take <= keys, f"claimed but not taken: {sorted(must_take - keys)}"


def test_what_was_taken_carries_a_difficulty_the_score_can_weigh(taken):
    assert all(objective["difficulty"] >= 1 for objective in taken)
    assert all(objective["category"] for objective in taken)
