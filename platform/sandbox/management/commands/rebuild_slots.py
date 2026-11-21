from django.conf import settings
from django.core.management.base import BaseCommand

from sandbox import service


class Command(BaseCommand):
    help = "Advance the slot rebuilds the pool owes, in a loop."

    def add_arguments(self, parser):
        parser.add_argument("--every", type=float, default=settings.REBUILD_EVERY_SECONDS)
        parser.add_argument("--rounds", type=int, default=None)

    def handle(self, every, rounds, **options):
        service.keep_rebuilding(every, rounds)
