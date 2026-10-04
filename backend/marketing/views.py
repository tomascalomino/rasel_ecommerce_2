import json
import uuid

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .consent import current_consent, expiry, set_cookie
from .models import BrowserEventReceipt, Consent, MetaPurchase
from .tracking import (
    ACTIONS,
    CONTACT,
    CYCLE,
    EVENT_SALT,
    PAGE_SALT,
    eligible,
    enabled,
    update_contact,
    checkout_rows,
)


@never_cache
@require_http_methods(["GET", "POST"])
def consent(request):
    if not enabled() or not eligible(request):
        return JsonResponse({"state": "disabled"}, status=403)
    choice = current_consent(request)
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            accepted = data["accepted"]
            if not isinstance(accepted, bool):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return JsonResponse({"error": "invalid_choice"}, status=400)
        with transaction.atomic():
            if choice:
                choice = Consent.objects.select_for_update().get(pk=choice.pk)
                if choice.accepted != accepted:
                    choice.revision += 1
                choice.accepted = accepted
                choice.updated_at = timezone.now()
                choice.expires_at = expiry()
                choice.save()
            else:
                choice = Consent.objects.create(accepted=accepted, expires_at=expiry())
            if not accepted:
                MetaPurchase.objects.filter(
                    consent=choice, status__in=["pending", "sending", "failed"]
                ).update(
                    status="cancelled",
                    diagnostic="consent_withdrawn",
                    claim_id=None,
                    claim_expires_at=None,
                )
                for key in (CONTACT, ACTIONS):
                    request.session.pop(key, None)
        request._meta_consent = choice
        if accepted and data.get("pageToken"):
            try:
                page = signing.loads(data["pageToken"], salt=PAGE_SALT, max_age=1800)
                update_contact(request, page)
            except (signing.BadSignature, ValueError, TypeError, KeyError):
                pass
    accepted = bool(choice and choice.permits())
    response = JsonResponse(
        {"state": "accepted" if accepted else ("rejected" if choice else "unknown")}
    )
    if request.method == "POST":
        set_cookie(request, response, choice)
        if not accepted:
            # JS also removes host and parent-domain variants created by Meta.
            for name in ("_fbp", "_fbc"):
                response.delete_cookie(name, samesite="Lax")
    return response


@never_cache
@require_POST
def claim(request):
    choice = current_consent(request)
    if (
        not settings.META_PIXEL_ENABLED
        or not eligible(request)
        or not choice
        or not choice.permits()
    ):
        return JsonResponse({"claimed": False}, status=403)
    try:
        data = signing.loads(
            json.loads(request.body)["token"], salt=EVENT_SALT, max_age=1800
        )
        event_id = uuid.UUID(data["id"])
        if data["name"] == "AddToCart":
            valid = (
                data["consent"] == str(choice.pk)
                and data["revision"] == choice.revision
            )
        elif data["name"] == "InitiateCheckout":
            valid = data["cycle"] == request.session.get(CYCLE) and bool(
                checkout_rows(request)
            )
        else:
            valid = False
        if not valid:
            return JsonResponse({"claimed": False}, status=403)
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        return JsonResponse({"claimed": False}, status=400)
    _, created = BrowserEventReceipt.objects.get_or_create(pk=event_id)
    return JsonResponse(
        {
            "claimed": created,
            "name": data["name"],
            "id": str(event_id),
            "data": data["data"] if created else {},
        }
    )
