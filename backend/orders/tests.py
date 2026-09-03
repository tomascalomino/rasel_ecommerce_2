from decimal import Decimal

from django.conf import settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse

from shipping.models import PickupPoint
from shipping.services import resolve_shipping
from shop.models import Category, Product, Variant
from django.contrib import admin as django_admin

from config.pricing import (
    discounted_amount,
    payment_discount,
    payment_discount_for_lines,
)

from .admin import OrderAdmin, cancel_and_restore_stock, mark_paid, mark_shipped
from .models import Order, OrderItem


def _request_with_messages():
    """Request mínimo con soporte de messages para invocar acciones de admin."""
    req = RequestFactory().post("/")
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


class PaymentPricingTests(TestCase):
    def test_minimum_five_percent_discount_rounds_price_down_to_fifty(self):
        self.assertEqual(
            payment_discount(Decimal("7400.00"), "transfer"),
            Decimal("400.00"),
        )
        self.assertEqual(
            discounted_amount(Decimal("7400.00")),
            Decimal("7000.00"),
        )
        self.assertEqual(discounted_amount(Decimal("13700.00")), Decimal("13000.00"))

    def test_line_discount_preserves_promotional_unit_prices(self):
        lines = [
            (Decimal("7400.00"), 2),
            (Decimal("13700.00"), 1),
        ]
        self.assertEqual(
            payment_discount_for_lines(lines, "transfer"),
            Decimal("1500.00"),
        )
        self.assertEqual(payment_discount_for_lines(lines, "mp"), Decimal("0.00"))

    def test_discount_applies_only_to_transfer_and_cash(self):
        subtotal = Decimal("1000.00")
        self.assertEqual(payment_discount(subtotal, "transfer"), Decimal("50.00"))
        self.assertEqual(payment_discount(subtotal, "cod"), Decimal("50.00"))
        self.assertEqual(payment_discount(subtotal, "mp"), Decimal("0.00"))


class TransferCheckoutTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="T-250",
            price_ars=Decimal("100.00"),
            compare_at_price_ars=Decimal("150.00"),
            promotion_label="Precio de lanzamiento",
            stock_qty=5,
            is_active=True,
        )

    def _add_to_cart(self, qty):
        session = self.client.session
        session["cart"] = {str(self.variant.id): {"qty": qty}}
        session.save()

    def _checkout_data(self):
        return {
            "full_name": "Test User",
            "email": "buyer@example.com",
            "phone": "",
            "delivery_method": "ship",
            "address_line": "Calle 1",
            "city": "CABA",
            "postal_code": "1000",
            "payment_method": "transfer",
        }

    def test_transfer_creates_order_decrements_stock_and_emails(self):
        self._add_to_cart(2)
        resp = self.client.post(reverse("orders:checkout"), self._checkout_data())
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.get()
        self.assertEqual(order.status, "pending")
        self.assertEqual(order.payment_method, "transfer")
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().unit_price, Decimal("100.00"))
        self.assertEqual(order.items.first().line_total, Decimal("200.00"))
        self.assertEqual(order.payment_discount_amount, Decimal("100.00"))
        quote = resolve_shipping("1000", subtotal=Decimal("200.00"))
        self.assertEqual(order.total_amount, Decimal("100.00") + quote.cost)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)

        # Email de "pedido reservado" al cliente (owner email no configurado en tests).
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("buyer@example.com", mail.outbox[0].to)
        body = mail.outbox[0].body
        self.assertIn("RESERVADO", body)
        self.assertIn(settings.WHATSAPP_NUMBER, body)
        self.assertIn("Descuento por transferencia/efectivo (mínimo 5%): -$100.00", body)
        self.assertNotIn("Precio de lanzamiento", body)
        # CABA/GBA: promesa de entrega en 48hs desde el pago.
        self.assertIn("48hs", body)

    def test_checkout_exposes_server_calculated_discount(self):
        self._add_to_cart(2)
        response = self.client.get(reverse("orders:checkout"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-offline-discount="100.00"')
        self.assertContains(response, "mínimo 5% de descuento")
        self.assertNotContains(response, "$ 150")
        self.assertNotContains(response, "Precio de lanzamiento")
        self.assertContains(response, 'id="payment-discount-row"')

    def test_transfer_interior_email_coordinates_by_whatsapp(self):
        # Interior (carrier_arranged): sin promesa de 48hs, la entrega se
        # coordina por el mismo WhatsApp del comprobante.
        self._add_to_cart(2)
        data = self._checkout_data()
        data.update({"postal_code": "5000", "city": "Córdoba"})
        resp = self.client.post(reverse("orders:checkout"), data)
        self.assertEqual(resp.status_code, 302)

        body = mail.outbox[0].body
        self.assertIn("se coordina por el mismo WhatsApp", body)
        self.assertNotIn("48hs", body)

    def test_transfer_blocks_when_insufficient_stock(self):
        self._add_to_cart(10)  # solo hay 5
        resp = self.client.post(reverse("orders:checkout"), self._checkout_data())

        self.assertEqual(resp.status_code, 200)  # re-render con error, no redirect
        self.assertEqual(Order.objects.count(), 0)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 5)  # stock intacto


class CodCheckoutTests(TestCase):
    """Efectivo a contraentrega: solo en zonas con cod_allowed (CABA/GBA)."""

    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="C-250",
            price_ars=Decimal("100.00"),
            stock_qty=5,
            is_active=True,
        )

    def _add_to_cart(self, qty):
        session = self.client.session
        session["cart"] = {str(self.variant.id): {"qty": qty}}
        session.save()

    def _checkout_data(self, postal_code="1425"):
        return {
            "full_name": "Test User",
            "email": "buyer@example.com",
            "phone": "",
            "delivery_method": "ship",
            "address_line": "Calle 1",
            "city": "CABA",
            "postal_code": postal_code,
            "payment_method": "cod",
        }

    def test_cod_creates_pending_order_in_eligible_zone(self):
        self._add_to_cart(2)
        resp = self.client.post(reverse("orders:checkout"), self._checkout_data("1425"))
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.get()
        self.assertRedirects(resp, reverse("orders:cod_info", args=[order.id]))
        self.assertEqual(order.status, "pending")
        self.assertEqual(order.payment_method, "cod")
        # El descuento mínimo se aplica a productos; el envío mantiene su costo completo.
        quote = resolve_shipping("1425", subtotal=Decimal("200.00"))
        self.assertEqual(order.payment_discount_amount, Decimal("100.00"))
        self.assertEqual(order.total_amount, Decimal("100.00") + quote.cost)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("buyer@example.com", mail.outbox[0].to)
        body = mail.outbox[0].body
        self.assertIn("efectivo al momento de la entrega", body)
        self.assertIn("Descuento por transferencia/efectivo (mínimo 5%): -$100.00", body)
        self.assertIn("48hs", body)
        self.assertIn(settings.WHATSAPP_NUMBER, body)

    def test_cod_rejected_in_national_zone(self):
        self._add_to_cart(2)
        resp = self.client.post(reverse("orders:checkout"), self._checkout_data("5000"))

        self.assertEqual(resp.status_code, 200)  # re-render con error de form
        self.assertContains(resp, "contraentrega")
        self.assertEqual(Order.objects.count(), 0)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 5)  # stock intacto


