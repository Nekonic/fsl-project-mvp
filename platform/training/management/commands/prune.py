from django.core.management.base import BaseCommand

from training.round import retention


class Command(BaseCommand):
    help = ("Delete closed leases with their rounds and events: those past CR_RETAIN_CLOSED_MINUTES, "
            "or only the closed ones among --leases.")

    def add_arguments(self, parser):
        parser.add_argument("--leases", type=int, nargs="*", help="only these leases, and only once closed")
        parser.add_argument("--dry-run", action="store_true", help="name the leases, delete nothing")

    def handle(self, leases=None, dry_run=False, **options):
        chosen = retention.expired() if leases is None else retention.closed_among(leases)
        if dry_run:
            self.stdout.write(f"would prune {len(chosen)} closed lease(s): {chosen}")
            return
        self.stdout.write(f"pruned {len(retention.drop(chosen))} closed lease(s)")
