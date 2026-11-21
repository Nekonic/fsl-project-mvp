from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from telemetry import events as log
from training.models import Lease, Round
from training.round import site


def cutoff(now: datetime | None = None) -> datetime:
    return (now or timezone.now()) - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES)


def expired(now: datetime | None = None) -> list[int]:
    return list(Lease.objects.filter(closed__lt=cutoff(now)).order_by("pk").values_list("pk", flat=True))


def closed_among(lease_ids: Iterable[int]) -> list[int]:
    return list(Lease.objects.filter(pk__in=list(lease_ids)).exclude(closed=None).order_by("pk")
                .values_list("pk", flat=True))


def drop(lease_ids: Iterable[int]) -> list[int]:
    dropped = []
    for lease_id in lease_ids:
        round_ids = list(Round.objects.filter(lease_id=lease_id).values_list("pk", flat=True))
        with transaction.atomic():
            log.forget(round_ids)
            Lease.objects.filter(pk=lease_id).delete()
        for round_id in round_ids:
            site.forget(round_id)
        dropped.append(lease_id)
    return dropped


def prune(now: datetime | None = None) -> list[int]:
    return drop(expired(now))
