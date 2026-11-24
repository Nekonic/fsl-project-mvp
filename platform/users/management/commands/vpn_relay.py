from django.core.management.base import BaseCommand

from sandbox import vpn as tunnel
from users import vpn


class Command(BaseCommand):
    help = "Write the learner tunnels' port map from the store, then relay each attached port to its kali."

    def handle(self, **options):
        vpn.write_map()
        tunnel.relay()
