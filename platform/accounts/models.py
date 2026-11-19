from django.db import models


class SignInBlock(models.Model):
    kind = models.CharField(max_length=16)
    value = models.CharField(max_length=64)
    username = models.CharField(max_length=150, blank=True, default="")
    reason = models.CharField(max_length=32)
    failures = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    until = models.DateTimeField()

    class Meta:
        ordering = ["-created"]
        constraints = [models.UniqueConstraint(fields=["kind", "value"], name="one_block_per_caller")]
