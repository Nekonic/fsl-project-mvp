import ipaddress
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from urllib.parse import urlsplit

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
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
from range.ports import RangeUnavailable
from rules import suricata
from scoring.correlate import correlate
from scoring.metrics import score as compute_score
from scoring.types import CORRELATION_STRATEGIES

                                                                            
                                                       
SESSION_FIELDS = ("id", "scenario", "started_at", "ended_at")
CASE_FIELDS = (
    "id", "case_id", "name", "malicious", "stage", "technique", "pattern",
    "correlation", "source_ip", "started_at", "ended_at", "meta",
)
DETECTION_FIELDS = (
    "id", "detection_id", "source", "signature", "severity", "timestamp",
    "src_ip", "marker",
)
                                                                          
                                                                       
DETECTION_DETAIL_FIELDS = DETECTION_FIELDS + ("raw",)
OBJECTIVE_FIELDS = ("id", "key", "name", "category", "difficulty", "achieved_at")
RULESET_FIELDS = ("id", "content", "created_at", "applied_at", "validation_output")
SUPPRESSION_FIELDS = (
    "id", "sid", "reason", "created_at", "expires_at", "restored_at",
)

                                                                             
                                                                            
                                                                       
                                       
SUPPRESSION_MINUTES = 60
CASE_REQUIRED = ("case_id", "name", "malicious", "correlation", "started_at", "ended_at")

                                                                         
                                                                    
                                                                          
                                                                          
                                                                      
            
CLOCK_SLACK = timedelta(seconds=5)

def _shape(obj, fields):
    return {name: getattr(obj, name) for name in fields}

def _listed(detection):
    raw = detection.raw or {}
    http = raw.get("http") or {}
    port = raw.get("dest_port")
    return dict(
        _shape(detection, DETECTION_FIELDS),
        dest=f"{raw['dest_ip']}:{port}" if raw.get("dest_ip") and port
             else (raw.get("dest_ip") or ""),
        method=http.get("http_method") or "",
        path=http.get("url") or "",
    )

def _reply(payload, status=200):
    return JsonResponse(payload, status=status, encoder=DjangoJSONEncoder, safe=False)

def _payload(request):
    return json.loads(request.body or b"{}")

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

    body = _payload(request)
    try:
        baseline = sorted(objectives.solved_keys(substrate().runner("wiki")))
    except objectives.ObjectivesUnavailable:
                                                                            
                                                                               
                                                                              
        baseline = None
    session = Session.objects.create(
        scenario=body.get("scenario") or "juice-shop", baseline=baseline
    )
    return _reply(_shape(session, SESSION_FIELDS), status=201)

@require_http_methods(["GET"])
def attacker_box(request):
    try:
        origin = attacker.find(substrate().describe(), request.GET.get("origin"))
    except RangeUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
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

def _segments():
    try:
        described = substrate().describe()
    except RangeUnavailable:
        return [], {}

    segments = topology.shape(described, declared.read())["segments"]

    zones = []
    for segment in segments:
        try:
            zones.append((ipaddress.ip_network(segment["subnet"]), segment))
        except ValueError:
            continue
    hosts = {
        node["address"]: node["name"]
        for segment in segments
        for node in segment["nodes"]
        if node["address"]
    }
    return zones, hosts

def _zone_of(address, zones):
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    return next((s for network, s in zones if parsed in network), None)

