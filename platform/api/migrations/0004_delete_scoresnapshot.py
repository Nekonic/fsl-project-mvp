from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_suppression'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ScoreSnapshot',
        ),
    ]
