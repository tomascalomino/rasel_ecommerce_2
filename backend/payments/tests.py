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
