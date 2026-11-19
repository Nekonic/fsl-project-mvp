from django.core.management.base import BaseCommand

from match import retention


class Command(BaseCommand):
    help = "Delete closed leases past CR_RETAIN_CLOSED_MINUTES with their rounds and events."

    def handle(self, **options):
        self.stdout.write(f"pruned {len(retention.prune())} closed lease(s)")
