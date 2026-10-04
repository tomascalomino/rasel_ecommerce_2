import json
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, transaction
from django.test import (
    Client,
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem
from orders.services import collect_and_complete, confirm_payment
from payments import tests as payment_tests
from payments.services import process_payment
from shipping.models import PickupPoint
from shop.models import Product, Variant

from .consent import COOKIE, SALT, expiry
from .delivery import claim_event, send_event
from .maintenance import cleanup
from .models import BrowserEventReceipt, Consent, MetaPurchase
from .purchases import hashed, record_purchase
from .tracking import ACTIONS, CONTACT, CYCLE

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1"
META_SETTINGS = {
    "META_PIXEL_ENABLED": True,
    "META_CAPI_ENABLED": True,
    "META_PIXEL_ID": "1400536168898337",
    "META_CAPI_ACCESS_TOKEN": "test-only-placeholder",
    "META_GRAPH_API_VERSION": "v26.0",
    "META_TEST_EVENT_CODE": "",
    "SITE_URL": "https://shop.example.com",
    "BREVO_API_KEY": "",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "ORDER_NOTIFICATION_EMAIL": "",
}


def config_from(response):
    return response.context["meta_config"]


def web_order(consent, **extra):
    now = timezone.now()
    fields = {
        "full_name": "Cliente de prueba",
        "email": " Buyer@Example.com ",
        "phone": "+54 9 11 1234-5678",
        "total_amount": Decimal("14300.00"),
        "shipping_cost": Decimal("1000.00"),
        "payment_discount_amount": Decimal("1500.00"),
        "payment_discount_percent": 10,
        "payment_method": "transfer",
        "web_checkout_id": uuid.uuid4(),
        "marketing_consent": consent,
        "marketing_captured_at": now,
        "marketing_context": {
            "consent_revision": consent.revision,
            "event_source_url": "https://shop.example.com/orders/checkout/",
            "fbp": "fb.1.1700000000000.123456",
            "fbc": "fb.1.1700000000000.realclick",
            "client_user_agent": UA,
        },
    }
    fields.update(extra)
    order = Order.objects.create(**fields)
    OrderItem.objects.create(
        order=order,
        variant_id_snapshot=42,
        product_name="Aceite",
        variant_name="500 ml",
        unit_price=Decimal("7400"),
        quantity=2,
        line_total=Decimal("14800"),
    )
    return order


@override_settings(**META_SETTINGS)
class BrowserConsentTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_USER_AGENT=UA)
        product = Product.objects.create(name="Aceite Meta")
        self.variant = Variant.objects.create(
            product=product,
            name="500 ml",
            sku="META-500",
            price_ars=Decimal("7400"),
            stock_qty=20,
        )
        self.pickup = PickupPoint.objects.create(
            name="Retiro", address="Local de prueba"
        )

    def choose(self, accepted=True, client=None, **extra):
        return (client or self.client).post(
            reverse("marketing:consent"),
            json.dumps({"accepted": accepted, **extra}),
            content_type="application/json",
        )

    def add(self, qty=1):
        return self.client.post(
            reverse("cart:add"), {"variant_id": self.variant.pk, "qty": qty}
        )

    def checkout(self):
        return self.client.post(
            reverse("orders:checkout"),
            {
                "full_name": "Comprador",
                "email": "buyer@example.com",
                "phone": "+5491112345678",
                "delivery_method": "pickup",
                "pickup_point": self.pickup.pk,
                "payment_method": "transfer",
            },
            HTTP_X_FORWARDED_FOR="203.0.113.123",
            HTTP_CF_CONNECTING_IP="203.0.113.124",
        )

    def test_unknown_choice_has_no_noscript_tracking_and_no_contact_storage(self):
        response = self.client.get("/?utm_source=instagram")
        config = config_from(response)
        self.assertEqual(config["state"], "unknown")
        self.assertNotContains(response, "facebook.com/tr?")
        self.assertNotIn(CONTACT, self.client.session)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("test-only-placeholder", response.content.decode())

    def test_acceptance_cookie_is_signed_and_saves_original_landing_campaign(self):
        config = config_from(
            self.client.get("/?utm_source=instagram&utm_campaign=aceite")
        )
        response = self.choose(pageToken=config["pageToken"])
        self.assertEqual(response.json()["state"], "accepted")
        self.assertTrue(response.cookies[COOKIE]["httponly"])
        self.assertEqual(response.cookies[COOKIE]["max-age"], 180 * 86400)
        consent_id = signing.loads(response.cookies[COOKIE].value, salt=SALT)
        self.assertTrue(Consent.objects.get(pk=consent_id).accepted)
        contact = self.client.session[CONTACT]
        self.assertEqual(contact["url"], "https://shop.example.com/")
        self.assertEqual(contact["utms"]["utm_source"], "instagram")
        page = self.client.get("/")
        self.assertContains(page, "facebook.com/tr?")
        self.assertEqual(config_from(page)["state"], "accepted")

    def test_choice_and_browser_claim_require_csrf(self):
        protected = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA)
        self.assertEqual(self.choose(client=protected).status_code, 403)
        config = config_from(protected.get("/"))
        response = protected.post(
            reverse("marketing:consent"),
            json.dumps({"accepted": True}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=config["csrf"],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            protected.post(
                reverse("marketing:claim"), "{}", content_type="application/json"
            ).status_code,
            403,
        )

    def test_invalid_choice_is_not_acceptance_and_expired_or_forged_cookie_is_unknown(
        self,
    ):
        for value in ("yes", 1, None):
            response = self.client.post(
                reverse("marketing:consent"),
                json.dumps({"accepted": value}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
        self.client.cookies[COOKIE] = "forged"
        self.assertEqual(config_from(self.client.get("/"))["state"], "unknown")
        self.choose()
        Consent.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(config_from(self.client.get("/"))["state"], "unknown")

    def test_reject_and_unanswered_checkout_both_work_without_purchase(self):
        for rejected in (False, True):
            if rejected:
                self.choose(False)
            self.add()
            self.assertEqual(self.checkout().status_code, 302)
            order = Order.objects.latest("pk")
            self.assertIsNotNone(order.web_checkout_id)
            self.assertEqual(order.marketing_context, {})
            confirm_payment(order.pk)
        self.assertFalse(MetaPurchase.objects.exists())

    def test_cart_event_claimed_once_after_successful_redirect(self):
        self.choose()
        self.add(2)
        page = self.client.get(reverse("cart:detail"))
        event = config_from(page)["events"][0]
        response = self.client.post(
            reverse("marketing:claim"),
            json.dumps(event),
            content_type="application/json",
        )
        payload = response.json()
        self.assertTrue(payload["claimed"])
        self.assertEqual(payload["name"], "AddToCart")
        self.assertEqual(payload["data"]["value"], 14800.0)
        self.assertEqual(
            payload["data"]["contents"], [{"id": str(self.variant.pk), "quantity": 2}]
        )
        repeated = self.client.post(
            reverse("marketing:claim"),
            json.dumps(event),
            content_type="application/json",
        )
        self.assertFalse(repeated.json()["claimed"])
        self.assertEqual(
            config_from(self.client.get(reverse("cart:detail")))["events"], []
        )

    def test_invalid_cart_inputs_and_decreases_do_not_emit_events(self):
        self.choose()
        for quantity in ("bad", "0", "-1"):
            self.add(quantity)
        self.client.post(reverse("cart:add"), {"variant_id": 99999, "qty": 1})
        self.assertNotIn(ACTIONS, self.client.session)
        self.add(2)
        self.client.get(reverse("cart:detail"))
        self.client.post(
            reverse("cart:update"), {"variant_id": self.variant.pk, "qty": 1}
        )
        self.assertNotIn(ACTIONS, self.client.session)
        self.client.post(
            reverse("cart:update"), {"variant_id": self.variant.pk, "qty": 3}
        )
        self.assertEqual(
            self.client.session[ACTIONS][0]["data"]["contents"][0]["quantity"], 2
        )

    def test_checkout_claim_stable_across_reload_invalid_post_and_forgery(self):
        self.add()
        first = config_from(self.client.get(reverse("orders:checkout")))["events"][0]
        self.choose()
        result = self.client.post(
            reverse("marketing:claim"),
            json.dumps(first),
            content_type="application/json",
        )
        self.assertTrue(result.json()["claimed"])
        for response in (
            self.client.get(reverse("orders:checkout")),
            self.client.post(reverse("orders:checkout"), {}),
        ):
            token = config_from(response)["events"][0]
            claimed = self.client.post(
                reverse("marketing:claim"),
                json.dumps(token),
                content_type="application/json",
            )
            self.assertFalse(claimed.json()["claimed"])
        forged = self.client.post(
            reverse("marketing:claim"),
            json.dumps({"token": "forged"}),
            content_type="application/json",
        )
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(BrowserEventReceipt.objects.count(), 1)
        self.checkout()
        self.assertNotIn(CYCLE, self.client.session)
        self.add()
        new = config_from(self.client.get(reverse("orders:checkout")))["events"][0]
        self.assertTrue(
            self.client.post(
                reverse("marketing:claim"),
                json.dumps(new),
                content_type="application/json",
            ).json()["claimed"]
        )

    def test_web_checkout_captures_real_cookies_and_ignores_spoofed_ip(self):
        self.choose()
        self.client.cookies["_fbp"] = "fb.1.1700000000000.123"
        self.client.cookies["_fbc"] = "fb.1.1700000000000.realclick"
        self.add(2)
        self.checkout()
        order = Order.objects.get()
        self.assertEqual(order.marketing_context["fbp"], "fb.1.1700000000000.123")
        self.assertEqual(order.marketing_context["client_user_agent"], UA)
        self.assertNotIn("client_ip_address", order.marketing_context)
        self.assertEqual(order.items.get().variant_id_snapshot, self.variant.pk)
        self.assertFalse(MetaPurchase.objects.exists())
        confirm_payment(order.pk)
        self.assertEqual(
            MetaPurchase.objects.get().payload["custom_data"]["value"], 13300
        )

    def test_checkout_does_not_claim_invalid_or_unavailable_cart(self):
        self.choose()
        self.add()
        first = config_from(self.client.get(reverse("orders:checkout")))["events"][-1]
        for changes in ({"stock_qty": 0}, {"stock_qty": 20, "is_active": False}):
            Variant.objects.filter(pk=self.variant.pk).update(**changes)
            response = self.client.get(reverse("orders:checkout"))
            self.assertEqual(config_from(response)["events"], [])
            self.assertEqual(
                self.client.post(
                    reverse("marketing:claim"),
                    json.dumps(first),
                    content_type="application/json",
                ).status_code,
                403,
            )
        self.assertFalse(BrowserEventReceipt.objects.exists())

    def test_optional_meta_context_failure_does_not_interrupt_cart(self):
        self.choose()
        with patch(
            "marketing.tracking.current_consent",
            side_effect=RuntimeError("unavailable"),
        ):
            response = self.add()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)]["qty"], 1)
        self.assertNotIn(ACTIONS, self.client.session)

    def test_missing_cookies_are_not_invented(self):
        self.choose()
        self.add()
        self.checkout()
        context = Order.objects.get().marketing_context
        self.assertNotIn("fbp", context)
        self.assertNotIn("fbc", context)

    def test_admin_private_urls_and_staff_are_excluded(self):
        self.choose()
        self.add()
        self.checkout()
        for url in (
            "/admin/login/",
            "/healthz",
            reverse("orders:transfer_info", args=[Order.objects.get().pk]),
        ):
            response = self.client.get(url)
            self.assertNotContains(response, "rasel-meta-config")
            self.assertNotContains(response, "facebook.com/tr?")
        user = get_user_model().objects.create_user("staff-meta", is_staff=True)
        self.client.force_login(user)
        self.assertNotContains(self.client.get("/"), "rasel-meta-config")

    @override_settings(META_PIXEL_ENABLED=False, META_CAPI_ENABLED=False)
    def test_disabled_default_has_no_banner_or_tracking(self):
        self.assertNotContains(self.client.get("/"), "data-meta-banner")
        self.assertEqual(self.choose().status_code, 403)

    def test_direct_navigation_and_mp_return_do_not_replace_campaign(self):
        self.choose()
        self.client.get("/?utm_source=instagram&utm_campaign=aceite")
        original = self.client.session[CONTACT]
        self.client.get(
            "/shop/", HTTP_REFERER="https://www.mercadopago.com.ar/checkout"
        )
        self.assertEqual(self.client.session[CONTACT], original)
        self.client.get("/contact/")
        self.assertEqual(self.client.session[CONTACT], original)


