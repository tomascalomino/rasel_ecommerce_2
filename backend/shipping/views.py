from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import ShippingZone
from .services import resolve_shipping


@require_GET
def quote(request):
    """
    Endpoint AJAX para el checkout: dado un código postal devuelve la zona,
    el costo y la localidad/provincia para confirmar en vivo de dónde es.
    """
    raw_cp = request.GET.get("postal_code", "") or request.GET.get("cp", "")
    q = resolve_shipping(raw_cp)
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
        }
    )


def shipping_info(request):
    """Página pública que explica el sistema de envíos (precios desde el Admin)."""
    zones = ShippingZone.objects.filter(is_active=True).order_by("sort_order", "name")
    return render(request, "shipping_info.html", {"zones": zones})
