from django.shortcuts import redirect, render
from django.contrib import messages
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .cart import Cart
from analytics.tracking import mark_cart_increase
from shop.models import Variant
from marketing.tracking import queue_cart_event
from config.pricing import get_offline_payment_discount_percent
from shop.coupons import SESSION_KEY as COUPON_SESSION_KEY, quote_coupon


def _cart_input(request, allow_zero=False):
    try:
        variant_id = int(request.POST.get("variant_id", ""))
        qty = int(request.POST.get("qty", 1))
    except (ValueError, TypeError):
        return None, None
    if qty < (0 if allow_zero else 1):
        return None, None
    variant = Variant.objects.filter(
        pk=variant_id,
        is_active=True,
        product__is_active=True,
    ).first()
    return variant, qty


def cart_detail(request):
    cart = Cart(request.session)
    rows = list(cart.items())
    subtotal = sum((item.line_total for item in rows), 0)
    quote = quote_coupon(
        request.session.get(COUPON_SESSION_KEY),
        rows,
        get_offline_payment_discount_percent(request),
    )
    return render(
        request,
        "cart/cart_detail.html",
        {
            "cart": cart,
            "coupon_quote": quote,
            "coupon_total": subtotal - quote.mp_amount,
            "cart_offline_total": subtotal
            - quote.payment_amount
            - quote.offline_amount,
        },
    )


@require_POST
@never_cache
def cart_add(request):
    cart = Cart(request.session)
    wants_json = request.headers.get("Accept") == "application/json"
    variant, qty = _cart_input(request)
    if not variant or variant.stock_qty < 1:
        error = "No se pudo agregar el producto. Revisá la presentación y cantidad."
        if wants_json:
            return JsonResponse({"error": error}, status=400)
        messages.error(request, error)
        return redirect("cart:detail")
    variant_id = variant.pk
    previous_qty = cart._cart.get(str(variant_id), {}).get("qty", 0)
    if previous_qty + qty > variant.stock_qty:
        error = "No hay stock suficiente para esa cantidad, incluyendo lo que ya tenés en el carrito."
        if wants_json:
            return JsonResponse({"error": error}, status=400)
        messages.error(request, error)
        return redirect("cart:detail")
    cart.add(variant_id=variant_id, qty=qty, override=False)
    mark_cart_increase(request, variant_id, 0, qty)
    meta_event = queue_cart_event(request, variant, qty)
    next_url = (request.POST.get("next") or "").strip()
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("shop:product_list")
    confirmation = {
        "variant_id": variant_id,
        "qty": qty,
        "continue_url": next_url,
    }
    if wants_json:
        return JsonResponse({
            "html": render_to_string(
                "partials/cart_added_summary.html",
                {**confirmation, "variant": variant, "cart_quantity": len(cart)},
                request=request,
            ),
            "cart_quantity": len(cart),
            "meta_events": [meta_event] if meta_event else [],
        })
    request.session["cart_added_confirmation"] = confirmation
    return redirect("cart:added")


@never_cache
def cart_added(request):
    confirmation = request.session.pop("cart_added_confirmation", None)
    if not confirmation:
        return redirect("cart:detail")
    variant = Variant.objects.filter(pk=confirmation["variant_id"]).select_related("product").first()
    if not variant:
        return redirect("cart:detail")
    return render(request, "cart/cart_added.html", {
        **confirmation,
        "variant": variant,
        "cart_quantity": len(Cart(request.session)),
    })


@require_POST
def cart_update(request):
    cart = Cart(request.session)
    variant, qty = _cart_input(request, allow_zero=True)
    if not variant:
        messages.error(
            request,
            "No se pudo actualizar el producto. Revisá la presentación y cantidad.",
        )
        return redirect("cart:detail")
    variant_id = variant.pk
    previous_qty = cart._cart.get(str(variant_id), {}).get("qty", 0)
    cart.set_qty(variant_id=variant_id, qty=qty)
    if previous_qty > 0:
        mark_cart_increase(request, variant_id, previous_qty, qty)
        queue_cart_event(request, variant, qty - previous_qty)
    if qty <= 0:
        messages.info(request, "Producto eliminado del carrito.")
    else:
        messages.success(request, "Cantidad actualizada.")
    return redirect("cart:detail")


@require_POST
def cart_remove(request):
    cart = Cart(request.session)
    variant_id = int(request.POST.get("variant_id"))
    cart.remove(variant_id=variant_id)
    messages.info(request, "Producto quitado del carrito.")
    return redirect("cart:detail")
