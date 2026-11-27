from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from telemetry import events as log
from training.models import Allocation, Round
from training.round import records, site


def cutoff(now: datetime | None = None) -> datetime:
    return (now or timezone.now()) - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES)


def expired(now: datetime | None = None) -> list[int]:
    return list(Allocation.objects.filter(closed__lt=cutoff(now)).order_by("pk").values_list("pk", flat=True))


def closed_among(allocation_ids: Iterable[int]) -> list[int]:
    return list(Allocation.objects.filter(pk__in=list(allocation_ids)).exclude(closed=None).order_by("pk")
                .values_list("pk", flat=True))


def drop(allocation_ids: Iterable[int]) -> list[int]:
    dropped = []
    for allocation_id in allocation_ids:
        for found in Round.objects.filter(allocation_id=allocation_id).exclude(started=None):
            records.keep(found)
        round_ids = list(Round.objects.filter(allocation_id=allocation_id).values_list("pk", flat=True))
        with transaction.atomic():
            log.forget(round_ids)
            Allocation.objects.filter(pk=allocation_id).delete()
        for round_id in round_ids:
            site.forget(round_id)
        dropped.append(allocation_id)
    return dropped


def prune(now: datetime | None = None) -> list[int]:
    records.prune(now)
    return drop(expired(now))
