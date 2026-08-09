from django.shortcuts import redirect, render
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .cart import Cart


def cart_detail(request):
    cart = Cart(request.session)
    return render(request, "cart/cart_detail.html", {"cart": cart})


@require_POST
def cart_add(request):
    cart = Cart(request.session)
    variant_id = int(request.POST.get("variant_id"))
    qty = int(request.POST.get("qty", 1))
    cart.add(variant_id=variant_id, qty=qty, override=False)
    messages.success(request, "Producto agregado al carrito.")
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("cart:detail")


@require_POST
def cart_update(request):
    cart = Cart(request.session)
    variant_id = int(request.POST.get("variant_id"))
    qty = int(request.POST.get("qty", 1))
    cart.set_qty(variant_id=variant_id, qty=qty)
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
