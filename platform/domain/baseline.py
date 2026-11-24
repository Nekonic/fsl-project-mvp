from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

HIGHER_IS_BETTER = {"attack": True, "defence": False}


@dataclass(frozen=True)
class Spread:
    n: int
    low: float | None
    median: float | None
    high: float | None


def percentile(value: float, samples: Sequence[float], higher_is_better: bool) -> float | None:
    if not samples:
        return None
    beaten = sum(1 for sample in samples if (value > sample if higher_is_better else value < sample))
    tied = sum(1 for sample in samples if sample == value)
    return 100.0 * (beaten + tied / 2) / len(samples)


def top_share(value: float, samples: Sequence[float], human_side: str) -> float | None:
    found = percentile(value, samples, HIGHER_IS_BETTER[human_side])
    return None if found is None else 100.0 - found


def spread(samples: Sequence[float]) -> Spread:
    ordered = sorted(samples)
    if not ordered:
        return Spread(0, None, None, None)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return Spread(len(ordered), ordered[0], median, ordered[-1])


def profile_key(parts: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


NOT_IN_DIGEST = {"problem": ("revision",), "round": ("matchups", "bot_steps")}


def problem_digest(snapshot: Mapping[str, Any]) -> str:
    kept = dict(snapshot)
    for part, left_out in NOT_IN_DIGEST.items():
        if isinstance(kept.get(part), Mapping):
            kept[part] = {key: value for key, value in kept[part].items() if key not in left_out}
    return profile_key(kept)