@override_settings(**META_SETTINGS)
class PurchaseTests(TestCase):
    def setUp(self):
        self.choice = Consent.objects.create(accepted=True, expires_at=expiry())
        self.order = web_order(self.choice)

    def paid(self):
        confirm_payment(self.order.pk)
        self.order.refresh_from_db()
        return MetaPurchase.objects.get(order=self.order)

    def test_pending_and_historical_orders_never_generate_purchase(self):
        self.assertFalse(MetaPurchase.objects.exists())
        legacy = Order.objects.create(
            full_name="Histórico",
            email="old@example.com",
            total_amount=100,
            payment_method="transfer",
        )
        confirm_payment(legacy.pk)
        self.assertFalse(MetaPurchase.objects.exists())
        self.order.payment_status = "rejected"
        with transaction.atomic():
            record_purchase(self.order)
        self.assertFalse(MetaPurchase.objects.exists())

    def test_approval_has_one_frozen_purchase_with_discount_and_shipping(self):
        event = self.paid()
        self.assertEqual(event.event_id, f"purchase_{self.order.web_checkout_id}")
        self.assertEqual(event.payload["custom_data"]["value"], 14300)
        self.assertEqual(event.payload["custom_data"]["currency"], "ARS")
        self.assertEqual(
            event.payload["custom_data"]["contents"],
            [{"id": "42", "quantity": 2, "item_price": 7400.0}],
        )
        self.assertEqual(
            event.payload["user_data"]["em"], [hashed("buyer@example.com")]
        )
        self.assertEqual(event.payload["user_data"]["ph"], [hashed("5491112345678")])
        self.assertEqual(
            event.payload["user_data"]["fbp"], self.order.marketing_context["fbp"]
        )
        self.assertEqual(event.payload["user_data"]["client_user_agent"], UA)
        self.assertNotIn("client_ip_address", event.payload["user_data"])
        self.order.total_amount = 1
        self.order.save(update_fields=["total_amount"])
        self.order.items.update(unit_price=1)
        confirm_payment(self.order.pk)
        self.assertEqual(MetaPurchase.objects.count(), 1)
        event.refresh_from_db()
        self.assertEqual(event.payload["custom_data"]["value"], 14300)
        self.assertEqual(
            event.payload["custom_data"]["contents"][0]["item_price"], 7400.0
        )
        self.assertEqual(event.occurred_at, self.order.paid_at)

    def test_local_phone_is_omitted_and_cash_collects_once(self):
        self.order.phone = "11 1234-5678"
        self.order.payment_method = "cod"
        self.order.save()
        collect_and_complete(self.order.pk)
        collect_and_complete(self.order.pk)
        self.assertEqual(MetaPurchase.objects.count(), 1)
        self.assertNotIn("ph", MetaPurchase.objects.get().payload["user_data"])

    def test_payment_and_outbox_rollback_together_without_network_calls(self):
        with patch("marketing.delivery.requests.post") as http:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    confirm_payment(self.order.pk)
                    raise RuntimeError("rollback")
            http.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "pending")
        self.assertIsNone(self.order.paid_at)
        self.assertFalse(MetaPurchase.objects.exists())

    def test_withdrawal_cancels_queue_and_reacceptance_does_not_resurrect(self):
        event = self.paid()
        client = Client(HTTP_USER_AGENT=UA)
        client.cookies[COOKIE] = signing.dumps(str(self.choice.pk), salt=SALT)
        client.post(
            reverse("marketing:consent"),
            '{"accepted":false}',
            content_type="application/json",
        )
        event.refresh_from_db()
        self.assertEqual(event.status, "cancelled")
        client.post(
            reverse("marketing:consent"),
            '{"accepted":true}',
            content_type="application/json",
        )
        with patch("marketing.delivery.requests.post") as http:
            self.assertEqual(send_event(event.pk), "skipped")
            http.assert_not_called()

    def test_expired_or_changed_consent_does_not_queue(self):
        self.choice.revision += 1
        self.choice.save()
        confirm_payment(self.order.pk)
        self.assertFalse(MetaPurchase.objects.exists())

    def test_admin_operator_can_confirm_but_readonly_cannot(self):
        for role, name in (
            ("Solo lectura", "reader-meta"),
            ("Operador", "operator-meta"),
        ):
            user = get_user_model().objects.create_user(name, is_staff=True)
            user.groups.add(Group.objects.get(name=role))
            client = Client(HTTP_USER_AGENT=UA)
            client.force_login(user)
            client.post(
                reverse("admin:orders_order_changelist"),
                {"action": "mark_paid", "_selected_action": str(self.order.pk)},
            )
            self.assertEqual(
                MetaPurchase.objects.count(), 0 if role == "Solo lectura" else 1
            )

    def test_sender_handles_timeout_and_retry_without_changing_payment(self):
        event = self.paid()
        frozen = event.payload
        with patch(
            "marketing.delivery.requests.post",
            side_effect=requests.Timeout("do not log secret"),
        ):
            self.assertEqual(send_event(event.pk), "pending")
        event.refresh_from_db()
        self.assertEqual(event.payload, frozen)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "approved")
        MetaPurchase.objects.filter(pk=event.pk).update(next_attempt_at=timezone.now())
        response = Mock(status_code=200)
        response.json.return_value = {"events_received": 1}
        with patch("marketing.delivery.requests.post", return_value=response) as http:
            self.assertEqual(send_event(event.pk), "sent")
            self.assertEqual(http.call_args.kwargs["json"]["data"], [frozen])
            self.assertEqual(
                http.call_args.kwargs["headers"]["Authorization"],
                "Bearer test-only-placeholder",
            )
            self.assertEqual(send_event(event.pk), "skipped")
            self.assertEqual(http.call_count, 1)

    def test_http_results_distinguish_temporary_permanent_and_acceptance(self):
        event = self.paid()
        for code, body, expected in (
            (429, {}, "pending"),
            (503, {}, "pending"),
            (400, {"error": {"code": 190, "message": "secret"}}, "failed"),
            (400, {"error": {"is_transient": True}}, "pending"),
            (200, {"events_received": 0}, "failed"),
            (200, {"events_received": 1}, "sent"),
        ):
            MetaPurchase.objects.filter(pk=event.pk).update(
                status="pending", next_attempt_at=timezone.now()
            )
            response = Mock(status_code=code)
            response.json.return_value = body
            with patch("marketing.delivery.requests.post", return_value=response):
                self.assertEqual(send_event(event.pk), expected)
            event.refresh_from_db()
            self.assertNotIn("secret", event.diagnostic)

    def test_missing_token_dry_run_and_test_mode_mismatch_send_nothing(self):
        event = self.paid()
        with patch("marketing.delivery.requests.post") as http:
            with override_settings(META_CAPI_ACCESS_TOKEN=""):
                self.assertEqual(send_event(event.pk), "disabled")
                output = StringIO()
                call_command("send_meta_events", "--send", stdout=output)
                self.assertIn("Falta META_CAPI_ACCESS_TOKEN", output.getvalue())
            call_command("send_meta_events", stdout=StringIO())
            with override_settings(META_TEST_EVENT_CODE="TEST_ONLY"):
                self.assertEqual(send_event(event.pk), "skipped")
            http.assert_not_called()
        event.refresh_from_db()
        self.assertEqual(event.status, "pending")
        self.assertEqual(event.attempts, 0)

    @override_settings(META_TEST_EVENT_CODE="TEST_ONLY")
    def test_test_code_is_request_level_and_command_can_limit_to_order(self):
        event = self.paid()
        response = Mock(status_code=200)
        response.json.return_value = {"events_received": 1}
        with patch("marketing.delivery.requests.post", return_value=response) as http:
            call_command(
                "send_meta_events",
                "--send",
                "--order",
                str(self.order.pk),
                stdout=StringIO(),
            )
        body = http.call_args.kwargs["json"]
        self.assertEqual(body["test_event_code"], "TEST_ONLY")
        self.assertNotIn("test_event_code", body["data"][0])
        event.refresh_from_db()
        self.assertEqual(event.status, "sent")

    def test_active_claim_blocks_second_sender_and_expired_claim_recovers(self):
        event = self.paid()
        claimed = claim_event(event.pk)
        self.assertIsNotNone(claimed)
        self.assertIsNone(claim_event(event.pk))
        MetaPurchase.objects.filter(pk=event.pk).update(
            claim_expires_at=timezone.now() - timedelta(seconds=1)
        )
        recovered = claim_event(event.pk)
        self.assertIsNotNone(recovered)
        self.assertNotEqual(claimed.claim_id, recovered.claim_id)

    def test_explicit_failed_retry_requires_order_and_preserves_event(self):
        event = self.paid()
        MetaPurchase.objects.filter(pk=event.pk).update(status="failed")
        with self.assertRaises(CommandError):
            call_command("send_meta_events", "--retry-failed", stdout=StringIO())
        response = Mock(status_code=200)
        response.json.return_value = {"events_received": 1}
        with patch("marketing.delivery.requests.post", return_value=response) as http:
            call_command(
                "send_meta_events",
                "--send",
                "--retry-failed",
                "--order",
                str(self.order.pk),
                stdout=StringIO(),
            )
        self.assertEqual(
            http.call_args.kwargs["json"]["data"][0]["event_id"], event.event_id
        )
        self.assertEqual(
            http.call_args.kwargs["json"]["data"][0]["event_time"],
            event.payload["event_time"],
        )

    def test_old_or_expired_events_are_not_redated(self):
        event = self.paid()
        original = event.payload
        MetaPurchase.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        with patch("marketing.delivery.requests.post") as http:
            self.assertEqual(send_event(event.pk), "skipped")
            http.assert_not_called()
        event.refresh_from_db()
        self.assertEqual(event.status, "expired")
        self.assertEqual(event.payload, original)

    def test_cleanup_removes_payload_then_audit_without_recreating_purchase(self):
        event = self.paid()
        MetaPurchase.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )
        Order.objects.filter(pk=self.order.pk).update(
            marketing_captured_at=timezone.now() - timedelta(days=91)
        )
        cleanup()
        event.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(event.payload, {})
        self.assertEqual(self.order.marketing_context, {})
        MetaPurchase.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(days=366)
        )
        cleanup()
        confirm_payment(self.order.pk)
        self.assertFalse(MetaPurchase.objects.exists())
        self.assertIsNotNone(self.order.paid_at)


