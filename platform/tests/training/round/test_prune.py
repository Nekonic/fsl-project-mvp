from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from training.models import Allocation


@pytest.fixture
def allocations(problem):
    now = timezone.now()

    def made(closed):
        return Allocation.objects.create(wargame_id="board", purpose="round", slot=1, expires_at=now + timedelta(hours=1),
                                    closed=closed).pk

    return {"listed_closed": made(now), "listed_open": made(None), "unlisted_closed": made(now)}


def pruned(*argv) -> str:
    said = StringIO()
    call_command("prune", *argv, stdout=said)
    return said.getvalue()


def test_listed_allocations_go_only_once_closed_and_unlisted_ones_stay(allocations):
    said = pruned("--allocations", str(allocations["listed_closed"]), str(allocations["listed_open"]))

    assert "pruned 1 closed allocation(s)" in said
    assert set(Allocation.objects.values_list("pk", flat=True)) == {allocations["listed_open"], allocations["unlisted_closed"]}


def test_a_dry_run_names_the_allocations_and_deletes_nothing(allocations):
    said = pruned("--allocations", str(allocations["listed_closed"]), "--dry-run")

    assert f"would prune 1 closed allocation(s): [{allocations['listed_closed']}]" in said
    assert Allocation.objects.count() == 3


def test_without_a_list_only_allocations_closed_past_the_retention_go(allocations, settings):
    settings.RETAIN_CLOSED_MINUTES = 0
    Allocation.objects.filter(pk=allocations["unlisted_closed"]).update(closed=timezone.now() - timedelta(minutes=5))

    pruned()

    assert allocations["unlisted_closed"] not in set(Allocation.objects.values_list("pk", flat=True))
    assert allocations["listed_open"] in set(Allocation.objects.values_list("pk", flat=True))
