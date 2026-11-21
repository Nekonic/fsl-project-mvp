from django.core.management.base import BaseCommand, CommandError

from cr import errors
from training.round import lifecycle as service


class Command(BaseCommand):
    help = "Print the address, host key alias and account of a player's terminal shell, if the player holds a grant."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("side", choices=sorted(service.SHELL_OF_SIDE))
        parser.add_argument("round_id", type=int)

    def handle(self, side, round_id, **options):
        try:
            shell = service.terminal_shell(round_id, side)
        except errors.DomainError as refused:
            raise CommandError(f"round {round_id} gives the {side} player no terminal: {refused.code}") from refused
        self.stdout.write(f"{shell.address} {shell.alias} {shell.account}")
