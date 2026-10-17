import logging
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from api.models import CustomerRequest, Detection, Session

log = logging.getLogger(__name__)

ROWS_PER_TRANSACTION = 2000


def prune(now=None) -> int:
    cutoff = (now or timezone.now()) - timedelta(minutes=settings.RETAIN_CLOSED_MINUTES)
    expired = list(Session.objects.filter(ended_at__lt=cutoff).order_by("pk").values_list("pk", flat=True))
    for pk in expired:
        for rows in (Detection.objects, CustomerRequest.objects):
            _delete_in_batches(rows.filter(session_id=pk))
        Session.objects.filter(pk=pk, ended_at__lt=cutoff).delete()
    return len(expired)


def _delete_in_batches(rows) -> None:
    while batch := list(rows.order_by().values_list("pk", flat=True)[:ROWS_PER_TRANSACTION]):
        rows.model.objects.filter(pk__in=batch).delete()


def prune_quietly(now=None) -> None:
    try:
        prune(now)
    except DatabaseError:
        log.exception("closed sessions past FSL_RETAIN_CLOSED_MINUTES could not be deleted")
