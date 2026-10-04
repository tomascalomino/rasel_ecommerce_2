"""Scheduled CABA campaigns and signed acceptance of server shipping quotes."""

import re
from datetime import timedelta
from decimal import Decimal

from django.core import signing
from django.utils import timezone

from .models import ShippingPromotion

QUOTE_SALT = "rasel.shipping.quote.v1"
SNAPSHOT_FIELDS = (
    "shipping_promotion",
    "shipping_promotion_label",
    "shipping_promotion_applied_at",
    "shipping_cost_before_promotion",
)


def compact_cp(raw):
    return re.sub(r"[\s-]", "", str(raw or "")).upper()


def is_caba_cp(raw):
    return bool(
        re.fullmatch(r"(?:1[0-4]\d{2}|C1[0-4]\d{2}(?:[A-Z]{3})?)", compact_cp(raw))
    )


def contradictory_cp(raw):
    match = re.fullmatch(r"([A-Z])(\d{4})(?:[A-Z]{3})?", compact_cp(raw))
    if not match:
        return False
    letter, number = match.groups()
    return (letter == "C") != (1000 <= int(number) <= 1499)


def active_promotion(now=None):
    now = now or timezone.now()
    return (
        ShippingPromotion.objects.filter(
            enabled=True,
            published_at__isnull=False,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("starts_at", "pk")
        .first()
    )


def promotion_data(promotion, now=None):
    if promotion is None:
        return None
    now = now or timezone.now()
    return {
        "id": promotion.pk,
        "title": promotion.title,
        "url": promotion.get_absolute_url(),
        "state": promotion.state_at(now),
        "starts_at": promotion.starts_at.isoformat(),
        "ends_at": promotion.ends_at.isoformat(),
        "dates": f"Del {timezone.localtime(promotion.starts_at):%d/%m} al {timezone.localtime(promotion.ends_at - timedelta(microseconds=1)):%d/%m}",
    }


def public_state(now=None, detail=None):
    now = now or timezone.now()
    campaigns = list(
        ShippingPromotion.objects.filter(
            published_at__isnull=False, ends_at__gt=now
        ).order_by("starts_at", "pk")
    )
    current = next((p for p in campaigns if p.starts_at <= now and p.enabled), None)
    current = current or next((p for p in campaigns if p.starts_at <= now), None)
    changes = [t for p in campaigns for t in (p.starts_at, p.ends_at) if t > now]
    return {
        "server_now": now.isoformat(),
        "campaign": promotion_data(current, now),
        "next_change_at": min(changes).isoformat() if changes else None,
        "detail": promotion_data(detail, now),
    }


def quote_payload(raw_cp, subtotal, quote):
    return {
        "cp": compact_cp(raw_cp),
        "subtotal": str(Decimal(subtotal or 0).quantize(Decimal("0.01"))),
        "cost": str(quote.cost.quantize(Decimal("0.01"))),
        "carrier": quote.carrier_arranged,
        "cod": quote.cod_allowed,
    }


def sign_quote(raw_cp, subtotal, quote):
    return signing.dumps(
        quote_payload(raw_cp, subtotal, quote), salt=QUOTE_SALT, compress=True
    )


class ShippingQuoteChanged(ValueError):
    def __init__(self, quote):
        self.quote = quote
        super().__init__(
            "Revisá el envío y confirmá el total actualizado antes de continuar. La cotización anterior puede haber cambiado o vencido."
        )


def confirm_quote(raw_cp, subtotal, token, now=None):
    from .services import resolve_shipping

    quote = resolve_shipping(raw_cp, subtotal=subtotal, now=now)
    try:
        accepted = signing.loads(token or "", salt=QUOTE_SALT)
    except (signing.BadSignature, TypeError, ValueError):
        raise ShippingQuoteChanged(quote) from None
    if accepted != quote_payload(raw_cp, subtotal, quote):
        raise ShippingQuoteChanged(quote)
    return quote


def quote_delivery(quote):
    return {
        "shipping_cost": quote.cost,
        "shipping_zone": quote.zone_name,
        "shipping_carrier_arranged": quote.carrier_arranged,
        **quote.promotion_snapshot,
    }


def revalidate_delivery(customer, delivery, subtotal, token, now):
    if delivery["delivery_method"] == "pickup":
        return delivery
    quote = confirm_quote(customer["postal_code"], subtotal, token, now)
    return {**delivery, **quote_delivery(quote), "cod_allowed": quote.cod_allowed}
