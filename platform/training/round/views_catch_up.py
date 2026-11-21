from rest_framework.views import APIView

from training.round import allocation as allocations
from training.round import lifecycle


def catch_up(request) -> None:
    found = getattr(request, "round", None)
    held = getattr(request, "allocation", None) or (found.allocation if found is not None else None)
    if found is not None:
        lifecycle.catch_up(found)
    if held is not None:
        allocations.close_if_expired(held)
    if found is not None:
        found.refresh_from_db()
        found.allocation.refresh_from_db()


class CatchingUpView(APIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        catch_up(request)
