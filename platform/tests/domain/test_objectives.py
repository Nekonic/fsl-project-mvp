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
from domain.types import RESPONSE_ORIGIN, RESPONSE_VERSION, CaseRecord, DetectionRecord, ObjectiveRecord, ResponseRecord

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def attempt(start, case_id="sqli", lasted=1, detected=False, malicious=True):
    return Attempt(case_id=case_id, marker=case_id, started_at=T0 + timedelta(seconds=start),
                   ended_at=T0 + timedelta(seconds=start + lasted), malicious=malicious,
                   detected=detected, detection_ids=("d1",) if detected else ())


def breach(key, difficulty, responded, detected=True):
    return Breach(key=key, name=key, category="c", difficulty=difficulty, detected=detected, responded=responded,
                  response_seconds=None, attributed_marker=None, detection_ids=())


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def sqli(marker, start, source_ip="198.51.100.7", expect=None, malicious=True):
    return CaseRecord("sqli", "sqli", malicious, "marker", marker, source_ip, at(start), at(start + 2), expect=expect)


def lost_at(seconds):
    return [ObjectiveRecord("db", "db", "loot", 3, achieved_at=at(seconds))]


def scored(cases, alerts, responses=(), taken=30):
    return breaches(lost_at(taken), attempts(cases, correlate(cases, alerts), alerts), responses)[0]


def test_an_untouched_round_has_no_coverage_and_no_damage():
    board = tally([], false_positives=0)

    assert (board.objectives, board.coverage, board.damage) == (0, None, 0)


def test_an_objective_lost_without_a_response_counts_double_whatever_detection_says():
    assert tally([breach("a", 3, False, detected=True)], 0).damage == 2 * tally([breach("a", 3, True)], 0).damage
    assert tally([breach("a", 3, False, detected=True)], 0).damage == tally([breach("a", 3, False, False)], 0).damage


def test_tier_difficulty_is_the_weight():
    board = tally([breach("easy", 1, True), breach("hard", 4, False, detected=False)], 0)

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

    lost = breaches(objectives, attempts(cases, result, [DetectionRecord("d1", T0, None, "m-sqli")]))

    assert [(b.key, b.detected, b.attributed_marker, b.detection_ids) for b in lost] == [
        ("db", True, "m-sqli", ("d1",))]


def test_a_case_fired_again_later_does_not_lend_its_alert_to_the_firing_that_took_the_objective():
    cases = [CaseRecord("sqli", "sqli", True, "marker", "m1", None, T0, T0 + timedelta(seconds=2)),
             CaseRecord("sqli", "sqli", True, "marker", "m2", None, T0 + timedelta(minutes=5),
                        T0 + timedelta(minutes=5, seconds=2))]
    alerts = [DetectionRecord("a", T0 + timedelta(minutes=5), None, "m2")]
    result = correlate(cases, alerts)
    objectives = [ObjectiveRecord("db", "db", "loot", 3, achieved_at=T0 + timedelta(seconds=10))]

    lost = breaches(objectives, attempts(cases, result, alerts))

    assert [(b.detected, b.attributed_marker, b.detection_ids) for b in lost] == [(False, "m1", ())]


def test_a_plain_request_sent_after_a_detected_attack_leaves_the_loss_detected():
    cases = [sqli("m-attack", 0), sqli("m-noise", 20, malicious=None)]

    assert scored(cases, [DetectionRecord("d1", at(1), None, "m-attack")]).detected is True


def test_an_alert_that_misses_the_attack_s_mechanism_does_not_detect_it():
    cases = [sqli("m-attack", 0, expect="sql injection")]

    assert scored(cases, [DetectionRecord("d1", at(1), None, "m-attack", signature="ET SCAN Nmap")]).detected is False


def test_a_detected_loss_with_no_response_counts_full():
    found = scored([sqli("m-attack", 0)], [DetectionRecord("d1", at(1), None, "m-attack")])

    assert (found.detected, found.responded, found.response_seconds) == (True, False, None)
    assert tally([found], 0).damage == 3


def refusing(seconds, *markers):
    return ResponseRecord(at(seconds), RESPONSE_VERSION, replayed=frozenset(markers), refused=frozenset(markers))


def test_a_version_applied_after_the_first_action_answers_a_loss_no_alert_saw():
    found = scored([sqli("m-attack", 0)], [], [refusing(10, "m-attack")])

    assert (found.detected, found.responded, found.response_seconds) == (False, True, None)
    assert tally([found], 0).damage == 1.5


def test_a_version_answers_a_loss_only_when_its_test_replayed_the_attack_s_requests_and_refused_them():
    cases = [sqli("m-attack", 0), sqli("m-probe", 3)]
    untested = ResponseRecord(at(10), RESPONSE_VERSION)
    other = refusing(10, "m-elsewhere")
    let_through = ResponseRecord(at(10), RESPONSE_VERSION, replayed=frozenset({"m-attack", "m-probe"}),
                                 refused=frozenset({"m-attack"}))

    assert [scored(cases, [], [one]).responded for one in (untested, other, let_through)] == [False, False, False]
    assert scored(cases, [], [refusing(10, "m-attack", "m-probe")]).responded is True


def test_a_plain_request_the_waf_let_through_does_not_cancel_a_version_that_refused_the_attack():
    cases = [sqli("m-attack", 0), sqli("m-noise", 5, malicious=None)]
    refused_attack = ResponseRecord(at(10), RESPONSE_VERSION, replayed=frozenset({"m-attack", "m-noise"}),
                                    refused=frozenset({"m-attack"}))

    assert scored(cases, [DetectionRecord("d1", at(1), None, "m-attack")], [refused_attack]).responded is True


def test_a_version_applied_before_the_first_alert_is_no_response_to_it():
    found = scored([sqli("m-attack", 5)], [DetectionRecord("d1", at(8), None, "m-attack")],
                   [refusing(6, "m-attack")])

    assert found.responded is False


def test_the_response_time_runs_from_the_first_alert_to_the_first_response():
    found = scored([sqli("m-attack", 0)], [DetectionRecord("d1", at(1), None, "m-attack")],
                   [refusing(25, "m-attack"), ResponseRecord(at(13), RESPONSE_ORIGIN, "198.51.100.7")])

    assert (found.responded, found.response_seconds) == (True, 12.0)


def test_spending_another_origin_or_acting_after_the_theft_is_no_response():
    found = scored([sqli("m-attack", 0)], [DetectionRecord("d1", at(1), None, "m-attack")],
                   [ResponseRecord(at(10), RESPONSE_ORIGIN, "203.0.113.9"), refusing(31, "m-attack")])

    assert found.responded is False


def test_benign_traffic_is_never_part_of_a_loss():
    found = scored([sqli("m-customer", 0, malicious=False)], [DetectionRecord("d1", at(1), None, "m-customer")],
                   [refusing(10, "m-customer")])

    assert (found.detected, found.responded, found.attributed_marker) == (False, False, None)