def _http(detection):
    return (detection.raw or {}).get("http") or {}

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
        http = _http(detection)

        if detection.src_ip:
            row = sources.get(detection.src_ip)
            if row is None:
                geo = located.get(detection.src_ip) or {}
                zone = _zone_of(detection.src_ip, zones)
                row = sources[detection.src_ip] = {
                    "src_ip": detection.src_ip,
                    "host": hosts.get(detection.src_ip, ""),
                    "zone": zone["name"] if zone else "",
                    "outside": bool(zone and zone["outside"]),
                    "country": geo.get("country_name") or "",
                    "country_code": geo.get("country_iso_code") or "",
                    "city": geo.get("city_name") or "",
                    "alerts": 0,
                }
            row["alerts"] += 1

        dest_ip = (detection.raw or {}).get("dest_ip")
        if dest_ip:
            port = (detection.raw or {}).get("dest_port") or ""
            key = f"{dest_ip}:{port}" if port else dest_ip
            row = destinations.get(key)
            if row is None:
                zone = _zone_of(dest_ip, zones)
                row = destinations[key] = {
                    "dest": key,
                    "host": hosts.get(dest_ip, ""),
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

        url = http.get("url")
        if url:
            key = (http.get("http_method") or "", url)
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
    try:
        shape = topology.shape(substrate().describe(), declared.read())
    except RangeUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    subnets = []
    for segment in shape["segments"]:
        segment["alerts"] = 0
        try:
            subnets.append((ipaddress.ip_network(segment["subnet"]), segment))
        except ValueError:
            continue

    unplaced = 0
    for detection in session.detections.all():
        try:
            address = ipaddress.ip_address(detection.src_ip or "")
        except ValueError:
            unplaced += 1
            continue
        found = next((s for network, s in subnets if address in network), None)
        if found is None:
                                                                              
                                                                       
            unplaced += 1
        else:
            found["alerts"] += 1

    return _reply({**shape, "unplaced": unplaced})

@require_http_methods(["GET"])
def origins(request):
    try:
        return _reply({"origins": attacker.origins(substrate().describe())})
    except RangeUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

@require_http_methods(["GET"])
def session_commands(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    try:
        typed = operator_log.commands(substrate().runner("attacker"))
    except (RangeUnavailable, operator_log.OperatorLogUnavailable) as exc:
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
        chosen = attacker.find(substrate().describe(), origin_id)
    except RangeUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    except attacker.UnknownOrigin as exc:
        raise Http404(str(exc))

    attacker.set_origin(chosen["address"], substrate().runner("proxy"))
    return _reply({"origin": chosen["id"], "source_ip": chosen["source_ip"]})

@require_http_methods(["POST"])
def attacker_label(request):
    attacker.set_label(_payload(request).get("case_id"), substrate().runner("proxy"))
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
    solved = {o["key"]: o for o in objectives.catalogue(substrate().runner("wiki")) if o["solved"]}

    if session.baseline is None:
                                                                           
                                                                 
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
            achieved_at=_solved_at(objective, session, observed_at),
        )
        for key, objective in solved.items()
        if key not in ignore
    ]
    Objective.objects.bulk_create(fresh)

    return {"achieved": len(fresh), "total": session.objectives.count()}

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
    except RangeUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
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

    recorded = Case.objects.create(
        session=session,
        case_id=case["case_id"],
        name=case["name"],
        malicious=bool(case["malicious"]),
        stage=case.get("stage") or "",
        technique=case.get("technique") or "",
        pattern=case.get("pattern") or "",
        correlation=case["correlation"],
        source_ip=case.get("source_ip"),
        started_at=started_at,
        ended_at=timezone.now(),
                                                                      
                                                                           
                                                                           
                                                                         
                                                                          
                                                               
        meta=dict(
            harness.case_meta(case),
            **({"origin": origin["id"], "target_url": origin["target_url"]}
               if origin else {}),
        ),
    )
    return _reply(_shape(recorded, CASE_FIELDS), status=201)

                                                                           
ROTATE = "rotate"

def _origin_for(session, requested):
    if not requested:
        return None

    described = substrate().describe()
    if requested != ROTATE:
        return attacker.find(described, requested)

    available = attacker.origins(described)
    if not available:
        raise attacker.UnknownOrigin("the stack declares no origins to rotate through")
    return available[session.cases.count() % len(available)]

