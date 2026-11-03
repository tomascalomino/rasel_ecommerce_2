from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.models import CommercialSettings, Coupon, CouponRedemption, Product, Variant


@override_settings(MP_CHECKOUT_ENABLED=True)
class CartPaymentSummaryTests(TestCase):
    def setUp(self):
        CommercialSettings.objects.filter(pk=1).update(
            offline_payment_discount_percent=10
        )
        product = Product.objects.create(name="Productos de prueba")
        self.boxes = [
            Variant.objects.create(
                product=product,
                name=name,
                sku=name,
                price_ars=price,
                stock_qty=10,
                pack_units=units,
            )
            for name, price, units in (("Caja x6", 83340, 6), ("Caja x9", 67780, 9))
        ]
        self.bottle = Variant.objects.create(
            product=product, name="Botella", sku="BOTTLE", price_ars=7780, stock_qty=10
        )
        session = self.client.session
        session["cart"] = {
            str(v.pk): {"qty": 1} for v in (*self.boxes, self.bottle)
        }
        session.save()

    def apply_coupon(self, *, percent=5, combine=True):
        coupon = Coupon.objects.create(
            code="cyberrasel",
            discount_percent=percent,
            max_uses=50,
            combine_payment_discount=combine,
            enabled=True,
            starts_at=timezone.now() - timedelta(days=1),
        )
        coupon.variants.set(self.boxes)
        self.client.post(reverse("shop:coupon_apply"), {"coupon_code": coupon.code})
        return coupon

    def summary(self, offline, card):
        response = self.client.get(reverse("cart:detail"))
        self.assertEqual(response.context["cart_offline_total"], Decimal(offline))
        self.assertEqual(response.context["coupon_total"], Decimal(card))
        self.assertContains(response, "Efectivo o transferencia")
        self.assertContains(response, "Tarjeta / Mercado Pago")
        self.assertContains(response, "Total de productos")
        return response

    def test_both_totals_without_coupon_keep_the_unit_rounding(self):
        self.summary("143000", "158900")

    def test_combined_coupon_discounts_boxes_only_and_preview_keeps_all_uses(self):
        coupon = self.apply_coupon()
        response = self.summary("136200", "151344")
        self.assertContains(response, "− $ 6.800")
        self.assertContains(response, "− $ 7.556")
        self.assertContains(response, "− $ 15.900")
        self.assertEqual(coupon.remaining_uses, 50)
        self.assertFalse(CouponRedemption.objects.exists())

    def test_non_combined_coupon_uses_best_price_per_presentation(self):
        self.apply_coupon(percent=20, combine=False)
        self.summary("127896", "128676")

    def test_zero_payment_discount_shows_equal_prices(self):
        CommercialSettings.objects.filter(pk=1).update(
            offline_payment_discount_percent=0
        )
        self.apply_coupon()
        self.summary("151344", "151344")

    def test_expired_coupon_does_not_reduce_either_displayed_total(self):
        coupon = self.apply_coupon()
        coupon.ends_at = timezone.now() - timedelta(seconds=1)
        coupon.save()
        response = self.summary("143000", "158900")
        self.assertContains(response, "Este cupón no está vigente.")

    @override_settings(MP_CHECKOUT_ENABLED=False)
    def test_disabled_mercado_pago_does_not_advertise_that_payment_option(self):
        self.apply_coupon()
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "Efectivo o transferencia")
        self.assertNotContains(response, "Tarjeta / Mercado Pago")
        self.assertEqual(response.context["cart_offline_total"], Decimal("136200"))
