"""Dispatcher with durable claims, bounded retries and no payment network I/O."""

import re
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Consent, MetaPurchase

RETRY_WINDOW = timedelta(hours=24)
CLAIM_WINDOW = timedelta(minutes=5)


def configuration_problem():
    if not settings.META_CAPI_ENABLED:
        return "META_CAPI_ENABLED=0: envío desactivado"
    if not settings.META_CAPI_ACCESS_TOKEN:
        return "Falta META_CAPI_ACCESS_TOKEN: envío desactivado"
    if not re.fullmatch(r"\d{1,30}", settings.META_PIXEL_ID):
        return "META_PIXEL_ID inválido: envío desactivado"
    if not re.fullmatch(r"v\d+\.0", settings.META_GRAPH_API_VERSION):
        return "META_GRAPH_API_VERSION inválida: envío desactivado"
    site = urlsplit(settings.SITE_URL)
    if site.scheme != "https" or not site.hostname:
        return "SITE_URL HTTPS requerida: envío desactivado"
    return ""


def claim_event(event_pk):
    now = timezone.now()
    with transaction.atomic():
        # Same lock order as withdrawal: consent, then outbox row.
        consent_id = (
            MetaPurchase.objects.filter(pk=event_pk)
            .values_list("consent_id", flat=True)
            .first()
        )
        consent = Consent.objects.select_for_update().filter(pk=consent_id).first()
        event = MetaPurchase.objects.select_for_update().filter(pk=event_pk).first()
        if not event or event.status not in {"pending", "sending"}:
            return None
        if (
            event.status == "sending"
            and event.claim_expires_at
            and event.claim_expires_at > now
        ):
            return None
        if not consent or not consent.permits(event.consent_revision):
            event.status, event.diagnostic = "cancelled", "consent_withdrawn_or_expired"
        elif (
            event.created_at + RETRY_WINDOW <= now
            or event.occurred_at < now - timedelta(days=7)
        ):
            event.status, event.diagnostic = "expired", "delivery_window_elapsed"
        elif event.next_attempt_at > now:
            return None
        elif (
            event.pixel_id != settings.META_PIXEL_ID
            or event.test_event_code != settings.META_TEST_EVENT_CODE
        ):
            # Never silently change destination or test mode of queued events.
            event.diagnostic = "destination_or_test_mode_mismatch"
            event.save(update_fields=["diagnostic"])
            return None
        elif not re.fullmatch(r"v\d+\.0", event.graph_version):
            event.status, event.diagnostic = "failed", "invalid_frozen_graph_version"
        elif not event.payload:
            event.status, event.diagnostic = "expired", "payload_purged"
        else:
            event.status = "sending"
            event.claim_id = uuid.uuid4()
            event.claim_expires_at = now + CLAIM_WINDOW
            event.attempts += 1
        event.save()
        return event if event.status == "sending" else None


def send_event(event_pk):
    if configuration_problem():
        return "disabled"
    event = claim_event(event_pk)
    if not event:
        return "skipped"
    # Recheck immediately before HTTP. A request already in flight cannot be recalled.
    if (
        not Consent.objects.filter(
            pk=event.consent_id,
            accepted=True,
            revision=event.consent_revision,
            expires_at__gt=timezone.now(),
        ).exists()
        or not MetaPurchase.objects.filter(
            pk=event.pk, claim_id=event.claim_id, status="sending"
        ).exists()
    ):
        return "skipped"
    body = {"data": [event.payload]}
    if event.test_event_code:
        body["test_event_code"] = event.test_event_code
    status, diagnostic = "failed", "invalid_response"
    try:
        response = requests.post(
            f"https://graph.facebook.com/{event.graph_version}/{event.pixel_id}/events",
            json=body,
            headers={"Authorization": f"Bearer {settings.META_CAPI_ACCESS_TOKEN}"},
            timeout=(5, 15),
            allow_redirects=False,
        )
        try:
            result = response.json()
        except ValueError:
            result = {}
        if not isinstance(result, dict):
            result = {}
        error = result.get("error", {})
        error = error if isinstance(error, dict) else {}
        received = result.get("events_received")
        if (
            response.status_code == 200
            and type(received) is int
            and received == 1
            and not error
        ):
            status, diagnostic = "sent", "events_received_1"
        elif (
            response.status_code == 429
            or response.status_code >= 500
            or error.get("is_transient") is True
        ):
            status, diagnostic = "pending", "temporary_meta_error"
        else:
            # Do not retain/log arbitrary Meta messages, request bodies or tokens.
            code = error.get("code")
            diagnostic = f"meta_http_{response.status_code}"
            if isinstance(code, int):
                diagnostic += f"_code_{code}"
    except requests.RequestException:
        status, diagnostic = "pending", "network_error"
    now = timezone.now()
    updates = {
        "status": status,
        "diagnostic": diagnostic,
        "claim_id": None,
        "claim_expires_at": None,
    }
    if status == "sent":
        updates["sent_at"] = now
    elif status == "pending":
        updates["next_attempt_at"] = now + timedelta(
            seconds=min(3600, 60 * 2 ** min(event.attempts - 1, 6))
        )
        if now >= event.created_at + RETRY_WINDOW:
            updates.update(status="expired", diagnostic="delivery_window_elapsed")
    # Do not overwrite a withdrawal or a newer lease's result.
    MetaPurchase.objects.filter(
        pk=event.pk, status="sending", claim_id=event.claim_id
    ).update(**updates)
    return status


def due_events(order_id=None):
    now = timezone.now()
    queryset = MetaPurchase.objects.filter(
        Q(status="pending", next_attempt_at__lte=now)
        | Q(status="sending", claim_expires_at__lte=now)
    ).order_by("created_at")
    if order_id is not None:
        queryset = queryset.filter(order_id=order_id)
    return queryset
