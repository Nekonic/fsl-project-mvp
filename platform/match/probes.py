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

from attack import service as attack
from content import service as content
from cr import errors
from defence import service as defence
from match import service
from match.models import Lease
from referee import service as referee

PROBE = "probe"
HTTP_SECONDS = 30
TOOL_SECONDS = 900
RECORDING, DONE, FAILED = "recording", "done", "failed"

logger = logging.getLogger(__name__)
guard = threading.Lock()


@dataclass
class Progress:
    lease: int
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


def record(wargame_id: str, user) -> Lease:
    declared = wargame_of(wargame_id)
    if Lease.objects.filter(purpose=PROBE, wargame_id=wargame_id, closed=None).exists():
        raise errors.Conflict(code="probe_running")
    lease = service.open_lease(user, wargame_id, purpose=PROBE)
    with guard:
        held[lease.pk] = Progress(lease=lease.pk, wargame=wargame_id)
    threaded(lambda: recorded(lease, declared))
    return lease


def progress(lease_id: int) -> Progress:
    lease = Lease.objects.filter(pk=lease_id, purpose=PROBE).first()
    if lease is None:
        raise errors.NotFound(code="unknown_lease")
    with guard:
        found = held.get(lease_id)
    return found or Progress(lease=lease_id, wargame=lease.wargame_id, state=DONE if lease.closed else FAILED)


def moved(lease_id: int, **changed) -> None:
    with guard:
        for name, value in changed.items():
            setattr(held[lease_id], name, value)


def reach(lease: Lease):
    one = service.slot_range(lease.slot)
    return lambda role: one.runner(role)


def written(folder: Path, name: str, document: dict) -> None:
    (folder / name).write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")


def hidden(value, truth):
    return referee.redact(value, truth) if isinstance(value, str) else value


def one_case(lease: Lease, declared, case: dict, truth: dict, folder: Path) -> dict:
    name, tool_case = case["name"], "tool" in case
    marker = f"probe-{uuid.uuid4().hex[:12]}"
    capture = defence.start_capture(lease, name, TOOL_SECONDS if tool_case else HTTP_SECONDS)
    try:
        probed = attack.fire_probe(lease, {"hosts": list(declared.hosts)}, case, marker)
    finally:
        (folder / f"{name}.pcap").write_bytes(defence.finish_capture(lease, capture))
    if probed.request is not None:
        written(folder, f"{name}.request.json", {key: hidden(value, truth) for key, value in probed.request.items()})
        written(folder, f"{name}.response.json", {"status": probed.status, "body": referee.redact(probed.body, truth)})
    return {"marker": marker, "malicious": bool(case.get("malicious")), "tool_case": tool_case}


def truth_of(lease: Lease, declared) -> dict:
    found = referee.ground_truth({"secret": declared.secret, "objective_model": declared.objective_model},
                                 reach(lease))
    return found if isinstance(found, dict) else {}


def recorded(lease: Lease, declared) -> None:
    try:
        cases = attack.cases_of({"case_file": declared.case_file})
        moved(lease.pk, total=len(cases))
        folder = Path(settings.CR_PROBES_OUT) / declared.id / "probes"
        folder.mkdir(parents=True, exist_ok=True)
        defence.detection_only(lease)
        truth = truth_of(lease, declared)
        listed = {}
        for case in cases:
            try:
                listed[case["name"]] = one_case(lease, declared, case, truth, folder)
            except (errors.DomainError, OSError, ValueError) as failed:
                logger.warning("probe lease %s: %s was not recorded: %s", lease.pk, case["name"], failed)
                with guard:
                    held[lease.pk].failed.append({"case": case["name"],
                                                  "code": getattr(failed, "code", "unavailable")})
                continue
            with guard:
                held[lease.pk].done.append(case["name"])
        written(folder, "manifest.json", {"image_digest": declared.image, "cases": listed,
                                          "recorded_at": service.now().isoformat()})
        moved(lease.pk, state=DONE)
    except (errors.DomainError, OSError) as failed:
        logger.warning("probe lease %s failed: %s", lease.pk, failed)
        moved(lease.pk, state=FAILED)
    finally:
        service.close_lease(lease)
