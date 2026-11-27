from rest_framework.views import APIView

from training.round import allocation as allocations
from training.round import lifecycle, records

ALERTS_READ = lifecycle.ALERTS_READ


def catch_up(request) -> None:
    found = getattr(request, "round", None)
    held = getattr(request, "allocation", None) or (found.allocation if found is not None else None)
    if found is not None:
        lifecycle.catch_up(found)
    elif held is not None:
        for running in held.rounds.filter(phase=lifecycle.RUNNING):
            lifecycle.catch_up(running)
    if held is not None:
        allocations.close_if_expired(held)
    if found is not None:
        found.refresh_from_db()
        found.allocation.refresh_from_db()
        records.keep_when_due(found)


class CatchingUpView(APIView):
    needs_reads: tuple[str, ...] = ()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        catch_up(request)
        for what in self.needs_reads:
            lifecycle.refuse_if_unread(request.round, what)
