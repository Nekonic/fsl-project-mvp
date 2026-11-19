from shared_sessions import CONTROL, verdicts_of


def test_both_strategies_find_the_same_declared_attack(terminal_windows):
    by_marker = verdicts_of(terminal_windows["by"]["marker"])
    by_window = verdicts_of(terminal_windows["by"]["window"])

    assert by_marker[CONTROL] == "tp", "the marker path missed a case it had stamped"
    assert by_window[CONTROL] == "tp", "the window path missed a case fired alone from its own source"
