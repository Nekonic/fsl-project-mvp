from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_case_expect'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='rotation',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
