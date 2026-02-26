from django.shortcuts import redirect, render
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
    return redirect("cart:detail")


@require_POST
def cart_update(request):
    cart = Cart(request.session)
    variant_id = int(request.POST.get("variant_id"))
    qty = int(request.POST.get("qty", 1))
    cart.set_qty(variant_id=variant_id, qty=qty)
    return redirect("cart:detail")


@require_POST
def cart_remove(request):
    cart = Cart(request.session)
    variant_id = int(request.POST.get("variant_id"))
    cart.remove(variant_id=variant_id)
    return redirect("cart:detail")
