import ipaddress
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta

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
    ScoreSnapshot,
    Session,
    Suppression,
)
from ingest import elastic
from redteam import harness
from rules import suricata
from scoring.correlate import correlate
from scoring.metrics import score as compute_score
from scoring.types import CORRELATION_STRATEGIES

# The JSON shape of each resource. The console templates and test/ both read
# these keys by name, so changing one is an API change.
SESSION_FIELDS = ("id", "scenario", "started_at", "ended_at")
CASE_FIELDS = (
    "id", "case_id", "name", "malicious", "technique", "correlation",
    "source_ip", "started_at", "ended_at", "meta",
)
DETECTION_FIELDS = (
    "id", "detection_id", "source", "signature", "severity", "timestamp",
    "src_ip", "marker",
)
# One alert plus the document it came from. Only the drawer asks for this:
# `raw` is the whole Elasticsearch record and far too heavy for a list.
DETECTION_DETAIL_FIELDS = DETECTION_FIELDS + ("raw",)
OBJECTIVE_FIELDS = ("id", "key", "name", "category", "difficulty", "achieved_at")
RULESET_FIELDS = ("id", "content", "created_at", "applied_at", "validation_output")
SUPPRESSION_FIELDS = (
    "id", "sid", "reason", "created_at", "expires_at", "restored_at",
)

# How long a rule stays silenced unless asked otherwise. Sentinel defaults to
# 24 hours; a range session lasts minutes, where 24 hours and "for good" are
# the same thing, and being indistinguishable from permanent is the one
# property a suppression must not have.
SUPPRESSION_MINUTES = 60
SCORE_FIELDS = (
    "id", "tp", "fp", "fn", "tn", "precision", "recall", "f1",
    "false_positive_rate", "warnings", "per_case", "computed_at",
)

CASE_REQUIRED = ("case_id", "name", "malicious", "correlation", "started_at", "ended_at")

# The target keeps its own clock and its timestamps arrive at millisecond
# precision, so comparing one to this session's start exactly is not
# meaningful - a value can round to just before a session it plainly falls
# inside. What the check is really rejecting is a restore, which is out by
# hours, so a few seconds of slack costs nothing and removes the false
# rejection.
CLOCK_SLACK = timedelta(seconds=5)


def _shape(obj, fields):
    return {name: getattr(obj, name) for name in fields}


def _listed(detection):
    """One row of the alert list.

    Destination and path come out of the stored record rather than out of new
    columns: only Suricata's record keeps the whole event, so ModSecurity's
    half of the same traffic reads empty here - which is the honest answer and
    the same one the map gives about geo.
    """
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
    """DjangoJSONEncoder renders datetimes the way the console expects."""
    return JsonResponse(payload, status=status, encoder=DjangoJSONEncoder, safe=False)


def _payload(request):
    return json.loads(request.body or b"{}")


@require_http_methods(["GET", "POST"])
def sessions(request):
    if request.method == "GET":
        return _reply([_shape(s, SESSION_FIELDS) for s in Session.objects.all()])

    body = _payload(request)
    try:
        baseline = sorted(objectives.solved_keys())
    except objectives.ObjectivesUnavailable:
        # Not fatal, and not an empty baseline either: null records that the
        # target could not be asked. Calling it "nothing was solved" would hand
        # the red team credit for every objective reached before they arrived.
        baseline = None
    session = Session.objects.create(
        scenario=body.get("scenario") or "juice-shop", baseline=baseline
    )
    return _reply(_shape(session, SESSION_FIELDS), status=201)


@require_http_methods(["GET"])
def attacker_box(request):
    """Where the terminal's traffic will come from, and where to send it.

    A labelled window is scored against this address, so it has to follow the
    origin the red team picked: leaving by Hong Kong while the window records
    Moscow matches no alert and scores a real attack as a miss.
    """
    try:
        origin = attacker.find(request.GET.get("origin"))
    except attacker.AttackerUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    except attacker.UnknownOrigin as exc:
        raise Http404(str(exc))

    return _reply(
        {
            "container": settings.ATTACKER_CONTAINER,
            "source_ip": origin["source_ip"],
            "origin": origin["id"],
            "origin_label": origin["label"],
            "target_url": origin["target_url"],
            "terminal_url": settings.ATTACKER_TERMINAL_URL,
        }
    )


# How many rows a top-N table shows. More than this is not read from a board
# and not scrolled through on a screen either.
TOP_N = 25


def _zones():
    """Which address range belongs to what, by name.

    Igloo's write-up of a real console names the defect this fixes: the device
    that raised an alert is obvious from the alert, but working out what its
    source and destination addresses *belong to* takes further work - so the
    console maps ranges to the name of the thing that owns them and shows that
    name beside the address. Here the ranges are the stack's own segments.
    """
    try:
        segments = topology.shape()["segments"]
    except topology.StackUnavailable:
        # The address is the fact and the zone is the extra. A stopped Docker
        # must not empty the board.
        return []

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


