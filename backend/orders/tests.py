from decimal import Decimal

from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse

from shop.models import Category, Product, Variant
from .admin import mark_paid, cancel_and_restore_stock
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

    def test_transfer_blocks_when_insufficient_stock(self):
        self._add_to_cart(10)  # solo hay 5
        resp = self.client.post(reverse("orders:checkout"), self._checkout_data())

        self.assertEqual(resp.status_code, 200)  # re-render con error, no redirect
        self.assertEqual(Order.objects.count(), 0)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 5)  # stock intacto


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
