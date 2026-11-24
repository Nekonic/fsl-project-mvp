from django.conf import settings
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


class VpnProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vpn_profile")
    public_key = models.CharField(max_length=64)
    server_public_key = models.CharField(max_length=64)
    server_private_key = models.CharField(max_length=64)
    address = models.GenericIPAddressField(protocol="IPv4", unique=True)
    port = models.PositiveIntegerField(unique=True)
    created = models.DateTimeField(auto_now_add=True)
    attached_round = models.PositiveIntegerField(null=True, blank=True)
    attached_slot = models.PositiveIntegerField(null=True, blank=True)
    attached_address = models.GenericIPAddressField(protocol="IPv4", null=True, blank=True)

    class Meta:
        ordering = ["port"]
