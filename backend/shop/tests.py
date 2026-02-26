from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Category, Product, Variant


class ProductListViewTests(TestCase):
	def setUp(self):
		category = Category.objects.create(name="Aceites")

		self.p1 = Product.objects.create(name="RaSel Clásico", category=category, is_active=True)
		Variant.objects.create(
			product=self.p1,
			name="250 ml",
			sku="RASEL-CL-250",
			price_ars=Decimal("120.00"),
			stock_qty=10,
			is_active=True,
		)

		self.p2 = Product.objects.create(name="RaSel Intenso", category=category, is_active=True)
		Variant.objects.create(
			product=self.p2,
			name="500 ml",
			sku="RASEL-IN-500",
			price_ars=Decimal("200.00"),
			stock_qty=0,
			is_active=True,
		)

		for idx in range(3, 15):
			product = Product.objects.create(name=f"Producto {idx}", category=category, is_active=True)
			Variant.objects.create(
				product=product,
				name="250 ml",
				sku=f"SKU-{idx}",
				price_ars=Decimal("100.00") + Decimal(idx),
				stock_qty=5,
				is_active=True,
			)

	def test_list_paginates(self):
		response = self.client.get(reverse("shop:product_list"))
		self.assertEqual(response.status_code, 200)
		self.assertIn("page_obj", response.context)
		self.assertEqual(len(response.context["products"]), 9)

	def test_search_filters_by_name(self):
		response = self.client.get(reverse("shop:product_list"), {"q": "Intenso"})
		self.assertEqual(response.status_code, 200)
		names = [product.name for product in response.context["products"]]
		self.assertIn("RaSel Intenso", names)
		self.assertNotIn("RaSel Clásico", names)

	def test_in_stock_filter(self):
		response = self.client.get(reverse("shop:product_list"), {"in_stock": "1", "q": "RaSel"})
		self.assertEqual(response.status_code, 200)
		names = [product.name for product in response.context["products"]]
		self.assertIn("RaSel Clásico", names)
		self.assertNotIn("RaSel Intenso", names)

	def test_sort_price_desc(self):
		response = self.client.get(reverse("shop:product_list"), {"sort": "price_desc"})
		self.assertEqual(response.status_code, 200)
		products = list(response.context["products"])
		self.assertGreaterEqual(products[0].min_price_ars, products[1].min_price_ars)
