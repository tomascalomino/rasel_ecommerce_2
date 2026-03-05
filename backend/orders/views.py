from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from decimal import Decimal

from cart.cart import Cart
from .models import Order, OrderItem
from .forms import CheckoutForm


@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = Cart(request.session)

    if len(cart) == 0:
        return redirect("shop:product_list")

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            order = Order.objects.create(
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                address_line=form.cleaned_data["address_line"],
                city=form.cleaned_data["city"],
                postal_code=form.cleaned_data["postal_code"],
                total_amount=cart.total(),
            )

            for item in cart.items():
                OrderItem.objects.create(
                    order=order,
                    product_name=item.variant.product.name,
                    variant_name=item.variant.name,
                    unit_price=item.unit_price,
                    quantity=item.qty,
                    line_total=item.line_total,
                )

            cart.clear()

            return redirect("orders:confirmation", order_id=order.id)

    else:
        form = CheckoutForm()

    return render(request, "orders/checkout.html", {"cart": cart, "form": form})


def confirmation(request, order_id):
    return render(request, "orders/confirmation.html", {"order_id": order_id})
