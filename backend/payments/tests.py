import json
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from orders.models import Order, OrderItem


class PaymentsFlowTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            full_name="Test User",
            email="test@example.com",
            phone="",
            address_line="Calle 123",
            city="CABA",
            postal_code="1000",
            total_amount="100.00",
        )
        OrderItem.objects.create(
            order=self.order,
            product_name="RaSel",
            variant_name="250 ml",
            unit_price="100.00",
            quantity=1,
            line_total="100.00",
        )

    @patch("payments.views.create_preference")
    def test_start_creates_preference_and_redirects(self, mock_create):
        mock_create.return_value = {"id": "pref_123", "init_point": "https://mp.test/init"}
        url = reverse("payments:start", kwargs={"order_id": self.order.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.mp_preference_id, "pref_123")


class WebhookTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            full_name="Webhook User",
            email="webhook@example.com",
            phone="",
            address_line="Av. Test 456",
            city="Rosario",
            postal_code="2000",
            total_amount="500.00",
            status="pending",
        )
        self.url = reverse("payments:webhook")

    @patch("payments.views.get_payment")
    def test_webhook_payment_approved_marks_order_paid(self, mock_get_payment):
        """
        Un POST al webhook con topic=payment y status=approved debe marcar
        la orden como pagada y guardar mp_payment_id + mp_status.
        """
        payment_id = "PAY-999"
        mock_get_payment.return_value = {
            "id": payment_id,
            "status": "approved",
            "external_reference": str(self.order.id),
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

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "paid")
        self.assertEqual(self.order.mp_payment_id, payment_id)
        self.assertEqual(self.order.mp_status, "approved")

    @patch("payments.views.get_payment")
    def test_webhook_payment_rejected_marks_order_cancelled(self, mock_get_payment):
        """
        Un webhook con status=rejected debe marcar la orden como cancelada.
        """
        payment_id = "PAY-777"
        mock_get_payment.return_value = {
            "id": payment_id,
            "status": "rejected",
            "external_reference": str(self.order.id),
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
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "cancelled")

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
