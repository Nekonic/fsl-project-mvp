from django.conf import settings
from django.core.management.base import BaseCommand

from training.round import follow


class Command(BaseCommand):
    help = "Drive slot refills, close expired leases and tick every running round, in a loop."

    def add_arguments(self, parser):
        parser.add_argument("--every", type=float, default=settings.FOLLOW_SECONDS)
        parser.add_argument("--rounds", type=int, default=None)

    def handle(self, every, rounds, **options):
        follow.run(every, rounds)
