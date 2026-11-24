from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse

from orders.models import CheckoutAttempt, Order
from orders.views import _submit_checkout
from payments.mercadopago import MercadoPagoError
from payments.models import PaymentDraft
from payments.services import release_reserved_stock
from shipping.models import PickupPoint
from shop.models import Product, Variant


def checkout_cart(client):
    variant = Variant.objects.create(
        product=Product.objects.create(name="Prueba"), name="250 ml",
        sku=f"TEST-{uuid4().hex}", price_ars=1000, stock_qty=5,
    )
    point = PickupPoint.objects.create(name="Prueba", address="Calle de prueba")
    client.post(reverse("cart:add"), {"variant_id": variant.pk, "qty": 1})
    page = client.get(reverse("orders:checkout"))
    return variant, {
        "checkout_attempt": page.context["checkout_attempt"],
        "full_name": "Compra de prueba", "email": "buyer@example.invalid",
        "delivery_method": "pickup", "pickup_point": point.pk,
        "payment_method": "transfer",
    }


@override_settings(MP_CHECKOUT_ENABLED=True)
class CheckoutReplayTests(TestCase):
    def test_old_form_requires_confirmation_and_replay_returns_same_order(self):
        variant, data = checkout_cart(self.client)
        url = reverse("orders:checkout")
        initial = self.client.post(url, {**data, "checkout_attempt": ""})
        self.assertContains(initial, "Revisá el resumen del carrito y confirmá")
        self.assertFalse(Order.objects.exists())
        with patch("orders.views.send_order_confirmation") as mail:
            first = self.client.post(url, data)
            repeated = self.client.post(url, data)
            mail.assert_called_once()
        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.url, first.url)
        self.client.post(reverse("cart:add"), {"variant_id": variant.pk, "qty": 1})
        self.client.post(url, data)
        self.assertEqual(len(self.client.session["cart"]), 1)
        next_token = self.client.get(url).context["checkout_attempt"]
        self.assertNotEqual(next_token, data["checkout_attempt"])
        self.assertEqual(self.client.post(url, {**data, "checkout_attempt": next_token}).status_code, 302)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_qty, 3)

    def test_provider_retry_reuses_reservation_and_pending_prevents_new_order(self):
        variant, data = checkout_cart(self.client)
        data["payment_method"] = "mp"
        url = reverse("orders:checkout")
        preference = {
            "id": "only-one",
            "init_point": "https://example.invalid/checkout",
            "collector_id": 123,
        }
        with patch("payments.services.create_preference", side_effect=[
            MercadoPagoError("temporary"), preference,
        ]) as create:
            self.assertEqual(self.client.post(url, data).status_code, 503)
            draft = PaymentDraft.objects.get()
            # A 503 doesn't save session updates. Retrying still resolves the same draft.
            self.assertNotIn("active_payment_draft", self.client.session)
            retry = self.client.post(reverse("payments:start", args=[draft.token]))
            self.assertEqual(retry.url, preference["init_point"])
            self.assertEqual(self.client.post(url, data).url, retry.url)
            self.assertEqual(create.call_count, 2)
            self.assertEqual(
                [call.kwargs["idempotency_key"] for call in create.call_args_list],
                [f"rasel-draft-{draft.token}"] * 2,
            )

        PaymentDraft.objects.filter(pk=draft.pk).update(state="pending")
        blocked = self.client.post(url, {**data, "payment_method": "transfer"}, follow=True)
        self.assertContains(blocked, "Estamos verificando el pago")
        self.assertFalse(Order.objects.exists())
        self.assertEqual(PaymentDraft.objects.count(), 1)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_qty, 4)

        release_reserved_stock(draft.token, "cancelled")
        self.client.get(reverse("payments:return", args=["status"]))
        new_token = self.client.get(url).context["checkout_attempt"]
        self.assertNotEqual(new_token, data["checkout_attempt"])
        self.assertEqual(self.client.post(url, {
            **data, "checkout_attempt": new_token, "payment_method": "transfer",
        }).status_code, 302)

    def test_token_from_another_session_requires_a_new_confirmation(self):
        _, data = checkout_cart(self.client)
        other = Client()
        session = other.session
        session["cart"] = self.client.session["cart"]
        session.save()
        self.assertContains(other.post(reverse("orders:checkout"), data), "Revisá el resumen")
        self.assertFalse(Order.objects.exists())


@override_settings(ANALYTICS_ENABLED=False, MP_CHECKOUT_ENABLED=True)
class CheckoutOverlapTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_overlapping_posts_commit_one_order_per_payment_method(self):
        for method in ("transfer", "cod", "mp"):
            with self.subTest(method=method):
                client = Client()
                variant, data = checkout_cart(client)
                data["payment_method"] = method
                barrier = Barrier(2)

                def enter_at_same_time(*args, **kwargs):
                    barrier.wait(timeout=10)
                    return _submit_checkout(*args, **kwargs)

                def submit():
                    browser = Client()
                    browser.cookies = deepcopy(client.cookies)
                    try:
                        return browser.post(reverse("orders:checkout"), data)
                    finally:
                        connections.close_all()

                with (
                    patch("orders.views._submit_checkout", side_effect=enter_at_same_time),
                    patch("orders.views.send_order_confirmation") as mail,
                    patch("payments.services.create_preference", return_value={
                        "id": "only-one",
                        "init_point": "https://example.invalid/checkout",
                        "collector_id": 123,
                    }) as preference,
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    first = pool.submit(submit)
                    second = pool.submit(submit)
                    responses = [first.result(timeout=20), second.result(timeout=20)]
                    if method == "mp":
                        self.assertIn(302, [response.status_code for response in responses])
                        self.assertTrue(all(response.status_code in {202, 302} for response in responses))
                        preference.assert_called_once()
                        mail.assert_not_called()
                        self.assertEqual(PaymentDraft.objects.count(), 1)
                        self.assertEqual(CheckoutAttempt.objects.filter(draft__isnull=False).count(), 1)
                    else:
                        self.assertEqual([response.status_code for response in responses], [302, 302])
                        self.assertEqual(responses[0].url, responses[1].url)
                        mail.assert_called_once()
                        self.assertEqual(Order.objects.filter(payment_method=method).count(), 1)
                variant.refresh_from_db()
                self.assertEqual(variant.stock_qty, 4)
