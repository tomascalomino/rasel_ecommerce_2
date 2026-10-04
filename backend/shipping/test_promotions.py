from datetime import timedelta
from decimal import Decimal
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.urls import reverse
from django.utils import timezone

from config.admin import sync_roles
from orders.models import Order
from payments.models import PaymentDraft
from payments.services import process_payment, build_preference_payload
from payments.tests import MP_TEST_SETTINGS
from shop.models import CommercialSettings, Product, Variant
from .models import ShippingPromotion, ShippingZone, PickupPoint
from .promotions import public_state
from .services import resolve_shipping


class CampaignTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.campaign = ShippingPromotion.objects.create(
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(days=7),
        )

    def publish(self):
        self.campaign.enabled = True
        self.campaign.save()

    def test_default_draft_not_public_and_no_effect(self):
        self.assertEqual(self.campaign.state, "draft")
        self.assertEqual(
            self.client.get(self.campaign.get_absolute_url()).status_code, 404
        )
        self.assertEqual(resolve_shipping("1425", 1).cost, Decimal("7000"))

    def test_boundaries_and_suspension_restore_original_rates(self):
        self.publish()
        start, end = self.campaign.starts_at, self.campaign.ends_at
        self.assertEqual(
            resolve_shipping("1425", 1, now=start - timedelta(microseconds=1)).cost,
            Decimal("7000"),
        )
        self.assertEqual(resolve_shipping("1425", 1, now=start).cost, 0)
        self.assertEqual(
            resolve_shipping("1425", 1, now=end - timedelta(microseconds=1)).cost, 0
        )
        self.assertEqual(resolve_shipping("1425", 1, now=end).cost, Decimal("7000"))
        self.campaign.enabled = False
        self.campaign.save()
        self.assertEqual(self.campaign.state, "suspended")
        self.assertEqual(public_state(self.now)["campaign"]["state"], "suspended")
        self.assertEqual(resolve_shipping("1425", 1).cost, Decimal("7000"))
        self.assertContains(self.client.get(reverse("home")), "Promoción suspendida")

    def test_geography_is_independent_of_zone_label_and_code(self):
        self.publish()
        zone = ShippingZone.objects.get(code="free")
        zone.code, zone.name = "delivery-local", "Reparto propio"
        zone.save()
        for cp in ("1000", "1499", "1425", "C1425ABC", " c1425-abc "):
            quote = resolve_shipping(cp, 1)
            self.assertEqual(quote.cost, 0, cp)
            self.assertEqual(quote.promotion.pk, self.campaign.pk)
            self.assertIsNone(quote.free_over)
            self.assertIsNone(quote.remaining_for_free)
            self.assertTrue(quote.cod_allowed)
        for cp in (
            "999",
            "1500",
            "1744",
            "1828",
            "5000",
            "B1425ABC",
            "11425",
            "bad1425",
            "1425ABC",
        ):
            self.assertIsNone(resolve_shipping(cp, 1).promotion, cp)
        self.assertEqual(resolve_shipping("1744", 1).cost, Decimal("7000"))
        self.assertTrue(resolve_shipping("5000", 1).carrier_arranged)

    def test_quote_metadata_cache_and_bad_input(self):
        self.publish()
        q = self.client.get(
            reverse("shipping:quote"), {"postal_code": "1425", "subtotal": "7780"}
        )
        self.assertEqual(q.json()["cost"], "0.00")
        self.assertEqual(q.json()["promotion"]["id"], self.campaign.pk)
        self.assertTrue(q.json()["quote_token"])
        self.assertIn("no-store", q["Cache-Control"])
        for subtotal in ("NaN", "Infinity", "-1", "bad", "1e999999"):
            self.assertEqual(
                self.client.get(
                    reverse("shipping:quote"),
                    {"postal_code": "1425", "subtotal": subtotal},
                ).status_code,
                200,
            )
        bad = self.client.get(
            reverse("shipping:quote"), {"postal_code": "B1425ABC"}
        ).json()
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["quote_token"], "")

    def test_zero_extra_saving_when_already_free(self):
        self.publish()
        q = resolve_shipping("1425", 100000)
        self.assertEqual(q.cost_before_promotion, 0)
        self.assertIsNotNone(q.promotion)

    def test_no_promotion_for_carrier_arranged_or_missing_zone(self):
        self.publish()
        ShippingZone.objects.filter(code="free").update(carrier_arranged=True)
        self.assertIsNone(resolve_shipping("1425", 1).promotion)
        ShippingZone.objects.all().update(is_active=False)
        self.assertIsNone(resolve_shipping("1425", 1).promotion)

    def test_dates_frozen_after_publication_and_overlap_rejected(self):
        self.publish()
        original_url = self.campaign.get_absolute_url()
        self.campaign.title = "Otro texto"
        with self.assertRaises(ValidationError):
            self.campaign.save()
        with self.assertRaises(ValidationError):
            ShippingPromotion.objects.create(
                enabled=True, starts_at=self.now, ends_at=self.now + timedelta(days=1)
            )
        with self.assertRaises(ValidationError):
            ShippingPromotion.objects.create(starts_at=self.now, ends_at=self.now)
        consecutive = ShippingPromotion.objects.create(
            enabled=True,
            starts_at=self.campaign.ends_at,
            ends_at=self.campaign.ends_at + timedelta(days=7),
        )
        self.assertEqual(consecutive.state, "scheduled")
        with patch(
            "shipping.views.public_state",
            return_value=public_state(self.campaign.ends_at),
        ):
            response = self.client.get(reverse("shipping:promotion_status"))
            self.assertEqual(response.json()["campaign"]["id"], consecutive.pk)
        with patch("django.utils.timezone.now", return_value=consecutive.ends_at):
            self.assertContains(self.client.get(original_url), "Promoción finalizada")

    def test_banner_only_on_purchase_surfaces_and_public_conditions_escaped(self):
        self.campaign.introduction = '<script>alert("x")</script>'
        self.publish()
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'id="shipping-promotion-banner"')
        self.assertIn("no-store", home["Cache-Control"])
        self.assertNotContains(
            self.client.get(reverse("orders:confirmation", args=[999])),
            'id="shipping-promotion-banner"',
        )
        conditions = self.client.get(self.campaign.get_absolute_url())
        self.assertContains(conditions, "&lt;script&gt;")
        self.assertContains(conditions, "(exclusivo)")
        self.assertContains(conditions, "UTC−3")

    def test_operator_and_read_only_admin_permissions(self):
        sync_roles()
        operator = get_user_model().objects.create_user(
            username="promo-operator", is_staff=True
        )
        operator.groups.add(Group.objects.get(name="Operador"))
        reader = get_user_model().objects.create_user(
            username="promo-reader", is_staff=True
        )
        reader.groups.add(Group.objects.get(name="Solo lectura"))
        self.assertTrue(operator.has_perm("shipping.add_shippingpromotion"))
        self.assertFalse(reader.has_perm("shipping.change_shippingpromotion"))
        self.client.force_login(operator)
        self.assertEqual(
            self.client.get(
                reverse("admin:shipping_shippingpromotion_add")
            ).status_code,
            200,
        )
        self.publish()
        response = self.client.get(
            reverse("admin:shipping_shippingpromotion_change", args=[self.campaign.pk])
        )
        self.assertContains(response, "Ver condiciones publicadas")
        self.assertNotContains(response, 'name="title"')
        self.assertEqual(
            self.client.post(
                reverse(
                    "admin:shipping_shippingpromotion_delete", args=[self.campaign.pk]
                ),
                {"post": "yes"},
            ).status_code,
            403,
        )


