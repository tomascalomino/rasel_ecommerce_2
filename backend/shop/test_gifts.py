from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from orders.emails import _build_lines
from payments.models import PaymentDraft
from payments.services import build_preference_payload, process_payment
from payments.tests import MP_TEST_SETTINGS
from shipping.models import PickupPoint
from shipping.services import resolve_shipping

from .gifts import GIFT_END, GIFT_LABEL, gift_state, offer_token
from .models import CommercialSettings, Product, Variant


@override_settings(**MP_TEST_SETTINGS)
class CyberGiftTests(TestCase):
    def setUp(self):
        self.now = GIFT_END - timedelta(days=3)
        self.clock = patch("django.utils.timezone.now", return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.config = CommercialSettings.objects.get(pk=1)
        self.product = Product.objects.create(name="RaSel")
        self.variant = Variant.objects.create(product=self.product, name="250 ml", sku="GIFT-TEST", price_ars=1000, stock_qty=50)
        self.point = PickupPoint.objects.filter(is_active=True).first()
        if not self.point:
            self.point = PickupPoint.objects.create(name="Retiro prueba", address="Dirección de prueba")

    def enable(self):
        self.config.cyber_gift_enabled = True
        self.config.save()

    def cart(self, qty=1):
        session = self.client.session
        session["cart"] = {str(self.variant.pk): {"qty": qty}}
        session.save()

    def form(self, method="transfer", delivery="pickup"):
        return {"full_name": "Prueba Cyber", "email": "cyber@example.com", "delivery_method": delivery,
                "pickup_point": self.point.pk, "address_line": "Calle de prueba 123", "city": "CABA", "postal_code": "1425",
                "payment_method": method, "gift_offer_token": offer_token(gift_state())}

    def submit(self, data):
        if data["delivery_method"] == "ship":
            quote = self.client.get(reverse("shipping:quote"), {"postal_code": data["postal_code"], "subtotal": str(self.variant.price_ars)}).json()
            data["shipping_quote_token"] = quote["quote_token"]
        return self.client.post(reverse("orders:checkout"), data)

    def test_default_disabled_publication_and_exact_argentine_cutoff(self):
        self.assertFalse(gift_state()["active"])
        self.enable()
        self.config.refresh_from_db()
        self.assertEqual(self.config.cyber_gift_started_at, self.now)
        self.assertFalse(gift_state(self.now - timedelta(microseconds=1))["active"])
        self.assertTrue(gift_state(self.now)["active"])
        self.assertTrue(gift_state(GIFT_END - timedelta(microseconds=1))["active"])
        self.assertFalse(gift_state(GIFT_END)["active"])
        self.assertEqual(timezone.localtime(GIFT_END).strftime("%d/%m/%Y %H:%M"), "09/11/2026 00:00")
        self.config.cyber_gift_enabled = False
        self.config.save()
        self.assertFalse(gift_state()["active"])
        self.enable()
        self.assertEqual(self.config.cyber_gift_started_at, self.now)

    def test_one_gift_for_multiple_units_and_historical_emails_after_close(self):
        self.enable()
        self.cart(3)
        response = self.submit(self.form())
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.gift_label, GIFT_LABEL)
        self.assertEqual(order.gift_applied_at, self.now)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items_subtotal, Decimal("3000"))
        self.assertEqual(order.total_amount, Decimal("2700"))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 47)
        self.assertEqual(mail.outbox[0].body.count("REGALO:"), 1)
        with patch("django.utils.timezone.now", return_value=GIFT_END):
            self.assertIn(GIFT_LABEL, _build_lines(order))
            self.assertContains(self.client.get(response.url), GIFT_LABEL)

    def test_cash_shipping_and_transfer_pickup_receive_same_gift(self):
        self.enable()
        for method, delivery in (("cod", "ship"), ("transfer", "pickup")):
            with self.subTest(method=method, delivery=delivery):
                self.cart()
                response = self.submit(self.form(method, delivery))
                self.assertEqual(response.status_code, 302)
                order = Order.objects.latest("id")
                self.assertEqual(order.gift_label, GIFT_LABEL)
                shipping = resolve_shipping("1425", subtotal=1000).cost if delivery == "ship" else 0
                self.assertEqual(order.total_amount, Decimal("900") + shipping)

    def test_stale_checkout_reconfirms_without_creating_or_reserving(self):
        self.enable()
        self.cart()
        for method in ("transfer", "mp"):
            data = self.form(method)
            with patch("django.utils.timezone.now", return_value=GIFT_END):
                response = self.submit(data)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "La promoción de la mini RaSel cambió o terminó")
            self.assertContains(response, "cyber@example.com")
        self.assertFalse(Order.objects.exists())
        self.assertFalse(PaymentDraft.objects.exists())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 50)
        with patch("django.utils.timezone.now", return_value=GIFT_END):
            self.assertEqual(self.submit(self.form()).status_code, 302)
        self.assertEqual(Order.objects.get().gift_label, "")

    def test_missing_or_tampered_offer_cannot_skip_active_gift_review(self):
        self.enable()
        self.cart()
        for token in ("", "forged"):
            data = self.form()
            data["gift_offer_token"] = token
            self.assertContains(self.submit(data), "La promoción de la mini RaSel cambió o terminó")
        self.assertFalse(Order.objects.exists())

    @patch("payments.services.create_preference", return_value={"id": "gift-pref", "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect", "collector_id": 445566})
    def test_mp_snapshots_once_and_approval_after_deadline_keeps_gift(self, create):
        self.enable()
        self.cart()
        self.assertEqual(self.submit(self.form("mp")).status_code, 302)
        draft = PaymentDraft.objects.get()
        self.assertEqual(draft.gift_label, GIFT_LABEL)
        self.assertEqual(len(draft.items), 1)
        payload = build_preference_payload(draft)
        self.assertEqual(sum(Decimal(str(row["unit_price"])) * row["quantity"] for row in payload["items"]), Decimal("1000"))
        self.assertNotIn(GIFT_LABEL, str(payload["items"]))
        payment = {"id": "GIFT-PAY", "status": "approved", "external_reference": str(draft.token), "metadata": {"draft_token": str(draft.token)}, "transaction_amount": 1000, "transaction_amount_refunded": 0, "currency_id": "ARS", "collector_id": 445566, "live_mode": True}
        with patch("django.utils.timezone.now", return_value=GIFT_END + timedelta(minutes=1)):
            with self.captureOnCommitCallbacks(execute=True):
                process_payment(payment, payment["id"])
                process_payment(payment, payment["id"])
        order = Order.objects.get()
        self.assertEqual(order.gift_label, GIFT_LABEL)
        self.assertEqual(order.gift_applied_at, draft.gift_applied_at)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 49)

    def test_status_and_public_html_are_not_cached_and_checkout_has_signed_offer(self):
        self.enable()
        self.cart()
        for url in (reverse("home"), reverse("shop:product_list"), reverse("cart:detail"), reverse("orders:checkout"), reverse("shop:gift_status")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response["Cache-Control"])
        checkout = self.client.get(reverse("orders:checkout"))
        self.assertTrue(checkout.context["form"]["gift_offer_token"].value())
        self.assertContains(checkout, "Mini RaSel de 28 ml × 1")
        self.assertTrue(self.client.get(reverse("shop:gift_status")).json()["active"])
