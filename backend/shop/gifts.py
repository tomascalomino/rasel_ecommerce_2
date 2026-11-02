"""Campaña Cyber Monday 2026: una mini por checkout, con cierre argentino."""

from datetime import datetime, timezone as dt_timezone

from django.core import signing
from django.utils import timezone

from .models import CommercialSettings

GIFT_LABEL = "Mini RaSel de 28 ml"
GIFT_END = datetime(2026, 11, 9, 3, tzinfo=dt_timezone.utc)
GIFT_FIELDS = ("gift_label", "gift_applied_at")
OFFER_SALT = "rasel.cyber-gift.2026"


def gift_state(now=None):
    now = now or timezone.now()
    config = CommercialSettings.objects.filter(pk=1).values(
        "cyber_gift_enabled", "cyber_gift_started_at"
    ).first()
    start = config["cyber_gift_started_at"] if config else None
    return {
        "active": bool(config and config["cyber_gift_enabled"] and start and start <= now < GIFT_END),
        "starts_at": start.isoformat() if start else None,
        "ends_at": GIFT_END.isoformat(),
        "server_now": now.isoformat(),
    }


def _offer(state):
    return {"active": state["active"], "starts_at": state["starts_at"] if state["active"] else None}


def offer_token(state):
    return signing.dumps(_offer(state), salt=OFFER_SALT)


class GiftOfferChanged(ValueError):
    pass


def checkout_gift(token, now):
    state = gift_state(now)
    try:
        accepted = signing.loads(token or "", salt=OFFER_SALT)
    except (signing.BadSignature, TypeError, ValueError):
        accepted = {"active": False, "starts_at": None}
    if accepted != _offer(state):
        raise GiftOfferChanged(
            "La promoción de la mini RaSel cambió o terminó. Revisá el regalo en el resumen y volvé a confirmar tu compra. Todavía no creamos el pedido ni reservamos stock."
        )
    return {"gift_label": GIFT_LABEL, "gift_applied_at": now} if state["active"] else {}
