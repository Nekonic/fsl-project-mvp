import pytest

import plays


@pytest.fixture(scope="module")
def scored_by(full_run):
    return full_run["scored_by"]


def test_forcing_time_windows_never_credits_more_than_the_markers_prove(scored_by):
    marker = plays.totals(scored_by["marker"])
    window = plays.totals(scored_by["window"])

    assert marker["tp"] > 0
    assert window["tp"] <= marker["tp"], (
        f"marker {marker['tp']} vs window {window['tp']} - cases fired back to back from one origin share "
        f"their windows, so time alone can only blur what the markers tell apart, never add to it"
    )
