from shared_sessions import verdicts_of


def test_both_strategies_find_the_same_attack(terminal_windows):
    by_marker = verdicts_of(terminal_windows["by"]["marker"])
    by_window = verdicts_of(terminal_windows["by"]["window"])

    assert by_marker["terminal-both-ways"] == "TP", "the marker path missed a window it had stamped"
    assert by_window["terminal-both-ways"] == "TP", "the window path missed traffic from its own source"
