"""Context processors globales del sitio."""

import re

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .pricing import get_offline_payment_discount_percent
from shipping.promotions import public_state
from shop.gifts import GIFT_END, gift_state


def site(request):
    """Expone datos de contacto del sitio a todos los templates."""
    number = getattr(settings, "WHATSAPP_NUMBER", "") or ""
    digits = re.sub(r"\D", "", number)
    url_name = request.resolver_match.view_name if request.resolver_match else ""
    show_banner = url_name in {
        "home",
        "shop:product_list",
        "shop:product_detail",
        "cart:detail",
    }
    now = timezone.now()
    show_checkout = url_name == "orders:checkout"
    show_gift_banner = show_banner and now < GIFT_END
    shipping_config = None
    if show_banner or show_checkout or url_name in {"shipping_info", "shipping_promotion"}:
        status_url = reverse("shipping:promotion_status")
        if url_name == "shipping_promotion":
            status_url += f"?campaign={request.resolver_match.kwargs['slug']}"
        shipping_config = {
            "state": public_state(
                now, detail=getattr(request, "_shipping_promotion_detail", None)
            ),
            "status_url": status_url,
        }
    if digits and not digits.startswith("54"):
        digits = f"549{digits}"
    return {
        "mp_checkout_enabled": settings.MP_CHECKOUT_ENABLED,
        "cyber_gift": gift_state(now) if show_gift_banner else None,
        "show_gift_banner": show_gift_banner,
        "show_gift_updates": show_gift_banner,
        "offline_payment_discount_percent": get_offline_payment_discount_percent(
            request
        ),
        "whatsapp_number": number,
        "whatsapp_link": f"https://wa.me/{digits}" if digits else "",
        "shipping_campaign": shipping_config["state"]["campaign"] if shipping_config else None,
        "show_shipping_banner": show_banner,
        "shipping_promotion_config": shipping_config,
    }
