from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from cart.cart import Cart
from payments.mercadopago import MercadoPagoError
from payments.services import (
    PaymentValidationError,
    create_checkout_preference,
    reserve_payment_draft,
)
from shipping.models import PickupPoint
from shipping.services import resolve_shipping
from shop.models import Variant

from .emails import send_order_confirmation
from .forms import CheckoutForm
from .models import Order, OrderItem


def _render_checkout(request, cart, form):
    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "form": form,
            "mp_enabled": settings.MP_CHECKOUT_ENABLED,
            "mp_max_installments": settings.MP_MAX_INSTALLMENTS,
            "pickup_points": PickupPoint.objects.filter(is_active=True),
        },
    )


def _delivery_from_form(form, subtotal):
    delivery_method = form.cleaned_data["delivery_method"]
    if delivery_method == "pickup":
        point = form.cleaned_data["pickup_point"]
        return {
            "delivery_method": delivery_method,
            "pickup_point": point,
            "pickup_point_label": f"{point.name} - {point.address}",
            "shipping_cost": Decimal("0.00"),
            "shipping_zone": "",
            "shipping_carrier_arranged": False,
            "cod_allowed": True,
            "grand_total": subtotal,
        }

    quote = resolve_shipping(form.cleaned_data["postal_code"], subtotal=subtotal)
    return {
        "delivery_method": delivery_method,
        "pickup_point": None,
        "pickup_point_label": "",
        "shipping_cost": quote.cost,
        "shipping_zone": quote.zone_name,
        "shipping_carrier_arranged": quote.carrier_arranged,
        "cod_allowed": quote.cod_allowed,
        "grand_total": subtotal + quote.cost,
    }


def _customer_from_form(form):
    return {
        key: form.cleaned_data[key]
        for key in (
            "full_name",
            "email",
            "phone",
            "address_line",
            "address_extra",
            "city",
            "postal_code",
        )
    }


def _create_offline_order(customer, delivery, cart_rows, payment_method):
    with transaction.atomic():
        validated = []
        for item in cart_rows:
            variant = (
                Variant.objects.select_for_update()
                .select_related("product")
                .get(id=item.variant.id, is_active=True)
            )
            if variant.stock_qty < item.qty:
                raise ValueError(
                    f"Sin stock suficiente de {variant.product.name} ({variant.name}). "
                    f"Disponible: {variant.stock_qty}."
                )
            validated.append((variant, item))

        order = Order.objects.create(
            **customer,
            delivery_method=delivery["delivery_method"],
            pickup_point=delivery["pickup_point"],
            pickup_point_label=delivery["pickup_point_label"],
            shipping_cost=delivery["shipping_cost"],
            shipping_zone=delivery["shipping_zone"],
            shipping_carrier_arranged=delivery["shipping_carrier_arranged"],
            total_amount=delivery["grand_total"],
            status="pending",
            payment_status="pending",
            payment_method=payment_method,
            stock_deducted=True,
        )
        for variant, item in validated:
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
        return order


@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = Cart(request.session)
    if len(cart) == 0:
        return redirect("shop:product_list")

    if request.method != "POST":
        return _render_checkout(request, cart, CheckoutForm())

    form = CheckoutForm(request.POST)
    if not form.is_valid():
        return _render_checkout(request, cart, form)

    payment_method = form.cleaned_data.get("payment_method", "transfer")
    cart_rows = list(cart.items())
    if not cart_rows:
        messages.error(request, "Los productos del carrito ya no estan disponibles.")
        return redirect("cart:detail")
    subtotal = sum((item.line_total for item in cart_rows), Decimal("0.00"))
    delivery = _delivery_from_form(form, subtotal)
    customer = _customer_from_form(form)

    if payment_method == "cod" and not delivery["cod_allowed"]:
        form.add_error(
            "payment_method",
            "El pago en efectivo a contraentrega esta disponible solo para CABA y GBA.",
        )
        return _render_checkout(request, cart, form)

    if payment_method in {"transfer", "cod"}:
        try:
            order = _create_offline_order(customer, delivery, cart_rows, payment_method)
        except (ValueError, Variant.DoesNotExist) as exc:
            messages.error(
                request,
                str(exc) if isinstance(exc, ValueError)
                else "Uno de los productos ya no esta disponible.",
            )
            return _render_checkout(request, cart, form)
        cart.clear()
        send_order_confirmation(order.id)
        destination = "orders:cod_info" if payment_method == "cod" else "orders:transfer_info"
        return redirect(destination, order_id=order.id)

    if not settings.MP_CHECKOUT_ENABLED:
        form.add_error("payment_method", "Mercado Pago no esta disponible en este momento.")
        return _render_checkout(request, cart, form)

    draft_delivery = {
        key: delivery[key]
        for key in (
            "delivery_method",
            "pickup_point",
            "pickup_point_label",
            "shipping_cost",
            "shipping_zone",
            "shipping_carrier_arranged",
        )
    }
    try:
        draft = reserve_payment_draft(
            customer=customer,
            delivery=draft_delivery,
            cart_rows=cart_rows,
            total_amount=delivery["grand_total"],
        )
    except (PaymentValidationError, Variant.DoesNotExist) as exc:
        messages.error(
            request,
            str(exc) if isinstance(exc, PaymentValidationError)
            else "Uno de los productos ya no esta disponible.",
        )
        return _render_checkout(request, cart, form)

    request.session["active_payment_draft"] = str(draft.token)
    request.session.modified = True
    try:
        draft = create_checkout_preference(draft.token)
    except MercadoPagoError:
        draft.processing_error = "preference_api_unavailable"
        draft.save(update_fields=["processing_error"])
        return render(
            request,
            "payments/payment_retry.html",
            {"draft": draft},
            status=503,
        )
    except PaymentValidationError as exc:
        messages.error(request, str(exc))
        return _render_checkout(request, cart, form)
    return redirect(draft.mp_init_point)


def confirmation(request, order_id):
    order = Order.objects.filter(id=order_id).first()
    return render(
        request,
        "orders/confirmation.html",
        {"order_id": order_id, "order": order},
    )


def transfer_info(request, order_id):
    from shipping.services import carrier_arranged_legend

    order = get_object_or_404(Order, id=order_id)
    return render(
        request,
        "orders/transfer_info.html",
        {
            "order": order,
            "bank": settings.BANK_TRANSFER,
            "notify_email": settings.ORDER_NOTIFICATION_EMAIL,
            "whatsapp": settings.WHATSAPP_NUMBER,
            "shipping_legend": (
                carrier_arranged_legend() if order.shipping_carrier_arranged else ""
            ),
        },
    )


def cod_info(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(
        request,
        "orders/cod_info.html",
        {
            "order": order,
            "notify_email": settings.ORDER_NOTIFICATION_EMAIL,
            "whatsapp": settings.WHATSAPP_NUMBER,
        },
    )
