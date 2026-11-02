from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings

from shop.models import Coupon, Product, Variant

seed_demo = import_module("shop.migrations.0012_seed_staging_coupon_demo").seed_demo


class CouponDemoTests(TestCase):
    def publish(self):
        seed_demo(apps, SimpleNamespace(connection=connection))

    def test_production_other_hosts_and_similar_urls_never_receive_fixture(self):
        for site in (
            "https://rasel.ar",
            "http://rasel-mp-staging.onrender.com",
            "https://rasel-mp-staging.onrender.com.example.org",
        ):
            with self.subTest(site=site), override_settings(SITE_URL=site):
                self.publish()
        self.assertFalse(Coupon.objects.exists())
        self.assertFalse(
            Product.objects.filter(slug="caja-prueba-cupon-staging").exists()
        )

    @override_settings(SITE_URL="https://rasel-mp-staging.onrender.com")
    def test_only_fake_box_is_eligible_and_existing_changes_are_preserved(self):
        self.publish()
        coupon = Coupon.objects.get(code="pruebacajas20")
        self.assertEqual(coupon.max_uses, 5)
        self.assertEqual(
            list(coupon.variants.values_list("sku", flat=True)), ["STAGING-COUPON-BOX6"]
        )
        coupon.enabled = False
        coupon.max_uses = 8
        coupon.save()
        self.publish()
        coupon.refresh_from_db()
        self.assertFalse(coupon.enabled)
        self.assertEqual(coupon.max_uses, 8)
        self.assertEqual(Variant.objects.filter(sku="STAGING-COUPON-BOX6").count(), 1)
