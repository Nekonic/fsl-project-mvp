from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from training.models import Lease


@pytest.fixture
def leases(problem):
    now = timezone.now()

    def made(closed):
        return Lease.objects.create(wargame_id="board", purpose="round", slot=1, expires_at=now + timedelta(hours=1),
                                    closed=closed).pk

    return {"listed_closed": made(now), "listed_open": made(None), "unlisted_closed": made(now)}


def pruned(*argv) -> str:
    said = StringIO()
    call_command("prune", *argv, stdout=said)
    return said.getvalue()


def test_listed_leases_go_only_once_closed_and_unlisted_ones_stay(leases):
    said = pruned("--leases", str(leases["listed_closed"]), str(leases["listed_open"]))

    assert "pruned 1 closed lease(s)" in said
    assert set(Lease.objects.values_list("pk", flat=True)) == {leases["listed_open"], leases["unlisted_closed"]}


def test_a_dry_run_names_the_leases_and_deletes_nothing(leases):
    said = pruned("--leases", str(leases["listed_closed"]), "--dry-run")

    assert f"would prune 1 closed lease(s): [{leases['listed_closed']}]" in said
    assert Lease.objects.count() == 3


def test_without_a_list_only_leases_closed_past_the_retention_go(leases, settings):
    settings.RETAIN_CLOSED_MINUTES = 0
    Lease.objects.filter(pk=leases["unlisted_closed"]).update(closed=timezone.now() - timedelta(minutes=5))

    pruned()

    assert leases["unlisted_closed"] not in set(Lease.objects.values_list("pk", flat=True))
    assert leases["listed_open"] in set(Lease.objects.values_list("pk", flat=True))
