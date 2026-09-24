import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='baseline',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.CreateModel(
            name='Objective',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=128)),
                ('name', models.CharField(max_length=256)),
                ('category', models.CharField(blank=True, default='', max_length=128)),
                ('difficulty', models.IntegerField(default=1)),
                ('achieved_at', models.DateTimeField()),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='objectives', to='api.session')),
            ],
            options={
                'ordering': ['achieved_at'],
                'unique_together': {('session', 'key')},
            },
        ),
    ]
