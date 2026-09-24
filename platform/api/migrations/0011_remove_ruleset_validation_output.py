from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_session_rotation'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='ruleset',
            name='validation_output',
        ),
    ]
