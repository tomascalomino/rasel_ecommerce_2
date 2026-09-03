from decimal import Decimal

from django.contrib import admin as django_admin
from django.core.exceptions import ValidationError
from django.contrib.staticfiles import finders
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .admin import VariantAdmin, VariantInline
from .models import Category, Product, Variant


class VariantPromotionTests(TestCase):
	def setUp(self):
		self.product = Product.objects.create(name="Aceite lanzamiento", is_active=True)

	def test_regular_price_is_optional_and_accepts_a_higher_value(self):
		without_comparison = Variant(
			product=self.product,
			name="250 ml",
			sku="LAUNCH-250",
			price_ars=Decimal("7400.00"),
		)
		without_comparison.full_clean()

		with_comparison = Variant(
			product=self.product,
			name="500 ml",
			sku="LAUNCH-500",
			price_ars=Decimal("9000.00"),
			compare_at_price_ars=Decimal("11000.00"),
			promotion_label="Precio de lanzamiento",
		)
		with_comparison.full_clean()
		self.assertEqual(with_comparison.promotion_label, "Precio de lanzamiento")

	def test_regular_price_and_promotion_label_must_be_completed_together(self):
		for compare_at_price, label, message in (
			(
				Decimal("11000.00"),
				"",
				"Ingresá el texto de promoción junto con el precio regular.",
			),
			(
				None,
				"Black Friday",
				"Ingresá el precio regular junto con el texto de promoción.",
			),
		):
			with self.subTest(compare_at_price=compare_at_price, label=label):
				variant = Variant(
					product=self.product,
					name=f"Presentación {label or 'sin texto'}",
					sku=f"PAIR-{label or 'EMPTY'}",
					price_ars=Decimal("9000.00"),
					compare_at_price_ars=compare_at_price,
					promotion_label=label,
				)
				with self.assertRaisesMessage(ValidationError, message):
					variant.full_clean()

	def test_promotion_label_is_trimmed_without_changing_its_case(self):
		variant = Variant(
			product=self.product,
			name="750 ml",
			sku="PROMO-750",
			price_ars=Decimal("9000.00"),
			compare_at_price_ars=Decimal("11000.00"),
			promotion_label="  Black Friday  ",
		)

		variant.full_clean()

		self.assertEqual(variant.promotion_label, "Black Friday")

	def test_regular_price_must_be_greater_than_the_sale_price(self):
		for regular_price in (Decimal("7400.00"), Decimal("7000.00")):
			with self.subTest(regular_price=regular_price):
				variant = Variant(
					product=self.product,
					name=f"Presentación {regular_price}",
					sku=f"INVALID-{regular_price}",
					price_ars=Decimal("7400.00"),
					compare_at_price_ars=regular_price,
					promotion_label="Precio de lanzamiento",
				)
				with self.assertRaisesMessage(
					ValidationError,
					"El precio regular debe ser mayor al precio de venta.",
				):
					variant.full_clean()

	def test_database_constraint_rejects_an_invalid_regular_price(self):
		with self.assertRaises(IntegrityError), transaction.atomic():
			Variant.objects.create(
				product=self.product,
				name="1 litro",
				sku="INVALID-DB",
				price_ars=Decimal("10000.00"),
				compare_at_price_ars=Decimal("9000.00"),
				promotion_label="Black Friday",
			)

	def test_database_constraint_rejects_unpaired_promotion_fields(self):
		invalid_values = (
			(Decimal("11000.00"), ""),
			(None, "Black Friday"),
		)
		for index, (compare_at_price, label) in enumerate(invalid_values):
			with self.subTest(compare_at_price=compare_at_price, label=label):
				with self.assertRaises(IntegrityError), transaction.atomic():
					Variant.objects.create(
						product=self.product,
						name=f"Inválida {index}",
						sku=f"PAIR-DB-{index}",
						price_ars=Decimal("9000.00"),
						compare_at_price_ars=compare_at_price,
						promotion_label=label,
					)

	def test_admin_exposes_promotion_fields_as_adjacent_editable_fields(self):
		variant_admin = VariantAdmin(Variant, django_admin.site)
		self.assertEqual(
			variant_admin.list_display[3:6],
			("price_ars", "compare_at_price_ars", "promotion_label"),
		)
		self.assertEqual(
			variant_admin.list_editable[:3],
			("price_ars", "compare_at_price_ars", "promotion_label"),
		)
		self.assertEqual(
			VariantInline.fields[2:5],
			("price_ars", "compare_at_price_ars", "promotion_label"),
		)


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
		self.assertEqual(len(response.context["page_obj"]), 9)

	def test_search_filters_by_name(self):
		response = self.client.get(reverse("shop:product_list"), {"q": "Intenso"})
		self.assertEqual(response.status_code, 200)
		names = [product.name for product in response.context["page_obj"]]
		self.assertIn("RaSel Intenso", names)
		self.assertNotIn("RaSel Clásico", names)

	def test_in_stock_filter(self):
		response = self.client.get(reverse("shop:product_list"), {"in_stock": "1", "q": "RaSel"})
		self.assertEqual(response.status_code, 200)
		names = [product.name for product in response.context["page_obj"]]
		self.assertIn("RaSel Clásico", names)
		self.assertNotIn("RaSel Intenso", names)

	def test_sort_price_desc(self):
		response = self.client.get(reverse("shop:product_list"), {"sort": "price_desc"})
		self.assertEqual(response.status_code, 200)
		products = list(response.context["page_obj"])
		self.assertGreaterEqual(products[0].min_price_ars, products[1].min_price_ars)

	def test_offline_discount_is_visible_on_product_detail(self):
		product_response = self.client.get(
			reverse("shop:product_detail", args=[self.p1.slug])
		)
		self.assertContains(product_response, "MÍN. 5% OFF")
		self.assertContains(product_response, "transferencia o efectivo")
		self.assertContains(product_response, "$ 100")
		self.assertContains(product_response, 'data-offline-price="100.00"')

	@override_settings(MP_CHECKOUT_ENABLED=True)
	def test_mp_brand_is_visible_on_home_and_product_when_checkout_is_enabled(self):
		for url in (reverse("home"), reverse("shop:product_detail", args=[self.p1.slug])):
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertContains(response, "mercado-pago-horizontal.svg")
				self.assertContains(response, "Hasta 6 cuotas")
				if url == reverse("home"):
					self.assertContains(response, "Pagá como prefieras")
					self.assertNotContains(response, "Pagá como preferís")

	@override_settings(MP_CHECKOUT_ENABLED=False)
	def test_mp_brand_is_hidden_when_checkout_is_disabled(self):
		for url in (reverse("home"), reverse("shop:product_detail", args=[self.p1.slug])):
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertNotContains(response, "mercado-pago-horizontal.svg")

	@override_settings(WHATSAPP_NUMBER="1162002357", MP_CHECKOUT_ENABLED=True)
	def test_home_promotes_wholesale_contact_by_whatsapp(self):
		response = self.client.get(reverse("home"))
		content = response.content.decode()

		self.assertContains(response, "¿Comprás para tu comercio?")
		self.assertContains(
			response,
			"Precios preferenciales para compras mayoristas según la cantidad que necesites.",
		)
		self.assertContains(
			response,
			'href="https://wa.me/5491162002357?text=Hola%20RaSel%2C%20quisiera%20consultar%20por%20compras%20mayoristas%20y%20precios%20preferenciales."',
		)
		self.assertContains(
			response,
			'<span class="wholesale-home-banner-cta-full">Consultar por WhatsApp</span>',
			html=True,
		)
		self.assertContains(
			response,
			'<span class="wholesale-home-banner-cta-mobile">WhatsApp</span>',
			html=True,
		)
		self.assertLess(content.index("Nuestra selección"), content.index("Pagá como prefieras"))
		self.assertLess(content.index("Pagá como prefieras"), content.index("¿Comprás para tu comercio?"))

	@override_settings(WHATSAPP_NUMBER="")
	def test_home_wholesale_banner_falls_back_to_contact(self):
		response = self.client.get(reverse("home"))

		self.assertContains(
			response,
			'<a class="btn btn-primary btn-small wholesale-home-banner-cta" href="/contact/">Contactanos</a>',
			html=True,
		)
		self.assertNotContains(response, "Consultar por WhatsApp")

	def test_contact_mentions_wholesale_purchases(self):
		response = self.client.get(reverse("contact"))

		self.assertContains(
			response,
			"¿Tenés dudas, querés hacer un pedido especial o consultar por compras mayoristas?",
		)


