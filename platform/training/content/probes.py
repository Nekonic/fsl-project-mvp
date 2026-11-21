from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from cr import errors
from sandbox.reach import slot_range
from scoring import baseline as referee
from training.attack import actions as attack
from training.content import problems as content
from training.defence import rules as defence
from training.models import Allocation
from training.round import allocation as allocations

PROBE = "probe"
HTTP_SECONDS = 30
TOOL_SECONDS = 900
RECORDING, DONE, FAILED = "recording", "done", "failed"

logger = logging.getLogger(__name__)
guard = threading.Lock()


@dataclass
class Progress:
    allocation: int
    wargame: str
    state: str = RECORDING
    total: int = 0
    done: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


held: dict[int, Progress] = {}


def threaded(work: Callable[[], None]) -> None:
    def run() -> None:
        try:
            work()
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True, name="cr-probes").start()


def wargame_of(wargame_id: str):
    declared = content.read_catalog().get(wargame_id)
    if declared is None:
        raise errors.NotFound(code="not_found", path="wargame")
    return declared


def record(wargame_id: str, user) -> Allocation:
    declared = wargame_of(wargame_id)
    if Allocation.objects.filter(purpose=PROBE, wargame_id=wargame_id, closed=None).exists():
        raise errors.Conflict(code="probe_running")
    allocation = allocations.open_allocation(user, wargame_id, purpose=PROBE)
    with guard:
        held[allocation.pk] = Progress(allocation=allocation.pk, wargame=wargame_id)
    threaded(lambda: recorded(allocation, declared))
    return allocation


def progress(allocation_id: int) -> Progress:
    allocation = Allocation.objects.filter(pk=allocation_id, purpose=PROBE).first()
    if allocation is None:
        raise errors.NotFound(code="unknown_allocation")
    with guard:
        found = held.get(allocation_id)
    return found or Progress(allocation=allocation_id, wargame=allocation.wargame_id, state=DONE if allocation.closed else FAILED)


def moved(allocation_id: int, **changed) -> None:
    with guard:
        for name, value in changed.items():
            setattr(held[allocation_id], name, value)


def reach(allocation: Allocation):
    one = slot_range(allocation.slot)
    return lambda role: one.runner(role)


def written(folder: Path, name: str, document: dict) -> None:
    (folder / name).write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")


def hidden(value, truth):
    return referee.redact(value, truth) if isinstance(value, str) else value


def one_case(allocation: Allocation, declared, case: dict, truth: dict, folder: Path) -> dict:
    name, tool_case = case["name"], "tool" in case
    marker = f"probe-{uuid.uuid4().hex[:12]}"
    capture = defence.start_capture(allocation, name, TOOL_SECONDS if tool_case else HTTP_SECONDS)
    try:
        probed = attack.fire_probe(allocation, {"hosts": list(declared.hosts)}, case, marker)
    finally:
        (folder / f"{name}.pcap").write_bytes(defence.finish_capture(allocation, capture))
    if probed.request is not None:
        written(folder, f"{name}.request.json", {key: hidden(value, truth) for key, value in probed.request.items()})
        written(folder, f"{name}.response.json", {"status": probed.status, "body": referee.redact(probed.body, truth)})
    return {"marker": marker, "malicious": bool(case.get("malicious")), "tool_case": tool_case}


def truth_of(allocation: Allocation, declared) -> dict:
    found = referee.ground_truth({"secret": declared.secret, "objective_model": declared.objective_model},
                                 reach(allocation))
    return found if isinstance(found, dict) else {}


def recorded(allocation: Allocation, declared) -> None:
    try:
        cases = attack.cases_of({"case_file": declared.case_file})
        moved(allocation.pk, total=len(cases))
        folder = Path(settings.CR_PROBES_OUT) / declared.id / "probes"
        folder.mkdir(parents=True, exist_ok=True)
        defence.detection_only(allocation)
        truth = truth_of(allocation, declared)
        listed = {}
        for case in cases:
            allocations.heartbeat(allocations.allocation(allocation.pk))
            try:
                listed[case["name"]] = one_case(allocation, declared, case, truth, folder)
            except (errors.DomainError, OSError, ValueError) as failed:
                logger.warning("probe allocation %s: %s was not recorded: %s", allocation.pk, case["name"], failed)
                with guard:
                    held[allocation.pk].failed.append({"case": case["name"],
                                                  "code": getattr(failed, "code", "unavailable")})
                continue
            with guard:
                held[allocation.pk].done.append(case["name"])
        written(folder, "manifest.json", {"image_digest": declared.image, "cases": listed,
                                          "recorded_at": timezone.now().isoformat()})
        moved(allocation.pk, state=DONE)
    except (errors.DomainError, OSError) as failed:
        logger.warning("probe allocation %s failed: %s", allocation.pk, failed)
        moved(allocation.pk, state=FAILED)
    finally:
        allocations.close_allocation(allocation)
