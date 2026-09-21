                                               

import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='RuleSet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('validation_output', models.TextField(blank=True, default='')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Session',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scenario', models.CharField(default='juice-shop', max_length=128)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),
        migrations.CreateModel(
            name='ScoreSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tp', models.IntegerField()),
                ('fp', models.IntegerField()),
                ('fn', models.IntegerField()),
                ('tn', models.IntegerField()),
                ('precision', models.FloatField()),
                ('recall', models.FloatField()),
                ('f1', models.FloatField()),
                ('false_positive_rate', models.FloatField()),
                ('warnings', models.JSONField(default=list)),
                ('per_case', models.JSONField(default=list)),
                ('computed_at', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='api.session')),
            ],
            options={
                'ordering': ['-computed_at'],
            },
        ),
        migrations.CreateModel(
            name='Detection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('detection_id', models.CharField(max_length=128)),
                ('source', models.CharField(max_length=32)),
                ('signature', models.TextField()),
                ('severity', models.IntegerField(blank=True, null=True)),
                ('timestamp', models.DateTimeField()),
                ('src_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('marker', models.CharField(blank=True, max_length=64, null=True)),
                ('raw', models.JSONField(blank=True, default=dict)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='detections', to='api.session')),
            ],
            options={
                'ordering': ['timestamp'],
                'unique_together': {('session', 'detection_id')},
            },
        ),
        migrations.CreateModel(
            name='Case',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('case_id', models.CharField(db_index=True, max_length=64)),
                ('name', models.CharField(max_length=128)),
                ('malicious', models.BooleanField()),
                ('technique', models.CharField(blank=True, default='', max_length=64)),
                ('correlation', models.CharField(max_length=16)),
                ('source_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('started_at', models.DateTimeField()),
                ('ended_at', models.DateTimeField()),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cases', to='api.session')),
            ],
            options={
                'ordering': ['started_at'],
                'unique_together': {('session', 'case_id')},
            },
        ),
    ]
