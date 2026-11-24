from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("marketing", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="MetaMaintenance",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("cleanup_after", models.DateTimeField(default=timezone.now)),
            ],
            options={"default_permissions": ()},
        ),
    ]
