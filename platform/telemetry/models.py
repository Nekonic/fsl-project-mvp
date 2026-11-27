from django.db import models
from django.utils import timezone

from domain.types import ENGINE_WAF, ENGINES
from training.models import Allocation, Round

ENGINE_CHOICES = [(engine, engine) for engine in ENGINES]


class Event(models.Model):
    id = models.BigAutoField(primary_key=True)
    round_id = models.BigIntegerField()
    kind = models.CharField(max_length=32)
    player_side = models.CharField(max_length=8, null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)
    body = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["round_id", "id"], name="event_round_cursor")]


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
        indexes = [
            models.Index(fields=["round", "marker"], name="blocked_waf_by_marker",
                         condition=models.Q(blocked=True, engine=ENGINE_WAF)),
            models.Index(fields=["round", "src_ip", "timestamp"], name="blocked_waf_unmarked",
                         condition=models.Q(blocked=True, engine=ENGINE_WAF, marker__isnull=True)),
        ]


class AlertCursor(models.Model):
    allocation = models.OneToOneField(Allocation, on_delete=models.CASCADE, related_name="alert_cursor")
    cursor = models.JSONField(default=dict)


class AccessCursor(models.Model):
    allocation = models.OneToOneField(Allocation, on_delete=models.CASCADE, related_name="access_cursor")
    cursor = models.JSONField(default=dict)
