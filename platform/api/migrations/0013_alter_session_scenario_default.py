from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("api", "0012_remove_session_truncated")]

    operations = [
        migrations.AlterField(
            model_name="session",
            name="scenario",
            field=models.CharField(default="board", max_length=128),
        ),
    ]
