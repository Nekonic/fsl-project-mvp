import functools
import hashlib
import ipaddress
import json
import math
import threading
import time
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import BadRequest
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

import requests

import attacker
import game
import scoreboard
import suppress
import topology
import wargames
from api import effect, loot
from api.refusals import Conflict
from api.models import (
    Case,
    Detection,
    Objective,
    RuleSet,
    Session,
    Suppression,
)
from ingest import elastic
from redteam import harness
import operator_log
from range import substrate
from range.ports import Drifted, RangeUnavailable, Shape
from rules import suricata
from scoring.correlate import correlate
from scoring.metrics import score as compute_score
from scoring.types import CORRELATION_STRATEGIES

SESSION_FIELDS = ("id", "scenario", "started_at", "ended_at")
CASE_FIELDS = (
    "id", "case_id", "name", "malicious", "stage", "technique", "pattern",
    "expect", "correlation", "source_ip", "started_at", "ended_at", "meta",
)
DETECTION_FIELDS = (
    "id", "detection_id", "source", "signature", "severity", "timestamp",
    "src_ip", "marker",
)
DETECTION_DETAIL_FIELDS = DETECTION_FIELDS + ("raw",)
OBJECTIVE_FIELDS = ("id", "key", "name", "category", "difficulty", "achieved_at")
RULESET_FIELDS = ("id", "content", "created_at", "applied_at")
SCORE_FIELDS = ("tp", "fp", "fn", "tn", "precision", "recall", "f1", "false_positive_rate")
SUPPRESSION_FIELDS = (
    "id", "sid", "reason", "created_at", "expires_at", "restored_at",
)

SUPPRESSION_MINUTES = 60
RULE_CHANGES = threading.RLock()

def _in_turn(change):
    @functools.wraps(change)
    def one_at_a_time(*args, **kwargs):
        with RULE_CHANGES:
            return change(*args, **kwargs)
    return one_at_a_time
SUPPRESSION_LONGEST = 24 * 60
CASE_REQUIRED = ("case_id", "name", "malicious", "correlation", "started_at", "ended_at")

def _shape(obj, fields):
    return {name: getattr(obj, name) for name in fields}

def _request_of(raw):
    http = raw.get("http") or {}
    if http or raw.get("dest_ip"):
        return (http.get("http_method") or "", http.get("url") or "",
                raw.get("dest_ip") or "", raw.get("dest_port"))
    request = raw.get("request") or {}
    return (request.get("method") or "", request.get("uri") or "",
            raw.get("host_ip") or "", raw.get("host_port"))

def _listed(detection, zones, located):
    method, path, dest_ip, dest_port = _request_of(detection.raw or {})
    return dict(
        _shape(detection, DETECTION_FIELDS),
        dest_ip=dest_ip,
        dest_port=dest_port,
        method=method,
        path=path,
        **_place(detection.src_ip, zones, located),
    )

def _place(address, zones, located):
    zone = _zone_of(address, zones) if address else None
    geo = located.get(address) or {}
    return {
        "zone": zone["name"] if zone else "",
        "outside": bool(zone and zone["outside"]),
        "country": geo.get("country_name") or "",
        "city": geo.get("city_name") or "",
    }

def _located(detections):
    located = {}
    for address, geo in detections.values_list("src_ip", "raw__src_geo"):
        if address and geo:
            located.setdefault(address, geo)
    return located

def _reply(payload, status=200):
    return JsonResponse(payload, status=status, safe=False)

