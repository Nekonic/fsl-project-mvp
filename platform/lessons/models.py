from django.conf import settings
from django.db import models
from django.utils import timezone

from domain.checks import NOT_YET, PASSED

VERDICTS = [(verdict, verdict) for verdict in (PASSED, NOT_YET)]


class StepResult(models.Model):
    round = models.ForeignKey("match.Round", on_delete=models.CASCADE, related_name="+")
    step_order = models.PositiveIntegerField()
    verdict = models.CharField(max_length=8, choices=VERDICTS)
    given = models.JSONField(null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]


class Progress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    problem = models.ForeignKey("content.Problem", on_delete=models.CASCADE, related_name="+")
    passed_order = models.PositiveIntegerField(default=0)
    passed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["user", "problem"], name="one_progress_per_problem")]
