from datetime import datetime, timedelta, timezone

import pytest

from domain.round_rules import (
    ALLOWED_MATCHUPS,
    Matchup,
    Phase,
    RoundState,
    Side,
    ended,
    may_end,
)

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def state(**fields):
    base = dict(phase=Phase.RUNNING, now=T0 + timedelta(seconds=60), started_at=T0, time_limit_s=None,
                objectives_total=2, objectives_lost=0, origins_total=3, origins_left=3, benign_passes=0)
    return RoundState(**{**base, **fields})


def test_a_running_round_with_nothing_happened_goes_on():
    assert ended(state()) is None


def test_the_time_limit_ends_the_round():
    assert ended(state(time_limit_s=60)) == "time_limit"
    assert ended(state(time_limit_s=61)) is None


def test_losing_every_objective_ends_the_round():
    assert ended(state(objectives_lost=2)) == "all_objectives_lost"
    assert ended(state(objectives_total=0, objectives_lost=0)) is None


def test_spent_origins_end_the_round_only_after_one_full_benign_pass():
    assert may_end(state(benign_passes=0)) is False
    assert ended(state(origins_left=0, benign_passes=0)) is None
    assert ended(state(origins_left=0, benign_passes=1)) == "origins_spent"


def test_a_round_without_origins_never_ends_on_origins():
    assert ended(state(origins_total=0, origins_left=0, benign_passes=5)) is None


@pytest.mark.parametrize("phase", [Phase.CREATED, Phase.STARTING, Phase.ENDED])
def test_only_a_running_round_ends(phase):
    assert ended(state(phase=phase, objectives_lost=2)) is None




def test_a_both_sides_problem_does_not_take_the_bot_vs_bot_matchup():
    assert Matchup.BOT_VS_BOT not in ALLOWED_MATCHUPS[Side.BOTH]
    assert ALLOWED_MATCHUPS[Side.BOTH] == {Matchup.PVP, Matchup.DEF_VS_BOT, Matchup.ATK_VS_BOT}
