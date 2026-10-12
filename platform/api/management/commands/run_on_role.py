import json

from django.core.management.base import BaseCommand, CommandError

from range import substrate
from range.ports import RangeUnavailable

ANSWER = "fsl.platform.answer="


class Command(BaseCommand):
    help = "Run a command on the host filling a role, through the range adapter."

    def add_arguments(self, parser):
        parser.add_argument("role")
        parser.add_argument("argv", help="the command as a JSON list")
        parser.add_argument("--timeout", type=float, default=60.0)

    def handle(self, role, argv, timeout, **options):
        try:
            ran = substrate().runner(role)(json.loads(argv), timeout=timeout)
        except RangeUnavailable as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(ANSWER + json.dumps({"exit_code": ran.exit_code, "output": ran.output}))
