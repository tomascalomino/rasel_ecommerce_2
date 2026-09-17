"""Last non-direct contact, independent from the cart/session lifetime."""

import logging
import re
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.utils import timezone

from .classification import eligible

logger = logging.getLogger(__name__)
COOKIE = "rasel_attribution"
SALT = "analytics.attribution.v1"
MAX_AGE = 30 * 24 * 60 * 60


def external_contact(request):
    from .tracking import source_for

    contact = source_for(request)
    if contact[0] == "directo":
        return None
    if contact[1] == "referencia":
        host = contact[0]
        own = (urlsplit(settings.SITE_URL).hostname or "").removeprefix("www.")
        if host == own or any(
            host == domain or host.endswith("." + domain)
            for domain in ("mercadopago.com", "mercadopago.com.ar")
        ):
            return None
    return contact


def current_contact(request):
    raw = request.COOKIES.get(COOKIE, "")
    try:
        data = signing.loads(raw, salt=SALT, max_age=MAX_AGE)
        if not isinstance(data, dict) or set(data) != {
            "source",
            "medium",
            "campaign",
            "at",
        }:
            return None
        if not re.fullmatch(r"[a-z0-9.-]{1,64}|[a-z0-9_-]{1,64}", data["source"]):
            return None
        if any(
            not re.fullmatch(r"[a-z0-9_-]{0,64}", data[key])
            for key in ("medium", "campaign")
        ):
            return None
        touched = timezone.datetime.fromisoformat(data["at"])
        now = timezone.now()
        if (
            timezone.is_naive(touched)
            or not now - timedelta(seconds=MAX_AGE) < touched <= now
        ):
            return None
        return data
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        return None


def update_cookie(request, response):
    contact = external_contact(request)
    if contact:
        value = dict(zip(("source", "medium", "campaign"), contact))
        value["at"] = timezone.now().isoformat()
        response.set_cookie(
            COOKIE,
            signing.dumps(value, salt=SALT),
            max_age=MAX_AGE,
            httponly=True,
            secure=request.is_secure() or not settings.DEBUG,
            samesite="Lax",
        )
    elif COOKIE in request.COOKIES and not current_contact(request):
        response.delete_cookie(COOKIE, samesite="Lax")


def checkout_snapshot(request):
    """Optional metadata only: no analytics I/O inside business transactions."""
    try:
        if not eligible(request):
            return {}
        now = timezone.now()
        contact = current_contact(request)
        # A tagged checkout can itself be a new marketing contact.
        external = external_contact(request)
        if external:
            contact = dict(zip(("source", "medium", "campaign"), external))
            contact["at"] = now.isoformat()
        snapshot = contact or {
            "source": "directo",
            "medium": "",
            "campaign": "",
            "at": None,
        }
        snapshot = {**snapshot, "captured_at": now.isoformat()}
        visit = getattr(request, "_analytics_candidate", None)
        if visit is not None:
            snapshot.update(
                visit=str(uuid.UUID(str(visit.id))),
                visit_started_at=visit.started_at.isoformat(),
            )
        return snapshot
    except Exception:
        logger.warning("No se pudo preparar la atribución del checkout.")
        return {}