class ProductCardPricingTests(TestCase):
	def setUp(self):
		category = Category.objects.create(name="Aceites premium")
		self.primary = Product.objects.create(
			name="AOVE Clásico",
			category=category,
			is_active=True,
		)
		Variant.objects.create(
			product=self.primary,
			name="500 ml",
			sku="AOVE-500",
			price_ars=Decimal("7400.00"),
			compare_at_price_ars=Decimal("10000.00"),
			promotion_label="Precio de lanzamiento",
			stock_qty=2,
			is_active=True,
		)
		Variant.objects.create(
			product=self.primary,
			name="750 ml",
			sku="AOVE-750",
			price_ars=Decimal("9000.00"),
			compare_at_price_ars=Decimal("9500.00"),
			promotion_label="Black Friday",
			stock_qty=3,
			is_active=True,
		)
		Variant.objects.create(
			product=self.primary,
			name="1 litro",
			sku="AOVE-1000",
			price_ars=Decimal("13000.00"),
			stock_qty=2,
			is_active=True,
		)
		Variant.objects.create(
			product=self.primary,
			name="Variante retirada",
			sku="AOVE-INACTIVA",
			price_ars=Decimal("100.00"),
			stock_qty=10,
			is_active=False,
		)

		self.out_of_stock = Product.objects.create(
			name="Pack sin stock",
			category=category,
			is_active=True,
		)
		Variant.objects.create(
			product=self.out_of_stock,
			name="Pack x2",
			sku="PACK-X2",
			price_ars=Decimal("2000.00"),
			stock_qty=0,
			is_active=True,
		)

		self.without_variants = Product.objects.create(
			name="Sin variantes",
			category=category,
			is_active=True,
		)
		Variant.objects.create(
			product=self.without_variants,
			name="Presentación retirada",
			sku="SIN-ACTIVAS",
			price_ars=Decimal("500.00"),
			stock_qty=10,
			is_active=False,
		)

	def test_home_and_catalog_show_exact_offline_price_for_active_minimum(self):
		for url, context_name in (
			(reverse("home"), "featured_products"),
			(reverse("shop:product_list"), "page_obj"),
		):
			with self.subTest(url=url):
				response = self.client.get(url)
				products = {product.pk: product for product in response.context[context_name]}

				self.assertEqual(products[self.primary.pk].min_price_ars, Decimal("7400.00"))
				self.assertEqual(
					products[self.primary.pk].compare_at_price_ars,
					Decimal("10000.00"),
				)
				self.assertEqual(
					products[self.primary.pk].promotion_label,
					"Precio de lanzamiento",
				)
				self.assertEqual(products[self.primary.pk].offline_price_ars, Decimal("7000.00"))
				self.assertTrue(products[self.primary.pk].in_stock)
				self.assertEqual(
					products[self.out_of_stock.pk].offline_price_ars,
					Decimal("1900.00"),
				)
				self.assertFalse(products[self.out_of_stock.pk].in_stock)
				self.assertIsNone(products[self.without_variants.pk].offline_price_ars)
				self.assertContains(response, 'class="product-card-offline-price"', count=2)
				self.assertContains(response, 'class="product-card-compare-price"', count=1)
				self.assertContains(response, "Precio de lanzamiento")
				self.assertContains(response, "$ 10.000")
				self.assertContains(response, "$ 7.000")
				self.assertContains(response, "$ 1.900")
				self.assertContains(response, "con transferencia o efectivo")

	def test_related_product_cards_show_offline_price(self):
		response = self.client.get(
			reverse("shop:product_detail", args=[self.primary.slug])
		)
		related = {product.pk: product for product in response.context["related_products"]}

		self.assertEqual(related[self.out_of_stock.pk].offline_price_ars, Decimal("1900.00"))
		self.assertFalse(related[self.out_of_stock.pk].in_stock)
		self.assertIsNone(related[self.without_variants.pk].offline_price_ars)
		self.assertContains(response, 'class="product-card-offline-price"', count=1)
		self.assertContains(response, "$ 1.900")

	def test_quick_add_is_available_on_home_catalog_and_related_cards(self):
		for url in (reverse("home"), reverse("shop:product_list")):
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertContains(
					response,
					f'data-quick-add-open="quick-add-{self.primary.pk}"',
				)
				self.assertContains(response, f'id="quick-add-{self.primary.pk}"')
				self.assertContains(response, 'data-price="7400.00"')
				self.assertContains(response, 'data-compare-at-price="10000.00"')
				self.assertContains(response, 'data-compare-at-price="9500.00"')
				self.assertContains(response, 'data-compare-at-price=""')
				self.assertContains(response, 'data-promotion-label="Precio de lanzamiento"')
				self.assertContains(response, 'data-promotion-label="Black Friday"')
				self.assertContains(response, 'data-promotion-label=""')
				self.assertContains(response, 'data-offline-price="7000.00"')
				self.assertContains(response, "Agregar al carrito")
				self.assertNotContains(response, "Variante retirada")
				self.assertNotContains(
					response,
					f'data-quick-add-open="quick-add-{self.out_of_stock.pk}"',
				)

		response = self.client.get(
			reverse("shop:product_detail", args=[self.out_of_stock.slug])
		)
		self.assertContains(
			response,
			f'data-quick-add-open="quick-add-{self.primary.pk}"',
		)
		self.assertContains(response, f'id="quick-add-{self.primary.pk}"')

	def test_detail_exposes_promotion_fields_for_each_variant(self):
		response = self.client.get(
			reverse("shop:product_detail", args=[self.primary.slug])
		)

		self.assertContains(response, 'id="product-promotion-comparison"')
		self.assertContains(response, 'id="product-promotion-label"')
		self.assertContains(response, 'id="product-compare-at-price"')
		self.assertContains(response, "$ 10.000")
		self.assertContains(response, 'data-compare-at-price="10000.00"')
		self.assertContains(response, 'data-compare-at-price="9500.00"')
		self.assertContains(response, 'data-compare-at-price=""')
		self.assertContains(response, 'data-promotion-label="Precio de lanzamiento"')
		self.assertContains(response, 'data-promotion-label="Black Friday"')
		self.assertContains(response, 'data-promotion-label=""')

	def test_quick_add_hides_variant_selector_when_only_one_is_available(self):
		product = Product.objects.create(name="Única presentación", is_active=True)
		variant = Variant.objects.create(
			product=product,
			name="250 ml",
			sku="UNICA-250",
			price_ars=Decimal("3500.00"),
			stock_qty=4,
			is_active=True,
		)

		response = self.client.get(reverse("shop:product_list"))

		self.assertContains(response, f'id="quick-add-{product.pk}"')
		self.assertContains(
			response,
			f'<input type="hidden" name="variant_id" value="{variant.pk}">',
			html=True,
		)
		self.assertNotContains(response, f'id="quick-add-variant-{product.pk}"')

	def test_home_no_longer_shows_general_offline_discount_banner(self):
		response = self.client.get(reverse("home"))

		self.assertNotContains(response, "offline-home-banner")
		self.assertNotContains(response, "Ahorrá pagando por transferencia o efectivo")


