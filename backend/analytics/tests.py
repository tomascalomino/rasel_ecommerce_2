import threading
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone

from config.admin import sync_roles
from orders.models import Order
from payments.mercadopago import MercadoPagoError
from payments.models import PaymentDraft
from shipping.models import PickupPoint
from shop.models import Product, Variant

from .maintenance import cleanup_batch, first_retained_day
from .models import (
    DailyDevice,
    DailyProduct,
    DailySource,
    DailyTotal,
    Measurement,
    Visit,
)
from .reports import report_context
from .tracking import SESSION_KEY, device_for, mark_stage, record, source_for

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile Safari/604.1"


def request_at(path="/", session=None, ua=UA):
    request = RequestFactory().get(path, HTTP_USER_AGENT=ua)
    request.user = AnonymousUser()
    request.session = session if session is not None else {}
    request.resolver_match = resolve(path.split("?")[0])
    return request


@override_settings(ANALYTICS_ENABLED=True)
class TrackingTests(TestCase):
    def test_recargas_y_etapas_una_vez_por_visita(self):
        request = request_at()
        record(request, pageview=True, stages=["cart_added"])
        record(request, pageview=True, stages=["cart_added", "checkout_opened"])
        self.assertEqual(Visit.objects.count(), 1)
        total = DailyTotal.objects.get()
        self.assertEqual(
            (total.visits, total.pageviews, total.cart_added, total.checkout_opened),
            (1, 2, 1, 1),
        )
        self.assertEqual(DailyDevice.objects.get().device, "mobile")

    def test_nueva_visita_a_los_30_minutos(self):
        now = timezone.now()
        request = request_at()
        with patch("analytics.tracking.timezone.now", return_value=now):
            record(request, pageview=True)
        with patch(
            "analytics.tracking.timezone.now", return_value=now + timedelta(minutes=30)
        ):
            record(request, pageview=True)
        self.assertEqual(Visit.objects.count(), 2)

    def test_actividad_extiende_visita_sin_modificar_sesion_en_cada_pagina(self):
        request = request_at()
        now = timezone.now()
        for minutes in (0, 20, 40):
            with patch(
                "analytics.tracking.timezone.now",
                return_value=now + timedelta(minutes=minutes),
            ):
                record(request, pageview=True)
        self.assertEqual(Visit.objects.count(), 1)

    def test_medianoche_paginas_por_dia_y_etapas_por_inicio(self):
        before = datetime(
            2026, 9, 6, 23, 55, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
        )
        request = request_at()
        with patch("analytics.tracking.timezone.now", return_value=before):
            record(request, pageview=True)
        with patch(
            "analytics.tracking.timezone.now",
            return_value=before + timedelta(minutes=10),
        ):
            record(
                request, pageview=True, stages=["checkout_opened", "checkout_submitted"]
            )
        first, second = list(DailyTotal.objects.order_by("day"))
        self.assertEqual(
            (first.visits, first.pageviews, first.checkout_submitted), (1, 1, 1)
        )
        self.assertEqual(
            (second.visits, second.pageviews, second.checkout_submitted), (0, 1, 0)
        )

    def test_invalid_session_token_restarts_measurement(self):
        record(request_at(session={SESSION_KEY: "invalid"}), pageview=True)
        self.assertEqual(Visit.objects.count(), 1)

    def test_first_source_wins_and_no_request_payload_saved(self):
        request = request_at(
            "/?utm_source=Instagram&utm_medium=social&utm_campaign=septiembre"
        )
        request.META["REMOTE_ADDR"] = "192.0.2.10"
        record(request, pageview=True)
        record(
            request_at("/?utm_source=another", session=request.session), pageview=True
        )
        source = DailySource.objects.get()
        self.assertEqual(
            (source.source, source.medium, source.campaign, source.visits),
            ("instagram", "social", "septiembre", 1),
        )
        self.assertNotIn("192.0.2.10", str(list(Visit.objects.values())))
        self.assertNotIn("Instagram", str(list(Visit.objects.values())))

    def test_sources_reject_emails_urls_and_unbounded_tags(self):
        for value in (
            "a@example.com",
            "https://example.com/secret",
            "a" * 65,
            "with spaces",
        ):
            with self.subTest(value=value):
                request = request_at("/?utm_source=" + value)
                self.assertEqual(source_for(request), ("directo", "", ""))
        request = request_at()
        request.META["HTTP_REFERER"] = "https://www.instagram.com/private?email=hidden"
        self.assertEqual(source_for(request), ("instagram.com", "referencia", ""))
        request.META["HTTP_REFERER"] = "http://testserver/cart/"
        self.assertEqual(source_for(request), ("directo", "", ""))
        request.META["HTTP_REFERER"] = "http://192.0.2.1/path"
        self.assertEqual(source_for(request), ("directo", "", ""))

    def test_source_cardinality_is_bounded(self):
        day = timezone.localdate()
        DailyTotal.objects.create(day=day)
        DailySource.objects.bulk_create(
            [DailySource(day=day, source=f"campaign-{i}") for i in range(100)]
        )
        record(request_at("/?utm_source=unbounded"), pageview=True)
        record(request_at("/?utm_source=another"), pageview=True)
        self.assertEqual(DailySource.objects.count(), 101)
        self.assertEqual(DailySource.objects.get(source="otros").visits, 2)

    def test_device_classification(self):
        for ua, expected in (
            (UA, "mobile"),
            ("Mozilla Windows NT", "desktop"),
            ("Mozilla Android 11 Tablet", "tablet"),
            ("Mozilla iPad", "tablet"),
            ("Unrecognized", "unknown"),
        ):
            self.assertEqual(device_for(request_at(ua=ua)), expected)

    def test_excluded_requests_never_write(self):
        client = Client(HTTP_USER_AGENT=UA)
        for path in (
            "/healthz",
            "/robots.txt",
            "/sitemap.xml",
            "/admin/",
            "/not-found/",
            "/orders/checkout/",
        ):
            client.get(path)
        for ua in (
            "",
            "Googlebot",
            "UptimeRobot/1.0",
            "facebookexternalhit",
            "WhatsApp",
            "curl/8.0",
        ):
            client.get("/", HTTP_USER_AGENT=ua)
        self.assertFalse(Visit.objects.exists())

    def test_staff_excluded_and_switch_off(self):
        staff = get_user_model().objects.create_user("staff", is_staff=True)
        client = Client(HTTP_USER_AGENT=UA)
        client.force_login(staff)
        client.get("/")
        client.logout()
        with override_settings(ANALYTICS_ENABLED=False):
            client.get("/")
        self.assertFalse(Visit.objects.exists())

    def test_product_snapshot_retained_after_product_deletion(self):
        product = Product.objects.create(name="Oliva")
        Client(HTTP_USER_AGENT=UA).get(
            reverse("shop:product_detail", args=[product.slug])
        )
        product.delete()
        self.assertEqual(DailyProduct.objects.get().product_name, "Oliva")

    def test_analytics_failure_keeps_public_response_and_rolls_back_counters(self):
        with patch(
            "analytics.tracking.DailyDevice.objects.get_or_create",
            side_effect=RuntimeError("private data"),
        ):
            with self.assertLogs("analytics.tracking", level="WARNING") as logs:
                response = Client(HTTP_USER_AGENT=UA).get("/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Visit.objects.exists())
        self.assertFalse(DailyTotal.objects.exists())
        self.assertNotIn("private data", str(logs.output))

    def test_rolled_back_business_transaction_does_not_queue_stage(self):
        request = request_at()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    mark_stage(request, "checkout_submitted")
                    raise ValueError("rollback")
            except ValueError:
                pass
        self.assertFalse(getattr(request, "_analytics_stages", set()))

    def test_same_visit_query_cost_is_bounded(self):
        request = request_at()
        record(request, pageview=True)
        with CaptureQueriesContext(connection) as queries:
            record(request, pageview=True)
        self.assertLessEqual(len(queries), 9)


@override_settings(ANALYTICS_ENABLED=True, MP_CHECKOUT_ENABLED=False)
class CheckoutTrackingTests(TransactionTestCase):
    def setUp(self):
        self.client = Client(HTTP_USER_AGENT=UA)
        self.product = Product.objects.create(name="Oliva")
        self.variant = Variant.objects.create(
            product=self.product,
            name="500 ml",
            sku="ANALYTICS",
            price_ars=Decimal("1000"),
            stock_qty=20,
        )
        self.point = PickupPoint.objects.create(name="Retiro", address="Calle 1")
        self.data = dict(
            full_name="Test",
            email="test@example.com",
            phone="",
            delivery_method="pickup",
            pickup_point=self.point.pk,
            payment_method="transfer",
        )

    def add(self, **kwargs):
        return self.client.post(
            reverse("cart:add"), dict(variant_id=self.variant.pk, qty=1, **kwargs)
        )

    def test_quick_add_and_cart_updates_deduplicate(self):
        self.assertEqual(self.add(next="/").url, "/")
        self.add()
        self.client.post(
            reverse("cart:update"), dict(variant_id=self.variant.pk, qty=3)
        )
        total = DailyTotal.objects.get()
        self.assertEqual((total.visits, total.cart_added), (1, 1))

    def test_invalid_zero_and_inactive_add_do_not_count(self):
        for variant_id, qty in ((999999, 1), (self.variant.pk, 0)):
            self.client.post(reverse("cart:add"), dict(variant_id=variant_id, qty=qty))
        self.variant.is_active = False
        self.variant.save()
        self.add()
        self.assertFalse(Visit.objects.exists())

    def test_existing_cart_decrease_does_not_count_increase_does(self):
        session = self.client.session
        session["cart"] = {str(self.variant.pk): {"qty": 3}}
        session.save()
        self.client.post(
            reverse("cart:update"), dict(variant_id=self.variant.pk, qty=2)
        )
        self.assertFalse(Visit.objects.exists())
        self.client.post(
            reverse("cart:update"), dict(variant_id=self.variant.pk, qty=3)
        )
        self.assertEqual(DailyTotal.objects.get().cart_added, 1)

    def test_checkout_invalid_then_transfer_and_refresh(self):
        self.add()
        self.client.get(reverse("orders:checkout"))
        self.client.post(reverse("orders:checkout"), {})
        self.assertEqual(DailyTotal.objects.get().checkout_submitted, 0)
        response = self.client.post(reverse("orders:checkout"), self.data)
        self.client.get(response.url)
        total = DailyTotal.objects.get()
        self.assertEqual((total.checkout_opened, total.checkout_submitted), (1, 1))
        self.assertEqual(Order.objects.get().payment_status, "pending")
        self.assertEqual(report_context("today")["sales"]["count"], 0)

    def test_cash_checkout_is_submitted_not_paid(self):
        self.add()
        response = self.client.post(
            reverse("orders:checkout"), {**self.data, "payment_method": "cod"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DailyTotal.objects.get().checkout_submitted, 1)
        self.assertEqual(Order.objects.get().payment_status, "pending")

    @override_settings(MP_CHECKOUT_ENABLED=True)
    def test_mp_provider_failure_counts_committed_draft_and_retry_does_not_duplicate(
        self,
    ):
        self.add()
        with patch(
            "orders.views.create_checkout_preference",
            side_effect=MercadoPagoError("unavailable"),
        ):
            response = self.client.post(
                reverse("orders:checkout"), {**self.data, "payment_method": "mp"}
            )
        self.assertEqual(response.status_code, 503)
        draft = PaymentDraft.objects.get()
        self.assertEqual(DailyTotal.objects.get().checkout_submitted, 1)
        # Django does not save session mutations on 503. Supply an established
        # draft session to exercise the existing retry endpoint independently.
        session = self.client.session
        session["active_payment_draft"] = str(draft.token)
        session.save()
        with patch(
            "payments.views.create_checkout_preference",
            side_effect=MercadoPagoError("unavailable"),
        ):
            retry = self.client.post(reverse("payments:start", args=[draft.token]))
        self.assertEqual(retry.status_code, 503)
        self.assertEqual(DailyTotal.objects.get().checkout_submitted, 1)
        self.assertFalse(Order.objects.exists())

    @override_settings(MP_CHECKOUT_ENABLED=True)
    def test_mp_success_creates_one_stage_and_no_paid_order(self):
        self.add()

        def preference(token):
            draft = PaymentDraft.objects.get(token=token)
            draft.mp_init_point = "https://www.mercadopago.com.ar/checkout/v1/redirect"
            return draft

        with patch("orders.views.create_checkout_preference", side_effect=preference):
            response = self.client.post(
                reverse("orders:checkout"), {**self.data, "payment_method": "mp"}
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DailyTotal.objects.get().checkout_submitted, 1)
        self.assertFalse(Order.objects.exists())

    def test_tracking_failure_does_not_change_order_stock_or_redirect(self):
        self.add()
        with patch("analytics.tracking.record", side_effect=RuntimeError("fail")):
            response = self.client.post(reverse("orders:checkout"), self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 19)


@override_settings(ANALYTICS_ENABLED=True)
class ReportTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "reportadmin", "admin@example.com", "test"
        )
        self.client.force_login(self.admin)

    def test_permissions_and_dashboard_link(self):
        self.assertContains(
            self.client.get(reverse("admin:index")), reverse("admin:reports")
        )
        staff = get_user_model().objects.create_user("reportstaff", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin:reports")).status_code, 403)
        self.assertNotContains(
            self.client.get(reverse("admin:index")), reverse("admin:reports")
        )
        sync_roles()
        for name in ("Operador", "Solo lectura"):
            staff.groups.set([Group.objects.get(name=name)])
            self.assertEqual(self.client.get(reverse("admin:reports")).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("admin:reports")).status_code, 302)

    def test_all_periods_empty_and_invalid_default(self):
        for period in ("today", "7", "30", "90", "12m", "invalid"):
            response = self.client.get(reverse("admin:reports"), {"period": period})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Todavía no hay visitas registradas")
        self.assertEqual(response.context["period"], "30")

    def test_sales_refunds_cancellations_and_local_date(self):
        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        base = dict(
            full_name="Test", email="t@example.com", total_amount=100, shipping_cost=10
        )
        for status, fulfillment, refund, created in (
            ("approved", "pending", 0, today),
            ("partially_refunded", "pending", 30, today),
            ("approved", "cancelled", 0, today),
            ("refunded", "pending", 100, today),
            ("pending", "pending", 0, today),
            ("approved", "pending", 0, today - timedelta(seconds=1)),
        ):
            Order.objects.create(
                **base,
                payment_status=status,
                fulfillment_status=fulfillment,
                mp_refunded_amount=refund,
                created_at=created,
            )
        self.assertEqual(
            report_context("today")["sales"], {"count": 2, "total": Decimal("170")}
        )

    def test_monthly_rollup_partial_history_and_zero_days(self):
        today = timezone.localdate()
        Measurement.objects.create(pk=1)
        DailyTotal.objects.create(
            day=today, visits=2, pageviews=5, checkout_submitted=1
        )
        context = report_context("12m")
        self.assertEqual(len(context["rows"]), 12)
        self.assertFalse(context["rows"][0]["available"])
        self.assertEqual(context["rows"][-1]["visits"], 2)
        self.assertEqual(context["funnel"][-1]["percent"], 50)
        response = self.client.get(reverse("admin:reports"), {"period": "12m"})
        self.assertContains(response, "Sin registro")
        self.assertNotContains(response, "&#x27;visits&#x27;")

    def test_paused_panel_keeps_historical_data(self):
        Measurement.objects.create(pk=1)
        DailyTotal.objects.create(day=timezone.localdate(), visits=10)
        with override_settings(ANALYTICS_ENABLED=False):
            response = self.client.get(reverse("admin:reports"))
        self.assertContains(response, "La medición está pausada")
        self.assertEqual(response.context["counts"]["visits"], 10)

    def test_report_query_count_does_not_grow_with_days(self):
        Measurement.objects.create(pk=1)
        with CaptureQueriesContext(connection) as queries:
            report_context("90")
        self.assertLessEqual(len(queries), 8)


class MaintenanceTests(TestCase):
    def test_expired_sessions_only_are_cleaned(self):
        now = timezone.now()
        Measurement.objects.create(pk=1, cleanup_after=now)
        Session.objects.create(
            session_key="expired", session_data="", expire_date=now - timedelta(days=1)
        )
        Session.objects.create(
            session_key="active", session_data="", expire_date=now + timedelta(days=1)
        )
        cleanup_batch(now=now)
        self.assertEqual(
            list(Session.objects.values_list("session_key", flat=True)), ["active"]
        )

    def test_cleanup_bounded_preserves_summaries_and_orders(self):
        now = timezone.now()
        today = timezone.localdate(now)
        Measurement.objects.create(pk=1, cleanup_after=now)
        for _ in range(3):
            Visit.objects.create(
                started_at=now - timedelta(days=91), day=today - timedelta(days=91)
            )
        Visit.objects.create(started_at=now, day=today)
        DailyTotal.objects.create(day=today - timedelta(days=91), visits=3)
        cutoff = first_retained_day(today)
        DailyTotal.objects.create(day=cutoff - timedelta(days=1), visits=100)
        DailyTotal.objects.create(day=cutoff, visits=50)
        Order.objects.create(full_name="Test", email="t@example.com", total_amount=10)
        self.assertEqual(cleanup_batch(now=now, batch_size=2), 3)
        self.assertEqual(cleanup_batch(now=now), 0)
        self.assertEqual(Visit.objects.count(), 2)
        self.assertEqual(DailyTotal.objects.count(), 2)
        self.assertEqual(Order.objects.count(), 1)
        output = StringIO()
        call_command("cleanup_analytics", stdout=output)
        self.assertEqual(Visit.objects.count(), 1)

    def test_calendar_retention_across_year_boundary(self):
        self.assertEqual(
            str(first_retained_day(datetime(2026, 1, 31).date())), "2025-02-01"
        )


class ConcurrentTrackingTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_cleanup_claims_one_batch(self):
        now = timezone.now()
        Measurement.objects.create(pk=1, cleanup_after=now)
        for _ in range(3):
            Visit.objects.create(
                started_at=now - timedelta(days=91), day=timezone.localdate()
            )
        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(cleanup_batch(now=now, batch_size=1))
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(Visit.objects.count(), 2)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_stage_is_counted_once(self):
        request = request_at()
        record(request, pageview=True)
        session = dict(request.session)
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                record(request_at(session=dict(session)), stages=["checkout_submitted"])
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(DailyTotal.objects.get().checkout_submitted, 1)