def _payload(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise BadRequest(f"the body is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise BadRequest(f"the body must be a JSON object, got {type(body).__name__}")
    return body

def _rule_file(request) -> str:
    content = _payload(request).get("content")
    if not isinstance(content, str):
        raise BadRequest(
            f'"content" must be the whole rule file as a string, got {content!r}'
        )
    return content

def _refuse_closed(session):
    if session.ended_at is not None:
        raise Conflict(f"session {session.pk} closed at {session.ended_at.isoformat()}")

SESSION_PAGE = 25

@require_http_methods(["GET", "POST"])
def sessions(request):
    if request.method == "GET":
        try:
            limit = max(1, min(SESSION_PAGE, int(request.GET.get("limit", SESSION_PAGE))))
        except ValueError:
            limit = SESSION_PAGE

        found = Session.objects.order_by("-id")
        state = request.GET.get("state")
        if state == "open":
            found = found.filter(ended_at=None)
        elif state == "closed":
            found = found.exclude(ended_at=None)

        return _reply([_shape(s, SESSION_FIELDS) for s in found[:limit]])

    scenario = _payload(request).get("scenario")
    if scenario is None:
        scenario = "board"
    if not isinstance(scenario, str) or scenario not in wargames.WARGAMES:
        raise BadRequest(
            f"{scenario!r} is not a wargame; expected one of {', '.join(wargames.WARGAMES)}"
        )
    adapter = substrate()
    if hasattr(adapter, "plan_slot"):
        if Session.objects.filter(ended_at=None).exists():
            raise Conflict("a session is already open on the range; close it first")
        verdict = _range_ready(adapter)
        if not verdict["ready"]:
            raise Conflict(
                "the range is not ready: " + "; ".join(verdict["slot"]["blocked"])
            )
    baseline = []
    model = wargames.objective_model(scenario)
    if model == "loot_verified":
        try:
            baseline = loot.ground_truth(scenario)
        except loot.GroundTruthUnavailable:
            baseline = None
    elif model == "effect_observed":
        try:
            baseline = effect.snapshot(adapter.runner("corp-db"))
        except (effect.StateUnavailable, RangeUnavailable):
            baseline = None
    session = Session.objects.create(scenario=scenario, baseline=baseline)
    return _reply(_shape(session, SESSION_FIELDS), status=201)

@require_http_methods(["GET"])
def attacker_box(request):
    origin = attacker.find(_standing(), request.GET.get("origin"))
    return _reply(
        {
            "container": settings.ATTACKER_CONTAINER,
            "source_ip": origin["source_ip"],
            "direct_ip": origin["direct_ip"],
            "origin": origin["id"],
            "origin_label": origin["label"],
            "target_url": origin["target_url"],
            "public_url": settings.PUBLIC_TARGET_URL,
            "terminal_url": settings.ATTACKER_TERMINAL_URL,
        }
    )

TOP_N = 25

def _standing():
    return Shape(segments=substrate().segments(), sensors=())

def _segments():
    try:
        standing = _standing()
    except RangeUnavailable:
        return [], {}

    segments = topology.shape(standing, settings.RANGE)["segments"]

    hosts = {
        node["address"]: node["name"]
        for segment in segments
        for node in segment["nodes"]
        if node["address"]
    }
    return _zones(segments), hosts

def _zones(segments):
    zones = []
    for segment in segments:
        try:
            zones.append((ipaddress.ip_network(segment["subnet"]), segment))
        except ValueError:
            continue
    return zones

def _zone_of(address, zones):
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    return next((s for network, s in zones if parsed in network), None)

@require_http_methods(["GET"])
def session_top(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = list(session.detections.all())
    zones, hosts = _segments()
    located = _located(session.detections)

    sources, destinations, signatures, paths = {}, {}, {}, {}

    def count(table, key, row):
        if key not in table:
            table[key] = dict(row(), alerts=0)
        table[key]["alerts"] += 1

    for detection in detections:
        method, url, dest_ip, port = _request_of(detection.raw or {})
        address = detection.src_ip
        if address:
            count(sources, address, lambda: {
                "src_ip": address,
                "host": detection.src_host,
                **_place(address, zones, located),
                "country_code": (located.get(address) or {}).get("country_iso_code") or "",
            })
        if dest_ip:
            count(destinations, (dest_ip, port), lambda: {
                "dest_ip": dest_ip,
                "dest_port": port,
                "host": detection.dest_host,
                "zone": _place(dest_ip, zones, {})["zone"],
            })
        count(signatures, (detection.signature, detection.source), lambda: {
            "signature": detection.signature,
            "engine": detection.source,
        })
        if url:
            count(paths, (method, url), lambda: {"method": method, "path": url})

    def top(rows):
        return sorted(rows, key=lambda r: -r["alerts"])[:TOP_N]

    return _reply({
        "sources": top(sources.values()),
        "destinations": top(destinations.values()),
        "signatures": top(signatures.values()),
        "paths": top(paths.values()),
    })

@require_http_methods(["GET"])
def session_topology(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    shape = topology.shape(substrate().describe(), settings.RANGE)

    for segment in shape["segments"]:
        segment["alerts"] = 0
    zones = _zones(shape["segments"])

    unplaced = 0
    for detection in session.detections.all():
        zone = _zone_of(detection.src_ip or "", zones)
        if zone is None:
            unplaced += 1
        else:
            zone["alerts"] += 1

    return _reply({**shape, "unplaced": unplaced})

@require_http_methods(["GET"])
def origins(request):
    return _reply({"origins": attacker.origins(_standing())})

@require_http_methods(["GET"])
def session_commands(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    typed = operator_log.commands(substrate().runner("attacker"))
    return _reply({
        "commands": [
            {
                "at": command.at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "case_id": command.marker,
                "text": command.text,
            }
            for command in operator_log.within(
                typed, session.started_at, session.ended_at
            )
        ]
    })

@require_http_methods(["POST"])
def attacker_origin(request):
    chosen = attacker.find(_standing(), _payload(request).get("origin"))
    attacker.wear_origin(chosen, substrate().runner("proxy"))
    return _reply({"origin": chosen["id"], "source_ip": chosen["source_ip"]})

@require_http_methods(["POST"])
def attacker_label(request):
    case_id = _payload(request).get("case_id")
    if case_id not in (None, "") and not (
        isinstance(case_id, str) and case_id.isprintable() and " " not in case_id
    ):
        raise BadRequest(
            '"case_id" must be one marker with no spaces or control characters, '
            f"or null to clear the label, got {case_id!r}"
        )
    attacker.set_label(case_id or None, substrate().runner("proxy"))
    return _reply({"ok": True})

@require_http_methods(["GET"])
def wargame_catalogue(request):
    return _reply(wargames.catalogue())

@require_http_methods(["GET"])
def wargame_cases(request, wargame_id):
    try:
        return _reply(wargames.cases(wargame_id))
    except wargames.UnknownWargame:
        raise Http404(wargame_id)

@require_http_methods(["GET"])
def wargame_objectives(request, wargame_id):
    if wargame_id not in wargames.WARGAMES:
        raise Http404(wargame_id)
    model = wargames.objective_model(wargame_id)
    if model == "none":
        return _reply([])
    return _reply(_loot_catalogue(wargames.objectives(wargame_id)))

def _loot_catalogue(spec):
    return [
        {
            "key": tier["key"],
            "name": tier["name"],
            "category": tier.get("category") or "",
            "difficulty": int(tier["difficulty"]),
            "description": tier.get("description") or "",
            "solved": False,
            "solved_at": None,
        }
        for tier in spec["tiers"]
    ]

@require_http_methods(["GET", "POST"])
def session_objectives(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    if request.method == "GET":
        return _reply(
            [_shape(o, OBJECTIVE_FIELDS) for o in session.objectives.all()]
        )
    _refuse_closed(session)
    return _reply(_observe_objectives(session))

def _observe_objectives(session) -> dict:
    model = wargames.objective_model(session.scenario)
    if model != "effect_observed":
        return {"achieved": 0, "total": session.objectives.count()}

    spec = wargames.objectives(session.scenario)
    total = len(spec["tiers"])
    try:
        changes = effect.read_changes(
            substrate().runner("corp-db"), session.started_at
        )
    except (effect.StateUnavailable, RangeUnavailable):
        return {"achieved": session.objectives.count(), "total": total}

    windows = list(session.cases.filter(malicious=True))
    rows = []
    for tier, at in effect.credited(spec, session.baseline, changes):
        case = _effect_window(windows, at)
        if case is None:
            continue
        rows.append(Objective(
            session=session, key=tier["key"], name=tier["name"],
            category=tier.get("category") or "", difficulty=int(tier["difficulty"]),
            achieved_at=at,
            earliest=case.started_at - scoreboard.CLOCK_SKEW,
            latest=case.ended_at + scoreboard.CLOCK_SKEW,
        ))
    before = session.objectives.count()
    Objective.objects.bulk_create(rows, ignore_conflicts=True)
    return {"achieved": session.objectives.count() - before, "total": total}


def _effect_window(cases, at):
    inside = [
        case for case in cases
        if case.started_at - scoreboard.CLOCK_SKEW <= at <= case.ended_at + scoreboard.CLOCK_SKEW
    ]
    return max(inside, key=lambda case: case.started_at, default=None)

@require_http_methods(["POST"])
def session_loot(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    if wargames.objective_model(session.scenario) != "loot_verified":
        raise BadRequest(
            f"{session.scenario!r} does not take loot; its objective model is "
            f"{wargames.objective_model(session.scenario)!r}"
        )
    truth = session.baseline
    if not isinstance(truth, dict):
        raise Conflict(
            f"session {session.pk} captured no ground-truth snapshot at start, "
            f"so submitted loot cannot be verified"
        )
    body = _payload(request)
    spec = wargames.objectives(session.scenario)
    matched_users = loot.matched(body.get("loot"), truth)
    fired, coverage = loot.tiers_fired(spec, matched_users, truth)

    attempted = session.cases.filter(malicious=True).exists()
    credited = fired if attempted else []

    at, earliest, latest = _loot_window(session, body.get("case_id"), timezone.now())
    attributed = scoreboard.attribute(at, _malicious_attempts(session), earliest, latest)

    before = session.objectives.count()
    Objective.objects.bulk_create(
        [
            Objective(
                session=session, key=tier["key"], name=tier["name"],
                category=tier.get("category") or "", difficulty=int(tier["difficulty"]),
                achieved_at=at, earliest=earliest, latest=latest,
            )
            for tier in credited
        ],
        ignore_conflicts=True,
    )
    return _reply({
        "matched": sorted(matched_users),
        "coverage": coverage,
        "credited": [tier["key"] for tier in credited],
        "objectives": session.objectives.count() - before,
        "attempted": attempted,
        "unattributed": [] if attributed else [tier["key"] for tier in credited],
    })

def _loot_window(session, case_id, submitted_at):
    if case_id:
        case = session.cases.filter(case_id=case_id, malicious=True).first()
        if case is not None:
            return (
                case.ended_at,
                case.started_at - scoreboard.CLOCK_SKEW,
                case.ended_at + scoreboard.CLOCK_SKEW,
            )
    return (
        submitted_at,
        submitted_at - scoreboard.ATTRIBUTION_WINDOW,
        submitted_at + scoreboard.CLOCK_SKEW,
    )

def _malicious_attempts(session):
    return [
        scoreboard.Attempt(
            case_id=case.case_id,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=True,
            detected=False,
            detection_ids=(),
        )
        for case in session.cases.filter(malicious=True)
    ]

@require_http_methods(["POST"])
def fire_attack(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)
    body = _payload(request)
    try:
        case = wargames.find_case(session.scenario, body.get("case"))
    except wargames.UnknownWargame as exc:
        raise Http404(str(exc))
    case = dict(case, case_id=str(uuid.uuid4()))
    case.setdefault("correlation", "marker")
    origin = _origin_for(session, body.get("origin"))

    target_url = origin["target_url"] if origin else settings.TARGET_URL
    spec = dict(case.get("request") or {})
    if spec:
        spec["headers"] = dict(spec.get("headers") or {}, Host=wargames.host(session.scenario))
        case["request"] = spec

    started_at = timezone.now()
    try:
        harness.fire(
            requests.Session(), case, target_url,
            substrate().launcher(
                origin["id"] if origin else settings.RANGE.default_origin
            ),
            target_url,
        )
    except harness.ToolUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    finished_at = timezone.now()
    Session.objects.filter(pk=session.pk, ended_at__lt=finished_at).update(ended_at=finished_at)
    recorded = _record_case(
        session, case, started_at, finished_at,
        dict(
            harness.case_meta(case),
            **({"origin": origin["id"], "target_url": origin["target_url"]}
               if origin else {}),
        ),
    )
    _settle_and_observe(session)
    return _reply(_shape(recorded, CASE_FIELDS), status=201)

def _record_case(session, case, started_at, ended_at, meta):
    return Case.objects.create(
        session=session,
        case_id=case["case_id"],
        name=case["name"],
        malicious=case["malicious"],
        stage=case.get("stage") or "",
        technique=case.get("technique") or "",
        pattern=case.get("pattern") or "",
        expect=case.get("expect") or "",
        correlation=case["correlation"],
        source_ip=case.get("source_ip"),
        started_at=started_at,
        ended_at=ended_at,
        meta=meta,
    )

def _settle_and_observe(session):
    return _observe_objectives(session)["achieved"]

ROTATE = "rotate"

def _origin_for(session, requested):
    if not requested:
        return None

    described = _standing()
    if requested != ROTATE:
        return attacker.find(described, requested)

    available = attacker.origins(described)
    if not available:
        raise attacker.UnknownOrigin("the stack declares no origins to rotate through")
    return available[_take_turn(session) % len(available)]

def _take_turn(session):
    with transaction.atomic():
        Session.objects.filter(pk=session.pk).update(rotation=F("rotation") + 1)
        return Session.objects.values_list("rotation", flat=True).get(pk=session.pk) - 1

@require_http_methods(["GET"])
def session_detail(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    return _reply(_shape(session, SESSION_FIELDS))

@require_http_methods(["POST"])
def close_session(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    _refuse_closed(session)

    closed_at = timezone.now()
    if not Session.objects.filter(pk=session.pk, ended_at=None).update(ended_at=closed_at):
        session.refresh_from_db()
        _refuse_closed(session)
    session.ended_at = closed_at
    reply = _shape(session, SESSION_FIELDS)

    adapter = substrate()
    if hasattr(adapter, "rebuild_slot"):
        try:
            with RULE_CHANGES:
                rebuilt = adapter.rebuild_slot()
            reply["rebuilding"] = [
                {"host": host, "server": server} for host, server in rebuilt
            ]
        except (Drifted, RangeUnavailable) as exc:
            reply["rebuild"] = str(exc)
    return _reply(reply)

@require_http_methods(["GET", "POST"])
def session_cases(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "GET":
        return _reply([_shape(c, CASE_FIELDS) for c in session.cases.all()])

    _refuse_closed(session)
    body = _payload(request)
    errors = _case_errors(body)
    if errors:
        return _reply(errors, status=400)

    try:
        case = _record_case(
            session, body, _instant(body["started_at"]), _instant(body["ended_at"]),
            body.get("meta") or {},
        )
    except IntegrityError:
        raise Conflict(f"case {body['case_id']} is already recorded in session {session.pk}")
    return _reply(
        _shape(case, CASE_FIELDS) | {"objectives": _settle_and_observe(session)}, status=201
    )

def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed

def _case_errors(body):
    errors = {
        field: ["This field is required."]
        for field in CASE_REQUIRED
        if body.get(field) is None
    }
    if body.get("malicious") is not None and not isinstance(body["malicious"], bool):
        errors["malicious"] = [f"must be true or false, got {body['malicious']!r}."]
    if body.get("expect") is not None and not isinstance(body["expect"], str):
        errors["expect"] = [f"must be text or null, got {body['expect']!r}."]
    for field in ("started_at", "ended_at"):
        if body.get(field) is not None and _instant(body[field]) is None:
            errors[field] = [f"must be an ISO 8601 time with its offset, got {body[field]!r}."]
    started, ended = _instant(body.get("started_at")), _instant(body.get("ended_at"))
    if started and ended and ended < started:
        errors["ended_at"] = ["is before started_at."]
    source = body.get("source_ip")
    if source is not None:
        try:
            ipaddress.ip_address(source if isinstance(source, str) else "")
        except ValueError:
            errors["source_ip"] = [f"must be an IP address, got {source!r}."]
    correlation = body.get("correlation")
    if correlation is not None and correlation not in CORRELATION_STRATEGIES:
        errors["correlation"] = [
            f'"{correlation}" is not a valid choice; expected one of '
            f"{', '.join(CORRELATION_STRATEGIES)}."
        ]
    return errors

@require_http_methods(["POST"])
def ingest_detections(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    start = session.started_at - timedelta(minutes=1)
    end = (session.ended_at or timezone.now()) + timedelta(minutes=1)
    try:
        restored = _restore_expired()
    except (RangeUnavailable, suricata.RulesUnreadable):
        restored = []

    documents, truncated = elastic.fetch(
        settings.ELASTIC_URL, settings.ELASTIC_INDEX, start, end
    )

    held = dict(session.detections.values_list("detection_id", "marker"))
    known = set(held)
    unmarked = {detection_id for detection_id, marker in held.items() if marker is None}
    stale = 0
    rows = []

    alerts = elastic.normalize_all(documents)
    for alert in alerts:
        if alert["marker"] and alert["detection_id"] in unmarked:
            Detection.objects.filter(
                session=session, detection_id=alert["detection_id"], marker=None
            ).update(marker=alert["marker"])

    productive = {a["detection_id"].split(":")[0] for a in alerts}
    skipped = sum(1 for doc_id, _ in documents if doc_id not in productive)

    _, hosts = _segments()

    for alert in alerts:
        if alert["detection_id"] in known or alert["timestamp"] is None:
            continue
        known.add(alert["detection_id"])
        if not start <= alert["timestamp"] <= end:
            stale += 1
            continue
        raw = alert.get("raw") or {}
        rows.append(Detection(
            session=session,
            src_host=hosts.get(alert.get("src_ip"), ""),
            dest_host=hosts.get(_request_of(raw)[2], ""),
            **alert,
        ))

    before = session.detections.count()
    Detection.objects.bulk_create(rows, ignore_conflicts=True)
    ingested = session.detections.count() - before

    reply = {"ingested": ingested, "skipped": skipped, "stale": stale, "restored": restored}
    if truncated:
        read, total = truncated
        reply["truncated"] = {"read": read, "total": total}
        session.read_of = [read, total]
        session.save(update_fields=["read_of"])
    return _reply(reply)

@require_http_methods(["GET"])
def session_detections(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = session.detections.all()

    after = request.GET.get("after")
    if after is not None:
        try:
            detections = detections.filter(id__gt=int(after, 10))
        except ValueError:
            raise BadRequest(f'"after" must be a row id, got {after!r}')

    detections = list(detections)
    addresses = {d.src_ip for d in detections if d.src_ip}
    zones, _ = _segments() if addresses else ([], {})
    located = _located(session.detections.filter(src_ip__in=addresses)) if addresses else {}
    return _reply([_listed(d, zones, located) for d in detections])

@require_http_methods(["GET"])
def detection_detail(request, detection_id):
    detection = get_object_or_404(Detection, pk=detection_id)
    return _reply(
        _shape(detection, DETECTION_DETAIL_FIELDS) | {"session": detection.session_id}
    )

@require_http_methods(["GET"])
def session_map(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = list(session.detections.all())
    site = settings.RANGE.defended_site

    located = {}
    for detection in detections:
        if not detection.src_ip or detection.src_ip in located:
            continue
        geo = (detection.raw or {}).get("src_geo") or {}
        where = geo.get("location") or {}
        if where.get("lat") is None or where.get("lon") is None:
            continue
        located[detection.src_ip] = (where["lat"], where["lon"], geo)

    points, unlocated = {}, 0
    for detection in detections:
        place = located.get(detection.src_ip)
        if place is None:
            unlocated += 1
            continue
        lat, lon, geo = place
        point = points.setdefault(
            (lat, lon),
            {
                "lat": lat,
                "lon": lon,
                "country": geo.get("country_name") or "",
                "country_code": geo.get("country_iso_code") or "",
                "city": geo.get("city_name") or "",
                "detections": 0,
                "ips": [],
            },
        )
        point["detections"] += 1
        if detection.src_ip not in point["ips"]:
            point["ips"].append(detection.src_ip)

    return _reply(
        {
            "points": sorted(points.values(), key=lambda p: -p["detections"]),
            "unlocated": unlocated,
            "target": site and _shape(site, ("lat", "lon", "label")),
        }
    )

@require_http_methods(["GET"])
def session_score(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    forced = request.GET.get("correlation")
    if forced is not None and forced not in CORRELATION_STRATEGIES:
        raise BadRequest(
            f'"{forced}" is not a valid strategy; expected one of '
            f"{', '.join(CORRELATION_STRATEGIES)}."
        )

    cases = list(session.cases.all())
    detections = list(session.detections.all())
    signatures = {d.detection_id: d.signature for d in detections}

    records = [c.to_record() for c in cases]
    if forced:
        records = [replace(record, correlation=forced) for record in records]

    result = correlate(records, [d.to_record() for d in detections])
    totals = compute_score(result)
    per_case = _per_case(result, _expected(session.scenario, cases), signatures)
    breaches = _breaches(session, cases, result)
    board = scoreboard.tally(breaches, totals.fp)
    warnings = list(totals.warnings) + _wrong_reason_warnings(per_case)
    if session.read_of:
        read, total = session.read_of or [0, 0]
        warnings.append(("score.warning.truncated", read, total))

    return _reply(
        {
            **_shape(totals, SCORE_FIELDS),
            "benign_cases": totals.fp + totals.tn,
            "unattributed": len(result.unmatched_detection_ids),
            "warnings": warnings,
            "per_case": per_case,
            "objectives": board.__dict__,
            "breaches": [
                dict(b.__dict__, detection_ids=list(b.detection_ids)) for b in breaches
            ],
            "game": _game(session, cases, detections, result, breaches, totals),
        }
    )

def _game(session, cases, detections, result, breaches, totals):
    if session.ended_at is None:
        return {"revealed": False}

    detected_at = {d.detection_id: d.timestamp for d in detections}
    first_hit = {
        match.case_id: min(
            (detected_at[d] for d in match.detection_ids if d in detected_at),
            default=None,
        )
        for match in result.matches
    }
    attempts = [
        game.Attempt(
            case_id=case.case_id,
            malicious=case.malicious,
            stage=case.stage or "",
            started_at=case.started_at,
            detected_at=first_hit.get(case.case_id),
            blocked=bool(case.meta.get("blocked")),
        )
        for case in cases
    ]
    taken = [
        game.Taken(key=b.key, difficulty=b.difficulty, detected=b.detected)
        for b in breaches
    ]
    settled = game.settle(attempts, taken, totals.tp, totals.fp, totals.fn, totals.tn)
    return dict(settled.__dict__, revealed=True)

def _attempts(cases, result):
    by_case = {match.case_id: match for match in result.matches}
    return [
        scoreboard.Attempt(
            case_id=case.case_id,
            started_at=case.started_at,
            ended_at=case.ended_at,
            malicious=case.malicious,
            detected=bool(by_case[case.case_id].detected),
            detection_ids=tuple(by_case[case.case_id].detection_ids),
        )
        for case in cases
        if case.case_id in by_case
    ]

def _breaches(session, cases, result):
    attempts = _attempts(cases, result)
    breaches = []
    for objective in session.objectives.all():
        credited = scoreboard.attribute(
            objective.achieved_at, attempts, objective.earliest, objective.latest
        )
        breaches.append(
            scoreboard.Breach(
                key=objective.key,
                name=objective.name,
                category=objective.category,
                difficulty=objective.difficulty,
                detected=bool(credited and credited.detected),
                detection_ids=tuple(credited.detection_ids) if credited else (),
            )
        )
    return breaches

def _expected(scenario, cases):
    catalogue = {}
    if any(case.expect is None for case in cases):
        try:
            catalogue = wargames.expectations(scenario)
        except wargames.UnknownWargame:
            pass
    return {
        case.case_id: catalogue.get(case.name) if case.expect is None else case.expect
        for case in cases
    }

def _per_case(result, expectations, signatures):
    indiscriminate = {
        signatures[d]
        for m in result.matches if not m.malicious
        for d in m.detection_ids if d in signatures
    }
    return [
        {
            "case_id": m.case_id,
            "name": m.name,
            "malicious": m.malicious,
            "detected": m.detected,
            "verdict": _verdict(m.malicious, m.detected),
            "detection_ids": list(m.detection_ids),
            "expect": expectations.get(m.case_id) or "",
            "corroborated": scoreboard.corroborated(
                expectations.get(m.case_id),
                [signatures[d] for d in m.detection_ids if d in signatures],
                indiscriminate,
            ),
        }
        for m in result.matches
    ]

def _wrong_reason_warnings(per_case):
    wrong = [c["name"] for c in per_case if c["detected"] and c["corroborated"] is False]
    if not wrong:
        return []
    return [("score.warning.wrong_reason", ", ".join(wrong))]

def _verdict(malicious: bool, detected: bool) -> str:
    if malicious:
        return "TP" if detected else "FN"
    return "FP" if detected else "TN"

@require_http_methods(["GET"])
def current_rules(request):
    content = _live_rules()
    return _reply({"content": content, "version": _version(content)})

@require_http_methods(["POST"])
@_in_turn
def validate_rules(request):
    outcome = suricata.validate(_rule_file(request), substrate().runner("sensor"))
    payload = {"ok": outcome.ok, "output": outcome.output.strip()}
    return _reply(payload, status=200 if outcome.ok else 400)

def _minutes(given) -> float:
    try:
        minutes = float(given)
    except (TypeError, ValueError, OverflowError):
        minutes = math.nan
    if not 0 < minutes <= SUPPRESSION_LONGEST:
        raise BadRequest(
            f'"minutes" must be more than 0 and at most {SUPPRESSION_LONGEST}, '
            f"got {given!r}"
        )
    return minutes

@require_http_methods(["GET", "POST"])
@_in_turn
def suppressions(request):
    expired = _restore_expired()

    if request.method == "GET":
        return _reply(
            {
                "suppressions": [
                    _shape(s, SUPPRESSION_FIELDS)
                    for s in Suppression.objects.filter(restored_at__isnull=True)
                ],
                "restored": expired,
            }
        )

    body = _payload(request)
    try:
        sid = int(body.get("sid"))
    except (TypeError, ValueError, OverflowError):
        raise BadRequest(f'"sid" must be a rule id, got {body.get("sid")!r}')

    minutes = _minutes(body.get("minutes", SUPPRESSION_MINUTES))
    expires_at = timezone.now() + timedelta(minutes=minutes)
    content = _live_rules()

    try:
        silenced = suppress.silence(content, sid, expires_at.isoformat())
    except KeyError:
        raise Http404(f"no active rule carries sid {sid}")

    original = suppress.find(content, sid)
    _apply(silenced)

    record = Suppression.objects.create(
        sid=sid,
        original=original,
        reason=body.get("reason") or "",
        expires_at=expires_at,
    )
    return _reply(_shape(record, SUPPRESSION_FIELDS), status=201)

@require_http_methods(["POST"])
@_in_turn
def restore_suppression(request, suppression_id):
    record = get_object_or_404(Suppression, pk=suppression_id, restored_at__isnull=True)
    ok, detail = _restore(record)
    if not ok:
        return _reply({"detail": detail}, status=400)
    return _reply(_shape(record, SUPPRESSION_FIELDS) | {"detail": detail})

def _restore(record) -> tuple[bool, str | None]:
    current = _live_rules()
    superseded = suppress.find(current, record.sid) is not None
    lift = suppress.discard if superseded else suppress.restore
    try:
        content = lift(current, record.sid, record.original)
    except KeyError:
        content = superseded = None
    if content is not None:
        try:
            _apply(content)
        except suricata.RuleApplyError as exc:
            return False, f"could not restore sid {record.sid}: {exc}"

    record.restored_at = timezone.now()
    record.save(update_fields=["restored_at"])
    if superseded:
        return True, (
            f"sid {record.sid} was superseded by an active rule carrying it, so "
            f"the silenced original was dropped rather than restored"
        )
    return True, None

def _due():
    return Suppression.objects.filter(
        restored_at__isnull=True, expires_at__lte=timezone.now()
    )

def _restore_expired() -> list:
    if not _due().exists():
        return []
    with RULE_CHANGES:
        lifted = []
        for record in list(_due()):
            ok, detail = _restore(record)
            lifted.append({"sid": record.sid, "ok": ok, "detail": detail})
        return lifted

def _live_rules():
    return suricata.current(substrate().runner("sensor"))

def _apply(content):
    suricata.apply(content, substrate().runner("sensor"), settings.FSL_SENSOR_RELOAD)

def _version(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]

@require_http_methods(["POST"])
@_in_turn
def apply_rules(request):
    content = _rule_file(request)
    body = _payload(request)
    if "base" in body:
        base = body["base"]
        live = _version(_live_rules())
        if base != live:
            raise Conflict(
                "the sensor's rules changed since this copy was loaded "
                f"(loaded {base or 'nothing'}, live {live}); reload them and edit again"
            )
    _apply(content)
    ruleset = RuleSet.objects.create(content=content, applied_at=timezone.now())
    return _reply(_shape(ruleset, RULESET_FIELDS))

def _fabric_plan(plan):
    return {
        "networks": list(plan.networks),
        "subnets": [
            {"segment": s.segment, "name": s.name, "cidr": s.cidr,
             "dhcp": s.dhcp, "gateway": s.gateway}
            for s in plan.subnets
        ],
        "keypair": plan.keypair,
        "groups": list(plan.groups),
        "reach": plan.reach,
        "present": list(plan.present),
        "drifted": list(plan.drifted),
        "leftovers": list(plan.leftovers),
        "clean": plan.clean,
    }

def _built_by_the_cloud(adapter, plans: str, what: str):
    if not hasattr(adapter, plans):
        raise Conflict(
            f"compose builds this range; the {what} built through the "
            f"OpenStack API only"
        )
    return adapter

def _image_plan(plan):
    return {
        "images": [
            {"host": i.host, "bundle": i.bundle, "state": i.state,
             "image": i.image, "builder": i.builder, "detail": i.detail}
            for i in plan.images
        ],
        "leftovers": [
            {"kind": kind, "id": ident, "why": why} for kind, ident, why in plan.leftovers
        ],
        "clean": plan.clean,
    }

@require_http_methods(["GET", "POST", "DELETE"])
def range_images(request):
    adapter = _built_by_the_cloud(substrate(), "plan_images", "images are")
    if request.method == "GET":
        return _reply(_image_plan(adapter.plan_images()))
    with RULE_CHANGES:
        if request.method == "POST":
            return _reply(_image_plan(adapter.ensure_images()))
        removed = adapter.clean_images()
    return _reply({"removed": [{"kind": kind, "id": ident} for kind, ident in removed]})

def _slot_plan(plan):
    return {
        "boot": list(plan.boot),
        "ports": [
            {"host": p.host, "segment": p.segment, "name": p.name,
             "addresses": [address for _, address in p.fixed_ips]}
            for p in plan.ports
        ],
        "standing": [
            {"host": host, "server": server, "status": status}
            for host, server, status in plan.standing
        ],
        "blocked": list(plan.blocked),
        "clean": plan.clean,
    }

@require_http_methods(["GET", "POST", "DELETE"])
def range_slot(request):
    adapter = _built_by_the_cloud(substrate(), "plan_slot", "slot is")
    if request.method == "GET":
        return _reply(_slot_plan(adapter.plan_slot()))
    with RULE_CHANGES:
        if request.method == "POST":
            return _reply(_slot_plan(adapter.ensure_slot()))
        removed = adapter.teardown_slot()
    return _reply({"removed": [{"kind": kind, "id": ident} for kind, ident in removed]})

@require_http_methods(["POST"])
def range_rebuild(request):
    adapter = _built_by_the_cloud(substrate(), "rebuild_slot", "slot is")
    with RULE_CHANGES:
        rebuilt = adapter.rebuild_slot()
    return _reply({"rebuilt": [{"host": host, "server": server} for host, server in rebuilt]})

@require_http_methods(["POST"])
def range_configure(request):
    adapter = _built_by_the_cloud(substrate(), "configure_slot", "slot is")
    with RULE_CHANGES:
        done = adapter.configure_slot()
    return _reply({"configured": [
        {"host": host, "reported": list(reported)} for host, reported in done
    ]})

def _ground_truth_readable(adapter) -> bool:
    try:
        loot.ground_truth("board")
        return True
    except loot.GroundTruthUnavailable:
        return False

def _baseline_rules() -> str:
    return (Path(settings.FSL_SOURCE) / "deploy/suricata/rules/local.rules").read_text()

def _rules_at_baseline(adapter) -> bool:
    try:
        live = suricata.current(adapter.runner("sensor"))
    except (suricata.RulesUnreadable, RangeUnavailable):
        return False
    if live != _baseline_rules():
        return False
    now = timezone.now()
    return not Suppression.objects.filter(
        restored_at__isnull=True, expires_at__gt=now
    ).exists()

def _range_ready(adapter) -> dict:
    plan = adapter.plan_slot()
    checks = {
        "active": plan.active,
        "ground_truth": _ground_truth_readable(adapter),
        "rules_baseline": _rules_at_baseline(adapter),
    }
    blocked = []
    if plan.boot or plan.blocked:
        phase = "NOT_STANDING"
        blocked += list(plan.blocked) or [f"{host} is not standing" for host in plan.boot]
    elif not plan.active:
        phase = "REBUILDING"
        blocked += [f"{host} is {status}" for host, _, status in plan.standing
                    if status != "ACTIVE"]
    elif not (checks["ground_truth"] and checks["rules_baseline"]):
        phase = "CHECKING"
    else:
        phase = "READY"
    if not checks["ground_truth"]:
        blocked.append("the target's ground truth could not be read")
    if not checks["rules_baseline"]:
        blocked.append("the sensor rules are off baseline or a suppression is in force")
    return {
        "ready": all(checks.values()),
        "substrate": "openstack",
        "slot": {
            "phase": phase,
            "standing": [{"host": host, "server": server, "status": status}
                         for host, server, status in plan.standing],
            "checks": checks,
            "blocked": blocked,
        },
    }

@require_http_methods(["GET"])
def range_ready(request):
    adapter = substrate()
    if not hasattr(adapter, "plan_slot"):
        return _reply({"ready": True, "substrate": "compose", "slot": None})
    return _reply(_range_ready(adapter))

CANARY_CASE = {
    "name": "range-canary",
    "malicious": True,
    "correlation": "marker",
    "request": {
        "method": "GET",
        "path": "/search/",
        "params": {"q": "' OR 1=1--"},
    },
}

def _canary_blocked(reason: str) -> dict:
    return {"corroborated": False, "suricata": False, "modsecurity": False,
            "skew_seconds": None, "blocked": [reason]}

def _range_canary(adapter) -> dict:
    token = "canary-" + uuid.uuid4().hex
    try:
        origin = attacker.find(_standing(), None)
    except (attacker.UnknownOrigin, RangeUnavailable) as exc:
        return _canary_blocked(f"no origin to fire the canary from: {exc}")
    try:
        attacker.wear_origin(origin, adapter.runner("proxy"))
    except RangeUnavailable as exc:
        return _canary_blocked(f"could not set the canary origin: {exc}")

    case = dict(CANARY_CASE, case_id=token)
    fired_at = timezone.now()
    try:
        harness.fire(requests.Session(), case, origin["target_url"],
                     adapter.launcher(origin["id"]), origin["target_url"])
    except harness.ToolUnavailable as exc:
        return _canary_blocked(f"the canary did not fire: {exc}")

    suricata_at = modsec_at = None
    reach = []
    for _ in range(max(1, int(settings.CANARY_WAIT / settings.CANARY_POLL))):
        time.sleep(settings.CANARY_POLL)
        try:
            documents, _ = elastic.fetch(
                settings.ELASTIC_URL, settings.ELASTIC_INDEX,
                fired_at - timedelta(minutes=1), timezone.now() + timedelta(minutes=1),
            )
        except elastic.ElasticUnavailable as exc:
            reach = [f"could not read Elasticsearch: {exc}"]
            continue
        reach = []
        marked = [d for d in elastic.normalize_all(documents)
                  if d["marker"] == token and d["timestamp"]]
        suricata_at = min((d["timestamp"] for d in marked if d["source"] == "suricata"),
                          default=None)
        modsec_at = min((d["timestamp"] for d in marked if d["source"] == "modsecurity"),
                        default=None)
        if suricata_at and modsec_at:
            break

    skew = (abs((suricata_at - modsec_at).total_seconds())
            if suricata_at and modsec_at else None)
    blocked = list(reach)
    if suricata_at is None:
        blocked.append("Suricata did not alert on the canary")
    if modsec_at is None:
        blocked.append("ModSecurity did not alert on the canary")
    if skew is not None and skew > settings.READY_SKEW:
        blocked.append(
            f"the engine clocks differ by {skew:.1f}s, over the {settings.READY_SKEW:g}s bound"
        )
    return {
        "corroborated": (suricata_at is not None and modsec_at is not None
                         and skew is not None and skew <= settings.READY_SKEW),
        "suricata": suricata_at is not None,
        "modsecurity": modsec_at is not None,
        "skew_seconds": skew,
        "blocked": blocked,
    }

@require_http_methods(["POST"])
def range_canary(request):
    return _reply(_range_canary(substrate()))

@require_http_methods(["GET", "POST", "DELETE"])
def range_fabric(request):
    adapter = _built_by_the_cloud(substrate(), "plan_fabric", "fabric is")
    if request.method == "GET":
        return _reply(_fabric_plan(adapter.plan_fabric()))
    with RULE_CHANGES:
        if request.method == "POST":
            return _reply(_fabric_plan(adapter.ensure_fabric()))
        removed = adapter.teardown_fabric()
    return _reply({"removed": [{"kind": kind, "id": ident} for kind, ident in removed]})
