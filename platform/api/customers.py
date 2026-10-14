import json
import random
import threading
from pathlib import Path

import yaml
from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import attacker
import traffic
import wargames
from api.models import CustomerRequest, Session
from range.ports import RangeUnavailable, Shape
from redteam import tools

PROGRAM = Path("deploy") / "traffic" / "users.py"
PULL_LIMIT = 1 << 20
PULLING = threading.Lock()
BLOCKED = 403
REFUSED_BY_APP = "app"
SHOWN_SOURCES = 40

class NoTraffic(LookupError):
    pass

def declared(scenario: str) -> dict:
    path = Path(settings.FSL_SOURCE) / "wargames" / scenario / "traffic.yaml"
    if scenario not in wargames.WARGAMES or not path.exists():
        raise NoTraffic(f"{scenario!r} declares no customers (wargames/{scenario}/traffic.yaml)")
    return traffic.checked(yaml.safe_load(path.read_text(encoding="utf-8")), path)

def _program() -> str:
    return (Path(settings.FSL_SOURCE) / PROGRAM).read_text(encoding="utf-8")

def _segments(state: dict) -> list[str]:
    return sorted({persona["origin"] for persona in state.get("personas") or []})

def _box(adapter, state: dict):
    return adapter.users_box(_segments(state), tools.TOOL_IMAGE)

def _keep(session, **changed) -> dict:
    state = dict(session.traffic or {}, **changed)
    Session.objects.filter(pk=session.pk).update(traffic=state)
    session.traffic = state
    return state

def _personas(adapter, mix: dict, seed: str) -> list[dict]:
    unbound = attacker.unbound_source(adapter.runner("attacker")) \
        if settings.ATTACKER_ORIGIN_MODE == "snat" else ""
    available = attacker.customer_origins(Shape(segments=adapter.segments(), sensors=()), unbound)
    return traffic.personas(mix, available, random.Random(seed))

def start(session, adapter, body: dict) -> dict:
    mix = declared(session.scenario)
    state = session.traffic or {}
    running = bool(state.get("running"))
    rate = traffic.rate_of(body.get("rate"), state.get("rate") if running else None)
    profile = traffic.profile_of(mix, body.get("profile"), state.get("profile") if running else None)
    personas = state["personas"] if running else _personas(adapter, mix, str(session.pk))
    box = adapter.users_box(sorted({persona["origin"] for persona in personas}), tools.TOOL_IMAGE)
    if not running:
        attacker.place_customers(box, _program())
    plan = traffic.plan(mix, profile, rate, personas, wargames.host(session.scenario), str(session.pk))
    started = attacker.run_customers(box, json.dumps(plan))
    now = timezone.now().isoformat()
    return _keep(
        session, running=True, rate=rate, profile=profile, personas=personas, error="",
        started_at=now if started or not state.get("started_at") else state["started_at"],
        stopped_at=None, offset=state.get("offset", 0),
    )

def stop(session, adapter) -> dict:
    state = session.traffic or {}
    if not state.get("running"):
        return state
    box = _box(adapter, state)
    attacker.stop_customers(box)
    pull(session, box)
    if hasattr(adapter, "drop_users_box"):
        adapter.drop_users_box()
    return _keep(session, running=False, stopped_at=timezone.now().isoformat())

def stop_on_close(session, adapter) -> None:
    try:
        stop(session, adapter)
    except RangeUnavailable as exc:
        _keep(session, running=False, stopped_at=timezone.now().isoformat(),
              error=f"stopping at close: {exc}")

def _row(session, record: dict):
    return CustomerRequest(
        session=session,
        marker=str(record["marker"])[:64],
        action=str(record.get("action", ""))[:32],
        step=str(record.get("step", ""))[:16],
        user=str(record.get("user", ""))[:16],
        origin=str(record.get("origin", ""))[:16],
        source_ip=record.get("source_ip") or None,
        method=str(record.get("method", ""))[:8],
        path=str(record.get("path", "")),
        status=int(record.get("status") or 0),
        refused_by=str(record.get("refused_by") or "")[:8],
        sent_at=parse_datetime(str(record.get("sent_at") or "")) or timezone.now(),
        elapsed_ms=max(0, int(record.get("elapsed_ms") or 0)),
    )

def pull(session, box) -> int:
    with PULLING:
        session.refresh_from_db(fields=["traffic"])
        offset = (session.traffic or {}).get("offset", 0)
        before = session.customer_requests.count()
        while True:
            chunk = attacker.customer_records(box, offset, PULL_LIMIT)
            found, used, _garbled = traffic.records(chunk)
            CustomerRequest.objects.bulk_create(
                [_row(session, record) for record in found], ignore_conflicts=True, batch_size=500,
            )
            offset += used
            _keep(session, offset=offset)
            if used == 0 or len(chunk.encode()) < PULL_LIMIT:
                break
        return session.customer_requests.count() - before

def refresh(session, adapter) -> None:
    state = session.traffic or {}
    if not state.get("running"):
        return
    try:
        pull(session, _box(adapter, state))
    except RangeUnavailable as exc:
        _keep(session, error=f"reading the records: {exc}")

def counted(requests) -> dict:
    return requests.aggregate(
        sent=Count("id"),
        served=Count("id", filter=Q(status__gte=200, status__lt=400)),
        blocked=Count("id", filter=Q(status=BLOCKED) & ~Q(refused_by=REFUSED_BY_APP)),
        unanswered=Count("id", filter=Q(status=0)),
        other=Count("id", filter=Q(status__gte=400) & ~(Q(status=BLOCKED) & ~Q(refused_by=REFUSED_BY_APP))),
    )

def status(session) -> dict:
    state = session.traffic or {}
    requests = session.customer_requests.all()
    try:
        profiles = sorted(declared(session.scenario)["profiles"])
    except NoTraffic:
        profiles = []
    return {
        "declared": bool(profiles),
        "profiles": profiles,
        "running": bool(state.get("running")),
        "rate": state.get("rate"),
        "profile": state.get("profile"),
        "started_at": state.get("started_at"),
        "stopped_at": state.get("stopped_at"),
        "error": state.get("error") or "",
        **counted(requests),
        "sources": list(
            requests.values("origin", "source_ip").annotate(requests=Count("id")).order_by("-requests")[:SHOWN_SOURCES]
        ),
        "by_action": {
            row["action"]: {"sent": row["sent"], "blocked": row["blocked"]}
            for row in requests.values("action").annotate(
                sent=Count("id"), blocked=Count("id", filter=Q(status=BLOCKED) & ~Q(refused_by=REFUSED_BY_APP)),
            )
        },
    }

def alerted_markers(session) -> set[str]:
    marked = session.detections.exclude(marker=None).values("marker")
    return set(session.customer_requests.filter(marker__in=marked).values_list("marker", flat=True))

def availability(session, alerted: set[str]) -> dict:
    requests = session.customer_requests.all()
    blocked = requests.filter(status=BLOCKED).exclude(refused_by=REFUSED_BY_APP)
    return {
        **counted(requests),
        "alerted": len(alerted),
        "blocked_actions": {
            row["action"]: row["n"] for row in blocked.values("action").annotate(n=Count("id"))
        },
    }
