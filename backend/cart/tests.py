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

    def test_adds_product_and_returns_to_safe_origin(self):
        response = self.client.post(
            reverse("cart:add"),
            {
                "variant_id": self.variant.pk,
                "qty": 2,
                "next": "/shop/?sort=price_asc",
            },
        )

        self.assertRedirects(
            response,
            "/shop/?sort=price_asc",
            fetch_redirect_response=False,
        )
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

        self.assertRedirects(response, reverse("cart:detail"))

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
