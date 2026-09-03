import hashlib
import hmac
import json
import threading
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from shipping.models import PickupPoint
from shop.models import Category, Product, Variant

from .admin import reconcile_expired_reservations
from .mercadopago import MercadoPagoError, validate_webhook_signature
from .models import PaymentDraft, PaymentEvent
from .services import process_payment, release_reserved_stock


MP_TEST_SETTINGS = {
    "MP_CHECKOUT_ENABLED": True,
    "MP_ENVIRONMENT": "test",
    "MP_ACCESS_TOKEN": "TEST-token-placeholder",
    "MP_WEBHOOK_SECRET": "TEST-secret-placeholder",
    "MP_MAX_INSTALLMENTS": 6,
    "MP_RESERVATION_MINUTES": 30,
    "MP_PENDING_MAX_HOURS": 48,
    "PAYMENT_ALERT_EMAIL": "alerts@example.com",
    "SITE_URL": "https://staging.example.com",
    "ORDER_NOTIFICATION_EMAIL": "",
    "BREVO_API_KEY": "",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


@override_settings(**MP_TEST_SETTINGS)
class MercadoPagoIntegrationTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aceites")
        product = Product.objects.create(name="RaSel", category=category, is_active=True)
        self.variant = Variant.objects.create(
            product=product,
            name="250 ml",
            sku="RASEL-250-MP",
            price_ars=Decimal("500.00"),
            stock_qty=1,
            is_active=True,
        )
        now = timezone.now()
        self.draft = PaymentDraft.objects.create(
            full_name="Test User",
            email="buyer@example.com",
            phone="",
            address_line="Calle 123",
            city="CABA",
            postal_code="1000",
            shipping_cost=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
            items=[
                {
                    "variant_id": self.variant.id,
                    "sku": self.variant.sku,
                    "product_name": product.name,
                    "variant_name": self.variant.name,
                    "unit_price": "500.00",
                    "quantity": 2,
                    "line_total": "1000.00",
                }
            ],
            state="reserved",
            stock_reserved_at=now,
            reservation_expires_at=now + timedelta(minutes=30),
            mp_collector_id="445566",
        )
        self.webhook_url = reverse("payments:webhook")

    def payment(self, status="approved", payment_id="PAY-1", **overrides):
        data = {
            "id": payment_id,
            "status": status,
            "status_detail": "accredited" if status == "approved" else "",
            "external_reference": str(self.draft.token),
            "metadata": {"draft_token": str(self.draft.token)},
            "transaction_amount": 1000,
            "transaction_amount_refunded": 0,
            "currency_id": "ARS",
            "collector_id": 445566,
            "live_mode": False,
        }
        data.update(overrides)
        return data

    def test_official_sdk_signature_validator_accepts_valid_and_rejects_invalid(self):
        data_id = "123456"
        request_id = "request-signature"
        timestamp = "1704908010"
        manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
        digest = hmac.new(
            MP_TEST_SETTINGS["MP_WEBHOOK_SECRET"].encode(),
            manifest.encode(),
            hashlib.sha256,
        ).hexdigest()
        signature = f"ts={timestamp},v1={digest}"
        self.assertTrue(
            validate_webhook_signature(
                signature,
                request_id,
                data_id,
                MP_TEST_SETTINGS["MP_WEBHOOK_SECRET"],
            )
        )
        self.assertFalse(
            validate_webhook_signature(
                "ts=1,v1=invalid",
                request_id,
                data_id,
                MP_TEST_SETTINGS["MP_WEBHOOK_SECRET"],
            )
        )

    def post_webhook(self, payment, *, notification_id="evt-1", signature_valid=True):
        payload = {
            "id": notification_id,
            "type": "payment",
            "action": "payment.updated",
            "data": {"id": str(payment["id"])},
        }
        with patch(
            "payments.views.validate_webhook_signature", return_value=signature_valid
        ), patch("payments.views.get_payment", return_value=payment):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.post(
                    f"{self.webhook_url}?data.id={payment['id']}",
                    data=json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_SIGNATURE="ts=1,v1=test",
                    HTTP_X_REQUEST_ID="request-1",
                )

    def test_start_is_post_only_session_bound_and_idempotent(self):
        url = reverse("payments:start", kwargs={"draft_id": self.draft.token})
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 403)

        session = self.client.session
        session["active_payment_draft"] = str(self.draft.token)
        session.save()
        preference = {
            "id": "pref-1",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect",
            "collector_id": 445566,
        }
        with patch("payments.services.create_preference", return_value=preference) as create:
            response = self.client.post(url)
            retry_response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(retry_response.status_code, 302)
        create.assert_called_once()
        payload = create.call_args.args[0]
        self.assertEqual(payload["external_reference"], str(self.draft.token))
        self.assertEqual(payload["metadata"]["draft_token"], str(self.draft.token))
        self.assertEqual(payload["payment_methods"]["installments"], 6)
        self.assertEqual(
            payload["payment_methods"]["excluded_payment_types"], [{"id": "ticket"}]
        )
        self.assertEqual(payload["auto_return"], "approved")
        self.assertEqual(
            payload["notification_url"],
            "https://staging.example.com/payments/webhook/?source_news=webhooks",
        )
        self.assertNotIn("binary_mode", payload)

    @patch("payments.admin.messages.success")
    @patch("payments.admin.search_payments", return_value=[])
    def test_admin_releases_expired_reservation_only_after_provider_search(
        self, search, success
    ):
        self.draft.state = "preference_created"
        self.draft.reservation_expires_at = timezone.now() - timedelta(minutes=1)
        self.draft.save(update_fields=["state", "reservation_expires_at"])

        reconcile_expired_reservations(
            None,
            object(),
            PaymentDraft.objects.filter(pk=self.draft.pk),
        )

        self.draft.refresh_from_db()
        self.variant.refresh_from_db()
        search.assert_called_once_with(str(self.draft.token))
        self.assertEqual(self.draft.state, "expired")
        self.assertIsNotNone(self.draft.stock_released_at)
        self.assertEqual(self.variant.stock_qty, 3)
        success.assert_called_once()

    @patch("payments.admin.messages.warning")
    @patch(
        "payments.admin.search_payments",
        side_effect=MercadoPagoError("temporary"),
    )
    def test_admin_keeps_stock_when_provider_lookup_fails(self, search, warning):
        self.draft.state = "preference_created"
        self.draft.reservation_expires_at = timezone.now() - timedelta(minutes=1)
        self.draft.save(update_fields=["state", "reservation_expires_at"])

        reconcile_expired_reservations(
            None,
            object(),
            PaymentDraft.objects.filter(pk=self.draft.pk),
        )

        self.draft.refresh_from_db()
        self.variant.refresh_from_db()
        search.assert_called_once_with(str(self.draft.token))
        self.assertIsNone(self.draft.stock_released_at)
        self.assertEqual(self.variant.stock_qty, 1)
        self.assertEqual(self.draft.processing_error, "temporary")
        warning.assert_called_once()

    def test_checkout_reserves_stock_before_redirecting_to_mercado_pago(self):
        variant = Variant.objects.create(
            product=self.variant.product,
            name="500 ml",
            sku="RASEL-CHECKOUT-MP",
            price_ars=Decimal("800.00"),
            compare_at_price_ars=Decimal("1200.00"),
            promotion_label="Black Friday",
            stock_qty=3,
        )
        point = PickupPoint.objects.filter(is_active=True).first()
        if point is None:
            point = PickupPoint.objects.create(name="Staging", address="Calle Falsa 1")
        session = self.client.session
        session["cart"] = {str(variant.id): {"qty": 2}}
        session.save()
        preference = {
            "id": "pref-checkout",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect",
            "collector_id": 445566,
        }
        with patch("payments.services.create_preference", return_value=preference):
            response = self.client.post(
                reverse("orders:checkout"),
                {
                    "full_name": "Checkout MP",
                    "email": "checkout@example.com",
                    "phone": "",
                    "delivery_method": "pickup",
                    "pickup_point": point.id,
                    "address_line": "",
                    "address_extra": "",
                    "city": "",
                    "postal_code": "",
                    "payment_method": "mp",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, preference["init_point"])
        draft = PaymentDraft.objects.exclude(pk=self.draft.pk).get()
        variant.refresh_from_db()
        self.assertEqual(draft.state, "preference_created")
        self.assertEqual(draft.total_amount, Decimal("1600.00"))
        self.assertEqual(draft.items[0]["unit_price"], "800.00")
        self.assertEqual(draft.items[0]["line_total"], "1600.00")
        self.assertEqual(variant.stock_qty, 1)
        self.assertEqual(
            self.client.session["active_payment_draft"], str(draft.token)
        )

    def test_invalid_signature_writes_nothing_and_does_not_query_api(self):
        payment = self.payment()
        with patch("payments.views.get_payment") as get_payment:
            response = self.post_webhook(payment, signature_valid=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(PaymentEvent.objects.count(), 0)
        get_payment.assert_not_called()

    def test_get_webhook_is_405(self):
        self.assertEqual(self.client.get(self.webhook_url).status_code, 405)
        self.assertEqual(PaymentEvent.objects.count(), 0)

    def test_approved_payment_creates_one_order_without_second_stock_discount(self):
        response = self.post_webhook(self.payment())
        self.assertEqual(response.status_code, 200)
        self.draft.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.draft.order.status, "paid")
        self.assertEqual(self.draft.order.payment_status, "approved")
        self.assertEqual(self.draft.order.payment_discount_amount, Decimal("0.00"))
        self.assertTrue(self.draft.order.stock_deducted)
        self.assertEqual(self.variant.stock_qty, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_duplicate_webhooks_create_one_order_and_one_email(self):
        payment = self.payment(payment_id="PAY-DUP")
        self.post_webhook(payment, notification_id="evt-dup")
        self.post_webhook(payment, notification_id="evt-dup")
        self.post_webhook(payment, notification_id="evt-another")
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(PaymentEvent.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 1)

    def test_rejected_payment_releases_stock_exactly_once(self):
        payment = self.payment(status="rejected", payment_id="PAY-REJECT")
        self.post_webhook(payment, notification_id="evt-reject")
        release_reserved_stock(self.draft.token, "rejected")
        self.draft.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(self.draft.state, "rejected")
        self.assertIsNotNone(self.draft.stock_released_at)
        self.assertEqual(self.variant.stock_qty, 3)
        self.assertEqual(Order.objects.count(), 0)

    def test_amount_mismatch_becomes_visible_review_with_alert(self):
        payment = self.payment(transaction_amount=999)
        response = self.post_webhook(payment, notification_id="evt-mismatch")
        self.assertEqual(response.status_code, 200)
        order = Order.objects.get()
        self.assertEqual(order.status, "payment_review")
        self.assertEqual(order.payment_status, "review")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("alerts@example.com", mail.outbox[0].to)

    def test_return_ignores_forged_browser_status(self):
        session = self.client.session
        session["active_payment_draft"] = str(self.draft.token)
        session.save()
        with patch("payments.views.get_payment") as get_payment:
            response = self.client.get(
                reverse("payments:return", kwargs={"result": "success"}),
                {"status": "approved", "external_reference": str(self.draft.token)},
            )
        self.assertEqual(response.status_code, 200)
        get_payment.assert_not_called()
        self.assertEqual(Order.objects.count(), 0)
        self.assertContains(response, "Estamos verificando el pago")

    def test_return_queries_api_and_finalizes_same_service(self):
        session = self.client.session
        session["active_payment_draft"] = str(self.draft.token)
        session.save()
        with patch("payments.views.get_payment", return_value=self.payment()):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.get(
                    reverse("payments:return", kwargs={"result": "failure"}),
                    {"payment_id": "PAY-1", "status": "rejected"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pago confirmado")
        self.assertEqual(Order.objects.count(), 1)

    def test_live_mode_mismatch_is_review_not_fulfilled(self):
        result = process_payment(self.payment(live_mode=True), "PAY-1")
        self.assertEqual(result.state, "review")
        self.assertEqual(result.error, "live_mode_mismatch")
        self.assertEqual(result.order.status, "payment_review")

    def test_regular_checkout_endpoint_accepts_test_user_live_mode_true(self):
        self.draft.mp_init_point = "https://www.mercadopago.com.ar/checkout/start"
        self.draft.save(update_fields=["mp_init_point"])

        result = process_payment(self.payment(live_mode=True), "PAY-1")

        self.assertEqual(result.state, "approved")
        self.assertEqual(result.order.status, "paid")
        self.assertEqual(result.order.payment_status, "approved")

    def test_reconciliation_resolves_live_mode_review_once(self):
        first = process_payment(self.payment(live_mode=True), "PAY-1")
        self.assertEqual(first.state, "review")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 1)

        self.draft.mp_init_point = "https://www.mercadopago.com.ar/checkout/start"
        self.draft.save(update_fields=["mp_init_point"])
        with self.captureOnCommitCallbacks(execute=True):
            result = process_payment(self.payment(live_mode=True), "PAY-1", reconciled=True)

        result.draft.refresh_from_db()
        result.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(result.draft.state, "approved")
        self.assertEqual(result.draft.processing_error, "")
        self.assertEqual(result.order.status, "paid")
        self.assertEqual(result.order.payment_status, "approved")
        self.assertTrue(result.order.confirmation_email_sent)
        self.assertEqual(self.variant.stock_qty, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_currency_mismatch_is_review_not_fulfilled(self):
        result = process_payment(self.payment(currency_id="USD"), "PAY-1")
        self.assertEqual(result.error, "currency_mismatch")
        self.assertEqual(result.order.status, "payment_review")

    def test_collector_mismatch_is_review_not_fulfilled(self):
        result = process_payment(self.payment(collector_id=999), "PAY-1")
        self.assertEqual(result.error, "collector_mismatch")
        self.assertEqual(result.order.status, "payment_review")

    def test_pending_payment_extends_reservation_without_releasing_stock(self):
        previous_expiry = self.draft.reservation_expires_at
        result = process_payment(self.payment(status="pending"), "PAY-1")
        self.draft.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(result.state, "pending")
        self.assertGreater(self.draft.reservation_expires_at, previous_expiry)
        self.assertIsNone(self.draft.stock_released_at)
        self.assertEqual(self.variant.stock_qty, 1)

    def test_refund_is_synced_without_restoring_stock(self):
        self.post_webhook(self.payment(), notification_id="evt-approved")
        refunded = self.payment(
            status="refunded",
            transaction_amount_refunded=1000,
        )
        self.post_webhook(refunded, notification_id="evt-refunded")
        order = Order.objects.get()
        self.variant.refresh_from_db()
        self.assertEqual(order.payment_status, "refunded")
        self.assertEqual(order.mp_refunded_amount, Decimal("1000.00"))
        self.assertEqual(self.variant.stock_qty, 1)

    @override_settings(MP_CHECKOUT_ENABLED=False)
    def test_kill_switch_blocks_retry_but_webhook_keeps_processing(self):
        session = self.client.session
        session["active_payment_draft"] = str(self.draft.token)
        session.save()
        retry_url = reverse("payments:start", kwargs={"draft_id": self.draft.token})
        self.assertEqual(self.client.post(retry_url).status_code, 503)
        response = self.post_webhook(self.payment(), notification_id="evt-after-kill")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 1)


@override_settings(**MP_TEST_SETTINGS)
class PaymentConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        category = Category.objects.create(name="Concurrencia")
        product = Product.objects.create(name="RaSel Concurrente", category=category)
        self.variant = Variant.objects.create(
            product=product,
            name="1 l",
            sku="RASEL-CONCURRENT",
            price_ars=Decimal("900.00"),
            stock_qty=4,
        )
        now = timezone.now()
        self.draft = PaymentDraft.objects.create(
            full_name="Concurrent User",
            email="concurrent@example.com",
            total_amount=Decimal("900.00"),
            items=[
                {
                    "variant_id": self.variant.id,
                    "sku": self.variant.sku,
                    "product_name": product.name,
                    "variant_name": self.variant.name,
                    "unit_price": "900.00",
                    "quantity": 1,
                    "line_total": "900.00",
                }
            ],
            state="reserved",
            stock_reserved_at=now,
            reservation_expires_at=now + timedelta(minutes=30),
            mp_collector_id="9090",
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_approval_creates_one_order(self):
        payment = {
            "id": "PAY-CONCURRENT",
            "status": "approved",
            "external_reference": str(self.draft.token),
            "metadata": {"draft_token": str(self.draft.token)},
            "transaction_amount": 900,
            "currency_id": "ARS",
            "collector_id": 9090,
            "live_mode": False,
        }
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                process_payment(payment.copy(), "PAY-CONCURRENT")
            except Exception as exc:  # pragma: no cover - asserted below on PostgreSQL
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(Order.objects.count(), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 4)


@override_settings(**MP_TEST_SETTINGS)
class ReconciliationTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Conciliacion")
        product = Product.objects.create(name="RaSel Cron", category=category)
        self.variant = Variant.objects.create(
            product=product,
            name="500 ml",
            sku="RASEL-CRON",
            price_ars=Decimal("700.00"),
            stock_qty=2,
        )
        now = timezone.now()
        self.draft = PaymentDraft.objects.create(
            full_name="Cron User",
            email="cron@example.com",
            total_amount=Decimal("700.00"),
            items=[
                {
                    "variant_id": self.variant.id,
                    "sku": self.variant.sku,
                    "product_name": product.name,
                    "variant_name": self.variant.name,
                    "unit_price": "700.00",
                    "quantity": 1,
                    "line_total": "700.00",
                }
            ],
            state="preference_created",
            stock_reserved_at=now - timedelta(minutes=40),
            reservation_expires_at=now - timedelta(minutes=10),
            mp_preference_id="pref-cron",
            mp_collector_id="123",
        )

    def payment(self, status="approved"):
        return {
            "id": "PAY-CRON",
            "status": status,
            "external_reference": str(self.draft.token),
            "metadata": {"draft_token": str(self.draft.token)},
            "transaction_amount": 700,
            "transaction_amount_refunded": 0,
            "currency_id": "ARS",
            "collector_id": 123,
            "live_mode": False,
        }

    @patch("payments.management.commands.reconcile_mp_payments.search_payments")
    def test_expired_reservation_is_released_only_after_api_search(self, search):
        search.return_value = []
        call_command("reconcile_mp_payments", batch_size=100)
        self.variant.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)
        self.assertEqual(self.draft.state, "expired")
        search.assert_called_once_with(str(self.draft.token))

    @patch("payments.management.commands.reconcile_mp_payments.search_payments")
    def test_provider_failure_keeps_stock_and_fails_cron(self, search):
        search.side_effect = MercadoPagoError("temporary")
        with self.assertRaises(CommandError):
            call_command("reconcile_mp_payments", batch_size=100)
        self.variant.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 2)
        self.assertIsNone(self.draft.stock_released_at)

    @patch("payments.management.commands.reconcile_mp_payments.search_payments")
    def test_lost_approved_webhook_is_finalized(self, search):
        search.return_value = [self.payment()]
        with self.captureOnCommitCallbacks(execute=True):
            call_command("reconcile_mp_payments", batch_size=100)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Order.objects.get().status, "paid")

    @patch("payments.management.commands.reconcile_mp_payments.get_payment")
    @patch("payments.management.commands.reconcile_mp_payments.cancel_payment")
    def test_old_pending_is_cancelled_before_stock_release(self, cancel, get):
        self.draft.created_at = timezone.now() - timedelta(hours=49)
        self.draft.mp_payment_id = "PAY-CRON"
        self.draft.state = "pending"
        self.draft.save(update_fields=["created_at", "mp_payment_id", "state"])
        get.side_effect = [self.payment(status="pending"), self.payment(status="cancelled")]
        cancel.return_value = self.payment(status="cancelled")
        call_command("reconcile_mp_payments", batch_size=100)
        cancel.assert_called_once()
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.state, "cancelled")
        self.assertIsNotNone(self.draft.stock_released_at)
