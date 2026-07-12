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

from .admin import OrderAdmin, cancel_and_restore_stock, mark_paid, mark_shipped
from .models import Order


def _request_with_messages():
    """Request mínimo con soporte de messages para invocar acciones de admin."""
    req = RequestFactory().post("/")
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


class TransferCheckoutTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Aceites")
        self.product = Product.objects.create(name="RaSel", category=self.category, is_active=True)
        self.variant = Variant.objects.create(
            product=self.product,
            name="250 ml",
            sku="T-250",
            price_ars=Decimal("100.00"),
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

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)

        # Email de "pedido reservado" al cliente (owner email no configurado en tests).
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("buyer@example.com", mail.outbox[0].to)
        body = mail.outbox[0].body
        self.assertIn("RESERVADO", body)
        self.assertIn(settings.WHATSAPP_NUMBER, body)
        # CABA/AMBA: promesa de entrega en 48hs desde el pago.
        self.assertIn("48hs", body)

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
    """Efectivo a contraentrega: solo en zonas con cod_allowed (CABA/AMBA)."""

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
        # Sin recargo: total = subtotal + envío resuelto en servidor.
        quote = resolve_shipping("1425", subtotal=Decimal("200.00"))
        self.assertEqual(order.total_amount, Decimal("200.00") + quote.cost)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("buyer@example.com", mail.outbox[0].to)
        body = mail.outbox[0].body
        self.assertIn("efectivo al momento de la entrega", body)
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
        self.assertEqual(order.total_amount, Decimal("200.00"))  # solo subtotal
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
