from django.core.management.base import BaseCommand

from training.round import retention


class Command(BaseCommand):
    help = ("Delete closed allocations with their rounds and events: those past CR_RETAIN_CLOSED_MINUTES, "
            "or only the closed ones among --allocations.")

    def add_arguments(self, parser):
        parser.add_argument("--allocations", type=int, nargs="*", help="only these allocations, and only once closed")
        parser.add_argument("--dry-run", action="store_true", help="name the allocations, delete nothing")

    def handle(self, allocations=None, dry_run=False, **options):
        chosen = retention.expired() if allocations is None else retention.closed_among(allocations)
        if dry_run:
            self.stdout.write(f"would prune {len(chosen)} closed allocation(s): {chosen}")
            return
        self.stdout.write(f"pruned {len(retention.drop(chosen))} closed allocation(s)")
