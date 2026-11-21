import json
import secrets
import sys

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    def handle(self, *args, **options):
        given = json.load(sys.stdin)
        with transaction.atomic():
            for user in User.objects.all():
                user.set_password(given.get(user.username) or secrets.token_urlsafe(24))
                user.save(update_fields=["password"])
