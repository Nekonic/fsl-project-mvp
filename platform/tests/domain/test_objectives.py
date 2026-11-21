from datetime import datetime, timedelta, timezone

from domain.scoring.correlate import correlate
from domain.scoring.objectives import (
    ATTRIBUTION_WINDOW,
    Attempt,
    Breach,
    attempts,
    attribute,
    breaches,
    tally,
)
from domain.types import CaseRecord, DetectionRecord, ObjectiveRecord

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def attempt(start, case_id="sqli", lasted=1, detected=False, malicious=True):
    return Attempt(case_id=case_id, marker=case_id, started_at=T0 + timedelta(seconds=start),
                   ended_at=T0 + timedelta(seconds=start + lasted), malicious=malicious,
                   detected=detected, detection_ids=("d1",) if detected else ())


def breach(key, difficulty, detected):
    return Breach(key=key, name=key, category="c", difficulty=difficulty, detected=detected,
                  attributed_marker=None, detection_ids=())


def test_an_untouched_round_has_no_coverage_and_no_damage():
    board = tally([], false_positives=0)

    assert (board.objectives, board.coverage, board.damage) == (0, None, 0)


def test_an_objective_lost_and_undetected_counts_double():
    assert tally([breach("a", 3, False)], 0).damage == 2 * tally([breach("a", 3, True)], 0).damage


def test_tier_difficulty_is_the_weight():
    board = tally([breach("easy", 1, True), breach("hard", 4, False)], 0)

    assert board.coverage == 1 / 5
    assert board.damage == 4 + 0.5 * 1


def test_false_positives_are_reported_beside_damage_never_inside_it():
    quiet = tally([breach("a", 2, False)], 0)
    noisy = tally([breach("a", 2, False)], 40)

    assert noisy.damage == quiet.damage
    assert noisy.false_positives == 40


def test_an_objective_is_credited_to_the_last_attempt_before_it():
    assert attribute(T0 + timedelta(seconds=12), [attempt(0, "first"), attempt(10, "second")]).case_id == "second"


def test_attribution_reaches_back_two_minutes_and_no_further():
    assert attribute(T0 + timedelta(seconds=5), [attempt(0)]) is not None
    assert attribute(T0 + ATTRIBUTION_WINDOW + timedelta(seconds=2), [attempt(0)]) is None
    assert attribute(T0 - timedelta(seconds=1), [attempt(0)]) is None


def test_a_deed_stamped_just_before_its_own_attack_still_belongs_to_it():
    credited = attribute(T0 + timedelta(seconds=0.33) - timedelta(milliseconds=25),
                         [attempt(0, "before"), attempt(0.33, "took-it")])

    assert credited.case_id == "took-it"


def test_a_breach_late_in_a_long_window_belongs_to_that_window():
    window = attempt(0, "terminal", lasted=300)

    assert attribute(T0 + timedelta(seconds=181), [window]) is window


def test_traffic_meant_to_pass_never_takes_an_objective_but_a_free_action_may():
    browsing = attempt(0, "benign-browse", detected=True, malicious=False)
    free = attempt(0, "a9", malicious=None)

    assert attribute(T0 + timedelta(seconds=5), [browsing]) is None
    assert attribute(T0 + timedelta(seconds=5), [browsing, free]) is free


def test_the_target_s_own_stamp_bounds_the_window():
    stamped = T0 + timedelta(seconds=75)

    assert attribute(stamped, [attempt(0, lasted=0.02)], earliest=stamped - timedelta(milliseconds=100),
                     latest=stamped + timedelta(milliseconds=101)) is None


def test_breaches_attribute_each_lost_objective_and_skip_kept_ones():
    cases = [CaseRecord("sqli", "sqli", True, "marker", "m-sqli", None, T0, T0 + timedelta(seconds=2))]
    result = correlate(cases, [DetectionRecord("d1", T0, None, "m-sqli")])
    objectives = [
        ObjectiveRecord("db", "db", "loot", 3, achieved_at=T0 + timedelta(seconds=1)),
        ObjectiveRecord("admin", "admin", "loot", 2),
    ]

    lost = breaches(objectives, attempts(cases, result))

    assert [(b.key, b.detected, b.attributed_marker, b.detection_ids) for b in lost] == [
        ("db", True, "m-sqli", ("d1",))]


def test_a_case_fired_again_later_does_not_lend_its_alert_to_the_firing_that_took_the_objective():
    cases = [CaseRecord("sqli", "sqli", True, "marker", "m1", None, T0, T0 + timedelta(seconds=2)),
             CaseRecord("sqli", "sqli", True, "marker", "m2", None, T0 + timedelta(minutes=5),
                        T0 + timedelta(minutes=5, seconds=2))]
    result = correlate(cases, [DetectionRecord("a", T0 + timedelta(minutes=5), None, "m2")])
    objectives = [ObjectiveRecord("db", "db", "loot", 3, achieved_at=T0 + timedelta(seconds=10))]

    lost = breaches(objectives, attempts(cases, result))

    assert [(b.detected, b.attributed_marker, b.detection_ids) for b in lost] == [(False, "m1", ())]
