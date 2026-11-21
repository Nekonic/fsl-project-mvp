from django.db import models

from training.models import Round


class Objective(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="objectives")
    key = models.CharField(max_length=128)
    name = models.CharField(max_length=256)
    achieved_at = models.DateTimeField()
    earliest = models.DateTimeField(null=True, blank=True)
    latest = models.DateTimeField(null=True, blank=True)
    attributed_marker = models.CharField(max_length=128, null=True, blank=True)
    seen = models.BooleanField(default=False)

    class Meta:
        ordering = ["achieved_at", "id"]
        constraints = [models.UniqueConstraint(fields=["round", "key"], name="one_loss_per_objective")]


class Verdict(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="verdicts")
    action = models.CharField(max_length=64)
    case = models.CharField(max_length=100)
    verdict = models.CharField(max_length=2)
    alerts = models.IntegerField()
    corroborated = models.BooleanField(null=True)
    judged_at = models.DateTimeField()

    class Meta:
        ordering = ["judged_at", "id"]
        constraints = [models.UniqueConstraint(fields=["round", "action"], name="one_verdict_per_case")]
