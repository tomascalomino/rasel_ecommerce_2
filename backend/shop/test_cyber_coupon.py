from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings

from cart.cart import CartItem
from .coupons import quote_coupon
from .models import Coupon, CouponRedemption, Product, Variant


prepare_coupon = import_module(
    "shop.migrations.0013_prepare_cyber_box_coupon"
).prepare_coupon


class CyberBoxCouponTests(TestCase):
    def prepare(self):
        prepare_coupon(apps, SimpleNamespace(connection=connection))

    def real_boxes(self):
        boxes = []
        for slug, units, size in (
            ("pack-6x500ml-blend", 6, 500),
            ("pack-9x250ml-blend", 9, 250),
        ):
            product = Product.objects.create(name=slug, slug=slug)
            boxes.append(
                Variant.objects.create(
                    product=product,
                    name=f"{units} x {size}",
                    sku=slug,
                    pack_units=units,
                    price_ars=10000,
                    stock_qty=60,
                )
            )
        return boxes

    @override_settings(SITE_URL="https://rasel.ar")
    def test_production_prepares_disabled_exact_boxes_without_changing_catalog(self):
        boxes = self.real_boxes()
        bottle = Variant.objects.create(
            product=boxes[0].product,
            name="Botella",
            sku="UNIT",
            price_ars=1000,
            stock_qty=40,
        )
        before = list(Variant.objects.values())
        self.prepare()
        coupon = Coupon.objects.get(code="cybercajarasel11")
        self.assertEqual(coupon.discount_percent, 5)
        self.assertEqual(coupon.max_uses, 50)
        self.assertTrue(coupon.combine_payment_discount)
        self.assertFalse(coupon.enabled)
        self.assertIsNone(coupon.ends_at)
        self.assertEqual(set(coupon.variants.all()), set(boxes))
        self.assertNotIn(bottle, coupon.variants.all())
        self.assertEqual(list(Variant.objects.values()), before)
        self.assertFalse(CouponRedemption.objects.exists())

    @override_settings(SITE_URL="https://rasel.ar")
    def test_missing_or_ambiguous_box_leaves_disabled_draft_without_eligibility(self):
        boxes = self.real_boxes()
        Variant.objects.create(
            product=boxes[0].product,
            name="Otra caja",
            sku="AMBIGUOUS",
            pack_units=6,
            price_ars=10000,
        )
        self.prepare()
        coupon = Coupon.objects.get()
        self.assertFalse(coupon.enabled)
        self.assertFalse(coupon.variants.exists())
        self.assertEqual(Variant.objects.count(), 3)

    def test_other_hosts_receive_no_configuration(self):
        for site in ("", "http://rasel.ar", "https://rasel.ar.example.org"):
            with self.subTest(site=site), override_settings(SITE_URL=site):
                self.prepare()
        self.assertFalse(Coupon.objects.exists())
        self.assertFalse(Product.objects.exists())

    @override_settings(SITE_URL="https://rasel.ar")
    def test_missing_catalog_is_not_created_and_draft_stays_disabled(self):
        self.prepare()
        coupon = Coupon.objects.get()
        self.assertFalse(coupon.enabled)
        self.assertFalse(coupon.variants.exists())
        self.assertFalse(Product.objects.exists())
        self.assertFalse(Variant.objects.exists())

    @override_settings(SITE_URL="https://rasel-mp-staging.onrender.com")
    def test_staging_prices_accumulate_five_percent_and_retries_preserve_edits(self):
        self.prepare()
        coupon = Coupon.objects.get()
        boxes = list(coupon.variants.order_by("pack_units"))
        self.assertEqual([b.pack_units for b in boxes], [6, 9])
        self.assertTrue(coupon.enabled)
        self.assertEqual(coupon.remaining_uses, 50)
        rows = [CartItem(variant=b, qty=2) for b in boxes]
        quote = quote_coupon(coupon.code, rows, 10)
        self.assertEqual(quote.mp_amount, Decimal("15112.00"))
        self.assertEqual(quote.payment_amount, Decimal("30240.00"))
        self.assertEqual(quote.offline_amount, Decimal("13600.00"))
        self.assertEqual(
            sum(r.unit_price * r.qty for r in rows)
            - quote.payment_amount
            - quote.offline_amount,
            Decimal("258400.00"),
        )
        coupon.enabled = False
        coupon.max_uses = 47
        coupon.discount_percent = 4
        coupon.save()
        coupon.variants.remove(boxes[0])
        boxes[0].stock_qty = 3
        boxes[0].save()
        self.prepare()
        coupon.refresh_from_db()
        boxes[0].refresh_from_db()
        self.assertFalse(coupon.enabled)
        self.assertEqual(coupon.max_uses, 47)
        self.assertEqual(coupon.discount_percent, 4)
        self.assertEqual(coupon.variants.count(), 1)
        self.assertEqual(boxes[0].stock_qty, 3)
