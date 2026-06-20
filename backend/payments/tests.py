import json
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from orders.models import Order
from payments.models import PaymentDraft
from shop.models import Category, Product, Variant


class PaymentsFlowTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="RASEL-250",
            price_ars="100.00",
            stock_qty=5,
            is_active=True,
        )

        self.draft = PaymentDraft.objects.create(
            full_name="Test User",
            email="test@example.com",
            phone="",
            address_line="Calle 123",
            city="CABA",
            postal_code="1000",
            total_amount="100.00",
            items=[
                {
                    "variant_id": self.variant.id,
                    "product_name": self.product.name,
                    "variant_name": self.variant.name,
                    "unit_price": "100.00",
                    "quantity": 1,
                    "line_total": "100.00",
                }
            ],
        )

    @patch("payments.views.create_preference")
    def test_start_creates_preference_and_redirects(self, mock_create):
        mock_create.return_value = {"id": "pref_123", "init_point": "https://mp.test/init"}
        url = reverse("payments:start", kwargs={"draft_id": self.draft.token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

        self.draft.refresh_from_db()
        self.assertEqual(self.draft.mp_preference_id, "pref_123")


class WebhookTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="RASEL-250-WH",
            price_ars="500.00",
            stock_qty=3,
            is_active=True,
        )
        self.draft = PaymentDraft.objects.create(
            full_name="Webhook User",
            email="webhook@example.com",
            phone="",
            address_line="Av. Test 456",
            city="Rosario",
            postal_code="2000",
            total_amount="500.00",
            items=[
                {
                    "variant_id": self.variant.id,
                    "product_name": self.product.name,
                    "variant_name": self.variant.name,
                    "unit_price": "500.00",
                    "quantity": 2,
                    "line_total": "1000.00",
                }
            ],
        )
        self.url = reverse("payments:webhook")

    @patch("payments.views.get_payment")
    def test_webhook_payment_approved_marks_order_paid(self, mock_get_payment):
        """
        Un POST al webhook con topic=payment y status=approved debe crear orden,
        marcarla paid y descontar stock de forma atómica.
        """
        payment_id = "PAY-999"
        mock_get_payment.return_value = {
            "id": payment_id,
            "status": "approved",
            "external_reference": str(self.draft.token),
        }

        payload = {
            "type": "payment",
            "data": {"id": payment_id},
        }
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

        self.draft.refresh_from_db()
        self.assertIsNotNone(self.draft.order_id)

        order = self.draft.order
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.mp_payment_id, payment_id)
        self.assertEqual(order.mp_status, "approved")

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 1)

    @patch("payments.views.get_payment")
    def test_webhook_payment_approved_is_idempotent(self, mock_get_payment):
        payment_id = "PAY-1000"
        mock_get_payment.return_value = {
            "id": payment_id,
            "status": "approved",
            "external_reference": str(self.draft.token),
        }

        payload = {
            "type": "payment",
            "data": {"id": payment_id},
        }
        resp1 = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        resp2 = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(Order.objects.count(), 1)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 1)

        # El email de confirmación se envía una sola vez pese a los 2 webhooks.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.draft.email, mail.outbox[0].to)

    @patch("payments.views.get_payment")
    def test_webhook_payment_rejected_marks_order_cancelled(self, mock_get_payment):
        """
        Un webhook con status=rejected debe actualizar estado del draft sin crear orden.
        """
        payment_id = "PAY-777"
        mock_get_payment.return_value = {
            "id": payment_id,
            "status": "rejected",
            "external_reference": str(self.draft.token),
        }

        payload = {
            "type": "payment",
            "data": {"id": payment_id},
        }
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(resp.status_code, 200)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.mp_status, "rejected")
        self.assertEqual(self.draft.order_id, None)

    def test_webhook_unknown_topic_returns_ok(self):
        """
        Un webhook con topic desconocido debe responder 200 sin explotar.
        """
        payload = {"type": "merchant_order", "data": {"id": "123"}}
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

    def test_webhook_ipn_query_params(self):
        """
        IPN clásico: topic y id llegan por query string.
        Sin MP_ACCESS_TOKEN real, solo verificamos que no explote y responda 200.
        """
        resp = self.client.post(
            f"{self.url}?topic=payment&id=12345",
            content_type="application/json",
        )
        # Puede ser 200 (procesó o falló gracefully)
        self.assertEqual(resp.status_code, 200)
