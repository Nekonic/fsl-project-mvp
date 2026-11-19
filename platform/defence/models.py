from django.db import models

from domain.types import ENGINES
from match.models import Lease, Round, Seat

ENGINE_CHOICES = [(engine, engine) for engine in ENGINES]


class Detection(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="detections")
    detection_id = models.CharField(max_length=200)
    engine = models.CharField(max_length=8, choices=ENGINE_CHOICES)
    rule = models.CharField(max_length=64, blank=True, default="")
    signature = models.TextField(blank=True, default="")
    severity = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField()
    src_ip = models.GenericIPAddressField(null=True, blank=True)
    marker = models.CharField(max_length=128, null=True, blank=True)
    uri = models.TextField(blank=True, default="")
    blocked = models.BooleanField(default=False)
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["round", "detection_id"], name="one_detection_per_round")]


class RuleTest(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="rule_tests")
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, null=True, blank=True, related_name="rule_tests")
    engine = models.CharField(max_length=8, choices=ENGINE_CHOICES)
    body_sha = models.CharField(max_length=64)
    body = models.TextField()
    syntax_ok = models.BooleanField(default=False)
    result = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class RuleSet(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="rule_sets")
    engine = models.CharField(max_length=8, choices=ENGINE_CHOICES)
    version = models.PositiveIntegerField()
    body = models.TextField()
    applied_at = models.DateTimeField()
    tested = models.ForeignKey(RuleTest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    seat = models.ForeignKey(Seat, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    same_as_tested = models.BooleanField(default=False)
    sensors = models.JSONField(default=list)
    drifted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["round_id", "engine", "version"]
        constraints = [models.UniqueConstraint(fields=["round", "engine", "version"], name="one_rule_set_per_version")]


class DisabledRule(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="disabled_rules")
    sid = models.PositiveBigIntegerField()
    original = models.TextField()
    reason = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    enabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class AlertCursor(models.Model):
    lease = models.OneToOneField(Lease, on_delete=models.CASCADE, related_name="alert_cursor")
    cursor = models.JSONField(default=dict)
