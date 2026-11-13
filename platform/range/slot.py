from __future__ import annotations

from dataclasses import dataclass

HOST = "cr_host"
TAG = "cr_tag"
BUNDLE = "cr_bundle"
NAMED_ON = "estate"


@dataclass(frozen=True)
class Plan:
    boot: tuple[str, ...] = ()
    standing: tuple[tuple[str, str, str], ...] = ()
    blocked: tuple[str, ...] = ()
    slot: int = 1
    stale: tuple[str, ...] = ()
    rebuilt: tuple[tuple[str, str], ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.boot or self.blocked or self.stale)

    @property
    def active(self) -> bool:
        return (
            self.clean
            and bool(self.standing)
            and all(status == "ACTIVE" for _, _, status in self.standing)
        )


def host_of(server: dict) -> str:
    return str((server.get("metadata") or {}).get(HOST) or "")


def known_as(server: dict) -> str:
    return host_of(server) or server["name"]
