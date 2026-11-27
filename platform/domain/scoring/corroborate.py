from __future__ import annotations

from collections.abc import Iterable, Mapping

from domain.types import CorrelationResult


def corroborated(expect: str | None, signatures: Iterable[str], indiscriminate: Iterable[str] = ()) -> bool | None:
    seen = list(signatures)
    if not expect or not seen:
        return None
    needle = expect.lower()
    noise = set(indiscriminate)
    return any(needle in signature.lower() for signature in seen if signature not in noise)


def indiscriminate_signatures(result: CorrelationResult, signatures: Mapping[str, str]) -> frozenset[str]:
    return frozenset(
        signatures[detection_id]
        for match in result.matches
        if match.malicious is False
        for detection_id in match.detection_ids
        if detection_id in signatures
    )
