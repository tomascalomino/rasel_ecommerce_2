"""First-party session counters. Never retain request payloads or network addresses."""

import logging
import ipaddress
import re
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .maintenance import cleanup_batch
from .models import (
    DailyDevice,
    DailyProduct,
    DailySource,
    DailyTotal,
    Measurement,
    Visit,
)

logger = logging.getLogger(__name__)
SESSION_KEY = "rasel_analytics_visit"
STAGES = {"cart_added", "checkout_opened", "checkout_submitted"}
BOT = re.compile(
    r"bot|crawler|spider|slurp|headless|uptimerobot|monitor|preview|facebookexternalhit|"
    r"whatsapp|curl|wget|python|http[-_]?client|lighthouse|pagespeed|pingdom|selenium",
    re.I,
)
PAGES = {
    "home",
    "about",
    "virgen_extra",
    "conservacion",
    "contact",
    "shipping_info",
    "terms",
    "privacy",
    "returns",
    "regret",
    "shop:product_list",
    "shop:product_detail",
    "cart:detail",
    "orders:checkout",
}


def eligible(request):
    return (
        settings.ANALYTICS_ENABLED
        and not getattr(request.user, "is_staff", False)
        and bool(request.META.get("HTTP_USER_AGENT", ""))
        and not BOT.search(request.META.get("HTTP_USER_AGENT", ""))
    )


def mark_stage(request, stage):
    """Queue only committed business outcomes; no analytics I/O inside checkout."""
    if stage not in STAGES:
        raise ValueError("Unknown analytics stage")

    def enqueue():
        stages = getattr(request, "_analytics_stages", set())
        stages.add(stage)
        request._analytics_stages = stages

    transaction.on_commit(enqueue, robust=True)


def mark_cart_increase(request, variant_id, previous_qty, current_qty):
    try:
        if current_qty <= previous_qty or not eligible(request):
            return
        from shop.models import Variant

        if Variant.objects.filter(
            pk=variant_id, is_active=True, product__is_active=True
        ).exists():
            mark_stage(request, "cart_added")
    except Exception:
        logger.warning("No se pudo registrar la etapa de carrito.")


def tag(value):
    # Campaign labels only, not arbitrary URLs, emails, or free-text query strings.
    value = str(value).strip().lower()
    return value if re.fullmatch(r"[a-z0-9_-]{1,64}", value) else ""


def source_for(request):
    source = tag(request.GET.get("utm_source", ""))
    if source:
        return (
            source,
            tag(request.GET.get("utm_medium", "")),
            tag(request.GET.get("utm_campaign", "")),
        )
    try:
        host = (urlsplit(request.META.get("HTTP_REFERER", "")).hostname or "").lower()
        own_host = (urlsplit("//" + request.get_host()).hostname or "").lower()
        host = host.removeprefix("www.")
        try:
            ipaddress.ip_address(host)
            return "directo", "", ""
        except ValueError:
            pass
        if host != own_host.removeprefix("www.") and re.fullmatch(
            r"[a-z0-9.-]{1,64}", host
        ):
            return host, "referencia", ""
    except ValueError:
        pass
    return "directo", "", ""


def device_for(request):
    ua = request.META.get("HTTP_USER_AGENT", "").lower()
    if "ipad" in ua or "tablet" in ua or ("android" in ua and "mobile" not in ua):
        return "tablet"
    if any(part in ua for part in ("mobile", "iphone", "ipod")):
        return "mobile"
    if any(part in ua for part in ("windows", "macintosh", "x11", "cros")):
        return "desktop"
    return "unknown"


def _increment(model, keys, field, defaults=None):
    obj, _ = model.objects.get_or_create(**keys, defaults=defaults or {})
    model.objects.filter(pk=obj.pk).update(**{field: F(field) + 1})


def record(request, *, pageview=False, stages=(), product=None):
    now = timezone.now()
    today = timezone.localdate(now)
    try:
        visit_id = uuid.UUID(str(request.session.get(SESSION_KEY, "")))
    except (ValueError, TypeError, AttributeError):
        visit_id = None
    with transaction.atomic():
        visit = (
            Visit.objects.select_for_update()
            .filter(pk=visit_id, last_seen_at__gt=now - timedelta(minutes=30))
            .first()
            if visit_id
            else None
        )
        new_visit = visit is None
        if new_visit:
            visit = Visit.objects.create(started_at=now, last_seen_at=now, day=today)
            Measurement.objects.get_or_create(pk=1, defaults={"started_at": now})
        new_stages = {stage for stage in stages if not getattr(visit, stage)}
        visit.last_seen_at = now
        for stage in new_stages:
            setattr(visit, stage, True)
        visit.save(update_fields=["last_seen_at", *sorted(new_stages)])

        # Lock days in the same order, including visits spanning midnight.
        for day in sorted({today, visit.day}):
            DailyTotal.objects.get_or_create(day=day)
            DailyTotal.objects.select_for_update().get(day=day)
        if pageview:
            DailyTotal.objects.filter(day=today).update(pageviews=F("pageviews") + 1)
        increments = {stage: F(stage) + 1 for stage in new_stages}
        if new_visit:
            increments["visits"] = F("visits") + 1
        if increments:
            DailyTotal.objects.filter(day=visit.day).update(**increments)
        if new_visit:
            source, medium, campaign = source_for(request)
            keys = dict(day=today, source=source, medium=medium, campaign=campaign)
            if (
                not DailySource.objects.filter(**keys).exists()
                and DailySource.objects.filter(day=today).count() >= 100
            ):
                keys = dict(day=today, source="otros", medium="", campaign="")
            _increment(DailySource, keys, "visits")
            _increment(
                DailyDevice, dict(day=today, device=device_for(request)), "visits"
            )
        if pageview and product:
            _increment(
                DailyProduct,
                dict(day=today, product_id=product[0]),
                "pageviews",
                defaults={"product_name": product[1][:200]},
            )
    if new_visit:
        request.session[SESSION_KEY] = str(visit.id)


class AnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.next_cleanup_check = 0

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if not eligible(request):
                return response
            name = getattr(request.resolver_match, "view_name", "")
            pageview = (
                request.method == "GET"
                and response.status_code == 200
                and response.get("Content-Type", "").startswith("text/html")
                and name in PAGES
            )
            stages = set(getattr(request, "_analytics_stages", ()))
            if pageview and name == "orders:checkout":
                stages.add("checkout_opened")
            if not pageview and not stages:
                return response
            record(
                request,
                pageview=pageview,
                stages=stages,
                product=getattr(request, "_analytics_product", None),
            )
            # Local throttle avoids querying the lease on every public request.
            if time.monotonic() >= self.next_cleanup_check:
                self.next_cleanup_check = time.monotonic() + 60
                cleanup_batch()
        except Exception:
            # Avoid logging request data, URLs, SQL parameters or identifiers.
            logger.warning("No se pudo actualizar la medición de visitas.")
        return response