class HomeProductOrderTests(TestCase):
	def test_bottles_are_selected_before_packs(self):
		for name in (
			"Pack 9x250ml Blend",
			"Botella 500ml RaSel",
			"Pack 6x500ml Blend",
			"Botella 250ml RaSel",
		):
			Product.objects.create(name=name, is_active=True)

		response = self.client.get(reverse("home"))

		self.assertEqual(
			[product.name for product in response.context["featured_products"]],
			[
				"Botella 250ml RaSel",
				"Botella 500ml RaSel",
				"Pack 6x500ml Blend",
			],
		)


class PublicNavigationCopyTests(TestCase):
	def test_home_uses_simplified_origin_and_requested_navigation_order(self):
		response = self.client.get(reverse("home"))
		content = response.content.decode()
		hero = content.split('<section class="hero-full"', 1)[1].split("</section>", 1)[0]

		self.assertContains(response, "<span>Andalgalá, Catamarca</span>", html=True)
		self.assertNotContains(response, "Blend · Andalgalá, Catamarca")
		self.assertNotContains(response, 'class="pill pill-meta"')
		self.assertLess(content.index("Quiénes Somos"), content.index("Conservación"))
		self.assertIn("Aceite de oliva premium.", hero)
		self.assertNotIn("pensado para uso diario", hero)
		self.assertIn("Acidez menor a 0,3%", hero)
		self.assertContains(response, "img/rasel-logo-header.webp")
		self.assertNotContains(response, "img/rasel-escudo.webp")

	def test_header_search_uses_one_accessible_control_and_unique_id(self):
		for index in range(5):
			Product.objects.create(name=f"Blend {index}", is_active=True)

		response = self.client.get(reverse("shop:product_list"), {"q": "Blend"})
		content = response.content.decode()

		self.assertEqual(content.count('id="header-search"'), 1)
		self.assertEqual(content.count('id="q"'), 1)
		self.assertContains(response, 'for="header-search"')
		self.assertContains(response, 'value="Blend" placeholder="Buscar productos"')
		self.assertContains(
			response,
			'class="search-submit" type="submit" aria-label="Buscar productos"',
		)
		self.assertNotContains(response, 'class="btn btn-small" type="submit"')


class SocialMetadataTests(TestCase):
	def test_home_uses_real_product_social_cover(self):
		response = self.client.get(reverse("home"))

		self.assertContains(response, "img/og-product-2026.jpg", count=2)
		self.assertNotContains(response, "img/og-cover.jpg")
		self.assertContains(response, '<meta property="og:image:type" content="image/jpeg">', html=True)
		self.assertContains(response, '<meta property="og:image:width" content="1200">', html=True)
		self.assertContains(response, '<meta property="og:image:height" content="800">', html=True)
		self.assertContains(
			response,
			'<meta property="og:image:alt" content="Botella de aceite de oliva virgen extra RaSel junto a un cuenco de aceite">',
			html=True,
		)

	def test_social_cover_is_the_documented_jpeg_size(self):
		asset_path = finders.find("img/og-product-2026.jpg")

		self.assertIsNotNone(asset_path)
		self.assertIsNone(finders.find("img/og-cover.jpg"))
		with Image.open(asset_path) as image:
			self.assertEqual(image.format, "JPEG")
			self.assertEqual(image.size, (1200, 800))
