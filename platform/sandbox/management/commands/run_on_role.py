import json

from django.core.management.base import BaseCommand, CommandError

from cr import errors
from sandbox import reach
from training.round import allocation as allocations

ANSWER = "cr.platform.answer="


class Command(BaseCommand):
    help = "Run a command on the host filling a role, through the range adapter."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("role")
        parser.add_argument("argv", help="the command as a JSON list")
        parser.add_argument("--timeout", type=float, default=60.0)
        parser.add_argument("--allocation", type=int, help="run on the slot this open allocation holds")
        parser.add_argument("--slot", type=int, help="run on this slot")

    def handle(self, role, argv, timeout, allocation=None, slot=None, **options):
        if allocation is not None:
            held = allocations.allocation(allocation)
            if held.closed is not None:
                raise CommandError(f"allocation {allocation} is closed, so it holds no slot")
            slot = held.slot
        try:
            ran = reach.slot_range(slot).runner(role)(json.loads(argv), timeout=timeout)
        except errors.DomainError as failed:
            raise CommandError(str(failed)) from failed
        self.stdout.write(ANSWER + json.dumps({"exit_code": ran.exit_code, "output": ran.output}))
