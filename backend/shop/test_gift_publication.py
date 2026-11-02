from datetime import datetime, timedelta, timezone as dt_timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings

from .models import CommercialSettings


class StagingGiftPublicationTests(TestCase):
    def setUp(self):
        self.migration = import_module("shop.migrations.0010_publish_cyber_gift_in_staging")
        self.now = datetime(2026, 11, 3, 15, tzinfo=dt_timezone.utc)
        self.config = CommercialSettings.objects.get(pk=1)

    def publish(self, url, now=None):
        with override_settings(SITE_URL=url), patch.object(
            self.migration.timezone, "now", return_value=now or self.now
        ):
            self.migration.publish_in_staging(apps, SimpleNamespace(connection=connection))
        self.config.refresh_from_db()

    def test_known_staging_publishes_once_without_changing_discount(self):
        CommercialSettings.objects.filter(pk=1).update(offline_payment_discount_percent=15)
        self.publish("https://rasel-mp-staging.onrender.com")
        self.assertTrue(self.config.cyber_gift_enabled)
        self.assertEqual(self.config.cyber_gift_started_at, self.now)
        self.assertEqual(self.config.offline_payment_discount_percent, 15)
        self.publish("https://rasel-mp-staging.onrender.com", self.now + timedelta(days=1))
        self.assertEqual(self.config.cyber_gift_started_at, self.now)

    def test_production_and_unknown_hosts_are_never_enabled(self):
        for url in (
            "https://rasel.ar", "https://www.rasel.ar", "",
            "https://staging.example.com", "http://rasel-mp-staging.onrender.com",
            "https://rasel-mp-staging.onrender.com.example.com",
        ):
            with self.subTest(url=url):
                self.publish(url)
                self.assertFalse(self.config.cyber_gift_enabled)
                self.assertIsNone(self.config.cyber_gift_started_at)

    def test_outside_campaign_dates_leaves_staging_disabled(self):
        for now in (
            datetime(2026, 11, 2, 2, 59, 59, tzinfo=dt_timezone.utc),
            datetime(2026, 11, 9, 3, tzinfo=dt_timezone.utc),
        ):
            with self.subTest(now=now):
                self.publish("https://rasel-mp-staging.onrender.com", now)
                self.assertFalse(self.config.cyber_gift_enabled)
                self.assertIsNone(self.config.cyber_gift_started_at)

    def test_existing_publication_and_manual_suspension_are_preserved(self):
        started = self.now - timedelta(hours=1)
        CommercialSettings.objects.filter(pk=1).update(
            cyber_gift_enabled=False, cyber_gift_started_at=started
        )
        self.publish("https://rasel-mp-staging.onrender.com")
        self.assertFalse(self.config.cyber_gift_enabled)
        self.assertEqual(self.config.cyber_gift_started_at, started)
