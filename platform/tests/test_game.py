from datetime import datetime, timedelta, timezone

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


def test_an_undetected_attack_scores_zero_speed():
    assert game.speed([attempt("a", True, "initial-compromise", None)]) == 0.0


def test_coverage_is_detected_stages_over_attacked_stages():
    attempts = [
        attempt("a", True, "initial-reconnaissance", 5),
        attempt("b", True, "initial-compromise", None),
        attempt("c", True, "complete-mission", 5),
    ]

    assert game.coverage(attempts) == 2 / 3


def test_benign_traffic_is_not_counted_in_coverage_or_speed():
    attempts = [
        attempt("a", True, "initial-compromise", 5),
        attempt("b", False, "", None),
    ]

    assert game.coverage(attempts) == 1.0
    assert game.speed(attempts) == 1.0


def test_accuracy_falls_when_benign_traffic_raises_alerts():
    clean = game.accuracy(tp=3, fp=0, fn=0, tn=3)
    noisy = game.accuracy(tp=3, fp=3, fn=0, tn=0)

    assert clean > noisy


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


def test_response_is_absent_until_something_is_blocked():
    attempts = [attempt("a", True, "initial-compromise", 5)]

    assert game.response(attempts) is None


def test_blocking_an_attack_raises_response_and_blocking_a_benign_lowers_it():
    stopped = game.response([attempt("a", True, "initial-compromise", 5, blocked=True)])
    collateral = game.response([
        attempt("a", True, "initial-compromise", 5, blocked=True),
        attempt("b", False, "", None, blocked=True),
    ])

    assert stopped == 1.0
    assert collateral < stopped


def test_blocking_the_attack_lifts_the_defender_balance():
    taken = [game.Taken(key="x", difficulty=4, detected=True)]

    passed = game.settle(
        [attempt("a", True, "initial-compromise", 60)], taken, tp=1, fp=0, fn=0, tn=1
    )
    blocked = game.settle(
        [attempt("a", True, "initial-compromise", 60, blocked=True)],
        taken, tp=1, fp=0, fn=0, tn=1,
    )

    assert blocked.response == 1.0
    assert passed.response is None
    assert blocked.balance > passed.balance


def test_the_pillars_are_reported_beside_the_balance():
    settled = game.settle(
        [attempt("a", True, "initial-compromise", 5)],
        [game.Taken(key="x", difficulty=4, detected=True)],
        tp=1, fp=0, fn=0, tn=1,
    )

    assert 0.0 <= settled.speed <= 1.0
    assert 0.0 <= settled.coverage <= 1.0
    assert 0.0 <= settled.accuracy <= 1.0
    assert settled.response is None
