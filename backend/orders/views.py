from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from cart.cart import Cart
from payments.models import PaymentDraft
from .forms import CheckoutForm


@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = Cart(request.session)

    if len(cart) == 0:
        return redirect("shop:product_list")

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            draft_items = []
            for item in cart.items():
                draft_items.append(
                    {
                        "variant_id": item.variant.id,
                        "product_name": item.variant.product.name,
                        "variant_name": item.variant.name,
                        "unit_price": str(item.unit_price),
                        "quantity": int(item.qty),
                        "line_total": str(item.line_total),
                    }
                )

            draft = PaymentDraft.objects.create(
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                address_line=form.cleaned_data["address_line"],
                city=form.cleaned_data["city"],
                postal_code=form.cleaned_data["postal_code"],
                total_amount=cart.total(),
                items=draft_items,
            )

            request.session["active_payment_draft"] = str(draft.token)
            request.session.modified = True

            return redirect("payments:start", draft_id=draft.token)

    else:
        form = CheckoutForm()

    return render(request, "orders/checkout.html", {"cart": cart, "form": form})


def confirmation(request, order_id):
    return render(request, "orders/confirmation.html", {"order_id": order_id})
