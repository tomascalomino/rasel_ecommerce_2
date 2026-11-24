from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from cart.cart import Cart, CartItem
from analytics.tracking import mark_stage
from analytics.attribution import checkout_snapshot
from marketing.tracking import checkout_snapshot as marketing_snapshot
from config.pricing import (
    get_offline_payment_discount_percent,
)
from payments.services import reserve_payment_draft
from payments.views import continue_payment
from shipping.models import PickupPoint
from shipping.services import resolve_shipping
from shipping.promotions import (
    SNAPSHOT_FIELDS,
    ShippingQuoteChanged,
    quote_delivery,
    revalidate_delivery,
    sign_quote,
)
from shop.models import Variant
from shop.gifts import GIFT_END, checkout_gift, gift_state, offer_token
from shop.coupons import (
    SESSION_KEY as COUPON_SESSION_KEY,
    assign_coupon,
    checkout_coupon,
    lock_coupon,
    normalize_code,
    quote_coupon,
)

from .attempts import (
    checkout_token, current_key, existing_payment, result_for_key, session_digest,
    submitted_key,
)
from .emails import send_order_confirmation
from .forms import CheckoutForm
from .models import CheckoutAttempt, Order, OrderItem


def _render_checkout(request, cart, form, discount_percent, review_quote=None):
    cart_rows = list(cart.items())
    subtotal = sum((item.line_total for item in cart_rows), Decimal("0.00"))
    request._rendered_checkout_cart = (cart, cart_rows)
    coupon_quote = quote_coupon(
        request.session.get(COUPON_SESSION_KEY), cart_rows, discount_percent
    )
    offline_discount = coupon_quote.payment_amount
    if review_quote is not None:
        data = form.data.copy()
        data["shipping_quote_token"] = sign_quote(
            data.get("postal_code"), subtotal, review_quote
        )
        form = CheckoutForm(data, discount_percent=discount_percent)
        form.is_valid()
        form.add_error(
            None,
            "Revisá el envío y confirmá el total actualizado. Todavía no creamos el pedido ni reservamos stock.",
        )
    selected_discount = (
        offline_discount
        if form["payment_method"].value() in {"transfer", "cod"}
        else Decimal("0.00")
    )
    now = timezone.now()
    current_gift = gift_state(now)
    selected_coupon_discount = coupon_quote.amount(form["payment_method"].value())
    if form.is_bound:
        form.data = form.data.copy()
        form.data["gift_offer_token"] = offer_token(current_gift)
        form.data["coupon_offer_token"] = coupon_quote.token
    else:
        form.initial["gift_offer_token"] = offer_token(current_gift)
        form.initial["coupon_offer_token"] = coupon_quote.token
        form.initial["coupon_code"] = coupon_quote.code
    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "cart_rows": cart_rows,
            "cart_subtotal": subtotal,
            "cyber_gift": current_gift,
            "show_gift_updates": now < GIFT_END,
            "form": form,
            "checkout_attempt": checkout_token(request.session),
            "coupon_quote": coupon_quote,
            "coupon_discount": selected_coupon_discount,
            "mp_enabled": settings.MP_CHECKOUT_ENABLED,
            "mp_max_installments": settings.MP_MAX_INSTALLMENTS,
            "offline_discount_amount": offline_discount,
            "offline_discount_percent": discount_percent,
            "pickup_points": PickupPoint.objects.filter(is_active=True),
            "review_quote": review_quote,
            "review_discount": selected_discount,
            "review_total": subtotal
            - selected_discount
            - selected_coupon_discount
            + (review_quote.cost if review_quote else 0),
        },
    )