@override_settings(
    ORDER_NOTIFICATION_EMAIL="", BREVO_API_KEY="", MP_CHECKOUT_ENABLED=False
)
class PromotionCheckoutTests(TestCase):
    def setUp(self):
        self.campaign = ShippingPromotion.objects.create(
            enabled=True,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(days=7),
        )
        self.variant = Variant.objects.create(
            product=Product.objects.create(name="Oliva demo"),
            name="250 ml",
            sku="PROMO-TEST",
            price_ars=Decimal("7780"),
            stock_qty=10,
        )
        session = self.client.session
        session["cart"] = {str(self.variant.pk): {"qty": 1}}
        session.save()
        self.data = dict(
            full_name="Cliente demo",
            email="demo@example.com",
            delivery_method="ship",
            address_line="Calle demo 1",
            city="CABA",
            postal_code="1425",
            payment_method="transfer",
        )

    def quote(self, cp="1425"):
        return self.client.get(
            reverse("shipping:quote"), {"postal_code": cp, "subtotal": "7780"}
        ).json()["quote_token"]

    def submit(self, **changes):
        return self.client.post(reverse("orders:checkout"), {**self.data, **changes})

    def test_no_javascript_review_then_confirm_preserves_values(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirmar total y continuar")
        self.assertContains(response, "Cliente demo")
        self.assertFalse(Order.objects.exists())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 10)
        token = response.context["form"]["shipping_quote_token"].value()
        confirmed = self.submit(shipping_quote_token=token)
        self.assertEqual(confirmed.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.shipping_cost, 0)
        self.assertEqual(order.shipping_cost_before_promotion, Decimal("7000"))
        self.assertEqual(order.shipping_promotion_savings, Decimal("7000"))
        self.assertEqual(order.total_amount, Decimal("7000"))
        self.assertEqual(order.payment_discount_amount, Decimal("780"))
        self.assertIn(self.campaign.title, mail.outbox[0].body)
        self.assertContains(self.client.get(confirmed.url), self.campaign.title)

    def test_expired_quote_reconfirms_before_any_stock_or_payment_write(self):
        token = self.quote()
        with patch("django.utils.timezone.now", return_value=self.campaign.ends_at):
            response = self.submit(shipping_quote_token=token)
            self.assertEqual(response.context["review_total"], Decimal("14000"))
            self.assertFalse(Order.objects.exists())
            self.assertFalse(PaymentDraft.objects.exists())
            new_token = response.context["form"]["shipping_quote_token"].value()
            self.assertEqual(
                self.submit(shipping_quote_token=new_token).status_code, 302
            )
        order = Order.objects.get()
        self.assertIsNone(order.shipping_promotion)
        self.assertEqual(order.shipping_cost, Decimal("7000"))

    def test_revalidates_after_stock_validation_crossing_boundary(self):
        token = self.quote()
        from orders.views import _delivery_from_form

        with patch(
            "django.utils.timezone.now", return_value=self.campaign.starts_at
        ) as clock:

            def cross_deadline(*args):
                result = _delivery_from_form(*args)
                clock.return_value = self.campaign.ends_at
                return result

            with patch("orders.views._delivery_from_form", side_effect=cross_deadline):
                response = self.submit(shipping_quote_token=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["review_quote"].cost, Decimal("7000"))
        self.assertFalse(Order.objects.exists())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 10)

    def test_cash_accumulates_and_snapshot_survives_suspension(self):
        self.assertEqual(
            self.submit(
                payment_method="cod", shipping_quote_token=self.quote()
            ).status_code,
            302,
        )
        order = Order.objects.get()
        self.campaign.enabled = False
        self.campaign.save()
        order.refresh_from_db()
        self.assertEqual(order.shipping_promotion_label, self.campaign.title)
        self.assertEqual(order.shipping_cost, 0)
        self.assertEqual(order.total_amount, Decimal("7000"))

    def test_forged_token_wrong_cp_and_inconsistent_prefix_create_nothing(self):
        for data in (
            {"shipping_quote_token": "forged"},
            {"postal_code": "1744", "shipping_quote_token": self.quote()},
            {"postal_code": "B1425ABC", "shipping_quote_token": self.quote()},
        ):
            self.assertEqual(self.submit(**data).status_code, 200)
            self.assertFalse(Order.objects.exists())

    def test_pickup_does_not_capture_campaign(self):
        point = PickupPoint.objects.filter(is_active=True).first()
        response = self.submit(delivery_method="pickup", pickup_point=point.pk)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(Order.objects.get().shipping_promotion)

    @override_settings(**MP_TEST_SETTINGS)
    def test_mp_draft_snapshot_survives_late_duplicate_approval(self):
        preference = {
            "id": "promo-pref",
            "init_point": "https://sandbox.mercadopago.com.ar/checkout/v1/redirect",
            "collector_id": 445566,
        }
        with patch("payments.services.create_preference", return_value=preference):
            response = self.submit(
                payment_method="mp", shipping_quote_token=self.quote()
            )
        self.assertEqual(response.status_code, 302)
        draft = PaymentDraft.objects.get()
        self.assertEqual(draft.total_amount, Decimal("7780"))
        self.assertEqual(draft.shipping_promotion.pk, self.campaign.pk)
        self.assertEqual(len(build_preference_payload(draft)["items"]), 1)
        payment = dict(
            id="PROMO-PAY",
            status="approved",
            external_reference=str(draft.token),
            metadata={"draft_token": str(draft.token)},
            transaction_amount=7780,
            transaction_amount_refunded=0,
            currency_id="ARS",
            collector_id=445566,
            live_mode=False,
        )
        with patch(
            "django.utils.timezone.now",
            return_value=self.campaign.ends_at + timedelta(minutes=1),
        ), self.captureOnCommitCallbacks(execute=True):
            process_payment(payment, "PROMO-PAY")
            process_payment(payment, "PROMO-PAY")
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.get()
        self.assertEqual(
            order.shipping_promotion_applied_at, draft.shipping_promotion_applied_at
        )
        self.assertEqual(order.shipping_cost_before_promotion, Decimal("7000"))
        self.assertEqual(order.shipping_cost, 0)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 9)
        self.assertEqual(len(mail.outbox), 1)


class CampaignConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_simultaneous_first_activations_cannot_overlap(self):
        CommercialSettings.objects.get_or_create(pk=1)
        start = timezone.now() + timedelta(hours=1)
        barrier = threading.Barrier(2)
        results = []

        def publish():
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                ShippingPromotion.objects.create(
                    enabled=True, starts_at=start, ends_at=start + timedelta(days=7)
                )
                results.append("published")
            except ValidationError:
                results.append("rejected")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=publish) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ["published", "rejected"])
        self.assertEqual(ShippingPromotion.objects.filter(enabled=True).count(), 1)
