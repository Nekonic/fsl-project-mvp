import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0027_session_lessons'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Suppression',
            new_name='DisabledRule',
        ),
        migrations.RenameField(
            model_name='disabledrule',
            old_name='restored_at',
            new_name='enabled_at',
        ),
        migrations.AlterField(
            model_name='disabledrule',
            name='session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='disabled_rules', to='api.session'),
        ),
    ]
