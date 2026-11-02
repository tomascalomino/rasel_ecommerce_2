from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import migrations
from django.utils import timezone


def publish_in_staging(apps, schema_editor):
    # Only this known test service may publish automatically. Production remains
    # controlled from its own admin after the approved main deployment.
    if settings.SITE_URL != "https://rasel-mp-staging.onrender.com":
        return
    now = timezone.now()
    start = datetime(2026, 11, 2, 3, tzinfo=dt_timezone.utc)
    end = datetime(2026, 11, 9, 3, tzinfo=dt_timezone.utc)
    if not start <= now < end:
        return
    config = apps.get_model("shop", "CommercialSettings")
    config.objects.using(schema_editor.connection.alias).filter(
        pk=1, cyber_gift_started_at__isnull=True
    ).update(cyber_gift_enabled=True, cyber_gift_started_at=now)


class Migration(migrations.Migration):
    dependencies = [("shop", "0009_commercialsettings_cyber_gift_enabled_and_more")]

    operations = [migrations.RunPython(publish_in_staging, migrations.RunPython.noop)]
