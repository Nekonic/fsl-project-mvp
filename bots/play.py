from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bots import calls, tools
from bots.provider import Provider

PROMPTS = Path(__file__).resolve().parent / "prompts"
SIDE_PROMPTS = {"attack": "attacker.md", "defence": "defender.md"}
DRIVER_PROMPT = "claude_code.md"
DEFAULT_TURNS = 200


@dataclass(frozen=True)
class Played:
    reason: str
    turns: int
    transcript: list[dict]


def system_prompt(side: str, *, driving_the_cli: bool = False) -> str:
    if side not in SIDE_PROMPTS:
        raise ValueError(f"side must be one of {tuple(SIDE_PROMPTS)}, not {side!r}")
    parts = [(PROMPTS / SIDE_PROMPTS[side]).read_text()]
    if driving_the_cli:
        parts.append((PROMPTS / DRIVER_PROMPT).read_text())
    return "\n\n".join(parts)


def opening(player: calls.Player, state: dict) -> str:
    return (f"Round {player.round_id}: you hold the {player.side} player. Your player's state, read just now with "
            f"{player.side}_state:\n{json.dumps(state, ensure_ascii=False)}")


def play(player: calls.Player, provider: Provider, *, turns: int = DEFAULT_TURNS,
         report: Callable[[dict], None] = lambda entry: None) -> Played:
    specs = tools.specs(player.side)
    system = system_prompt(player.side)
    session = calls.session_for(player)
    state = calls.call(player, f"{player.side}_state", {}, session)
    transcript = [{"role": "user", "text": opening(player, state)}]
    report(transcript[0])
    for turn_number in range(1, turns + 1):
        turn = provider.turn(system, specs, transcript)
        said = {"role": "assistant", "text": turn.text,
                "calls": [{"id": call.id, "name": call.name, "arguments": call.arguments} for call in turn.calls]}
        transcript.append(said)
        report(said)
        if not turn.calls:
            return Played("finished", turn_number, transcript)
        for call in turn.calls:
            result = {"role": "tool", "call_id": call.id, "name": call.name,
                      "result": calls.call(player, call.name, call.arguments, session)}
            transcript.append(result)
            report(result)
    return Played("out_of_turns", turns, transcript)