def _http(detection):
    """The request an alert was raised on, where the record kept it.

    Suricata keeps the whole event, so the method, host, path and user agent
    are all there. ModSecurity's record keeps the message alone, so these read
    empty for its half of the same traffic - said, not guessed.
    """
    return (detection.raw or {}).get("http") or {}


@require_http_methods(["GET"])
def session_top(request, session_id):
    """The board: each dimension of the traffic, counted, biggest first.

    The shape every real console has. Cloudflare's security events screen is a
    summary, one time series and "top events by source" - addresses,
    countries, paths, hosts - each a table of one dimension with its count.
    Igloo's adds the zone beside the address, which is what makes an address
    mean something to whoever is reading it.
    """
    session = get_object_or_404(Session, pk=session_id)
    detections = list(session.detections.all())
    zones = _zones()

    # Geo belongs to the address, not the alert - only Suricata's records keep
    # the whole document. See session_map.
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
    """The shape of the range, with what arrived on each segment.

    Read off Docker rather than drawn, because a picture of a network is wrong
    within a session and a wrong picture is worse than none: it is believed.

    The counts are what make it one object with the alert stream. A segment
    reading zero is not an empty box - it is a place attacks could arrive and
    nothing is watching, which is the thing a blue team most needs to see.
    """
    session = get_object_or_404(Session, pk=session_id)
    try:
        shape = topology.shape()
    except topology.StackUnavailable as exc:
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
            # Counted, never dropped: a diagram whose numbers do not add up to
            # the alert count beside it is worse than one that says so.
            unplaced += 1
        else:
            found["alerts"] += 1

    return _reply({**shape, "unplaced": unplaced})


@require_http_methods(["GET"])
def origins(request):
    """Every place an attack can be sent from."""
    try:
        return _reply({"origins": attacker.origins()})
    except attacker.AttackerUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)


@require_http_methods(["POST"])
def attacker_label(request):
    """Open or close the marker the proxy stamps on the attacker's traffic."""
    attacker.set_label(_payload(request).get("case_id"))
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
        return _reply(objectives.catalogue())
    except objectives.ObjectivesUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)


@require_http_methods(["GET", "POST"])
def session_objectives(request, session_id):
    """What the red team has actually taken, as judged by the target itself.

    POST asks the target what it now considers solved and records anything new
    since this session opened. Nothing here is labelled by the platform: the
    application decides whether it was beaten.
    """
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "GET":
        return _reply(
            [_shape(o, OBJECTIVE_FIELDS) for o in session.objectives.all()]
        )

    try:
        return _reply(_observe_objectives(session))
    except objectives.ObjectivesUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)


def _observe_objectives(session) -> dict:
    """Record what the target now counts as solved and this session did not.

    The moment to ask is the moment a case is reported, because that is when
    the red team has just finished doing something. Asking once at the end of
    a run stamps every objective with the same time, and attribution then
    credits them all to whichever case happened to fire last - which in a run
    that ends on benign traffic is nobody at all.
    """
    solved = {o["key"]: o for o in objectives.catalogue() if o["solved"]}

    if session.baseline is None:
        # The target was unreachable when the session opened. Establish the
        # baseline now and credit nobody for what came before it.
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
    """Send one catalogue case and record what it was.

    Ground truth is written only after the traffic has left. A case recorded
    for an attack that never went out is a false negative charged to the
    defence, which is the one mistake this platform must not make.
    """
    session = get_object_or_404(Session, pk=session_id)

    try:
        case = wargames.find_case(session.scenario, _payload(request).get("case"))
    except wargames.UnknownWargame as exc:
        raise Http404(str(exc))

    case = dict(case, case_id=str(uuid.uuid4()))
    case.setdefault("correlation", "marker")

    try:
        origin = _origin_for(session, _payload(request).get("origin"))
    except attacker.AttackerUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)
    except attacker.UnknownOrigin as exc:
        raise Http404(str(exc))

    target_url = origin["target_url"] if origin else settings.TARGET_URL

    started_at = timezone.now()
    try:
        # The tool target is the same door: an external tool that dialled the
        # default one would leave by a different address than the case says.
        harness.fire(requests.Session(), case, target_url, target_url)
    except harness.ToolUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    recorded = Case.objects.create(
        session=session,
        case_id=case["case_id"],
        name=case["name"],
        malicious=bool(case["malicious"]),
        technique=case.get("technique") or "",
        correlation=case["correlation"],
        source_ip=case.get("source_ip"),
        started_at=started_at,
        ended_at=timezone.now(),
        # The origin and the door it was dialled through, but *not* an
        # address: origins are discovered from the attacker box, and a case
        # fired here leaves from the platform, which has its own address on
        # the same network. Recording that address would name a source no
        # alert carries - the one mistake this platform must not make. The
        # map is read off the alerts, which carry the true one.
        meta=dict(
            harness.case_meta(case),
            **({"origin": origin["id"], "target_url": origin["target_url"]}
               if origin else {}),
        ),
    )
    return _reply(_shape(recorded, CASE_FIELDS), status=201)


