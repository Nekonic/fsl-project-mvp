from rest_framework import serializers

from api.models import Case, Detection, RuleSet, ScoreSnapshot, Session
from scoring.types import CORRELATION_STRATEGIES


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = ["id", "scenario", "started_at", "ended_at"]
        read_only_fields = ["id", "started_at", "ended_at"]


class CaseSerializer(serializers.ModelSerializer):
    correlation = serializers.ChoiceField(choices=CORRELATION_STRATEGIES)

    class Meta:
        model = Case
        fields = [
            "id",
            "case_id",
            "name",
            "malicious",
            "technique",
            "correlation",
            "source_ip",
            "started_at",
            "ended_at",
            "meta",
        ]
        read_only_fields = ["id"]


class DetectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Detection
        fields = [
            "id",
            "detection_id",
            "source",
            "signature",
            "severity",
            "timestamp",
            "src_ip",
            "marker",
        ]


class RuleSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleSet
        fields = ["id", "content", "created_at", "applied_at", "validation_output"]


class ScoreSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScoreSnapshot
        fields = [
            "id",
            "tp",
            "fp",
            "fn",
            "tn",
            "precision",
            "recall",
            "f1",
            "false_positive_rate",
            "warnings",
            "per_case",
            "computed_at",
        ]
