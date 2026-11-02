from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.urls import reverse
from django.utils import timezone

from cart.cart import CartItem
from orders.emails import _totals_block
from orders.models import Order
from orders.services import cancel_and_restore
from orders.views import _create_offline_order
from payments.models import PaymentDraft
from payments.services import (
    build_preference_payload,
    process_payment,
    release_reserved_stock,
)
from payments.tests import MP_TEST_SETTINGS
from shipping.models import PickupPoint, ShippingPromotion
from .coupons import CouponError, SESSION_KEY, quote_coupon
from .models import CommercialSettings, Coupon, CouponRedemption, Product, Variant


@override_settings(**MP_TEST_SETTINGS)
class CouponTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Cajas de prueba")
        self.box = Variant.objects.create(
            product=self.product,
            name="Caja x6",
            sku="COUPON-BOX",
            price_ars=10000,
            stock_qty=30,
            pack_units=6,
        )
        self.bottle = Variant.objects.create(
            product=self.product,
            name="Botella",
            sku="COUPON-UNIT",
            price_ars=1000,
            stock_qty=30,
        )
        self.point = PickupPoint.objects.create(
            name="Retiro ficticio", address="No concurrir"
        )
        CommercialSettings.objects.filter(pk=1).update(
            cyber_gift_enabled=False, offline_payment_discount_percent=10
        )
        self.coupon = Coupon.objects.create(
            code="cybercajarasel11",
            discount_percent=20,
            max_uses=2,
            enabled=True,
            starts_at=timezone.now() - timedelta(days=1),
        )
        self.coupon.variants.add(self.box)
        self.mailer = patch("orders.views.send_order_confirmation")
        self.mailer.start()
        self.addCleanup(self.mailer.stop)

    def cart(self, qty=2, bottle=True):
        session = self.client.session
        session["cart"] = {str(self.box.pk): {"qty": qty}}
        if bottle:
            session["cart"][str(self.bottle.pk)] = {"qty": 1}
        session.save()

    def apply(self, code="cybercajarasel11", **data):
        follow = data.pop("follow", False)
        return self.client.post(
            reverse("shop:coupon_apply"), {"coupon_code": code, **data}, follow=follow
        )

    def form(self, method="transfer"):
        response = self.client.get(reverse("orders:checkout"))
        return {
            "full_name": "Prueba Cupón",
            "email": "coupon@example.invalid",
            "phone": "1100000000",
            "delivery_method": "pickup",
            "pickup_point": self.point.pk,
            "payment_method": method,
            "coupon_code": self.client.session.get(SESSION_KEY, ""),
            "coupon_offer_token": response.context["form"][
                "coupon_offer_token"
            ].value(),
            "gift_offer_token": response.context["form"]["gift_offer_token"].value(),
        }

    def submit(self, data=None):
        return self.client.post(reverse("orders:checkout"), data or self.form())

    def draft(self):
        self.cart(qty=2)
        self.apply()
        with patch(
            "payments.services.create_preference",
            return_value={
                "id": "coupon-pref",
                "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect",
                "collector_id": 445566,
            },
        ):
            self.assertEqual(self.submit(self.form("mp")).status_code, 302)
        return PaymentDraft.objects.latest("pk")

    def payment(self, draft):
        return {
            "id": f"COUPON-PAY-{draft.pk}",
            "status": "approved",
            "external_reference": str(draft.token),
            "metadata": {"draft_token": str(draft.token)},
            "transaction_amount": str(draft.total_amount),
            "transaction_amount_refunded": 0,
            "currency_id": "ARS",
            "collector_id": 445566,
            "live_mode": True,
        }

    def test_code_normalization_and_preview_do_not_consume_quota(self):
        self.cart()
        self.assertEqual(self.apply("  CYBERCAJARASEL11  ").status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], self.coupon.code)
        self.assertContains(self.client.get(reverse("cart:detail")), "$ 17.000")
        self.assertEqual(self.coupon.remaining_uses, 2)
        self.assertFalse(CouponRedemption.objects.exists())

    def test_only_selected_boxes_and_one_use_for_whole_order(self):
        self.cart()
        self.apply()
        self.assertEqual(self.submit().status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.items_subtotal, Decimal("21000"))
        self.assertEqual(order.coupon_discount_amount, Decimal("4000"))
        self.assertEqual(order.payment_discount_amount, Decimal("100"))
        self.assertEqual(order.total_amount, Decimal("16900"))
        self.assertEqual(self.coupon.remaining_uses, 1)
        self.assertEqual(CouponRedemption.objects.get().state, "used")
        self.assertIn("Cupón cybercajarasel11", _totals_block(order))
        self.assertIn("Subtotal: $21000", _totals_block(order))

    def test_combined_percentages_are_sequential_on_eligible_net_prices(self):
        self.coupon.combine_payment_discount = True
        self.coupon.save()
        self.cart()
        self.apply()
        self.assertEqual(self.submit().status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.payment_discount_amount, Decimal("2100"))
        self.assertEqual(order.coupon_discount_amount, Decimal("3600"))
        self.assertEqual(order.total_amount, Decimal("15300"))

    def test_better_offline_price_does_not_spend_coupon(self):
        self.coupon.discount_percent = 5
        self.coupon.save()
        self.cart()
        self.apply()
        self.assertEqual(self.submit().status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.total_amount, Decimal("18900"))
        self.assertEqual(order.coupon_code, "")
        self.assertFalse(CouponRedemption.objects.exists())

    def test_ineligible_cart_unknown_code_and_empty_code_are_rejected(self):
        session = self.client.session
        session["cart"] = {str(self.bottle.pk): {"qty": 1}}
        session.save()
        for code in (self.coupon.code, "noexiste", ""):
            response = self.apply(code, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(CouponRedemption.objects.exists())

    def test_checkout_without_applying_code_or_with_forged_token_cannot_order(self):
        self.cart()
        data = self.form()
        data["coupon_code"] = self.coupon.code
        self.assertContains(self.submit(data), "Aplicá el código")
        self.apply()
        data = self.form()
        data["coupon_offer_token"] = "forged"
        self.assertContains(self.submit(data), "El cupón o su descuento cambió")
        self.assertFalse(Order.objects.exists())
        self.assertFalse(PaymentDraft.objects.exists())
        self.box.refresh_from_db()
        self.assertEqual(self.box.stock_qty, 30)

    def test_last_coupon_sold_and_changed_conditions_reconfirm_before_stock(self):
        self.coupon.max_uses = 1
        self.coupon.save()
        self.cart()
        self.apply()
        stale = self.form()
        self.assertEqual(self.submit(stale).status_code, 302)
        self.cart()
        self.apply()
        self.assertContains(self.submit(stale), "Se agotaron los usos")
        self.assertEqual(Order.objects.count(), 1)
        self.box.refresh_from_db()
        self.assertEqual(self.box.stock_qty, 28)
        self.coupon.max_uses = 2
        self.coupon.discount_percent = 25
        self.coupon.save()
        session = self.client.session
        session[SESSION_KEY] = self.coupon.code
        session.save()
        self.assertContains(self.submit(stale), "El cupón o su descuento cambió")
        self.assertEqual(Order.objects.count(), 1)

    def test_disabled_scheduled_and_expired_codes_cannot_apply(self):
        rows = [CartItem(self.box, 1)]
        now = timezone.now()
        self.assertTrue(
            quote_coupon(self.coupon.code, rows, 10, now=self.coupon.starts_at).coupon
        )
        self.assertTrue(
            quote_coupon(
                self.coupon.code,
                rows,
                10,
                now=self.coupon.starts_at - timedelta(microseconds=1),
            ).error
        )
        self.coupon.ends_at = now
        self.coupon.save()
        self.assertTrue(quote_coupon(self.coupon.code, rows, 10, now=now).error)
        self.coupon.ends_at = None
        self.coupon.enabled = False
        self.coupon.save()
        self.assertTrue(quote_coupon(self.coupon.code, rows, 10).error)

    def test_apply_and_remove_preserve_checkout_fields_without_javascript(self):
        self.cart()
        data = self.form()
        response = self.apply(
            coupon_next="checkout",
            **{k: v for k, v in data.items() if k != "coupon_code"},
        )
        form = response.context["form"]
        self.assertContains(response, f'action="{reverse("orders:checkout")}"')
        self.assertEqual(form["full_name"].value(), "Prueba Cupón")
        self.assertEqual(form["payment_method"].value(), "transfer")
        self.assertEqual(form["delivery_method"].value(), "pickup")
        self.assertFalse(form.is_bound)
        response = self.apply(
            coupon_next="checkout",
            coupon_action="remove",
            **{k: v for k, v in data.items() if k != "coupon_code"},
        )
        self.assertEqual(
            response.context["form"]["email"].value(), "coupon@example.invalid"
        )
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_mp_amounts_snapshot_and_repeated_approval_after_coupon_end(self):
        draft = self.draft()
        self.assertEqual(draft.total_amount, Decimal("17000"))
        payload = build_preference_payload(draft)
        self.assertEqual(
            sum(
                Decimal(str(r["unit_price"])) * r["quantity"] for r in payload["items"]
            ),
            draft.total_amount,
        )
        self.assertEqual(self.coupon.remaining_uses, 1)
        self.assertEqual(CouponRedemption.objects.get().state, "reserved")
        self.coupon.enabled = False
        self.coupon.save()
        payment = self.payment(draft)
        process_payment(payment, payment["id"])
        process_payment(payment, payment["id"])
        order = Order.objects.get()
        self.assertEqual(order.coupon_discount_amount, Decimal("4000"))
        self.assertEqual(order.items_subtotal, Decimal("21000"))
        self.assertEqual(CouponRedemption.objects.count(), 1)
        self.assertEqual(CouponRedemption.objects.get().state, "used")

    def test_mp_release_returns_quota_once(self):
        draft = self.draft()
        self.assertTrue(release_reserved_stock(draft.token, "expired"))
        self.assertFalse(release_reserved_stock(draft.token, "expired"))
        self.assertEqual(self.coupon.remaining_uses, 2)
        self.assertEqual(CouponRedemption.objects.get().state, "released")

    def test_late_approved_payment_without_quota_requires_review_keeps_paid_total(self):
        self.coupon.max_uses = 1
        self.coupon.save()
        draft = self.draft()
        release_reserved_stock(draft.token, "expired")
        self.cart()
        self.apply()
        self.assertEqual(self.submit().status_code, 302)
        payment = self.payment(draft)
        result = process_payment(payment, payment["id"])
        self.assertEqual(result.state, "review")
        self.assertEqual(result.order.total_amount, draft.total_amount)
        self.assertEqual(result.order.coupon_code, self.coupon.code)
        self.assertEqual(CouponRedemption.objects.get(draft=draft).state, "review")
        self.assertEqual(self.coupon.remaining_uses, 0)
        self.assertEqual(process_payment(payment, payment["id"]).state, "review")

    def test_unpaid_cancellation_returns_coupon_paid_order_does_not(self):
        self.cart()
        self.apply()
        self.submit()
        order = Order.objects.get()
        cancel_and_restore(order.pk)
        cancel_and_restore(order.pk)
        self.assertEqual(self.coupon.remaining_uses, 2)
        self.cart()
        self.apply()
        self.submit()
        paid = Order.objects.latest("pk")
        Order.objects.filter(pk=paid.pk).update(
            payment_status="approved", paid_at=timezone.now()
        )
        cancel_and_restore(paid.pk)
        self.assertEqual(self.coupon.remaining_uses, 1)

    def test_limit_cannot_drop_below_allocated_and_history_survives_edits(self):
        self.cart()
        self.apply()
        self.submit()
        self.coupon.max_uses = 0
        with self.assertRaises(ValidationError):
            self.coupon.full_clean()
        self.coupon.max_uses = 2
        self.coupon.code = "otro-codigo"
        self.coupon.discount_percent = 30
        self.coupon.save()
        order = Order.objects.get()
        self.assertEqual(order.coupon_code, "cybercajarasel11")
        self.assertEqual(order.coupon_discount_percent, 20)
        self.assertEqual(order.coupon_discount_amount, Decimal("4000"))

    def test_coupon_gift_and_caba_shipping_stack(self):
        CommercialSettings.objects.filter(pk=1).update(
            cyber_gift_enabled=True,
            cyber_gift_started_at=timezone.now() - timedelta(minutes=1),
        )
        ShippingPromotion.objects.create(
            title="CABA prueba",
            introduction="Solo pruebas",
            starts_at=timezone.now() - timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1),
            enabled=True,
        )
        self.cart()
        self.apply()
        data = self.form()
        data.update(
            delivery_method="ship",
            address_line="No enviar 123",
            city="CABA",
            postal_code="1425",
        )
        data["shipping_quote_token"] = self.client.get(
            reverse("shipping:quote"), {"postal_code": "1425", "subtotal": "21000"}
        ).json()["quote_token"]
        self.assertEqual(self.submit(data).status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.shipping_cost, 0)
        self.assertTrue(order.gift_label)
        self.assertEqual(order.total_amount, Decimal("16900"))


class CouponConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_last_use_between_different_stock_rows_cannot_be_sold_twice(self):
        product = Product.objects.create(name="Cajas concurrentes")
        variants = [
            Variant.objects.create(
                product=product,
                name=f"Caja {n}",
                sku=f"RACE-COUPON-{n}",
                price_ars=10000,
                stock_qty=10,
                pack_units=6,
            )
            for n in range(2)
        ]
        coupon = Coupon.objects.create(
            code="ultimo-cupon",
            discount_percent=20,
            max_uses=1,
            enabled=True,
            starts_at=timezone.now() - timedelta(days=1),
        )
        coupon.variants.add(*variants)
        gate = Barrier(2)

        def buy(variant_id):
            close_old_connections()
            try:
                variant = Variant.objects.get(pk=variant_id)
                rows = [CartItem(variant, 1)]
                quote = quote_coupon(coupon.code, rows, 10)
                gate.wait(timeout=10)
                try:
                    _create_offline_order(
                        {
                            "full_name": "Prueba",
                            "email": "race@example.invalid",
                            "phone": "",
                            "address_line": "",
                            "address_extra": "",
                            "city": "",
                            "postal_code": "",
                        },
                        {
                            "items_subtotal": Decimal("10000"),
                            "delivery_method": "pickup",
                            "pickup_point": None,
                            "pickup_point_label": "Prueba",
                            "shipping_cost": Decimal(0),
                            "shipping_zone": "",
                            "shipping_carrier_arranged": False,
                            "cod_allowed": True,
                        },
                        rows,
                        "transfer",
                        10,
                        coupon_code=coupon.code,
                        coupon_offer_token=quote.token,
                    )
                    return "used"
                except CouponError:
                    return "exhausted"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, [v.pk for v in variants]))
        self.assertEqual(sorted(results), ["exhausted", "used"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(CouponRedemption.objects.count(), 1)
        self.assertEqual(
            sum(
                Variant.objects.filter(pk__in=[v.pk for v in variants]).values_list(
                    "stock_qty", flat=True
                )
            ),
            19,
        )
