from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import Order

from .version import APP_VERSION


class AppVersionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="version-admin",
            email="version@example.com",
            password="test-password",
        )

    def test_settings_version_matches_root_file(self):
        version_file = settings.BASE_DIR.parent / "app_version"
        self.assertEqual(APP_VERSION, version_file.read_text(encoding="utf-8").strip())
        self.assertEqual(settings.APP_VERSION, APP_VERSION)

    def test_admin_displays_current_version(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["app_version"], APP_VERSION)
        self.assertContains(response, f"v{APP_VERSION}")


class AdminDashboardOrderStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="dashboard-admin",
            email="dashboard@example.com",
            password="test-password",
        )
        common = {
            "full_name": "Cliente",
            "email": "cliente@example.com",
            "payment_method": "transfer",
            "fulfillment_status": "pending",
        }
        Order.objects.create(
            **common, payment_status="approved", total_amount=Decimal("100.00")
        )
        Order.objects.create(
            **common,
            payment_status="partially_refunded",
            total_amount=Decimal("100.00"),
            mp_refunded_amount=Decimal("30.00"),
        )
        Order.objects.create(
            **common, payment_status="refunded", total_amount=Decimal("100.00")
        )
        Order.objects.create(
            **common, payment_status="pending", total_amount=Decimal("100.00")
        )
        Order.objects.create(
            **{**common, "payment_method": "cod"},
            payment_status="pending",
            total_amount=Decimal("100.00"),
        )

    def test_dashboard_separates_payment_and_preparation_and_uses_net_sales(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.context["dash_pending_payment_count"], 2)
        self.assertEqual(response.context["dash_orders_to_prepare_count"], 2)
        self.assertEqual(response.context["dash_sales_today"]["count"], 2)
        self.assertEqual(
            response.context["dash_sales_today"]["total"], Decimal("170.00")
        )
        self.assertContains(response, "Cobros pendientes")
        self.assertContains(response, "Pedidos para preparar")


from decimal import Decimal
