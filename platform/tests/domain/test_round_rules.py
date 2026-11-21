from datetime import datetime, timedelta, timezone

import pytest

from domain.round_rules import (
    END_REASONS,
    AllocationState,
    Matchup,
    Phase,
    RoundState,
    Side,
    ended,
    human_players,
    may_end,
    may_start_scored,
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


def test_a_scored_round_may_not_start_on_an_allocation_where_an_objective_fell():
    assert may_start_scored(AllocationState(objective_fallen=False)) is True
    assert may_start_scored(AllocationState(objective_fallen=True)) is False


def test_each_matchup_players_humans_where_it_says():
    assert human_players(Matchup.PVP) == (Side.ATTACK, Side.DEFENCE)
    assert human_players(Matchup.DEF_VS_BOT) == (Side.DEFENCE,)
    assert human_players("atk_vs_bot") == (Side.ATTACK,)


def test_end_reasons_include_the_manual_ones():
    assert {"ended_by_operator", "forfeit_attack", "forfeit_defence", "allocation_expired"} <= set(END_REASONS)