def _delivery_from_form(form, subtotal, payment_method, discount_amount):
    delivery_method = form.cleaned_data["delivery_method"]
    discounted_subtotal = subtotal - discount_amount
    if delivery_method == "pickup":
        point = form.cleaned_data["pickup_point"]
        return {
            "delivery_method": delivery_method,
            "items_subtotal": subtotal,
            "pickup_point": point,
            "pickup_point_label": f"{point.name} - {point.address}",
            "shipping_cost": Decimal("0.00"),
            "shipping_zone": "",
            "shipping_carrier_arranged": False,
            "cod_allowed": True,
            "payment_discount_amount": discount_amount,
            "grand_total": discounted_subtotal,
        }

    quote = resolve_shipping(form.cleaned_data["postal_code"], subtotal=subtotal)
    return {
        "delivery_method": delivery_method,
        "items_subtotal": subtotal,
        "pickup_point": None,
        "pickup_point_label": "",
        **quote_delivery(quote),
        "cod_allowed": quote.cod_allowed,
        "payment_discount_amount": discount_amount,
        "grand_total": discounted_subtotal + quote.cost,
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


def _create_offline_order(
    customer,
    delivery,
    cart_rows,
    payment_method,
    discount_percent,
    analytics_attribution=None,
    marketing=None,
    shipping_quote_token=None,
    gift_offer_token=None,
    coupon_code=None,
    coupon_offer_token=None,
):
    with transaction.atomic():
        lock_coupon(coupon_code)
        validated = []
        validated_subtotal = Decimal("0.00")
        for item in sorted(cart_rows, key=lambda row: row.variant.pk):
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
            unit_price = variant.price_ars
            line_total = unit_price * item.qty
            validated_subtotal += line_total
            validated.append((variant, item.qty, unit_price, line_total))

        if validated_subtotal != delivery["items_subtotal"]:
            raise ValueError(
                "El precio de uno de los productos cambió. Revisá el pedido."
            )

        now = timezone.now()
        coupon_quote = checkout_coupon(
            coupon_code,
            [CartItem(v, qty) for v, qty, _, _ in validated],
            discount_percent,
            coupon_offer_token,
            payment_method,
            now=now,
        )
        discount_amount = (
            coupon_quote.payment_amount
            if payment_method in {"transfer", "cod"}
            else Decimal("0.00")
        )
        delivery = revalidate_delivery(
            customer, delivery, validated_subtotal, shipping_quote_token, now
        )
        if payment_method == "cod" and not delivery["cod_allowed"]:
            raise ValueError("El pago en efectivo no está disponible para tu zona.")
        grand_total = (
            validated_subtotal
            - discount_amount
            - coupon_quote.amount(payment_method)
            + delivery["shipping_cost"]
        )
        gift = checkout_gift(gift_offer_token, now)

        order = Order.objects.create(
            created_at=now,
            **gift,
            **coupon_quote.snapshot(payment_method),
            **(marketing or {}),
            **customer,
            analytics_attribution=analytics_attribution or {},
            analytics_attributed_at=(analytics_attribution or {}).get("captured_at"),
            delivery_method=delivery["delivery_method"],
            pickup_point=delivery["pickup_point"],
            pickup_point_label=delivery["pickup_point_label"],
            shipping_cost=delivery["shipping_cost"],
            shipping_zone=delivery["shipping_zone"],
            shipping_carrier_arranged=delivery["shipping_carrier_arranged"],
            **{key: delivery[key] for key in SNAPSHOT_FIELDS if key in delivery},
            payment_discount_amount=discount_amount,
            payment_discount_percent=(discount_percent if discount_amount > 0 else 0),
            total_amount=grand_total,
            fulfillment_status="pending",
            payment_status="pending",
            payment_method=payment_method,
            stock_deducted=True,
        )
        assign_coupon(coupon_quote, order=order, method=payment_method)
        for variant, quantity, unit_price, line_total in validated:
            OrderItem.objects.create(
                order=order,
                variant=variant,
                variant_id_snapshot=variant.pk,
                product_name=variant.product.name,
                variant_name=variant.name,
                unit_price=unit_price,
                quantity=quantity,
                line_total=line_total,
            )
            variant.stock_qty -= quantity
            variant.save(update_fields=["stock_qty"])
        return order


@require_http_methods(["GET", "POST"])
@never_cache
def checkout(request):
    cart = Cart(request.session)
    key = None
    if request.method == "POST":
        key = submitted_key(request.session, request.POST.get("checkout_attempt"))
        if key and (attempt := result_for_key(request.session, key)):
            return _checkout_result(request, cart, attempt)
    if len(cart) == 0:
        return redirect("shop:product_list")

    discount_percent = get_offline_payment_discount_percent(request)

    if request.method != "POST":
        if request.session.get("active_payment_draft"):
            return redirect("payments:return", result="status")
        return _render_checkout(
            request,
            cart,
            CheckoutForm(discount_percent=discount_percent),
            discount_percent,
        )

    form = CheckoutForm(request.POST, discount_percent=discount_percent)
    if key != current_key(request.session):
        form.add_error(None, "Revisá el resumen del carrito y confirmá para continuar.")
        return _render_checkout(request, cart, form, discount_percent)
    if not form.is_valid():
        return _render_checkout(request, cart, form, discount_percent)
    if normalize_code(form.cleaned_data["coupon_code"]) != request.session.get(
        COUPON_SESSION_KEY, ""
    ):
        form.add_error(
            None,
            "Aplicá el código con el botón Aplicar para revisar el descuento antes de continuar.",
        )
        return _render_checkout(request, cart, form, discount_percent)

    payment_method = form.cleaned_data.get("payment_method", "transfer")
    cart_rows = list(cart.items())
    if not cart_rows:
        messages.error(request, "Los productos del carrito ya no estan disponibles.")
        return redirect("cart:detail")
    subtotal = sum((item.line_total for item in cart_rows), Decimal("0.00"))
    coupon_quote = quote_coupon(
        request.session.get(COUPON_SESSION_KEY), cart_rows, discount_percent
    )
    discount_amount = (
        coupon_quote.payment_amount
        if payment_method in {"transfer", "cod"}
        else Decimal("0.00")
    ) + coupon_quote.amount(payment_method)
    delivery = _delivery_from_form(
        form,
        subtotal,
        payment_method,
        discount_amount,
    )
    customer = _customer_from_form(form)

    if payment_method == "cod" and not delivery["cod_allowed"]:
        form.add_error(
            "payment_method",
            "El pago en efectivo a contraentrega esta disponible solo para CABA y GBA.",
        )
        return _render_checkout(request, cart, form, discount_percent)

    try:
        attempt, resume_draft, created = _submit_checkout(
            request, key, form, customer, delivery, cart_rows, payment_method, discount_percent
        )
    except ShippingQuoteChanged as exc:
        return _render_checkout(request, cart, form, discount_percent, exc.quote)
    except (ValueError, Variant.DoesNotExist) as exc:
        messages.error(
            request,
            (
                str(exc)
                if isinstance(exc, ValueError)
                else "Uno de los productos ya no esta disponible."
            ),
        )
        return _render_checkout(request, cart, form, discount_percent)
    if resume_draft:
        return continue_payment(request, resume_draft)
    if created:
        mark_stage(request, "checkout_submitted")
        if attempt.order_id:
            send_order_confirmation(attempt.order_id)
    return _checkout_result(request, cart, attempt)


def _submit_checkout(
    request, key, form, customer, delivery, cart_rows, payment_method, discount_percent
):
    with transaction.atomic():
        # Every guest cart already has a database session. This also serializes
        # two POSTs with different cycle keys while a payment is still open.
        if not Session.objects.select_for_update().filter(pk=request.session.session_key).exists():
            raise ValueError("Tu sesión venció. Volvé al carrito para continuar.")
        if attempt := result_for_key(request.session, key):
            return attempt, None, False
        if draft := existing_payment(request.session, check_attempts=True):
            return None, draft, False

        options = {
            "analytics_attribution": checkout_snapshot(request),
            "marketing": marketing_snapshot(request),
            "shipping_quote_token": form.cleaned_data["shipping_quote_token"],
            "gift_offer_token": form.cleaned_data["gift_offer_token"],
            "coupon_code": request.session.get(COUPON_SESSION_KEY),
            "coupon_offer_token": form.cleaned_data["coupon_offer_token"],
        }
        attempt = CheckoutAttempt(key=key, session_digest=session_digest(request.session))
        if payment_method == "mp":
            draft_delivery = {
                field: delivery[field]
                for field in (
                    "delivery_method", "pickup_point", "pickup_point_label",
                    "shipping_cost", "shipping_zone", "shipping_carrier_arranged",
                )
            }
            attempt.draft = reserve_payment_draft(
                customer=customer,
                delivery=draft_delivery,
                cart_rows=cart_rows,
                total_amount=delivery["grand_total"],
                **options,
            )
        else:
            attempt.order = _create_offline_order(
                customer, delivery, cart_rows, payment_method, discount_percent, **options
            )
        attempt.save(force_insert=True)
        return attempt, None, True


def _checkout_result(request, cart, attempt):
    if attempt.order_id:
        if current_key(request.session) == attempt.key and len(cart):
            cart.clear()
        destination = (
            "orders:cod_info" if attempt.order.payment_method == "cod" else "orders:transfer_info"
        )
        return redirect(destination, order_id=attempt.order_id)
    return continue_payment(request, attempt.draft)


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
