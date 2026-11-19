from django.db import models

from domain.types import ACTION_KINDS, CORRELATION_STRATEGIES
from match.models import Lease, Round, Seat

KINDS = [(kind, kind) for kind in ACTION_KINDS]
CORRELATIONS = [(strategy, strategy) for strategy in CORRELATION_STRATEGIES]
STOPPED_BY = [(reason, reason) for reason in ("seat", "origin_spent", "round_end")]


class Action(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="actions")
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name="actions")
    kind = models.CharField(max_length=8, choices=KINDS)
    case_id = models.CharField(max_length=100, null=True, blank=True)
    malicious = models.BooleanField(null=True, blank=True)
    expect = models.CharField(max_length=200, null=True, blank=True)
    marker = models.CharField(max_length=64)
    correlation = models.CharField(max_length=8, choices=CORRELATIONS)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    started = models.DateTimeField()
    ended = models.DateTimeField()
    charged = models.BooleanField(default=False)
    access_seen = models.BooleanField(default=False)
    meta = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["round", "marker"], name="one_action_per_marker")]


class ToolRun(models.Model):
    action = models.OneToOneField(Action, on_delete=models.CASCADE, related_name="run")
    tool = models.CharField(max_length=32)
    argv = models.JSONField(default=list)
    started = models.DateTimeField()
    ended = models.DateTimeField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    stopped_by = models.CharField(max_length=16, choices=STOPPED_BY, null=True, blank=True)
    output_path = models.CharField(max_length=200)

    class Meta:
        ordering = ["id"]


class OriginBudget(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="origin_budgets")
    origin_id = models.CharField(max_length=32)
    ip = models.GenericIPAddressField()
    label = models.CharField(max_length=100)
    budget = models.PositiveIntegerField()
    left = models.IntegerField()
    spent_at = models.DateTimeField(null=True, blank=True)
    recent = models.JSONField(default=list)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["round", "ip"], name="one_budget_per_origin")]


class AccessCursor(models.Model):
    lease = models.OneToOneField(Lease, on_delete=models.CASCADE, related_name="access_cursor")
    cursor = models.JSONField(default=dict)
