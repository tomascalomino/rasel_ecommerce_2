from unittest.mock import patch

from django.db import OperationalError
from django.test import Client, TestCase
from django.urls import reverse

from analytics.models import Visit


class StorefrontProbeTests(TestCase):
    def test_catalogue_echoes_nonce_without_tracking_a_visit(self):
        nonce = "a" * 32
        response = self.client.get(
            reverse("shop:product_list"), {"_rasel_probe": nonce},
            HTTP_USER_AGENT="RaSel Storefront Monitor/1.0",
        )
        self.assertContains(response, "Tienda")
        self.assertEqual(response["X-RaSel-Probe"], nonce)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(Visit.objects.exists())

    def test_database_failure_breaks_catalogue_and_keeps_liveness(self):
        browser = Client(raise_request_exception=False)
        with patch("shop.views.Product.objects.filter", side_effect=OperationalError("test outage")):
            catalogue = browser.get(
                reverse("shop:product_list"), {"_rasel_probe": "a" * 32},
                HTTP_USER_AGENT="RaSel Storefront Monitor/1.0",
            )
            self.assertEqual(catalogue.status_code, 500)
            with self.assertNumQueries(0):
                self.assertContains(browser.get("/healthz"), "ok")
        self.assertNotIn("X-RaSel-Probe", catalogue)
