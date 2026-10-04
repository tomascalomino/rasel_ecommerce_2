from datetime import timedelta

from django.core import signing
from django.utils import timezone

from .models import Consent

COOKIE = "rasel_meta_consent"
SALT = "marketing.consent.v1"
MAX_AGE = 180 * 24 * 60 * 60


def current_consent(request):
    if hasattr(request, "_meta_consent"):
        return request._meta_consent
    try:
        consent_id = signing.loads(
            request.COOKIES.get(COOKIE, ""), salt=SALT, max_age=MAX_AGE
        )
        consent = Consent.objects.filter(
            pk=consent_id, expires_at__gt=timezone.now()
        ).first()
    except (signing.BadSignature, ValueError, TypeError, AttributeError):
        consent = None
    request._meta_consent = consent
    return consent


def set_cookie(request, response, consent):
    response.set_cookie(
        COOKIE,
        signing.dumps(str(consent.pk), salt=SALT),
        max_age=MAX_AGE,
        httponly=True,
        secure=request.is_secure(),
        samesite="Lax",
    )


def expiry():
    return timezone.now() + timedelta(seconds=MAX_AGE)
