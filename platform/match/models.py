from django.conf import settings
from django.db import models

from content.models import Problem, Wargame
from domain.round_rules import BOT, END_REASONS, HUMAN, Matchup, Phase

PURPOSES = [(purpose, purpose) for purpose in ("round", "lesson", "probe")]
KINDS = [(kind, kind) for kind in ("lesson", "round")]
MATCHUPS = [(matchup.value, matchup.value) for matchup in Matchup]
PHASES = [(phase.value, phase.value) for phase in Phase]
SIDES = [(side, side) for side in ("attack", "defence")]
CLIENTS = [(client, client) for client in (HUMAN, BOT)]
REASONS = [(reason, reason) for reason in END_REASONS]


class Lease(models.Model):
    wargame = models.ForeignKey(Wargame, on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=8, choices=PURPOSES)
    slot = models.PositiveIntegerField(null=True, blank=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="+")
    opened = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    closed = models.DateTimeField(null=True, blank=True)
    browse_marker = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["id"]


class Round(models.Model):
    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="rounds")
    problem = models.ForeignKey(Problem, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=8, choices=KINDS)
    matchup = models.CharField(max_length=16, choices=MATCHUPS, blank=True, default="")
    phase = models.CharField(max_length=8, choices=PHASES, default=Phase.CREATED.value)
    snapshot = models.JSONField(default=dict)
    baseline = models.JSONField(null=True, blank=True)
    read_of = models.JSONField(default=dict)
    traffic = models.JSONField(default=dict)
    started = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    ended = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=24, choices=REASONS, blank=True, default="")

    class Meta:
        ordering = ["id"]


class Seat(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="seats")
    side = models.CharField(max_length=8, choices=SIDES)
    client = models.CharField(max_length=8, choices=CLIENTS)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                             related_name="+")
    bot_name = models.CharField(max_length=64, blank=True, default="")
    token_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    token_revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["round_id", "side"]
        constraints = [models.UniqueConstraint(fields=["round", "side"], name="one_seat_per_side")]


class CustomerRequest(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="customer_requests")
    marker = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    user = models.CharField(max_length=32)
    origin = models.CharField(max_length=32)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    method = models.CharField(max_length=8)
    path = models.TextField()
    status = models.PositiveSmallIntegerField()
    refused_by = models.CharField(max_length=8, blank=True, default="")
    sent_at = models.DateTimeField()
    elapsed_ms = models.PositiveIntegerField(default=0)
    benign_case = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["sent_at"]
        constraints = [models.UniqueConstraint(fields=["round", "marker"], name="one_customer_request_per_marker")]
