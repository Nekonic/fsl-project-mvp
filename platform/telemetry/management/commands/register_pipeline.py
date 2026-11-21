from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cr import config
from telemetry import elastic


class Command(BaseCommand):
    help = "Put the ingest pipeline into Elasticsearch."
    requires_system_checks = []

    def handle(self, **options):
        if not elastic.register_pipeline(config.build(source=settings.CR_SOURCE).elastic):
            raise CommandError("Elasticsearch did not take the ingest pipeline")
