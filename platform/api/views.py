import functools
import hashlib
import ipaddress
import json
import math
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from urllib.parse import urlsplit

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
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
import objectives
import scoreboard
import suppress
import topology
import wargames
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
from range import declared, substrate
from range.ports import RangeUnavailable, Shape
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

CLOCK_SLACK = timedelta(seconds=5)

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
    zone = _zone_of(detection.src_ip, zones) if detection.src_ip else None
    geo = located.get(detection.src_ip) or {}
    return dict(
        _shape(detection, DETECTION_FIELDS),
        dest_ip=dest_ip,
        dest_port=dest_port,
        method=method,
        path=path,
        zone=zone["name"] if zone else "",
        outside=bool(zone and zone["outside"]),
        country=geo.get("country_name") or "",
        city=geo.get("city_name") or "",
    )

def _located(session, addresses):
    located = {}
    carried = session.detections.filter(src_ip__in=addresses)
    for address, geo in carried.values_list("src_ip", "raw__src_geo"):
        if geo and address not in located:
            located[address] = geo
    return located

def _reply(payload, status=200):
    return JsonResponse(payload, status=status, encoder=DjangoJSONEncoder, safe=False)

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

def _closed(session):
    if session.ended_at is None:
        return None
    return _reply(
        {"detail": f"session {session.pk} closed at {session.ended_at.isoformat()}"},
        status=409,
    )

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
        scenario = "juice-shop"
    if not isinstance(scenario, str) or scenario not in wargames.WARGAMES:
        raise BadRequest(
            f"{scenario!r} is not a wargame; expected one of {', '.join(wargames.WARGAMES)}"
        )
    try:
        baseline = sorted(objectives.solved_keys(substrate().runner("wiki")))
    except objectives.ObjectivesUnavailable:
        baseline = None
    session = Session.objects.create(scenario=scenario, baseline=baseline)
    return _reply(_shape(session, SESSION_FIELDS), status=201)

@require_http_methods(["GET"])
def attacker_box(request):
    try:
        origin = attacker.find(_standing(), request.GET.get("origin"))
    except attacker.UnknownOrigin as exc:
        raise Http404(str(exc))

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

    segments = topology.shape(standing, declared.read())["segments"]

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

    located = {}
    for detection in detections:
        if detection.src_ip and detection.src_ip not in located:
            geo = (detection.raw or {}).get("src_geo") or {}
            if geo:
                located[detection.src_ip] = geo

    sources, destinations, signatures, paths = {}, {}, {}, {}
    for detection in detections:
        method, url, dest_ip, port = _request_of(detection.raw or {})

        if detection.src_ip:
            row = sources.get(detection.src_ip)
            if row is None:
                geo = located.get(detection.src_ip) or {}
                zone = _zone_of(detection.src_ip, zones)
                row = sources[detection.src_ip] = {
                    "src_ip": detection.src_ip,
                    "host": detection.src_host,
                    "zone": zone["name"] if zone else "",
                    "outside": bool(zone and zone["outside"]),
                    "country": geo.get("country_name") or "",
                    "country_code": geo.get("country_iso_code") or "",
                    "city": geo.get("city_name") or "",
                    "alerts": 0,
                }
            row["alerts"] += 1

        if dest_ip:
            key = (dest_ip, port)
            row = destinations.get(key)
            if row is None:
                zone = _zone_of(dest_ip, zones)
                row = destinations[key] = {
                    "dest_ip": dest_ip,
                    "dest_port": port,
                    "host": detection.dest_host,
                    "zone": zone["name"] if zone else "",
                    "alerts": 0,
                }
            row["alerts"] += 1

        key = (detection.signature, detection.source)
        row = signatures.setdefault(key, {
            "signature": detection.signature,
            "engine": detection.source,
            "alerts": 0,
        })
        row["alerts"] += 1

        if url:
            key = (method, url)
            row = paths.setdefault(key, {
                "method": key[0],
                "path": url,
                "alerts": 0,
            })
            row["alerts"] += 1

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
    shape = topology.shape(substrate().describe(), declared.read())

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

    try:
        typed = operator_log.commands(substrate().runner("attacker"))
    except operator_log.OperatorLogUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

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
    origin_id = _payload(request).get("origin")
    try:
        chosen = attacker.find(_standing(), origin_id)
    except attacker.UnknownOrigin as exc:
        raise Http404(str(exc))

    attacker.set_origin(chosen["address"], substrate().runner("proxy"))
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
    try:
        return _reply(objectives.catalogue(substrate().runner("wiki")))
    except objectives.ObjectivesUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

