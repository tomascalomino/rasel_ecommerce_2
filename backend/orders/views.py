from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from cart.cart import Cart
from payments.models import PaymentDraft
from .models import Order, OrderItem
from shop.models import Variant
from .forms import CheckoutForm
from django.db import transaction


@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = Cart(request.session)

    if len(cart) == 0:
        return redirect("shop:product_list")

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            payment_method = form.cleaned_data.get("payment_method", "mp")

            if payment_method == "transfer":
                # Implementación para Transferencia Bancaria
                with transaction.atomic():
                    # 1. Crear Orden
                    order = Order.objects.create(
                        full_name=form.cleaned_data["full_name"],
                        email=form.cleaned_data["email"],
                        phone=form.cleaned_data["phone"],
                        address_line=form.cleaned_data["address_line"],
                        city=form.cleaned_data["city"],
                        postal_code=form.cleaned_data["postal_code"],
                        total_amount=cart.total(),
                        status="pending",
                        payment_method="transfer",
                    )

                    # 2. Guardar Items y descontar stock (MVP)
                    for item in cart.items():
                        variant_id = item.variant.id
                        qty = item.qty
                        variant = Variant.objects.select_for_update().get(id=variant_id)

                        OrderItem.objects.create(
                            order=order,
                            variant=variant,
                            product_name=variant.product.name,
                            variant_name=variant.name,
                            unit_price=item.unit_price,
                            quantity=qty,
                            line_total=item.line_total,
                        )

                        if variant.stock_qty >= qty:
                            variant.stock_qty -= qty
                            variant.save(update_fields=["stock_qty"])

                    # 3. Limpiar el carrito y redirigir
                    cart.clear()
                    request.session.modified = True
                    return redirect("orders:transfer_info", order_id=order.id)
            else:
                # Implementación para Mercado Pago
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
                messages.info(
                    request,
                    "Datos guardados. Continuá con el pago para confirmar tu pedido.",
                )

                return redirect("payments:start", draft_id=draft.token)
    else:
        form = CheckoutForm()

    return render(request, "orders/checkout.html", {"cart": cart, "form": form})


def confirmation(request, order_id):
    return render(request, "orders/confirmation.html", {"order_id": order_id})


def transfer_info(request, order_id):
    from django.shortcuts import get_object_or_404

    order = get_object_or_404(Order, id=order_id)
    return render(request, "orders/transfer_info.html", {"order": order})
