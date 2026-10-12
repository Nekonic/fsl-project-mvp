import json

from django.core.management.base import BaseCommand, CommandError

from api.models import Session
from range import substrate
from range.ports import RangeUnavailable

ANSWER = "fsl.platform.answer="


class Command(BaseCommand):
    help = "Run a command on the host filling a role, through the range adapter."

    def add_arguments(self, parser):
        parser.add_argument("role")
        parser.add_argument("argv", help="the command as a JSON list")
        parser.add_argument("--timeout", type=float, default=60.0)
        parser.add_argument("--session", type=int, help="run on the range slot this open session holds")
        parser.add_argument("--slot", type=int, help="run on this range slot")

    def handle(self, role, argv, timeout, session=None, slot=None, **options):
        try:
            ran = self.slot(substrate(), session, slot).runner(role)(json.loads(argv), timeout=timeout)
        except RangeUnavailable as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(ANSWER + json.dumps({"exit_code": ran.exit_code, "output": ran.output}))

    @staticmethod
    def slot(adapter, session, slot):
        if not hasattr(adapter, "in_slot"):
            return adapter
        if session is not None:
            held = Session.objects.filter(pk=session).values_list("ended_at", "slot").first()
            if held is None:
                raise CommandError(f"there is no session {session}")
            if held[0] is not None:
                raise CommandError(f"session {session} has closed, so it holds no slot")
            return adapter.in_slot(held[1] or 1)
        if slot is not None:
            return adapter.in_slot(slot)
        if adapter.slots > 1:
            raise CommandError(
                f"the range has {adapter.slots} slots; name the one to run on with --session or --slot"
            )
        return adapter