@require_http_methods(["GET"])
def session_detail(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    return _reply(_shape(session, SESSION_FIELDS))

@require_http_methods(["POST"])
def close_session(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at"])
    return _reply(_shape(session, SESSION_FIELDS))

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

    case = Case.objects.create(
        session=session,
        case_id=body["case_id"],
        name=body["name"],
        malicious=bool(body["malicious"]),
        stage=body.get("stage") or "",
        technique=body.get("technique") or "",
        pattern=body.get("pattern") or "",
        correlation=body["correlation"],
        source_ip=body.get("source_ip"),
        started_at=parse_datetime(body["started_at"]),
        ended_at=parse_datetime(body["ended_at"]),
        meta=body.get("meta") or {},
    )

                                                                          
                                                                            
                                                                             
                                                                         
                                                                              
                                                                               
                                                                              
                                                               
    time.sleep(settings.TARGET_SETTLE)

                                                                              
                                                                               
                                                                           
                                                                             
    try:
        observed = _observe_objectives(session)["achieved"]
    except objectives.ObjectivesUnavailable:
        observed = None

    return _reply(
        _shape(case, CASE_FIELDS) | {"objectives": observed}, status=201
    )

def _case_errors(body):
    errors = {
        field: ["This field is required."]
        for field in CASE_REQUIRED
        if body.get(field) is None
    }
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
        documents, truncated = elastic.fetch(
            settings.ELASTIC_URL, settings.ELASTIC_INDEX, start, end
        )
    except elastic.ElasticUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    known = set(
        Detection.objects.filter(session=session).values_list("detection_id", flat=True)
    )
    ingested = 0

    alerts = elastic.normalize_all(documents)

                                                                       
                                                                          
                                       
    productive = {a["detection_id"].split(":")[0] for a in alerts}
    skipped = sum(1 for doc_id, _ in documents if doc_id not in productive)

    for alert in alerts:
        if alert["detection_id"] in known or alert["timestamp"] is None:
            continue
        Detection.objects.create(session=session, **alert)
        known.add(alert["detection_id"])
        ingested += 1

    reply = {"ingested": ingested, "skipped": skipped}
    if truncated:
        read, total = truncated
        reply["truncated"] = {"read": read, "total": total}
    return _reply(reply)

@require_http_methods(["GET"])
def session_detections(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    detections = session.detections.all()

    after = request.GET.get("after")
    if after is not None:
        if not after.lstrip("-").isdigit():
            return _reply({"detail": f'"after" must be a row id, got {after!r}'}, 400)
        detections = detections.filter(id__gt=int(after))

    return _reply([_listed(d) for d in detections])

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
    per_case = _per_case(result, _expectations(session.scenario), signatures)
    board = scoreboard.tally(_breaches(session, cases, result), totals.fp)
    warnings = list(totals.warnings) + _wrong_reason_warnings(per_case)

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
            "warnings": warnings,
            "per_case": per_case,
            "objectives": board.__dict__,
            "breaches": _breach_rows(session, cases, result),
        }
    )

def _attempts(cases, result):
    by_case = {match.case_id: match for match in result.matches}
    return [
        scoreboard.Attempt(
            case_id=case.case_id,
            started_at=case.started_at,
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
        credited = scoreboard.attribute(objective.achieved_at, attempts)
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

def _breach_rows(session, cases, result):
    return [
        {
            "key": b.key,
            "name": b.name,
            "category": b.category,
            "difficulty": b.difficulty,
            "detected": b.detected,
            "detection_ids": list(b.detection_ids),
        }
        for b in _breaches(session, cases, result)
    ]

def _solved_at(objective, session, observed_at):
    stamp = objective.get("solved_at")
    if not stamp:
        return observed_at
    try:
        solved_at = datetime.fromisoformat(stamp)
    except ValueError:
        return observed_at
    believable = session.started_at - CLOCK_SLACK <= solved_at <= observed_at
    return solved_at if believable else observed_at

def _expectations(scenario):
    try:
        return wargames.expectations(scenario)
    except wargames.UnknownWargame:
        return {}

def _per_case(result, expectations, signatures):
    return [
        {
            "case_id": m.case_id,
            "name": m.name,
            "malicious": m.malicious,
            "detected": m.detected,
            "verdict": _verdict(m.malicious, m.detected),
            "detection_ids": list(m.detection_ids),
            "expect": expectations.get(m.name) or "",
            "corroborated": scoreboard.corroborated(
                expectations.get(m.name),
                [signatures[d] for d in m.detection_ids if d in signatures],
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
    return _reply({"content": suricata.current(substrate().runner('sensor'))})

@require_http_methods(["POST"])
def validate_rules(request):
    outcome = suricata.validate(_payload(request).get("content", ""),
                                 substrate().runner("sensor"))
    payload = {"ok": outcome.ok, "output": outcome.output}
    return _reply(payload, status=200 if outcome.ok else 400)

@require_http_methods(["GET", "POST"])
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
    except (TypeError, ValueError):
        return _reply({"detail": f'"sid" must be a rule id, got {body.get("sid")!r}'}, 400)

    minutes = body.get("minutes") or SUPPRESSION_MINUTES
    expires_at = timezone.now() + timedelta(minutes=float(minutes))
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
def restore_suppression(request, suppression_id):
    record = get_object_or_404(Suppression, pk=suppression_id, restored_at__isnull=True)
    problem = _restore(record)
    if problem:
        return _reply({"detail": problem}, status=400)
    return _reply(_shape(record, SUPPRESSION_FIELDS))

def _restore(record) -> str | None:
    try:
        content = suppress.restore(suricata.current(substrate().runner('sensor')), record.sid, record.original)
    except KeyError:
                                                                            
                                                                          
        record.restored_at = timezone.now()
        record.save(update_fields=["restored_at"])
        return None

    try:
        suricata.apply(content, substrate().runner('sensor'), settings.FSL_SENSOR_RELOAD)
    except suricata.RuleApplyError as exc:
                                                                             
                                                                               
                                                          
        return f"could not restore sid {record.sid}: {exc}"

    record.restored_at = timezone.now()
    record.save(update_fields=["restored_at"])
    return None

def _restore_expired() -> list:
    due = Suppression.objects.filter(
        restored_at__isnull=True, expires_at__lte=timezone.now()
    )
    lifted = []
    for record in list(due):
        problem = _restore(record)
        lifted.append({"sid": record.sid, "ok": problem is None, "detail": problem})
    return lifted

@require_http_methods(["POST"])
def apply_rules(request):
    content = _payload(request).get("content", "")
    try:
        suricata.apply(content, substrate().runner('sensor'), settings.FSL_SENSOR_RELOAD)
    except suricata.RuleApplyError as exc:
        return _reply({"detail": str(exc)}, status=400)

    ruleset = RuleSet.objects.create(
        content=content, applied_at=timezone.now(), validation_output=""
    )
    return _reply(_shape(ruleset, RULESET_FIELDS))