class PickupCheckoutTests(TestCase):
    """Retiro en punto de retiro: sin cargo, sin dirección, efectivo permitido."""

    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="P-250",
            price_ars=Decimal("100.00"),
            stock_qty=5,
            is_active=True,
        )
        # Los puntos se siembran en shipping.0008_seed_pickup_points.
        self.point = PickupPoint.objects.order_by("sort_order").first()

    def _add_to_cart(self, qty):
        session = self.client.session
        session["cart"] = {str(self.variant.id): {"qty": qty}}
        session.save()

    def _pickup_data(self, payment="transfer", **overrides):
        data = {
            "full_name": "Test User",
            "email": "buyer@example.com",
            "phone": "",
            "delivery_method": "pickup",
            "pickup_point": str(self.point.id),
            "payment_method": payment,
        }
        data.update(overrides)
        return data

    def test_pickup_transfer_creates_order_without_address(self):
        self._add_to_cart(2)
        resp = self.client.post(reverse("orders:checkout"), self._pickup_data("transfer"))

        order = Order.objects.get()
        self.assertRedirects(resp, reverse("orders:transfer_info", args=[order.id]))
        self.assertEqual(order.delivery_method, "pickup")
        self.assertEqual(order.pickup_point_id, self.point.id)
        self.assertIn(self.point.name, order.pickup_point_label)
        self.assertEqual(order.shipping_cost, Decimal("0.00"))
        self.assertEqual(order.payment_discount_amount, Decimal("100.00"))
        self.assertEqual(order.total_amount, Decimal("100.00"))
        self.assertEqual(order.address_line, "")
        self.assertEqual(order.postal_code, "")

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Retiro en", mail.outbox[0].body)
        self.assertIn("Sin cargo", mail.outbox[0].body)

    def test_pickup_cod_allowed_without_postal_code(self):
        # Con retiro, el efectivo no depende de la zona: no hay CP en el POST.
        self._add_to_cart(1)
        resp = self.client.post(reverse("orders:checkout"), self._pickup_data("cod"))

        order = Order.objects.get()
        self.assertRedirects(resp, reverse("orders:cod_info", args=[order.id]))
        self.assertEqual(order.payment_method, "cod")
        self.assertEqual(order.delivery_method, "pickup")
        self.assertEqual(order.payment_discount_amount, Decimal("50.00"))
        self.assertEqual(order.total_amount, Decimal("50.00"))
        body = mail.outbox[0].body
        self.assertIn("efectivo al momento del retiro", body)
        # Retiro: se coordina por WhatsApp, sin promesa de 48hs.
        self.assertIn(settings.WHATSAPP_NUMBER, body)
        self.assertNotIn("48hs", body)
        self.assertIn("Retiro", body)

    def test_pickup_requires_pickup_point(self):
        self._add_to_cart(1)
        resp = self.client.post(
            reverse("orders:checkout"), self._pickup_data("transfer", pickup_point="")
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Elegí el punto de retiro")
        self.assertEqual(Order.objects.count(), 0)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 5)

    def test_ship_still_requires_address(self):
        self._add_to_cart(1)
        resp = self.client.post(
            reverse("orders:checkout"),
            {
                "full_name": "Test User",
                "email": "buyer@example.com",
                "phone": "",
                "delivery_method": "ship",
                "payment_method": "transfer",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "obligatorio para envío a domicilio", count=3)
        self.assertEqual(Order.objects.count(), 0)


class OrderAdminActionTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="A-250",
            price_ars=Decimal("100.00"),
            stock_qty=5,
            is_active=True,
        )

    def _create_transfer_order(self, qty=2):
        session = self.client.session
        session["cart"] = {str(self.variant.id): {"qty": qty}}
        session.save()
        self.client.post(
            reverse("orders:checkout"),
            {
                "full_name": "Test User",
                "email": "buyer@example.com",
                "phone": "",
                "delivery_method": "ship",
                "address_line": "Calle 1",
                "city": "CABA",
                "postal_code": "1000",
                "payment_method": "transfer",
            },
        )
        return Order.objects.get()

    def _create_mp_order(self, *, status="paid", payment_status="approved", qty=2):
        order = Order.objects.create(
            full_name="MP User",
            email="mp@example.com",
            total_amount=Decimal("200.00"),
            payment_method="mp",
            status=status,
            payment_status=payment_status,
            mp_payment_id=f"PAY-{status}-{payment_status}",
            mp_status=payment_status,
            stock_deducted=True,
        )
        OrderItem.objects.create(
            order=order,
            variant=self.variant,
            product_name=self.product.name,
            variant_name=self.variant.name,
            unit_price=Decimal("100.00"),
            quantity=qty,
            line_total=Decimal("100.00") * qty,
        )
        self.variant.stock_qty -= qty
        self.variant.save(update_fields=["stock_qty"])
        return order

    def test_mark_paid_sets_status_and_emails_once(self):
        order = self._create_transfer_order()
        mail.outbox.clear()

        req = _request_with_messages()
        mark_paid(None, req, Order.objects.filter(id=order.id))

        order.refresh_from_db()
        self.assertEqual(order.status, "paid")
        self.assertEqual(len(mail.outbox), 1)  # "pago confirmado" al cliente

        # Idempotente: repetir la acción no reenvía el email.
        mark_paid(None, req, Order.objects.filter(id=order.id))
        self.assertEqual(len(mail.outbox), 1)

    def test_mark_shipped_sets_status_and_emails_once(self):
        order = self._create_transfer_order()
        mail.outbox.clear()

        req = _request_with_messages()
        mark_shipped(None, req, Order.objects.filter(id=order.id))

        order.refresh_from_db()
        self.assertEqual(order.status, "shipped")
        self.assertEqual(len(mail.outbox), 1)  # "pedido enviado" al cliente
        self.assertIn("en camino", mail.outbox[0].subject)
        self.assertIn("despachado", mail.outbox[0].body)

        # Idempotente: repetir la acción no reenvía el email.
        mark_shipped(None, req, Order.objects.filter(id=order.id))
        self.assertEqual(len(mail.outbox), 1)

    def test_status_change_in_admin_form_sends_emails(self):
        """Editar el estado desde el formulario del admin también avisa al cliente."""
        order = self._create_transfer_order()
        mail.outbox.clear()
        model_admin = OrderAdmin(Order, django_admin.site)
        req = _request_with_messages()

        order.status = "paid"
        model_admin.save_model(req, order, None, change=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Pago confirmado", mail.outbox[0].subject)

        order.status = "shipped"
        model_admin.save_model(req, order, None, change=True)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("en camino", mail.outbox[1].subject)

        # Guardar sin cambiar el estado no reenvía nada.
        model_admin.save_model(req, order, None, change=True)
        self.assertEqual(len(mail.outbox), 2)

    def test_owner_email_shows_customer_email_without_angle_brackets(self):
        """Brevo genera HTML desde el texto plano: <email> se pierde como etiqueta."""
        from .emails import _owner_body

        order = self._create_transfer_order()
        body = _owner_body(order)
        self.assertIn("Email: buyer@example.com", body)
        self.assertNotIn("<buyer@example.com>", body)

    def test_cancel_restores_stock_once(self):
        order = self._create_transfer_order(qty=2)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)  # 5 - 2

        req = _request_with_messages()
        cancel_and_restore_stock(None, req, Order.objects.filter(id=order.id))

        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(self.variant.stock_qty, 5)  # repuesto

        # Idempotente: no devuelve stock dos veces.
        cancel_and_restore_stock(None, req, Order.objects.filter(id=order.id))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 5)

    def test_mp_review_cannot_be_marked_paid_manually(self):
        order = self._create_mp_order(
            status="payment_review", payment_status="review"
        )
        mark_paid(None, _request_with_messages(), Order.objects.filter(id=order.id))
        order.refresh_from_db()
        self.assertEqual(order.status, "payment_review")
        self.assertEqual(order.payment_status, "review")

    def test_mp_approved_cannot_be_cancelled_as_if_it_were_a_refund(self):
        order = self._create_mp_order()
        cancel_and_restore_stock(
            None, _request_with_messages(), Order.objects.filter(id=order.id)
        )
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, "paid")
        self.assertFalse(order.stock_restored)
        self.assertEqual(self.variant.stock_qty, 3)

    def test_mp_refunded_unshipped_can_be_cancelled_and_restocked(self):
        order = self._create_mp_order(payment_status="refunded")
        cancel_and_restore_stock(
            None, _request_with_messages(), Order.objects.filter(id=order.id)
        )
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, "cancelled")
        self.assertTrue(order.stock_restored)
        self.assertEqual(self.variant.stock_qty, 5)

    def test_mp_refunded_shipped_waits_for_physical_return(self):
        order = self._create_mp_order(status="shipped", payment_status="refunded")
        cancel_and_restore_stock(
            None, _request_with_messages(), Order.objects.filter(id=order.id)
        )
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, "shipped")
        self.assertFalse(order.stock_restored)
        self.assertEqual(self.variant.stock_qty, 3)


