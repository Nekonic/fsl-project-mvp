from __future__ import annotations

from dataclasses import dataclass

BUILDING = "BUILDING"
READY = "READY"
DELETING = "DELETING"
FAILED = "FAILED"

ACTIVE = "ACTIVE"
SETTING_UP = "SETTING_UP"
SETUP_FAILED = "SETUP_FAILED"

COMPLETE = "CREATE_COMPLETE"
SETUP_LOG = "/var/log/cloud-init-output.log"


@dataclass(frozen=True)
class Plan:
    boot: tuple[str, ...] = ()
    standing: tuple[tuple[str, str, str], ...] = ()
    blocked: tuple[str, ...] = ()
    slot: int = 1
    stale: tuple[str, ...] = ()
    rebuilt: tuple[tuple[str, str], ...] = ()
    wargame: str = ""
    stack: str = ""
    stack_id: str = ""
    failures: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.boot or self.blocked or self.stale)

    @property
    def active(self) -> bool:
        return (
            self.clean
            and not self.failures
            and bool(self.standing)
            and all(status == ACTIVE for _, _, status in self.standing)
        )

    def serves(self, wargame: str) -> bool:
        return not self.wargame or not wargame or self.wargame == wargame


def assigned(number: int, wargames: tuple[str, ...], counts: tuple[tuple[str, int], ...] = ()) -> str:
    for wargame, count in counts:
        if number <= count:
            return wargame
        number -= count
    if counts:
        return ""
    return wargames[(number - 1) % len(wargames)] if wargames else ""


def stack_state(status: str) -> str:
    if status.endswith("_FAILED"):
        return FAILED
    if status.startswith("DELETE"):
        return DELETING
    return READY if status == COMPLETE else BUILDING


def server_status(stack: str, server: str, provisioned: str) -> str:
    if stack_state(stack) == FAILED:
        return SETUP_FAILED
    if stack != COMPLETE:
        return stack_state(stack)
    return provisioned if server == ACTIVE else server or BUILDING


def phase(plan: Plan, held, resetting: dict, checks: dict, running: str = "running", failed: str = "failed") -> tuple[str, list[str]]:
    if held is not None:
        return "IN_USE", [f"allocation {held} holds this slot"]
    if resetting["state"] == running:
        return "RESETTING", [
            "the slot is refilling after an allocation closed (its stack deleted and created again, its sensor "
            "back on the baseline rules)"
        ]
    if resetting["state"] == failed:
        return "RESET_FAILED", [
            f"the slot refill after the last allocation failed: {resetting['reason']}"
        ]
    if plan.boot or plan.blocked:
        return "NOT_STANDING", list(plan.blocked) or [f"{name} is not standing" for name in plan.boot]
    if plan.stale:
        return "STALE", [f"{name} was created from another template or other parameters than the platform's" for name in plan.stale]
    if plan.failures or any(status == SETUP_FAILED for _, _, status in plan.standing):
        return SETUP_FAILED, list(plan.failures) or [
            f"{host} failed its setup; {SETUP_LOG} on it says why"
            for host, _, status in plan.standing if status == SETUP_FAILED]
    if not plan.active:
        return "REBUILDING", [f"{host} is {status}" for host, _, status in plan.standing if status != ACTIVE]
    if not (checks.get("ground_truth") and checks.get("rules_baseline")):
        return "CHECKING", []
    return "READY", []
