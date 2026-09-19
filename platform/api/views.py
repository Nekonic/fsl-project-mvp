import json
import uuid
from dataclasses import replace
from datetime import timedelta

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
import wargames
from api.models import Case, Detection, Objective, RuleSet, ScoreSnapshot, Session
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
SCORE_FIELDS = (
    "id", "tp", "fp", "fn", "tn", "precision", "recall", "f1",
    "false_positive_rate", "warnings", "per_case", "computed_at",
)

CASE_REQUIRED = ("case_id", "name", "malicious", "correlation", "started_at", "ended_at")


def _shape(obj, fields):
    return {name: getattr(obj, name) for name in fields}


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
    try:
        return _reply(
            {
                "container": settings.ATTACKER_CONTAINER,
                "source_ip": attacker.source_ip(),
                "terminal_url": settings.ATTACKER_TERMINAL_URL,
            }
        )
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
        solved = {o["key"]: o for o in objectives.catalogue() if o["solved"]}
    except objectives.ObjectivesUnavailable as exc:
        return _reply({"detail": str(exc)}, status=503)

    if session.baseline is None:
        # The target was unreachable when the session opened. Establish the
        # baseline now and credit nobody for what came before it.
        session.baseline = sorted(solved)
        session.save(update_fields=["baseline"])
        return _reply({"achieved": 0, "baseline": len(session.baseline)})

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
            achieved_at=observed_at,
        )
        for key, objective in solved.items()
        if key not in ignore
    ]
    Objective.objects.bulk_create(fresh)

    return _reply({"achieved": len(fresh), "total": session.objectives.count()})


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

    started_at = timezone.now()
    try:
        harness.fire(
            requests.Session(), case, settings.TARGET_URL, settings.TOOL_TARGET_URL
        )
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
        meta=harness.case_meta(case),
    )
    return _reply(_shape(recorded, CASE_FIELDS), status=201)


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
    return _reply(_shape(case, CASE_FIELDS), status=201)


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

    return _reply([_shape(d, DETECTION_FIELDS) for d in detections])


@require_http_methods(["GET"])
def detection_detail(request, detection_id):
    """One alert with the log record behind it, for the console's drawer."""
    detection = get_object_or_404(Detection, pk=detection_id)
    return _reply(
        _shape(detection, DETECTION_DETAIL_FIELDS) | {"session": detection.session_id}
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

    records = [c.to_record() for c in cases]
    if forced:
        records = [replace(record, correlation=forced) for record in records]

    result = correlate(records, [d.to_record() for d in detections])
    totals = compute_score(result)
    board = scoreboard.tally(_breaches(session, cases, result), totals.fp)

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
        warnings=list(totals.warnings),
        per_case=_per_case(result),
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


def _per_case(result):
    return [
        {
            "case_id": m.case_id,
            "name": m.name,
            "malicious": m.malicious,
            "detected": m.detected,
            "verdict": _verdict(m.malicious, m.detected),
            "detection_ids": list(m.detection_ids),
        }
        for m in result.matches
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