class AdminRolesTests(TestCase):
    """Los grupos de roles se siembran vía post_migrate (config.admin.sync_roles)."""

    def test_operator_group_has_expected_permissions(self):
        from django.contrib.auth.models import Group

        operator = Group.objects.get(name="Operador")
        codenames = set(operator.permissions.values_list("codename", flat=True))
        # Gestiona el día a día...
        self.assertIn("change_order", codenames)
        self.assertIn("change_variant", codenames)
        self.assertIn("add_product", codenames)
        self.assertIn("change_shippingzone", codenames)
        # ...pero no borra datos críticos ni administra usuarios.
        self.assertNotIn("delete_order", codenames)
        self.assertNotIn("delete_product", codenames)
        self.assertNotIn("add_user", codenames)

    def test_readonly_group_only_views(self):
        from django.contrib.auth.models import Group

        readonly = Group.objects.get(name="Solo lectura")
        codenames = set(readonly.permissions.values_list("codename", flat=True))
        self.assertIn("view_order", codenames)
        self.assertTrue(
            all(codename.startswith("view_") for codename in codenames), codenames
        )

    def test_order_actions_require_change_permission(self):
        self.assertEqual(mark_paid.allowed_permissions, ["change"])
        self.assertEqual(cancel_and_restore_stock.allowed_permissions, ["change"])
