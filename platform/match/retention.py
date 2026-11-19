from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from events import log
from match import site
from match.models import Lease, Round


def cutoff(now: datetime | None = None) -> datetime:
    return (now or timezone.now()) - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES)


def prune(now: datetime | None = None) -> list[int]:
    expired = list(Lease.objects.filter(closed__lt=cutoff(now)).order_by("pk").values_list("pk", flat=True))
    for lease_id in expired:
        round_ids = list(Round.objects.filter(lease_id=lease_id).values_list("pk", flat=True))
        with transaction.atomic():
            log.forget(round_ids)
            Lease.objects.filter(pk=lease_id).delete()
        for round_id in round_ids:
            site.forget(round_id)
    return expired
