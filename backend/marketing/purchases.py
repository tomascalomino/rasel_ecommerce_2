"""Transactional outbox creation. Never perform network I/O here."""

import hashlib
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Consent, MetaPurchase


def hashed(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def user_data(order):
    context = order.marketing_context
    result = {"em": [hashed(order.email.strip().lower())]}
    # Local/ambiguous numbers are omitted; do not invent a country/mobile prefix.
    phone = re.sub(r"[\s().-]", "", order.phone)
    if re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        result["ph"] = [hashed(phone[1:])]
    for field in ("fbp", "fbc", "client_user_agent"):
        if context.get(field):
            result[field] = context[field]
    return result


def confirmation_time(provider_time=None):
    try:
        value = (
            parse_datetime(provider_time) if isinstance(provider_time, str) else None
        )
        if value and timezone.is_aware(value) and value <= timezone.now():
            return value
    except (ValueError, TypeError):
        pass
    return timezone.now()


def record_purchase(order, provider_time=None):
    """Call inside the payment transaction, with the order already locked.

    paid_at is the permanent first-confirmation latch, even after audit cleanup.
    A repeated approval never reconstructs an old purchase event.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Purchase must be recorded in the payment transaction")
    if order.payment_status != "approved" or order.paid_at is not None:
        return
    order.paid_at = confirmation_time(provider_time)
    order.save(update_fields=["paid_at"])
    if not order.web_checkout_id or not order.marketing_consent_id:
        return
    consent = (
        Consent.objects.select_for_update()
        .filter(pk=order.marketing_consent_id)
        .first()
    )
    revision = order.marketing_context.get("consent_revision")
    if not consent or not consent.permits(revision) or revision is None:
        return
    event_id = f"purchase_{order.web_checkout_id}"
    items = list(order.items.all())
    contents = [
        {
            "id": str(item.variant_id_snapshot),
            "quantity": item.quantity,
            "item_price": float(item.unit_price),
        }
        for item in items
        if item.variant_id_snapshot is not None
    ]
    payload = {
        "event_name": "Purchase",
        "event_id": event_id,
        "event_time": int(order.paid_at.timestamp()),
        "action_source": "website",
        "event_source_url": order.marketing_context["event_source_url"],
        "user_data": user_data(order),
        "custom_data": {
            "currency": "ARS",
            "value": float(order.total_amount),
            "order_id": str(order.pk),
            "content_type": "product",
            "contents": contents,
            "content_ids": [row["id"] for row in contents],
            "num_items": sum(item.quantity for item in items),
        },
    }
    MetaPurchase.objects.get_or_create(
        order=order,
        defaults={
            "consent": consent,
            "consent_revision": revision,
            "event_id": event_id,
            "occurred_at": order.paid_at,
            "payload": payload,
            "pixel_id": settings.META_PIXEL_ID,
            "graph_version": settings.META_GRAPH_API_VERSION,
            "test_event_code": settings.META_TEST_EVENT_CODE,
        },
    )
