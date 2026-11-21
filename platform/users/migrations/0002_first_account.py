from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations

FIRST_USER = "admin"
FIRST_PASSWORD = "123456"


def first_account(apps, schema_editor):
    users = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    if not users.objects.filter(username=FIRST_USER).exists():
        users.objects.create(username=FIRST_USER, password=make_password(FIRST_PASSWORD),
                             is_staff=True, is_superuser=True, is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(first_account, migrations.RunPython.noop),
    ]
