import pytest

import plays


@pytest.fixture(scope="module")
def scored_by(full_run):
    return full_run["scored_by"]


@pytest.mark.parametrize("strategy", ["marker", "window"])
def test_a_strategy_scores_only_declared_cases(full_run, scored_by, strategy):
    declared = {case["name"] for case in full_run["declared"]}

    assert set(plays.per_case(scored_by[strategy])) <= declared, (
        "a free action entered the per-case outcomes; the platform never decides whether a free action was an attack"
    )


def test_forcing_time_windows_never_credits_more_than_the_markers_prove(scored_by):
    marker = plays.totals(scored_by["marker"])
    window = plays.totals(scored_by["window"])

    assert marker["tp"] > 0
    assert window["tp"] <= marker["tp"], (
        f"marker {marker['tp']} vs window {window['tp']} - cases fired back to back from one origin share "
        f"their windows, so time alone can only blur what the markers tell apart, never add to it"
    )