# Asking for this instead of a place means "somewhere else than last time".
ROTATE = "rotate"


def _origin_for(session, requested):
    """Which place this attack leaves from, or None for the default door.

    Rotation is counted off the session's own cases rather than held as
    state: there is nothing to reset, and two windows onto one session cannot
    disagree about whose turn it is.
    """
    if not requested:
        return None
    if requested != ROTATE:
        return attacker.find(requested)

    available = attacker.origins()
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

    body = _payload(request)
    errors = _case_errors(body)
    if errors:
        return _reply(errors, status=400)

    case = Case.objects.create(
        session=session,
        case_id=body["case_id"],
        name=body["name"],
        malicious=bool(body["malicious"]),
        technique=body.get("technique") or "",
        correlation=body["correlation"],
        source_ip=body.get("source_ip"),
        started_at=parse_datetime(body["started_at"]),
        ended_at=parse_datetime(body["ended_at"]),
        meta=body.get("meta") or {},
    )

    # Give the target a beat before answering. Measured on a live run: the
    # shop records a solve about 80ms after it has answered the request that
    # earned it, while the red team fires its next case about 70ms later - so
    # every solve landed just inside the *following* case and attribution
    # credited it there. The red team blocks on this response, so waiting here
    # spaces the cases far enough apart for the target's own timestamps to fall
    # in the right window. Cheap at fifteen cases; it belongs here rather than
    # in the harness, which is the hypothesis and may not grow.
    time.sleep(settings.TARGET_SETTLE)

    # Best effort, and never at the cost of the case: what the red team did is
    # what this endpoint exists to record, and losing it because the shop would
    # not answer a side question would put a real attack on record as never
    # having happened. `objectives: null` says the target could not be asked.
    try:
        observed = _observe_objectives(session)["achieved"]
    except objectives.ObjectivesUnavailable:
        observed = None

    return _reply(
        _shape(case, CASE_FIELDS) | {"objectives": observed}, status=201
    )


def _case_errors(body):
    """Reject a case before it reaches the database.

    An unknown correlation strategy must never be stored: the scoring core
    raises on it, which would turn one bad case into an unscorable session.
    """
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
    """Pull Elasticsearch documents for the session window and store them.

    Alerts already stored are skipped. Repeated calls must give the same result
    so the blue team can fix a rule and re-ingest.
    """
    session = get_object_or_404(Session, pk=session_id)
    start, end = _session_window(session)

    try:
        documents = elastic.fetch(settings.ELASTIC_URL, settings.ELASTIC_INDEX, start, end)
    except elastic.ElasticUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    known = set(
        Detection.objects.filter(session=session).values_list("detection_id", flat=True)
    )
    ingested = 0

    alerts = elastic.normalize_all(documents)

    # Documents that produced no alert at all. One document can produce
    # several alerts (a ModSecurity transaction with several messages), so
    # subtraction would not count this.
    productive = {a["detection_id"].split(":")[0] for a in alerts}
    skipped = sum(1 for doc_id, _ in documents if doc_id not in productive)

    for alert in alerts:
        if alert["detection_id"] in known or alert["timestamp"] is None:
            continue
        Detection.objects.create(session=session, **alert)
        known.add(alert["detection_id"])
        ingested += 1

    return _reply({"ingested": ingested, "skipped": skipped})


@require_http_methods(["GET"])
def session_detections(request, session_id):
    """The alerts, or just the ones a live console has not seen yet.

    `?after=` is what keeps a two-second refresh cheap. A bad value is rejected
    rather than ignored, because falling back to "everything" would arrive at
    the console as a sudden flood of alerts that are not new.
    """
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
    """One alert with the log record behind it, for the console's drawer."""
    detection = get_object_or_404(Detection, pk=detection_id)
    return _reply(
        _shape(detection, DETECTION_DETAIL_FIELDS) | {"session": detection.session_id}
    )


