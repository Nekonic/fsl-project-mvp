from shared_sessions import verdicts_of


def test_an_unlabelled_attack_is_scored_by_time_and_source(terminal_windows):
    assert verdicts_of(terminal_windows["score"])["terminal-sqli"] == "TP"


def test_benign_terminal_traffic_in_its_own_window_stays_clean(terminal_windows):
    assert terminal_windows["sqli_seen_by_both"], (
        "the attack sent after the benign request was not seen by both engines, "
        "so an alert the benign request drew may not have landed yet and a clean "
        "benign window proves nothing"
    )

    assert verdicts_of(terminal_windows["score"])["terminal-benign"] == "TN"


def test_the_match_was_made_without_a_marker(terminal_windows):
    matched = {
        detection_id
        for case in terminal_windows["score"]["per_case"]
        if case["name"] == "terminal-sqli"
        for detection_id in case["detection_ids"]
    }
    assert matched, "nothing was attributed to the attack window"

    markers = {d["marker"] for d in terminal_windows["detections"] if d["detection_id"] in matched}
    assert markers == {None}, f"expected unlabelled traffic, saw markers {markers}"
