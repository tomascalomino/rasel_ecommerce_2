from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from shop.models import Product, Variant


class CartAddViewTests(TestCase):
    def setUp(self):
        product = Product.objects.create(name="Aceite de prueba", is_active=True)
        self.variant = Variant.objects.create(
            product=product,
            name="500 ml",
            sku="CART-500",
            price_ars=Decimal("7400.00"),
            compare_at_price_ars=Decimal("9000.00"),
            promotion_label="Precio de lanzamiento",
            stock_qty=5,
            is_active=True,
        )

    def test_adds_product_and_offers_checkout_or_safe_origin_without_javascript(self):
        response = self.client.post(
            reverse("cart:add"),
            {
                "variant_id": self.variant.pk,
                "qty": 2,
                "next": "/shop/?sort=price_asc",
            },
        )

        self.assertRedirects(response, reverse("cart:added"), fetch_redirect_response=False)
        confirmation = self.client.get(response.url)
        self.assertContains(confirmation, 'href="/shop/?sort=price_asc"')
        self.assertContains(confirmation, 'href="' + reverse("orders:checkout") + '"')
        self.assertContains(confirmation, "Cantidad agregada: 2")
        self.assertContains(confirmation, "Seguir comprando")
        self.assertIn("no-store", confirmation["Cache-Control"])
        self.assertRedirects(self.client.get(response.url), reverse("cart:detail"))
        self.assertEqual(
            self.client.session["cart"][str(self.variant.pk)]["qty"],
            2,
        )

    def test_rejects_external_return_url(self):
        response = self.client.post(
            reverse("cart:add"),
            {
                "variant_id": self.variant.pk,
                "qty": 1,
                "next": "https://example.com/phishing",
            },
        )

        self.assertRedirects(response, reverse("cart:added"), fetch_redirect_response=False)
        confirmation = self.client.get(response.url)
        self.assertEqual(confirmation.context["continue_url"], reverse("shop:product_list"))
        self.assertNotContains(confirmation, "https://example.com/phishing")

    def test_ajax_confirmation_counts_existing_cart_and_does_not_queue_flash(self):
        self.client.post(reverse("cart:add"), {"variant_id": self.variant.pk, "qty": 1})
        response = self.client.post(
            reverse("cart:add"),
            {"variant_id": self.variant.pk, "qty": 2, "next": "/shop/"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cart_quantity"], 3)
        self.assertIn("Cantidad agregada: 2", payload["html"])
        self.assertIn("Aceite de prueba", payload["html"])
        self.assertIn("500 ml", payload["html"])
        self.assertEqual(payload["meta_events"], [])
        self.assertNotIn("_messages", self.client.cookies)
        self.assertIn("no-store", response["Cache-Control"])
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 5)

    def test_ajax_errors_do_not_modify_cart(self):
        for data in (
            {"variant_id": 999999, "qty": 1},
            {"variant_id": self.variant.pk, "qty": 0},
            {"variant_id": self.variant.pk, "qty": "invalid"},
            {"variant_id": self.variant.pk, "qty": 6},
        ):
            with self.subTest(data=data):
                response = self.client.post(reverse("cart:add"), data, HTTP_ACCEPT="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
                self.assertNotIn("cart", self.client.session)

    def test_stock_limit_includes_previously_added_units(self):
        self.client.post(reverse("cart:add"), {"variant_id": self.variant.pk, "qty": 4})
        response = self.client.post(
            reverse("cart:add"), {"variant_id": self.variant.pk, "qty": 2},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("stock suficiente", response.json()["error"])
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)]["qty"], 4)

    def test_confirmation_escapes_product_text(self):
        self.variant.name = '<script>alert("variant")</script>'
        self.variant.save()
        response = self.client.post(
            reverse("cart:add"), {"variant_id": self.variant.pk}, HTTP_ACCEPT="application/json",
        )
        self.assertNotIn("<script>", response.json()["html"])
        self.assertIn("&lt;script&gt;", response.json()["html"])

    def test_cart_uses_only_the_sale_price(self):
        session = self.client.session
        session["cart"] = {str(self.variant.pk): {"qty": 1}}
        session.save()

        response = self.client.get(reverse("cart:detail"))

        self.assertContains(response, "$ 7.400")
        self.assertNotContains(response, "$ 9.000")
        self.assertNotContains(response, "Precio de lanzamiento")
        cart_item = next(iter(response.context["cart"].items()))
        self.assertEqual(cart_item.unit_price, Decimal("7400.00"))