@override_settings(**{**payment_tests.MP_TEST_SETTINGS, **META_SETTINGS})
class MercadoPagoPurchaseTests(TestCase):
    def setUp(self):
        payment_tests.MercadoPagoIntegrationTests.setUp(self)
        self.choice = Consent.objects.create(accepted=True, expires_at=expiry())
        self.draft.web_checkout_id = uuid.uuid4()
        self.draft.marketing_consent = self.choice
        self.draft.marketing_captured_at = timezone.now()
        self.draft.marketing_context = {
            "consent_revision": self.choice.revision,
            "event_source_url": "https://shop.example.com/orders/checkout/",
            "client_user_agent": UA,
        }
        self.draft.save()

    def payment(self, *args, **kwargs):
        return payment_tests.MercadoPagoIntegrationTests.payment(self, *args, **kwargs)

    def test_pending_and_rejected_webhooks_do_not_generate_purchase(self):
        for state in ("pending", "rejected"):
            payment_tests.MercadoPagoIntegrationTests.post_webhook(
                self, self.payment(state), notification_id=state
            )
        self.assertFalse(MetaPurchase.objects.exists())

    def test_verified_webhook_approval_copies_context_and_deduplicates(self):
        approved_at = (timezone.now() - timedelta(minutes=8)).isoformat()
        payment = self.payment(date_approved=approved_at)
        for notification in ("first", "first", "new-delivery"):
            response = payment_tests.MercadoPagoIntegrationTests.post_webhook(
                self, payment, notification_id=notification
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(MetaPurchase.objects.count(), 1)
        order = Order.objects.get()
        self.assertEqual(order.web_checkout_id, self.draft.web_checkout_id)
        self.assertEqual(order.marketing_context["client_user_agent"], UA)
        self.assertEqual(order.paid_at.isoformat(), approved_at)
        self.assertEqual(
            MetaPurchase.objects.get().payload["custom_data"]["value"], 1000
        )

    def test_invalid_signature_amount_and_review_cannot_generate_purchase(self):
        payment_tests.MercadoPagoIntegrationTests.post_webhook(
            self, self.payment(), signature_valid=False
        )
        self.assertFalse(MetaPurchase.objects.exists())
        process_payment(self.payment(transaction_amount=1), "PAY-1")
        self.assertEqual(Order.objects.get().payment_status, "review")
        self.assertFalse(MetaPurchase.objects.exists())

    def test_reconciliation_generates_the_same_purchase_once(self):
        payment = self.payment()
        process_payment(payment, "PAY-1", reconciled=True)
        process_payment(payment, "PAY-1", reconciled=True)
        self.assertEqual(MetaPurchase.objects.count(), 1)


@override_settings(**META_SETTINGS)
class ConcurrentMetaTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_offline_confirmations_create_one_purchase(self):
        choice = Consent.objects.create(accepted=True, expires_at=expiry())
        order = web_order(choice)
        barrier = threading.Barrier(2)
        errors = []

        def confirm():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with patch("orders.services.send_payment_confirmed"):
                    confirm_payment(order.pk)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(MetaPurchase.objects.count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_dispatchers_claim_only_once(self):
        choice = Consent.objects.create(accepted=True, expires_at=expiry())
        order = web_order(choice)
        with patch("orders.services.send_payment_confirmed"):
            confirm_payment(order.pk)
        event = MetaPurchase.objects.get()
        barrier = threading.Barrier(2)
        results, errors = [], []

        def claim():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(claim_event(event.pk))
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum(result is not None for result in results), 1)
