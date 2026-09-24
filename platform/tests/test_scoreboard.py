from scoreboard import DETECTED_WEIGHT, Breach, tally

def breach(difficulty, detected, key="k"):
    return Breach(
        key=key, name=key, category="Injection",
        difficulty=difficulty, detected=detected, detection_ids=("d1",) if detected else (),
    )

def test_an_untouched_session_is_full_coverage_not_zero():
    scored = tally([], false_positives=0)

    assert scored.objectives == 0
    assert scored.coverage == 1.0
    assert scored.damage == 0

def test_an_undetected_breach_costs_more_than_a_detected_one():
    seen = tally([breach(4, detected=True)], false_positives=0)
    missed = tally([breach(4, detected=False)], false_positives=0)

    assert missed.damage > seen.damage
    assert seen.damage == 4 * DETECTED_WEIGHT
    assert missed.damage == 4

def test_coverage_weighs_by_difficulty_not_by_count():
    scored = tally(
        [breach(1, True, "a"), breach(1, True, "b"), breach(6, False, "c")],
        false_positives=0,
    )

    assert scored.objectives == 3
    assert scored.detected_difficulty == 2
    assert scored.undetected_difficulty == 6
    assert scored.coverage == 2 / 8

def test_false_positives_are_reported_beside_damage_never_inside_it():
    quiet = tally([breach(3, detected=True)], false_positives=0)
    noisy = tally([breach(3, detected=True)], false_positives=9)

    assert noisy.damage == quiet.damage
    assert noisy.false_positives == 9

from datetime import datetime, timedelta, timezone

from scoreboard import ATTRIBUTION_WINDOW, Attempt, attribute

T0 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

def attempt(seconds, case_id="c", detected=True, lasted=0, malicious=True):
    started_at = T0 + timedelta(seconds=seconds)
    return Attempt(
        case_id=case_id, started_at=started_at,
        ended_at=started_at + timedelta(seconds=lasted),
        malicious=malicious,
        detected=detected, detection_ids=("d",) if detected else (),
    )

def test_an_objective_is_credited_to_the_last_attempt_before_it():
    attempts = [attempt(0, "first"), attempt(10, "second")]

    credited = attribute(T0 + timedelta(seconds=12), attempts)

    assert credited.case_id == "second"

def test_polling_lag_does_not_lose_the_attribution():
    credited = attribute(T0 + timedelta(seconds=5), [attempt(0)])

    assert credited is not None

def test_an_objective_nobody_was_attacking_for_belongs_to_nobody():
    stale = T0 + ATTRIBUTION_WINDOW + timedelta(seconds=1)

    assert attribute(stale, [attempt(0)]) is None

def test_an_objective_before_any_attempt_belongs_to_nobody():
    assert attribute(T0 - timedelta(seconds=1), [attempt(0)]) is None

from scoreboard import corroborated

ANOMALY = "Inbound Anomaly Score Exceeded (Total Score: 5)"

def test_a_case_that_declares_nothing_is_not_judged():
    assert corroborated(None, ["FSL SQLi attempt - URI"]) is None
    assert corroborated("", ["FSL SQLi attempt - URI"]) is None

def test_evidence_matching_the_mechanism_corroborates():
    assert corroborated("SQL", ["FSL SQLi attempt - request body"]) is True
    assert corroborated("SQL", ["SQL Injection Attack Detected via libinjection"]) is True

def test_the_match_is_case_insensitive_because_signatures_are_prose():
    assert corroborated("traversal", ["FSL path traversal attempt"]) is True
    assert corroborated("TRAVERSAL", ["FSL path traversal attempt"]) is True

def test_an_alert_about_something_else_does_not_corroborate():
    assert corroborated("traversal", ["FSL XSS attempt - script tag"]) is False

def test_a_generic_anomaly_alert_alone_does_not_corroborate():
    assert corroborated("SQL", [ANOMALY]) is False
    assert corroborated("SQL", [ANOMALY, "SQL Injection Attack Detected"]) is True


def test_a_deed_stamped_just_before_its_own_attack_still_belongs_to_it():
    attempts = [attempt(0, "before"), attempt(0.33, "took-it")]

    credited = attribute(
        T0 + timedelta(seconds=0.33) - timedelta(milliseconds=25), attempts
    )

    assert credited.case_id == "took-it"

def test_a_deed_long_before_an_attack_is_not_dragged_into_it():
    attempts = [attempt(0, "before"), attempt(0.33, "after")]

    credited = attribute(
        T0 + timedelta(seconds=0.33) - timedelta(milliseconds=200), attempts
    )

    assert credited.case_id == "before"

def test_a_signature_that_also_fires_on_traffic_meant_to_pass_corroborates_nothing():
    catch_all = "SQL XSS traversal Restricted File"

    assert corroborated("SQL", [catch_all], indiscriminate={catch_all}) is False, (
        "the defence writes the signature text, so one rule whose msg contains "
        "every expect value in the case file corroborates every attack. The "
        "block-everything defence the case file says must not win, wins"
    )

def test_a_signature_that_only_ever_fired_on_the_attack_still_corroborates():
    assert corroborated(
        "SQL", ["FSL SQLi attempt - URI"], indiscriminate={"FSL deliberate false positive"}
    ) is True

def test_a_case_with_one_discriminating_alert_among_noise_is_corroborated():
    assert corroborated(
        "SQL",
        ["SQL XSS traversal Restricted File", "FSL SQLi attempt - URI"],
        indiscriminate={"SQL XSS traversal Restricted File"},
    ) is True, (
        "one indiscriminate alert alongside a real one hid the real one"
    )

def test_nothing_indiscriminate_is_the_same_answer_as_before():
    assert corroborated("SQL", ["FSL SQLi attempt - URI"], indiscriminate=set()) is True
    assert corroborated("SQL", ["FSL XSS attempt"], indiscriminate=set()) is False
    assert corroborated(None, ["anything"], indiscriminate=set()) is None


def test_a_breach_late_in_a_long_window_belongs_to_that_window():
    window = attempt(0, "terminal", lasted=300)

    credited = attribute(T0 + timedelta(seconds=181), [window])

    assert credited is window, (
        "a five-minute terminal window took an objective three minutes in and "
        "the breach was scored as nobody's, undetected at full damage, because "
        "only the window's first two minutes counted"
    )


def test_traffic_meant_to_pass_never_takes_an_objective():
    browsing = attempt(0, "benign-browse", detected=True, malicious=False)

    assert attribute(T0 + timedelta(seconds=5), [browsing]) is None, (
        "a benign case's false positive 'detected' a breach it could not have "
        "caused, and the breach was scored as caught"
    )


def test_the_target_s_own_stamp_is_not_stretched_to_a_case_long_finished():
    finished = attempt(0, "sqli", lasted=0.02)
    stamped = T0 + timedelta(seconds=75)

    credited = attribute(
        stamped, [finished],
        earliest=stamped - timedelta(milliseconds=100),
        latest=stamped + timedelta(milliseconds=101),
    )

    assert credited is None, (
        "the target stamped the breach 75 seconds after the only case had "
        "finished, and the two-minute allowance meant for polling lag handed "
        "it to that case"
    )


def test_a_stamp_truncated_to_the_second_still_reaches_its_own_case():
    took_it = attempt(1.5, "ssrf", lasted=0.2)
    truncated = T0 + timedelta(seconds=1)

    credited = attribute(
        truncated, [took_it],
        earliest=truncated - timedelta(milliseconds=100),
        latest=truncated + timedelta(seconds=1, milliseconds=100),
    )

    assert credited is took_it
