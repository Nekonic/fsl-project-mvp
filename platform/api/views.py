from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.models import Detection, RuleSet, ScoreSnapshot, Session
from api.serializers import (
    CaseSerializer,
    DetectionSerializer,
    RuleSetSerializer,
    ScoreSnapshotSerializer,
    SessionSerializer,
)
from ingest import elastic
from rules import suricata
from scoring.correlate import correlate
from scoring.metrics import score as compute_score


@api_view(["POST"])
def create_session(request):
    serializer = SessionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    session = serializer.save()
    return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def session_detail(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    return Response(SessionSerializer(session).data)


@api_view(["POST"])
def close_session(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at"])
    return Response(SessionSerializer(session).data)


@api_view(["GET", "POST"])
def session_cases(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "GET":
        return Response(CaseSerializer(session.cases.all(), many=True).data)

    serializer = CaseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    case = serializer.save(session=session)
    return Response(CaseSerializer(case).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
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
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

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

    return Response({"ingested": ingested, "skipped": skipped})


@api_view(["GET"])
def session_detections(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    return Response(DetectionSerializer(session.detections.all(), many=True).data)


@api_view(["GET"])
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

    return Response(ScoreSnapshotSerializer(snapshot).data)


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


@api_view(["GET"])
def current_rules(request):
    return Response({"content": suricata.current()})


@api_view(["POST"])
def validate_rules(request):
    """Validate only. Even on success, nothing is written and no RuleSet is made."""
    content = request.data.get("content", "")
    outcome = suricata.validate(content)
    payload = {"ok": outcome.ok, "output": outcome.output}
    if outcome.ok:
        return Response(payload)
    return Response(payload, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
def apply_rules(request):
    content = request.data.get("content", "")
    try:
        suricata.apply(content)
    except suricata.RuleApplyError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    ruleset = RuleSet.objects.create(
        content=content, applied_at=timezone.now(), validation_output=""
    )
    return Response(RuleSetSerializer(ruleset).data)
