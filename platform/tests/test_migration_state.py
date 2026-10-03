import os

import django
import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_model_state_matches_the_migrations():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")
    django.setup()
    call_command("makemigrations", "api", check=True, dry_run=True, verbosity=0)
