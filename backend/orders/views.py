from decimal import Decimal

from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from cart.cart import Cart
from payments.models import PaymentDraft
from shipping.models import PickupPoint
from shipping.services import resolve_shipping
from .models import Order, OrderItem
from .emails import send_order_confirmation
from shop.models import Variant
from .forms import CheckoutForm
from django.db import transaction


def _render_checkout(request, cart, form):
    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "form": form,
            "mp_enabled": settings.MP_ENABLED,
            "pickup_points": PickupPoint.objects.filter(is_active=True),
        },
    )


@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = Cart(request.session)

    if len(cart) == 0:
        return redirect("shop:product_list")

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            payment_method = form.cleaned_data.get("payment_method", "mp")
            delivery_method = form.cleaned_data["delivery_method"]
            subtotal = cart.total()

            if delivery_method == "pickup":
                # Retiro sin cargo: el cliente pasa a buscar el pedido, no hay
                # envío que cotizar. Efectivo siempre permitido (paga al retirar).
                point = form.cleaned_data["pickup_point"]
                pickup_label = f"{point.name} — {point.address}"
                shipping_cost = Decimal("0.00")
                shipping_zone = ""
                carrier_arranged = False
                cod_allowed = True
                grand_total = subtotal
            else:
                # Costo de envío resuelto del lado del servidor (fuente de verdad):
                # nunca se confía en lo que mande el cliente. El subtotal define si
                # se alcanza el mínimo de compra para envío gratis (zonas con free_over).
                point = None
                pickup_label = ""
                quote = resolve_shipping(
                    form.cleaned_data["postal_code"], subtotal=subtotal
                )
                shipping_cost = quote.cost
                shipping_zone = quote.zone_name
                carrier_arranged = quote.carrier_arranged
                cod_allowed = quote.cod_allowed
                grand_total = subtotal + quote.cost

            # Contraentrega solo en zonas de reparto propio (el JS del checkout
            # deshabilita la opción, pero la fuente de verdad está acá).
            if payment_method == "cod" and not cod_allowed:
                form.add_error(
                    "payment_method",
                    "El pago en efectivo a contraentrega está disponible solo "
                    "para CABA y AMBA. Elegí otro método de pago.",
                )
                return _render_checkout(request, cart, form)

            if payment_method in ("transfer", "cod"):
                # Transferencia y contraentrega comparten flujo: la orden queda
                # pendiente y el pago se resuelve fuera del sitio.
                try:
                    with transaction.atomic():
                        # 1. Validar stock de TODOS los items antes de crear la orden
                        validated_rows = []
                        for item in cart.items():
                            variant = (
                                Variant.objects.select_for_update()
                                .select_related("product")
                                .get(id=item.variant.id, is_active=True)
                            )
                            if variant.stock_qty < item.qty:
                                raise ValueError(
                                    f"Sin stock suficiente de {variant.product.name} "
                                    f"({variant.name}). Disponible: {variant.stock_qty}."
                                )
                            validated_rows.append((variant, item))

                        # 2. Crear Orden
                        order = Order.objects.create(
                            full_name=form.cleaned_data["full_name"],
                            email=form.cleaned_data["email"],
                            phone=form.cleaned_data["phone"],
                            address_line=form.cleaned_data["address_line"],
                            city=form.cleaned_data["city"],
                            postal_code=form.cleaned_data["postal_code"],
                            delivery_method=delivery_method,
                            pickup_point=point,
                            pickup_point_label=pickup_label,
                            shipping_cost=shipping_cost,
                            shipping_zone=shipping_zone,
                            shipping_carrier_arranged=carrier_arranged,
                            total_amount=grand_total,
                            status="pending",
                            payment_method=payment_method,
                        )

                        # 3. Guardar Items y descontar stock (ya validado arriba)
                        for variant, item in validated_rows:
                            OrderItem.objects.create(
                                order=order,
                                variant=variant,
                                product_name=variant.product.name,
                                variant_name=variant.name,
                                unit_price=item.unit_price,
                                quantity=item.qty,
                                line_total=item.line_total,
                            )
                            variant.stock_qty -= item.qty
                            variant.save(update_fields=["stock_qty"])
                except (ValueError, Variant.DoesNotExist) as exc:
                    messages.error(
                        request,
                        str(exc) if isinstance(exc, ValueError)
                        else "Uno de los productos ya no está disponible.",
                    )
                    return _render_checkout(request, cart, form)

                # 4. Limpiar el carrito, notificar por email y redirigir
                cart.clear()
                request.session.modified = True
                send_order_confirmation(order.id)
                if payment_method == "cod":
                    return redirect("orders:cod_info", order_id=order.id)
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
                    delivery_method=delivery_method,
                    pickup_point=point,
                    pickup_point_label=pickup_label,
                    shipping_cost=shipping_cost,
                    shipping_zone=shipping_zone,
                    shipping_carrier_arranged=carrier_arranged,
                    total_amount=grand_total,
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

    return _render_checkout(request, cart, form)


def confirmation(request, order_id):
    order = Order.objects.filter(id=order_id).first()
    return render(
        request,
        "orders/confirmation.html",
        {"order_id": order_id, "order": order},
    )


def transfer_info(request, order_id):
    from django.shortcuts import get_object_or_404
    from shipping.services import carrier_arranged_legend

    order = get_object_or_404(Order, id=order_id)
    return render(
        request,
        "orders/transfer_info.html",
        {
            "order": order,
            "bank": settings.BANK_TRANSFER,
            "notify_email": settings.ORDER_NOTIFICATION_EMAIL,
            "shipping_legend": (
                carrier_arranged_legend() if order.shipping_carrier_arranged else ""
            ),
        },
    )


def cod_info(request, order_id):
    from django.shortcuts import get_object_or_404

    order = get_object_or_404(Order, id=order_id)
    return render(
        request,
        "orders/cod_info.html",
        {
            "order": order,
            "notify_email": settings.ORDER_NOTIFICATION_EMAIL,
        },
    )
