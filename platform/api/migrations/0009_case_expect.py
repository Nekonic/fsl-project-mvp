from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0008_objective_earliest_latest'),
    ]

    operations = [
        migrations.AddField(
            model_name='case',
            name='expect',
            field=models.CharField(max_length=128, null=True),
        ),
    ]
