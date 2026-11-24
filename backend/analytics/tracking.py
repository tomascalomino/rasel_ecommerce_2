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
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from .maintenance import CLEANUP_INTERVAL, cleanup_batch
from .classification import PAGES, eligible, exclusion_reason
from .models import (
    DailyDevice,
    DailyProduct,
    DailySource,
    DailyTotal,
    Measurement,
    Visit,
    DailyExclusion,
    QualityMeasurement,
)

logger = logging.getLogger(__name__)
SESSION_KEY = "rasel_analytics_visit"
STAGES = {"cart_added", "checkout_opened", "checkout_submitted"}


def _session_visit_id(request):
    try:
        return uuid.UUID(str(request.session.get(SESSION_KEY, "")))
    except (ValueError, TypeError, AttributeError):
        return None


def prepare_visit(request):
    now = timezone.now()
    visit_id = _session_visit_id(request)
    visit = (
        Visit.objects.filter(
            pk=visit_id, last_seen_at__gt=now - timedelta(minutes=30)
        ).first()
        if visit_id
        else None
    )
    request._analytics_candidate = visit or Visit(
        started_at=now, last_seen_at=now, day=timezone.localdate(now), quality_version=2
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


def mark_cart_increase(request, previous_qty, current_qty):
    """Record an increase after the cart view validates the variant."""
    try:
        if current_qty > previous_qty and eligible(request):
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


def _increment(model, keys, counts, defaults=None):
    rows = model.objects.filter(**keys)
    updates = {field: F(field) + count for field, count in counts.items()}
    if rows.update(**updates):
        return False
    _, created = model.objects.get_or_create(
        **keys, defaults={**(defaults or {}), **counts}
    )
    if not created:
        rows.update(**updates)
    return created


def _count_product(day, product):
    if product:
        _increment(
            DailyProduct,
            {"day": day, "product_id": product[0]},
            {"pageviews": 1},
            defaults={"product_name": product[1][:200]},
        )


def _count_source(request, day):
    # The DailyTotal write for a new visit serializes the per-day source cap.
    source, medium, campaign = source_for(request)
    keys = dict(day=day, source=source, medium=medium, campaign=campaign)
    if DailySource.objects.filter(**keys).update(visits=F("visits") + 1):
        return
    if DailySource.objects.filter(day=day).count() >= 100:
        keys = dict(day=day, source="otros", medium="", campaign="")
    _increment(DailySource, keys, {"visits": 1})


def record(request, *, pageview=False, stages=(), product=None):
    now = timezone.now()
    today = timezone.localdate(now)
    visit_id = _session_visit_id(request)
    current_visits = Visit.objects.filter(
        pk=visit_id, last_seen_at__gt=now - timedelta(minutes=30)
    )
    stages = set(stages)
    with transaction.atomic():
        if (
            visit_id and pageview and not stages
            and current_visits.update(last_seen_at=Greatest("last_seen_at", Value(now)))
        ):
            _increment(DailyTotal, {"day": today}, {"pageviews": 1})
            _count_product(today, product)
            return

        visit = current_visits.select_for_update().first() if visit_id else None
        new_visit = visit is None
        has_activity = bool(stages & {"cart_added", "checkout_submitted"})
        if new_visit:
            candidate = getattr(request, "_analytics_candidate", None)
            new_stages = stages
            became_active = has_activity
            visit = Visit.objects.create(
                **(
                    {"id": candidate.id}
                    if candidate is not None and candidate._state.adding
                    else {}
                ),
                started_at=now,
                last_seen_at=now,
                day=today,
                quality_version=2,
                active=became_active,
                **dict.fromkeys(new_stages, True),
            )
            Measurement.objects.get_or_create(pk=1, defaults={"started_at": now})
            QualityMeasurement.objects.get_or_create(pk=1, defaults={"started_at": now})
        else:
            new_stages = {stage for stage in stages if not getattr(visit, stage)}
            became_active = (
                visit.quality_version == 2 and not visit.active and has_activity
            )
            visit.last_seen_at = max(visit.last_seen_at, now)
            for stage in new_stages:
                setattr(visit, stage, True)
            fields = ["last_seen_at", *sorted(new_stages)]
            if became_active:
                visit.active = True
                fields.append("active")
            visit.save(update_fields=fields)

        increments = dict.fromkeys(new_stages, 1)
        if new_visit:
            increments.update(visits=1, quality_visits=1)
        if became_active:
            increments["active_visits"] = 1
        counts_by_day = {visit.day: increments} if increments else {}
        if pageview:
            counts_by_day.setdefault(today, {})["pageviews"] = 1
        # Updates lock only affected days, in the same order across midnight.
        for day, counts in sorted(counts_by_day.items()):
            _increment(DailyTotal, {"day": day}, counts)
        if new_visit:
            _count_source(request, today)
            _increment(
                DailyDevice, dict(day=today, device=device_for(request)), {"visits": 1}
            )
        if pageview:
            _count_product(today, product)
    if new_visit:
        request.session[SESSION_KEY] = str(visit.id)


class AnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.next_cleanup_check = 0

    def maybe_cleanup(self):
        if time.monotonic() >= self.next_cleanup_check:
            self.next_cleanup_check = time.monotonic() + CLEANUP_INTERVAL.total_seconds()
            cleanup_batch()

    def process_view(self, request, view_func, view_args, view_kwargs):
        name = getattr(request.resolver_match, "view_name", "")
        if request.method == "GET" and name in PAGES:
            try:
                if eligible(request):
                    prepare_visit(request)
            except Exception:
                logger.warning("No se pudo preparar la medición de visitas.")

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if not settings.ANALYTICS_ENABLED:
                return response
            name = getattr(request.resolver_match, "view_name", "")
            pageview = (
                request.method == "GET"
                and response.status_code == 200
                and response.get("Content-Type", "").startswith("text/html")
                and name in PAGES
            )
            stages = set(getattr(request, "_analytics_stages", ()))
            if not pageview and not stages:
                return response
            reason = exclusion_reason(request)
            if reason:
                if pageview:
                    with transaction.atomic():
                        created = _increment(
                            DailyExclusion,
                            dict(day=timezone.localdate(), reason=reason),
                            {"requests": 1},
                        )
                        if created:
                            QualityMeasurement.objects.get_or_create(pk=1)
                    self.maybe_cleanup()
                return response
            if pageview and name == "orders:checkout":
                stages.add("checkout_opened")
            record(
                request,
                pageview=pageview,
                stages=stages,
                product=getattr(request, "_analytics_product", None),
            )
            if pageview:
                from .attribution import update_cookie

                update_cookie(request, response)
            # Local throttle avoids querying the lease on every public request.
            self.maybe_cleanup()
        except Exception:
            # Avoid logging request data, URLs, SQL parameters or identifiers.
            logger.warning("No se pudo actualizar la medición de visitas.")
        return response
