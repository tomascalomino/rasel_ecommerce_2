import json
import threading
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection, close_old_connections
from django.test import (
    Client,
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from payments.models import PaymentDraft
from shipping.models import PickupPoint
from shop.models import Product, Variant
from .activity import SALT as ACTIVITY_SALT
from .attribution import COOKIE, SALT, current_contact
from .maintenance import cleanup_batch, first_retained_day
from .models import DailyExclusion, DailyTotal, Measurement, QualityMeasurement, Visit
from .reports import report_context
from .tests import UA, request_at
from .tracking import SESSION_KEY, record


@override_settings(ANALYTICS_ENABLED=True)
class QualityTests(TestCase):
    def setUp(self):
        self.browser = Client(HTTP_USER_AGENT=UA, enforce_csrf_checks=True)

    def signal(self, token, event="interaction", browser=None):
        browser = browser or self.browser
        return browser.post(
            reverse("analytics_activity"),
            json.dumps({"event": event, "token": token}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value,
        )

    def test_exclusions_are_disjoint_and_health_never_writes(self):
        with CaptureQueriesContext(connection) as queries:
            self.browser.get("/healthz")
        self.assertFalse(
            any(
                q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"}
                for q in queries
            )
        )
        for agent, reason in (
            ("Go-http-client/2.0", "monitor"),
            ("UptimeRobot", "monitor"),
            ("okhttp/4.12", "bot"),
            ("axios/1", "bot"),
            ("meta-externalagent/1.1", "bot"),
            ("", "missing_agent"),
        ):
            self.browser.get("/", HTTP_USER_AGENT=agent)
            self.assertTrue(DailyExclusion.objects.filter(reason=reason).exists())
        for header in ("HTTP_PURPOSE", "HTTP_SEC_PURPOSE", "HTTP_X_PURPOSE"):
            self.browser.get("/", **{header: "prefetch"})
        self.assertEqual(
            sum(DailyExclusion.objects.values_list("requests", flat=True)), 9
        )
        self.assertFalse(Visit.objects.exists())
        self.assertFalse(Measurement.objects.exists())
        self.assertTrue(QualityMeasurement.objects.exists())
        self.browser.get("/", HTTP_USER_AGENT="Unrecognized")
        self.assertEqual(Visit.objects.count(), 1)

    def test_activity_deduplicates_without_extending_visit(self):
        page = self.browser.get("/")
        token = page.context["analytics_activity_token"]
        visit = Visit.objects.get()
        last_seen = visit.last_seen_at
        self.assertEqual(self.signal(token).status_code, 204)
        self.signal(token)
        visit.refresh_from_db()
        self.assertTrue(visit.active)
        self.assertEqual(visit.last_seen_at, last_seen)
        total = DailyTotal.objects.get()
        self.assertEqual(
            (total.visits, total.quality_visits, total.active_visits, total.pageviews),
            (1, 1, 1, 1),
        )

    def test_visible_time_stale_pages_and_expiry(self):
        token = self.browser.get("/").context["analytics_activity_token"]
        self.signal(token, "visible")
        self.assertFalse(Visit.objects.get().active)
        with patch(
            "analytics.activity.timezone.now",
            return_value=timezone.now() + timedelta(seconds=11),
        ):
            self.signal(token, "visible")
        self.assertTrue(Visit.objects.get().active)
        Visit.objects.update(last_seen_at=timezone.now() - timedelta(minutes=31))
        new_token = self.browser.get("/").context["analytics_activity_token"]
        self.signal(token)
        self.assertEqual(DailyTotal.objects.get().active_visits, 1)
        Visit.objects.update(last_seen_at=timezone.now() - timedelta(minutes=31))
        self.signal(new_token)
        self.assertEqual(DailyTotal.objects.get().active_visits, 1)

    def test_csrf_tampering_other_session_and_no_visit(self):
        token = self.browser.get("/").context["analytics_activity_token"]
        self.assertEqual(self.signal(token + "invalid").status_code, 400)
        response = self.browser.post(
            reverse("analytics_activity"),
            json.dumps({"event": "interaction", "token": token}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        other = Client(HTTP_USER_AGENT=UA, enforce_csrf_checks=True)
        other.get("/")
        self.signal(token, browser=other)
        self.assertEqual(DailyTotal.objects.get().active_visits, 0)
        self.browser.cookies.pop("sessionid")
        self.signal(token)
        self.assertEqual(Visit.objects.count(), 2)

    def test_failure_pause_and_staff_do_not_signal(self):
        token = self.browser.get("/").context["analytics_activity_token"]
        with patch(
            "analytics.activity.Visit.objects.select_for_update",
            side_effect=RuntimeError("private"),
        ):
            self.assertEqual(self.signal(token).status_code, 204)
        with override_settings(ANALYTICS_ENABLED=False):
            self.signal(token)
            response = self.browser.get("/")
            self.assertNotContains(response, 'name="rasel-activity"')
        staff = get_user_model().objects.create_user("qualitystaff", is_staff=True)
        self.browser.force_login(staff)
        self.signal(token)
        self.assertEqual(DailyTotal.objects.get().active_visits, 0)

    def test_midnight_and_legacy_are_not_backfilled(self):
        now = timezone.localtime().replace(hour=23, minute=59, second=0, microsecond=0)
        with patch("analytics.tracking.timezone.now", return_value=now):
            token = self.browser.get("/").context["analytics_activity_token"]
        with patch(
            "analytics.activity.timezone.now", return_value=now + timedelta(minutes=2)
        ):
            self.signal(token)
        self.assertEqual(DailyTotal.objects.get(day=now.date()).active_visits, 1)
        self.assertEqual(DailyTotal.objects.count(), 1)
        Visit.objects.update(quality_version=1, active=False)
        self.signal(token)
        self.assertEqual(DailyTotal.objects.get().active_visits, 1)


@override_settings(ANALYTICS_ENABLED=True, SITE_URL="https://rasel.ar")
class AttributionCookieTests(TestCase):
    def setUp(self):
        self.browser = Client(HTTP_USER_AGENT=UA)

    def contact(self):
        request = request_at()
        request.COOKIES[COOKIE] = self.browser.cookies[COOKIE].value
        return current_contact(request)

    def test_last_contact_direct_return_provider_and_replacement(self):
        response = self.browser.get(
            "/?utm_source=Instagram&utm_medium=paid&utm_campaign=septiembre"
        )
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["max-age"], 2592000)
        original = cookie.value
        for referrer in (
            "",
            "https://www.rasel.ar/shop/",
            "https://www.mercadopago.com.ar/checkout/",
        ):
            response = self.browser.get("/", HTTP_REFERER=referrer)
            self.assertNotIn(COOKIE, response.cookies)
            self.assertEqual(self.browser.cookies[COOKIE].value, original)
        self.assertEqual(self.contact()["source"], "instagram")
        self.browser.get("/?utm_source=whatsapp&utm_medium=social")
        self.assertEqual(self.contact()["source"], "whatsapp")
        self.assertEqual(self.contact()["campaign"], "")

    def test_expired_or_tampered_cookie_never_attributed(self):
        self.browser.get("/?utm_source=instagram")
        with patch(
            "analytics.attribution.timezone.now",
            return_value=timezone.now() + timedelta(days=30, seconds=1),
        ):
            self.assertIsNone(self.contact())
        self.browser.cookies[COOKIE] = "tampered"
        self.assertIsNone(self.contact())
        response = self.browser.get("/")
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)

    def test_excluded_traffic_and_invalid_campaign_never_sets_cookie(self):
        for agent in ("axios/1", "Go-http-client/2", ""):
            self.assertNotIn(
                COOKIE,
                self.browser.get(
                    "/?utm_source=instagram", HTTP_USER_AGENT=agent
                ).cookies,
            )
        self.assertNotIn(
            COOKIE,
            self.browser.get(
                "/?utm_source=instagram", HTTP_SEC_PURPOSE="prefetch"
            ).cookies,
        )
        self.assertNotIn(COOKIE, self.browser.get("/?utm_source=a@example.com").cookies)
        with override_settings(ANALYTICS_ENABLED=False):
            self.assertNotIn(COOKIE, self.browser.get("/?utm_source=instagram").cookies)


@override_settings(ANALYTICS_ENABLED=True, MP_CHECKOUT_ENABLED=False)
class CheckoutAttributionTests(TransactionTestCase):
    def setUp(self):
        product = Product.objects.create(name="Audit oil")
        self.variant = Variant.objects.create(
            product=product, name="500 ml", sku="QUALITY", price_ars=1000, stock_qty=20
        )
        self.point = PickupPoint.objects.create(name="Retiro", address="Test")
        self.browser = Client(HTTP_USER_AGENT=UA)
        self.data = dict(
            full_name="Test",
            email="test@example.com",
            phone="",
            delivery_method="pickup",
            pickup_point=self.point.pk,
            payment_method="transfer",
        )

    def add(self):
        self.browser.post(
            reverse("cart:add"), {"variant_id": self.variant.pk, "qty": 1}
        )

    def test_offline_snapshot_survives_cookie_changes_and_refunds(self):
        self.browser.get("/?utm_source=instagram&utm_campaign=launch")
        self.add()
        self.browser.post(reverse("orders:checkout"), self.data)
        order = Order.objects.get()
        self.assertEqual(order.analytics_attribution["source"], "instagram")
        self.assertEqual(
            order.analytics_attribution["visit"], self.browser.session[SESSION_KEY]
        )
        self.browser.get("/?utm_source=facebook")
        order.payment_status = "partially_refunded"
        order.mp_refunded_amount = 100
        order.save()
        report = report_context("today")
        self.assertEqual(report["attribution_rows"][0]["label"], "instagram")
        self.assertEqual(
            sum(row["total"] for row in report["attribution_rows"]),
            report["sales"]["total"],
        )
        order.payment_status = "refunded"
        order.save()
        self.assertEqual(report_context("today")["sales"]["count"], 0)

    def test_cash_direct_and_attribution_failure_do_not_block_purchase(self):
        self.add()
        self.browser.post(
            reverse("orders:checkout"), {**self.data, "payment_method": "cod"}
        )
        self.assertEqual(Order.objects.get().analytics_attribution["source"], "directo")
        self.add()
        with patch(
            "analytics.attribution.current_contact", side_effect=RuntimeError("failure")
        ):
            response = self.browser.post(reverse("orders:checkout"), self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.latest("pk").analytics_attribution, {})

    @override_settings(MP_CHECKOUT_ENABLED=True)
    def test_mp_draft_captures_campaign_before_provider_failure(self):
        from payments.mercadopago import MercadoPagoError

        self.browser.get("/?utm_source=instagram")
        self.add()
        with patch(
            "orders.views.create_checkout_preference",
            side_effect=MercadoPagoError("unavailable"),
        ):
            response = self.browser.post(
                reverse("orders:checkout"), {**self.data, "payment_method": "mp"}
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            PaymentDraft.objects.get().analytics_attribution["source"], "instagram"
        )
        self.assertEqual(DailyTotal.objects.get().active_visits, 1)


class QualityReportRetentionTests(TestCase):
    def test_no_retroactive_quality_and_bounded_sales_reconcile(self):
        now = timezone.now()
        Measurement.objects.create(started_at=now - timedelta(days=20))
        QualityMeasurement.objects.create(started_at=now)
        DailyTotal.objects.create(
            day=timezone.localdate() - timedelta(days=10), visits=500
        )
        DailyTotal.objects.create(
            day=timezone.localdate(), visits=4, quality_visits=4, active_visits=2
        )
        for index in range(11):
            Order.objects.create(
                full_name="Test",
                email="test@example.com",
                total_amount=100,
                payment_status="approved",
                analytics_attribution={
                    "source": f"campaign{index}",
                    "medium": "paid",
                    "campaign": "launch",
                },
                analytics_attributed_at=now,
            )
        Order.objects.create(
            full_name="Legacy",
            email="test@example.com",
            total_amount=50,
            payment_status="approved",
        )
        report = report_context("30")
        self.assertEqual(report["activity_percent"], 50)
        self.assertFalse(report["rows"][-11]["quality_available"])
        self.assertTrue(report["rows"][-1]["quality_available"])
        self.assertEqual(sum(row["total"] for row in report["attribution_rows"]), 1150)
        self.assertEqual(sum(row["count"] for row in report["attribution_rows"]), 12)
        self.assertEqual(report["attribution_rows"][-2]["label"], "Orígenes restantes")
        self.assertEqual(report["attribution_rows"][-1]["label"], "Sin atribución")

    def test_cleanup_erases_only_expired_metadata_and_exclusions(self):
        now = timezone.now()
        QualityMeasurement.objects.create()
        old = timezone.make_aware(
            timezone.datetime.combine(
                first_retained_day(timezone.localdate()), timezone.datetime.min.time()
            )
        ) - timedelta(days=1)
        order = Order.objects.create(
            full_name="Test",
            email="test@example.com",
            total_amount=100,
            analytics_attribution={"source": "old"},
            analytics_attributed_at=old,
        )
        draft = PaymentDraft.objects.create(
            full_name="Test",
            email="test@example.com",
            total_amount=100,
            analytics_attribution={"source": "old"},
            analytics_attributed_at=old,
        )
        DailyExclusion.objects.create(day=old.date(), reason="bot", requests=50)
        cleanup_batch(now=now, force=True)
        order.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(order.analytics_attribution, {})
        self.assertEqual(draft.analytics_attribution, {})
        self.assertEqual(order.total_amount, 100)
        self.assertFalse(DailyExclusion.objects.exists())


@override_settings(ANALYTICS_ENABLED=True)
class ConcurrentActivityTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_tabs_mark_activity_once(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        from .activity import activity

        request = request_at()
        record(request, pageview=True)
        token = signing.dumps(
            {
                "visit": request.session[SESSION_KEY],
                "issued": timezone.now().timestamp(),
            },
            salt=ACTIVITY_SALT,
        )
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            close_old_connections()
            try:
                req = RequestFactory().post(
                    "/analytics/activity/",
                    json.dumps({"event": "interaction", "token": token}),
                    content_type="application/json",
                    HTTP_USER_AGENT=UA,
                )
                req.user = AnonymousUser()
                req.session = dict(request.session)
                barrier.wait(timeout=10)
                response = activity(req)
                if response.status_code != 204:
                    errors.append(response.status_code)
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                close_old_connections()

        with self.assertNoLogs("analytics.activity", level="WARNING"):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
                self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(DailyTotal.objects.get().active_visits, 1)