@require_http_methods(["GET", "POST"])
def session_objectives(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method != "GET":
        shut = _closed(session)
        if shut:
            return shut

    if request.method == "GET":
        return _reply(
            [_shape(o, OBJECTIVE_FIELDS) for o in session.objectives.all()]
        )

    try:
        return _reply(_observe_objectives(session))
    except objectives.ObjectivesUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

def _observe_objectives(session) -> dict:
    found, unreadable = objectives.observe(substrate().runner("wiki"))
    solved = {o["key"]: o for o in found if o["solved"]}

    if session.baseline is None:
        if unreadable:
            raise objectives.ObjectivesUnavailable(unreadable)
        session.baseline = sorted(solved)
        session.save(update_fields=["baseline"])
        return {"achieved": 0, "baseline": len(session.baseline)}

    ignore = set(session.baseline) | set(
        session.objectives.values_list("key", flat=True)
    )
    observed_at = timezone.now()
    fresh = [
        Objective(
            session=session,
            key=key,
            name=objective["name"],
            category=objective["category"],
            difficulty=objective["difficulty"],
            achieved_at=at,
            earliest=earliest,
            latest=latest,
        )
        for key, objective in solved.items()
        if key not in ignore
        for at, earliest, latest in [_achieved(objective, session, observed_at)]
    ]
    before = session.objectives.count()
    Objective.objects.bulk_create(fresh, ignore_conflicts=True)

    total = session.objectives.count()
    observed = {"achieved": total - before, "total": total}
    if unreadable:
        observed["unreadable"] = unreadable
    return observed

@require_http_methods(["POST"])
def fire_attack(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    shut = _closed(session)
    if shut:
        return shut

    try:
        case = wargames.find_case(session.scenario, _payload(request).get("case"))
    except wargames.UnknownWargame as exc:
        raise Http404(str(exc))

    case = dict(case, case_id=str(uuid.uuid4()))
    case.setdefault("correlation", "marker")

    try:
        origin = _origin_for(session, _payload(request).get("origin"))
    except attacker.UnknownOrigin as exc:
        raise Http404(str(exc))

    target_url = settings.TARGET_URL
    if origin:
        target_url = origin["target_url"]
        spec = dict(case.get("request") or {})
        if spec:
            spec["headers"] = dict(
                spec.get("headers") or {},
                Host=urlsplit(settings.PUBLIC_TARGET_URL).netloc,
            )
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
    recorded = Case.objects.create(
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
        ended_at=finished_at,
        meta=dict(
            harness.case_meta(case),
            **({"origin": origin["id"], "target_url": origin["target_url"]}
               if origin else {}),
        ),
    )

    time.sleep(settings.TARGET_SETTLE)
    try:
        _observe_objectives(session)
    except (objectives.ObjectivesUnavailable, RangeUnavailable):
        pass
    return _reply(_shape(recorded, CASE_FIELDS), status=201)

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
    shut = _closed(session)
    if shut:
        return shut

    try:
        unobserved = _observe_objectives(session).get("unreadable")
    except (objectives.ObjectivesUnavailable, RangeUnavailable) as exc:
        unobserved = str(exc)

    closed_at = timezone.now()
    if not Session.objects.filter(pk=session.pk, ended_at=None).update(ended_at=closed_at):
        session.refresh_from_db()
        return _closed(session)
    session.ended_at = closed_at
    reply = _shape(session, SESSION_FIELDS)
    if unobserved:
        reply["unobserved"] = unobserved
    return _reply(reply)

@require_http_methods(["GET", "POST"])
def session_cases(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "GET":
        return _reply([_shape(c, CASE_FIELDS) for c in session.cases.all()])

    shut = _closed(session)
    if shut:
        return shut

    body = _payload(request)
    errors = _case_errors(body)
    if errors:
        return _reply(errors, status=400)

    try:
        case = Case.objects.create(
            session=session,
            case_id=body["case_id"],
            name=body["name"],
            malicious=body["malicious"],
            stage=body.get("stage") or "",
            technique=body.get("technique") or "",
            pattern=body.get("pattern") or "",
            expect=body.get("expect") or "",
            correlation=body["correlation"],
            source_ip=body.get("source_ip"),
            started_at=_instant(body["started_at"]),
            ended_at=_instant(body["ended_at"]),
            meta=body.get("meta") or {},
        )
    except IntegrityError:
        return _reply(
            {"detail": f"case {body['case_id']} is already recorded in session {session.pk}"},
            status=409,
        )

    time.sleep(settings.TARGET_SETTLE)

    try:
        observed = _observe_objectives(session)["achieved"]
    except (objectives.ObjectivesUnavailable, RangeUnavailable):
        observed = None

    return _reply(
        _shape(case, CASE_FIELDS) | {"objectives": observed}, status=201
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
    start, end = _session_window(session)
    try:
        restored = _restore_expired()
    except (RangeUnavailable, suricata.RulesUnreadable):
        restored = []

    try:
        documents, truncated = elastic.fetch(
            settings.ELASTIC_URL, settings.ELASTIC_INDEX, start, end
        )
    except elastic.ElasticUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    known = set(
        Detection.objects.filter(session=session).values_list("detection_id", flat=True)
    )
    stale = 0
    rows = []

    alerts = elastic.normalize_all(documents)

    unmarked = set(
        Detection.objects.filter(session=session, marker=None).values_list("detection_id", flat=True)
    )
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

    before = Detection.objects.filter(session=session).count()
    Detection.objects.bulk_create(rows, ignore_conflicts=True)
    ingested = Detection.objects.filter(session=session).count() - before

    reply = {"ingested": ingested, "skipped": skipped, "stale": stale, "restored": restored}
    if truncated:
        read, total = truncated
        reply["truncated"] = {"read": read, "total": total}
        session.truncated = True
        session.read_of = [read, total]
        session.save(update_fields=["truncated", "read_of"])
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
            return _reply({"detail": f'"after" must be a row id, got {after!r}'}, 400)

    detections = list(detections)
    addresses = {d.src_ip for d in detections if d.src_ip}
    zones, _ = _segments() if addresses else ([], {})
    located = _located(session, addresses) if addresses else {}
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
        }
    )

@require_http_methods(["GET"])
def session_score(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    forced = request.GET.get("correlation")
    if forced is not None and forced not in CORRELATION_STRATEGIES:
        return _reply(
            {
                "detail": f'"{forced}" is not a valid strategy; expected one of '
                f"{', '.join(CORRELATION_STRATEGIES)}."
            },
            status=400,
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
    if session.truncated:
        read, total = session.read_of or [0, 0]
        warnings.append(("score.warning.truncated", read, total))

    return _reply(
        {
            "tp": totals.tp,
            "fp": totals.fp,
            "fn": totals.fn,
            "tn": totals.tn,
            "precision": totals.precision,
            "recall": totals.recall,
            "f1": totals.f1,
            "false_positive_rate": totals.false_positive_rate,
            "benign_cases": totals.fp + totals.tn,
            "unattributed": len(result.unmatched_detection_ids),
            "warnings": warnings,
            "per_case": per_case,
            "objectives": board.__dict__,
            "breaches": [
                dict(b.__dict__, detection_ids=list(b.detection_ids)) for b in breaches
            ],
        }
    )

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

def _achieved(objective, session, observed_at):
    stamp = objective.get("solved_at")
    try:
        solved_at = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        solved_at = None
    if solved_at is None or not session.started_at - CLOCK_SLACK <= solved_at <= observed_at:
        return observed_at, None, None
    resolution = timedelta(milliseconds=1) if "." in stamp else timedelta(seconds=1)
    lookback = (
        scoreboard.ATTRIBUTION_WINDOW if objective.get("stamped_late") else scoreboard.CLOCK_SKEW
    )
    return (
        solved_at,
        solved_at - lookback,
        solved_at + resolution + scoreboard.CLOCK_SKEW,
    )

def _expected(scenario, cases):
    unrecorded = any(case.expect is None for case in cases)
    catalogue = _expectations(scenario) if unrecorded else {}
    return {
        case.case_id: catalogue.get(case.name) if case.expect is None else case.expect
        for case in cases
    }

def _expectations(scenario):
    try:
        return wargames.expectations(scenario)
    except wargames.UnknownWargame:
        return {}

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

def _session_window(session):
    start = session.started_at - timedelta(minutes=1)
    end = (session.ended_at or timezone.now()) + timedelta(minutes=1)
    return start, end

@require_http_methods(["GET"])
def current_rules(request):
    content = suricata.current(substrate().runner('sensor'))
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
        return _reply({"detail": f'"sid" must be a rule id, got {body.get("sid")!r}'}, 400)

    minutes = _minutes(body.get("minutes", SUPPRESSION_MINUTES))
    expires_at = timezone.now() + timedelta(minutes=minutes)
    content = suricata.current(substrate().runner('sensor'))

    try:
        silenced = suppress.silence(content, sid, expires_at.isoformat())
    except KeyError:
        raise Http404(f"no active rule carries sid {sid}")

    original = suppress.find(content, sid)
    try:
        suricata.apply(silenced, substrate().runner('sensor'), settings.FSL_SENSOR_RELOAD)
    except suricata.RuleApplyError as exc:
        return _reply({"detail": str(exc)}, status=400)

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
    current = suricata.current(substrate().runner('sensor'))
    superseded = suppress.find(current, record.sid) is not None
    lift = suppress.discard if superseded else suppress.restore
    try:
        content = lift(current, record.sid, record.original)
    except KeyError:
        record.restored_at = timezone.now()
        record.save(update_fields=["restored_at"])
        return True, None

    try:
        suricata.apply(content, substrate().runner('sensor'), settings.FSL_SENSOR_RELOAD)
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

def _version(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]

@require_http_methods(["POST"])
@_in_turn
def apply_rules(request):
    content = _rule_file(request)
    body = _payload(request)
    if "base" in body:
        base = body["base"]
        live = _version(suricata.current(substrate().runner('sensor')))
        if base != live:
            return _reply({
                "detail": "the sensor's rules changed since this copy was loaded "
                          f"(loaded {base or 'nothing'}, live {live}); reload them and edit again",
            }, status=409)
    try:
        suricata.apply(content, substrate().runner('sensor'), settings.FSL_SENSOR_RELOAD)
    except suricata.RuleApplyError as exc:
        return _reply({"detail": str(exc)}, status=400)

    ruleset = RuleSet.objects.create(content=content, applied_at=timezone.now())
    return _reply(_shape(ruleset, RULESET_FIELDS))
