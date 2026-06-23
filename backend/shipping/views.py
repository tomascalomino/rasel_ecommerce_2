from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import ShippingZone
from .services import resolve_shipping


def _parse_subtotal(raw):
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value >= 0 else None


@require_GET
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
            "ok": q.cp is not None,
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
                str(q.remaining_for_free)
                if q.remaining_for_free is not None
                else None
            ),
            "carrier_arranged": q.carrier_arranged,
            "note": q.note,
        }
    )


def shipping_info(request):
    """Página pública que explica el sistema de envíos (precios desde el Admin)."""
    zones = ShippingZone.objects.filter(is_active=True).order_by("sort_order", "name")
    return render(request, "shipping_info.html", {"zones": zones})
