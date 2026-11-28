from rest_framework.views import APIView

from training.round import lifecycle
from training.round.reading import catch_up

ALERTS_READ = lifecycle.ALERTS_READ


class CatchingUpView(APIView):
    needs_reads: tuple[str, ...] = ()
    reads_logs = True

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.reads_logs:
            catch_up(request)
        for what in self.needs_reads:
            lifecycle.refuse_if_unread(request.round, what)
