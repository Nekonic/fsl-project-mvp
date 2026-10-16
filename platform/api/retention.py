import logging
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from api.models import Session

log = logging.getLogger(__name__)


def prune(now=None) -> int:
    cutoff = (now or timezone.now()) - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES)
    expired = list(Session.objects.filter(ended_at__lt=cutoff).order_by("pk").values_list("pk", flat=True))
    for pk in expired:
        Session.objects.filter(pk=pk, ended_at__lt=cutoff).delete()
    return len(expired)


def prune_quietly(now=None) -> None:
    try:
        prune(now)
    except DatabaseError:
        log.exception("closed sessions past FSL_RETAIN_CLOSED_MINUTES could not be deleted")
