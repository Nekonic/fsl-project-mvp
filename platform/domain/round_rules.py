from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Matchup(StrEnum):
    PVP = "pvp"
    DEF_VS_BOT = "def_vs_bot"
    ATK_VS_BOT = "atk_vs_bot"


class Phase(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    ENDED = "ended"


class Side(StrEnum):
    ATTACK = "attack"
    DEFENCE = "defence"
    BOTH = "both"


HUMAN, BOT = "human", "bot"

PLAYERS = {
    Matchup.PVP: {Side.ATTACK: HUMAN, Side.DEFENCE: HUMAN},
    Matchup.DEF_VS_BOT: {Side.ATTACK: BOT, Side.DEFENCE: HUMAN},
    Matchup.ATK_VS_BOT: {Side.ATTACK: HUMAN, Side.DEFENCE: BOT},
}

ALLOWED_MATCHUPS = {
    Side.ATTACK: frozenset({Matchup.ATK_VS_BOT}),
    Side.DEFENCE: frozenset({Matchup.DEF_VS_BOT}),
    Side.BOTH: frozenset({Matchup.DEF_VS_BOT, Matchup.ATK_VS_BOT}),
}

TIME_LIMIT = "time_limit"
ALL_OBJECTIVES_LOST = "all_objectives_lost"
ORIGINS_SPENT = "origins_spent"
AUTOMATIC_REASONS = (TIME_LIMIT, ALL_OBJECTIVES_LOST, ORIGINS_SPENT)
MANUAL_REASONS = ("ended_by_operator", "forfeit_attack", "forfeit_defence", "allocation_expired")
END_REASONS = AUTOMATIC_REASONS + MANUAL_REASONS


def bot_sides(matchup: str) -> tuple[str, ...]:
    return tuple(side.value for side, client in PLAYERS[Matchup(matchup)].items() if client == BOT)


def plays_a_problem(matchup: str) -> bool:
    return Matchup(matchup) != Matchup.PVP


def human_side(matchup: str) -> str | None:
    humans = [side.value for side, client in PLAYERS[Matchup(matchup)].items() if client == HUMAN]
    return humans[0] if len(humans) == 1 else None


@dataclass(frozen=True)
class RoundState:
    phase: Phase
    now: datetime
    started_at: datetime | None = None
    time_limit_s: int | None = None
    objectives_total: int = 0
    objectives_lost: int = 0
    origins_total: int = 0
    origins_left: int = 0
    benign_passes: int = 0


@dataclass(frozen=True)
class AllocationState:
    objective_fallen: bool


def may_end(state: RoundState) -> bool:
    return state.benign_passes >= 1


def ended(state: RoundState) -> str | None:
    if state.phase != Phase.RUNNING:
        return None
    if (
        state.time_limit_s is not None
        and state.started_at is not None
        and state.now >= state.started_at + timedelta(seconds=state.time_limit_s)
    ):
        return TIME_LIMIT
    if state.objectives_total and state.objectives_lost >= state.objectives_total:
        return ALL_OBJECTIVES_LOST
    if state.origins_total and state.origins_left == 0 and may_end(state):
        return ORIGINS_SPENT
    return None


def may_start_scored(allocation_state: AllocationState) -> bool:
    return not allocation_state.objective_fallen
