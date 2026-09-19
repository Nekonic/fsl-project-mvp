import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

import requests

import wargames
from api.models import Case, Detection, RuleSet, ScoreSnapshot, Session
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
    session = Session.objects.create(scenario=body.get("scenario") or "juice-shop")
    return _reply(_shape(session, SESSION_FIELDS), status=201)


@require_http_methods(["GET"])
def wargame_catalogue(request):
    return _reply(wargames.catalogue())


@require_http_methods(["GET"])
def wargame_cases(request, wargame_id):
    try:
        return _reply(wargames.cases(wargame_id))
    except wargames.UnknownWargame:
        raise Http404(wargame_id)


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
    session = get_object_or_404(Session, pk=session_id)
    return _reply([_shape(d, DETECTION_FIELDS) for d in session.detections.all()])


@require_http_methods(["GET"])
def session_score(request, session_id):
    """Score the stored cases against the stored alerts and snapshot it."""
    session = get_object_or_404(Session, pk=session_id)

    cases = list(session.cases.all())
    detections = list(session.detections.all())

    result = correlate([c.to_record() for c in cases], [d.to_record() for d in detections])
    totals = compute_score(result)

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

    return _reply(_shape(snapshot, SCORE_FIELDS))


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
