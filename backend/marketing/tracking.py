"""Optional public browser events; keep internal analytics independent."""

import logging
import re
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import timezone

from analytics.classification import PAGES, exclusion_reason
from cart.cart import Cart

from .consent import current_consent

logger = logging.getLogger(__name__)
EVENT_SALT = "marketing.browser.v1"
CYCLE = "rasel_meta_checkout_cycle"
ACTIONS = "rasel_meta_cart_events"
CONTACT = "rasel_meta_contact"
PAGE_SALT = "marketing.page.v1"
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def enabled():
    return settings.META_PIXEL_ENABLED or settings.META_CAPI_ENABLED


def eligible(request):
    return not exclusion_reason(request)


def public_page(request):
    match = request.resolver_match
    return match and match.view_name in PAGES and eligible(request)


def public_url(request):
    # Public allowlisted paths only, no payment IDs or arbitrary query strings.
    return settings.SITE_URL.rstrip("/") + request.path


def page_contact(request):
    utms = {
        key: value
        for key in UTM_KEYS
        if re.fullmatch(r"[a-zA-Z0-9_. -]{1,128}", value := request.GET.get(key, ""))
    }
    try:
        referrer = (
            urlsplit(request.META.get("HTTP_REFERER", "")).hostname or ""
        ).lower()
    except ValueError:
        referrer = ""
    own = (urlsplit(settings.SITE_URL).hostname or request.get_host()).removeprefix(
        "www."
    )
    external = bool(
        referrer
        and referrer.removeprefix("www.") != own
        and not any(
            referrer == host or referrer.endswith("." + host)
            for host in ("mercadopago.com", "mercadopago.com.ar")
        )
    )
    return {"url": public_url(request), "utms": utms, "external": external}


def update_contact(request, page=None):
    consent = current_consent(request)
    if not consent or not consent.permits():
        return
    now = timezone.now()
    contact = request.session.get(CONTACT, {})
    if contact and (
        contact.get("consent") != str(consent.pk)
        or contact.get("revision") != consent.revision
        or contact.get("expires", 0) <= now.timestamp()
    ):
        contact = {}
        request.session.pop(CONTACT, None)
    page = page or page_contact(request)
    if page["utms"] or page["external"] or not contact:
        request.session[CONTACT] = {
            "url": page["url"],
            "utms": page["utms"],
            "consent": str(consent.pk),
            "revision": consent.revision,
            "expires": (now + timedelta(days=30)).timestamp(),
        }


def checkout_snapshot(request):
    snapshot = {"web_checkout_id": uuid.uuid4()}
    if not enabled() or not eligible(request):
        return snapshot
    try:
        consent = current_consent(request)
        if not consent or not consent.permits():
            return snapshot
        update_contact(request)
        contact = request.session.get(CONTACT, {})
        context = {
            "consent_revision": consent.revision,
            "event_source_url": settings.SITE_URL.rstrip("/")
            + reverse("orders:checkout"),
            "source_url": contact.get("url", ""),
            "utms": contact.get("utms", {}),
            "client_user_agent": request.META.get("HTTP_USER_AGENT", "")[:1024],
        }
        for key, cookie in (("fbp", "_fbp"), ("fbc", "_fbc")):
            value = request.COOKIES.get(cookie, "")
            if re.fullmatch(r"fb\.\d+\.\d+\.[A-Za-z0-9_.-]{1,400}", value):
                context[key] = value
        # No IP extraction: the production proxy trust chain is unverified.
        snapshot.update(
            marketing_consent=consent,
            marketing_context=context,
            marketing_captured_at=timezone.now(),
        )
    except Exception:
        logger.warning("No se pudo preparar el contexto opcional de Meta.")
    return snapshot


def commerce_data(rows):
    return {
        "content_type": "product",
        "currency": "ARS",
        "content_ids": [str(row.variant.pk) for row in rows],
        "contents": [{"id": str(row.variant.pk), "quantity": row.qty} for row in rows],
        "num_items": sum(row.qty for row in rows),
        "value": float(sum(row.line_total for row in rows)),
    }


def checkout_rows(request):
    cart = Cart(request.session)
    rows = list(cart.items())
    if len(rows) != len(cart._cart) or any(
        not row.variant.product.is_active
        or row.qty <= 0
        or row.qty > row.variant.stock_qty
        for row in rows
    ):
        return []
    return rows


def queue_cart_event(request, variant, quantity):
    if not settings.META_PIXEL_ENABLED or not eligible(request) or quantity <= 0:
        return
    try:
        consent = current_consent(request)
        if not consent or not consent.permits():
            return
        actions = request.session.get(ACTIONS, [])[-19:]
        actions.append(
            {
                "id": str(uuid.uuid4()),
                "name": "AddToCart",
                "consent": str(consent.pk),
                "revision": consent.revision,
                "data": {
                    "content_type": "product",
                    "currency": "ARS",
                    "content_ids": [str(variant.pk)],
                    "contents": [{"id": str(variant.pk), "quantity": quantity}],
                    "value": float(variant.price_ars * quantity),
                },
            }
        )
        request.session[ACTIONS] = actions
    except Exception:
        logger.warning("No se pudo preparar la acción opcional de Meta.")


def context(request):
    if not enabled() or not public_page(request):
        return {}
    try:
        consent = current_consent(request)
        accepted = bool(consent and consent.permits())
        update_contact(request)
        match = request.resolver_match.view_name
        events = []
        if settings.META_PIXEL_ENABLED:
            if accepted:
                for action in request.session.pop(ACTIONS, []):
                    if (
                        action["consent"] == str(consent.pk)
                        and action["revision"] == consent.revision
                    ):
                        events.append({"token": signing.dumps(action, salt=EVENT_SALT)})
            if match == "orders:checkout":
                rows = checkout_rows(request)
                if rows:
                    cycle = request.session.get(CYCLE)
                    if not cycle:
                        cycle = str(uuid.uuid4())
                        request.session[CYCLE] = cycle
                    action = {
                        "id": cycle,
                        "cycle": cycle,
                        "name": "InitiateCheckout",
                        "data": commerce_data(rows),
                    }
                    events.append({"token": signing.dumps(action, salt=EVENT_SALT)})
        return {
            "meta_public": True,
            "meta_noscript": accepted and settings.META_PIXEL_ENABLED,
            "meta_pixel_id": settings.META_PIXEL_ID,
            "meta_config": {
                "pixelId": settings.META_PIXEL_ID,
                "pixelEnabled": settings.META_PIXEL_ENABLED,
                "state": (
                    "accepted" if accepted else ("rejected" if consent else "unknown")
                ),
                "consentEndpoint": reverse("marketing:consent"),
                "claimEndpoint": reverse("marketing:claim"),
                "csrf": get_token(request),
                "pageToken": signing.dumps(page_contact(request), salt=PAGE_SALT),
                "product": match == "shop:product_detail",
                "events": events,
            },
        }
    except Exception:
        logger.warning("No se pudo preparar la medición opcional de Meta.")
        return {}
