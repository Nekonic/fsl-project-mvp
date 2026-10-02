from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [("api", "0011_remove_ruleset_validation_output")]

    operations = [
        migrations.RemoveField(model_name="session", name="truncated"),
    ]
