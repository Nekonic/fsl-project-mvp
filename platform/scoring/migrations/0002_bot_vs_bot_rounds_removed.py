from django.db import migrations


def bot_vs_bot_rounds_removed(apps, schema_editor):
    apps.get_model("training", "RoundRecord").objects.filter(matchup="bot_vs_bot").delete()
    apps.get_model("training", "Round").objects.filter(matchup="bot_vs_bot").delete()


class Migration(migrations.Migration):

    dependencies = [
        ('scoring', '0001_initial'),
        ('telemetry', '0002_blocked_waf_lookups'),
        ('training', '0003_bot_rounds'),
    ]

    run_before = [
        ('training', '0004_no_baseline'),
    ]

    operations = [
        migrations.RunPython(bot_vs_bot_rounds_removed, migrations.RunPython.noop),
    ]
