from datetime import datetime, timedelta, timezone

import pytest

import game

T0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def attempt(case_id, malicious, stage, delay_seconds, blocked=False):
    detected_at = None if delay_seconds is None else T0 + timedelta(seconds=delay_seconds)
    return game.Attempt(
        case_id=case_id, malicious=malicious, stage=stage,
        started_at=T0, detected_at=detected_at, blocked=blocked,
    )


def test_a_fast_detection_scores_higher_speed_than_a_slow_one():
    fast = game.speed([attempt("a", True, "initial-compromise", 5)])
    slow = game.speed([attempt("a", True, "initial-compromise", 90)])

    assert fast > slow
    assert 0.0 <= slow < fast <= 1.0
    assert game.speed([attempt("a", True, "initial-compromise", None)]) == 0.0


def test_coverage_is_detected_stages_over_attacked_stages():
    attempts = [
        attempt("a", True, "initial-reconnaissance", 5),
        attempt("b", True, "initial-compromise", None),
        attempt("c", True, "complete-mission", 5),
    ]

    assert game.coverage(attempts) == 2 / 3
    assert game.coverage([attempt("a", True, "initial-compromise", None),
                          attempt("b", True, "initial-compromise", 5)]) == 1.0, (
        "coverage dedups by stage: one detected attempt covers the stage")


def test_benign_traffic_is_not_counted_in_coverage_or_speed():
    attempts = [
        attempt("a", True, "initial-compromise", 5),
        attempt("b", False, "", None),
    ]

    assert game.coverage(attempts) == 1.0
    assert game.speed(attempts) == 1.0


def test_an_undetected_objective_is_worth_more_to_the_attacker():
    taken = game.attacker_take([game.Taken(key="x", difficulty=4, detected=False)])
    caught = game.attacker_take([game.Taken(key="x", difficulty=4, detected=True)])

    assert taken > caught > 0


def test_a_false_positive_tips_the_balance_toward_the_attacker():
    attempts = [attempt("a", True, "initial-compromise", 5)]
    taken = [game.Taken(key="x", difficulty=4, detected=True)]

    clean = game.settle(attempts, taken, tp=1, fp=0, fn=0, tn=2)
    noisy = game.settle(attempts, taken, tp=1, fp=2, fn=0, tn=0)

    assert noisy.balance < clean.balance


def test_a_strong_defence_ends_ahead_and_a_breached_one_behind():
    attempts = [
        attempt("a", True, "initial-reconnaissance", 4),
        attempt("b", True, "initial-compromise", 4),
    ]
    strong = game.settle(
        attempts,
        [game.Taken(key="x", difficulty=5, detected=True)],
        tp=2, fp=0, fn=0, tn=3,
    )

    missed = [
        attempt("a", True, "initial-reconnaissance", None),
        attempt("b", True, "initial-compromise", None),
    ]
    weak = game.settle(
        missed,
        [game.Taken(key="x", difficulty=5, detected=False)],
        tp=0, fp=3, fn=2, tn=0,
    )

    assert strong.balance > 0 > weak.balance


def test_blocking_an_attack_raises_response_and_blocking_a_benign_lowers_it():
    stopped = game.response([attempt("a", True, "initial-compromise", 5, blocked=True)])
    collateral = game.response([
        attempt("a", True, "initial-compromise", 5, blocked=True),
        attempt("b", False, "", None, blocked=True),
    ])

    assert stopped == 1.0
    assert collateral < stopped


def test_an_absent_response_pillar_redistributes_its_weight_not_scores_it_zero():
    settled = game.settle(
        [attempt("a", True, "initial-compromise", 5)],
        [game.Taken(key="x", difficulty=4, detected=True)],
        tp=1, fp=0, fn=0, tn=1,
    )

    assert settled.response is None
    assert settled.defender == pytest.approx(4.0), (
        "the three present pillars are perfect, so renormalising over 0.75 gives "
        "quality 1.0 and defender 4.0; scoring the absent response as 0.0 would "
        "give quality 0.75 and defender 3.0"
    )
    assert settled.attacker == 4 * game.DETECTED_TAKE
    assert settled.balance == settled.defender - settled.attacker
