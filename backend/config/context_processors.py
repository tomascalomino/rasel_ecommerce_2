"""Context processors globales del sitio."""

import re

from django.conf import settings

from .pricing import get_offline_payment_discount_percent
from shipping.promotions import public_state
from django.urls import reverse


def site(request):
    """Expone datos de contacto del sitio a todos los templates."""
    number = getattr(settings, "WHATSAPP_NUMBER", "") or ""
    digits = re.sub(r"\D", "", number)
    url_name = request.resolver_match.view_name if request.resolver_match else ""
    promotion_state = public_state()
    show_banner = url_name in {
        "home",
        "shop:product_list",
        "shop:product_detail",
        "cart:detail",
    }
    campaign = promotion_state["campaign"]
    detail_slug = (
        request.resolver_match.kwargs.get("slug")
        if url_name == "shipping_promotion"
        else None
    )
    status_url = reverse("shipping:promotion_status")
    if detail_slug:
        status_url += f"?campaign={detail_slug}"
    if digits and not digits.startswith("54"):
        digits = f"549{digits}"
    return {
        "mp_checkout_enabled": settings.MP_CHECKOUT_ENABLED,
        "offline_payment_discount_percent": get_offline_payment_discount_percent(
            request
        ),
        "whatsapp_number": number,
        "whatsapp_link": f"https://wa.me/{digits}" if digits else "",
        "shipping_promotion_state": promotion_state,
        "shipping_campaign": campaign,
        "show_shipping_banner": show_banner,
        "shipping_promotion_config": {
            "state": promotion_state,
            "status_url": status_url,
            "show_banner": show_banner,
            "detail_slug": detail_slug,
        },
    }
