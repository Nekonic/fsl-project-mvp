from django.db import models
from django.utils import timezone


class Event(models.Model):
    id = models.BigAutoField(primary_key=True)
    round_id = models.BigIntegerField()
    kind = models.CharField(max_length=32)
    seat_side = models.CharField(max_length=8, null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)
    body = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["round_id", "id"], name="event_round_cursor")]
