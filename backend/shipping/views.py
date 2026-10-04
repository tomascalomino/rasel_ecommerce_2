from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import ShippingPromotion, ShippingZone
from .promotions import contradictory_cp, promotion_data, public_state, sign_quote
from .services import resolve_shipping


def _parse_subtotal(raw):
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return (
        value
        if value.is_finite() and 0 <= value <= Decimal("99999999999999.99")
        else None
    )


@require_GET
@never_cache
def quote(request):
    """
    Endpoint AJAX para el checkout: dado un código postal (y el subtotal del
    carrito) devuelve la zona, el costo y la localidad/provincia para confirmar
    en vivo de dónde es y cuánto sale el envío.
    """
    raw_cp = request.GET.get("postal_code", "") or request.GET.get("cp", "")
    subtotal = _parse_subtotal(request.GET.get("subtotal"))
    q = resolve_shipping(raw_cp, subtotal=subtotal)
    return JsonResponse(
        {
            "ok": q.cp is not None and not contradictory_cp(raw_cp),
            "cp": q.cp,
            "locality": q.locality,
            "province": q.province,
            "location_label": q.location_label,
            "zone_code": q.zone_code,
            "zone_name": q.zone_name,
            "cost": str(q.cost),
            "cost_display": q.cost_display,
            "free": q.is_free,
            "free_over": str(q.free_over) if q.free_over is not None else None,
            "remaining_for_free": (
                str(q.remaining_for_free) if q.remaining_for_free is not None else None
            ),
            "carrier_arranged": q.carrier_arranged,
            "note": q.note,
            "cod_allowed": q.cod_allowed,
            "promotion": promotion_data(q.promotion),
            "quote_token": (
                sign_quote(raw_cp, subtotal, q)
                if q.cp is not None and not contradictory_cp(raw_cp)
                else ""
            ),
        }
    )


def shipping_info(request):
    """Página pública que explica el sistema de envíos (precios desde el Admin)."""
    zones = ShippingZone.objects.filter(is_active=True).order_by("sort_order", "name")
    return render(request, "shipping_info.html", {"zones": zones})


@require_GET
@never_cache
def promotion_status(request):
    detail = None
    if request.GET.get("campaign"):
        detail = get_object_or_404(
            ShippingPromotion, slug=request.GET["campaign"], published_at__isnull=False
        )
    return JsonResponse(public_state(detail=detail))


@require_GET
@never_cache
def promotion_detail(request, slug):
    campaign = get_object_or_404(
        ShippingPromotion, slug=slug, published_at__isnull=False
    )
    return render(
        request, "shipping/promotion_detail.html", {"promotion_detail": campaign}
    )
