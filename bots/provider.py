from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Turn:
    text: str = ""
    calls: tuple[ToolCall, ...] = ()


class Provider(Protocol):
    def turn(self, system: str, tools: list[dict], transcript: list[dict]) -> Turn: ...


class ProviderNotFound(RuntimeError):
    pass


def load(reference: str) -> Provider:
    module_name, _, attribute = reference.partition(":")
    if not module_name or not attribute:
        raise ProviderNotFound(f"{reference!r}: name a provider as package.module:factory")
    try:
        module = importlib.import_module(module_name)
    except ImportError as missing:
        raise ProviderNotFound(f"{reference!r}: {missing}") from missing
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ProviderNotFound(f"{reference!r}: {module_name} has no callable {attribute}")
    made = factory()
    if not callable(getattr(made, "turn", None)):
        raise ProviderNotFound(f"{reference!r}: {attribute}() returned something without turn()")
    return made