@require_http_methods(["GET"])
def session_map(request, session_id):
    """Where the attacks came from, as points a map can draw.

    A location belongs to an address, not to an alert. The ingest pipeline
    writes it onto the Elasticsearch document, and only Suricata's records keep
    the whole document - ModSecurity's keep the message alone. So each address
    is placed once, from whichever alert happened to carry it, and then every
    alert from that address counts. Counting only the alerts that carry geo
    would make the WAF invisible on the map and halve every origin.

    Addresses that resolve to nothing are not guessed at. They are counted, and
    said so, because "seventeen alerts from somewhere unplaceable" is a fact
    about the range and an empty map is not.
    """
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
    """Score the stored cases against the stored alerts and snapshot it.

    `?correlation=` overrides what every case declared, so the same traffic can
    be scored both ways and the strategies compared. Only terminal windows
    carry both a marker and a source, so only they answer differently.
    """
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

    snapshot = ScoreSnapshot.objects.create(
        session=session,
        tp=totals.tp,
        fp=totals.fp,
        fn=totals.fn,
        tn=totals.tn,
        precision=totals.precision,
        recall=totals.recall,
        f1=totals.f1,
        false_positive_rate=totals.false_positive_rate,
        warnings=warnings,
        per_case=per_case,
    )

    return _reply(
        _shape(snapshot, SCORE_FIELDS)
        | {"objectives": board.__dict__, "breaches": _breach_rows(session, cases, result)}
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
    """When the target says it fell, if that can be believed.

    Prefer it: the poll is always late, because `solved` flips after the
    request that did it has been answered, and by then the red team may have
    moved on to the next case - which is then credited with the breach.

    Do not believe a stamp from before this session opened. The target
    rewrites every one of them in bulk when it restores its own state, and a
    restore is not a solve.
    """
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
    """Say so when a true positive is not evidence of anything.

    An alert inside the window is not an alert about the attack. Left
    unreported, a rule set that catches every case for reasons unrelated to
    any of them scores exactly as well as one that works.
    """
    wrong = [c["name"] for c in per_case if c["detected"] and c["corroborated"] is False]
    if not wrong:
        return []
    return [
        f"Detected for the wrong reason: {', '.join(wrong)}. Nothing attributed "
        f"to these mentions the mechanism the case declared, so the true "
        f"positive is not evidence that the defence saw this attack."
    ]


def _verdict(malicious: bool, detected: bool) -> str:
    if malicious:
        return "TP" if detected else "FN"
    return "FP" if detected else "TN"


def _session_window(session):
    """The session window. Still open means "up to now". One minute of slack."""
    start = session.started_at - timedelta(minutes=1)
    end = (session.ended_at or timezone.now()) + timedelta(minutes=1)
    return start, end


@require_http_methods(["GET"])
def current_rules(request):
    return _reply({"content": suricata.current()})


@require_http_methods(["POST"])
def validate_rules(request):
    """Validate only. Even on success, nothing is written and no RuleSet is made."""
    outcome = suricata.validate(_payload(request).get("content", ""))
    payload = {"ok": outcome.ok, "output": outcome.output}
    return _reply(payload, status=200 if outcome.ok else 400)


@require_http_methods(["GET", "POST"])
def suppressions(request):
    """Silence a rule, or see what is silenced.

    This is the loop no console closes: an analyst records "false positive"
    and the rule that produced it is untouched, because recording verdicts and
    editing detections belong to different teams and different tools. Here
    they are the same button.
    """
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
    content = suricata.current()

    try:
        silenced = suppress.silence(content, sid, expires_at.isoformat())
    except KeyError:
        raise Http404(f"no active rule carries sid {sid}")

    original = suppress.find(content, sid)
    try:
        suricata.apply(silenced)
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
    """Put one rule back. Returns what went wrong, or None."""
    try:
        content = suppress.restore(suricata.current(), record.sid, record.original)
    except KeyError:
        # The line is already back - edited by hand, most likely. Nothing to
        # undo, so stop tracking it rather than writing the rule in twice.
        record.restored_at = timezone.now()
        record.save(update_fields=["restored_at"])
        return None

    try:
        suricata.apply(content)
    except suricata.RuleApplyError as exc:
        # Leave it on the books. A suppression that cannot be lifted is worse
        # news than one that is still running, and silently marking it restored
        # would leave the rule off with nothing saying so.
        return f"could not restore sid {record.sid}: {exc}"

    record.restored_at = timezone.now()
    record.save(update_fields=["restored_at"])
    return None


def _restore_expired() -> list:
    """Lift every suppression whose deadline has passed."""
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
        suricata.apply(content)
    except suricata.RuleApplyError as exc:
        return _reply({"detail": str(exc)}, status=400)

    ruleset = RuleSet.objects.create(
        content=content, applied_at=timezone.now(), validation_output=""
    )
    return _reply(_shape(ruleset, RULESET_FIELDS))
