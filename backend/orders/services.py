from dataclasses import dataclass

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from shop.models import Variant

from .emails import (
    send_order_completed,
    send_order_shipped,
    send_payment_confirmed,
)
from .models import Order


class OrderTransitionError(ValueError):
    """La transición solicitada no es válida para el estado de la orden."""


@dataclass(frozen=True)
class TransitionResult:
    changed: bool
    order_id: int


def _get_locked_order(order_id: int) -> Order:
    return Order.objects.select_for_update().get(pk=order_id)


def _ensure_active(order: Order) -> None:
    if order.fulfillment_status == "cancelled" or order.payment_status == "cancelled":
        raise OrderTransitionError("La orden está cancelada.")
    if order.payment_status == "review":
        raise OrderTransitionError("La orden requiere revisión de pago.")
    if order.payment_status in {
        "rejected",
        "refunded",
        "partially_refunded",
        "charged_back",
    }:
        raise OrderTransitionError(
            f"El estado financiero es {order.get_payment_status_display().lower()}."
        )


def confirm_payment(order_id: int) -> TransitionResult:
    with transaction.atomic():
        order = _get_locked_order(order_id)
        _ensure_active(order)
        if order.fulfillment_status == "completed":
            raise OrderTransitionError("La orden ya está completada.")
        if order.payment_method == "mp":
            raise OrderTransitionError(
                "Mercado Pago solo puede aprobarse mediante su API o conciliación."
            )
        if order.payment_status == "approved":
            changed = False
        elif order.payment_status == "pending":
            order.payment_status = "approved"
            order.save(update_fields=["payment_status"])
            changed = True
        else:
            raise OrderTransitionError(
                "El pago no puede confirmarse desde su estado actual."
            )
    send_payment_confirmed(order_id)
    return TransitionResult(changed=changed, order_id=order_id)


def dispatch_or_ready(order_id: int) -> TransitionResult:
    with transaction.atomic():
        order = _get_locked_order(order_id)
        _ensure_active(order)
        if order.payment_status != "approved" and not (
            order.payment_method == "cod" and order.payment_status == "pending"
        ):
            raise OrderTransitionError("Primero debe confirmarse el pago.")
        target = "ready_for_pickup" if order.delivery_method == "pickup" else "shipped"
        if order.fulfillment_status == target:
            changed = False
        elif order.fulfillment_status == "pending":
            order.fulfillment_status = target
            order.save(update_fields=["fulfillment_status"])
            changed = True
        else:
            raise OrderTransitionError(
                "La entrega no puede retroceder ni volver a despacharse."
            )
    send_order_shipped(order_id)
    return TransitionResult(changed=changed, order_id=order_id)


def complete_order(order_id: int) -> TransitionResult:
    with transaction.atomic():
        order = _get_locked_order(order_id)
        _ensure_active(order)
        if order.payment_status != "approved":
            raise OrderTransitionError("Primero debe confirmarse el pago.")
        if order.fulfillment_status == "completed":
            changed = False
        elif order.fulfillment_status in {"pending", "shipped", "ready_for_pickup"}:
            order.fulfillment_status = "completed"
            order.completed_at = timezone.now()
            order.save(update_fields=["fulfillment_status", "completed_at"])
            changed = True
        else:
            raise OrderTransitionError(
                "La orden no puede completarse desde su estado actual."
            )
    send_order_completed(order_id)
    return TransitionResult(changed=changed, order_id=order_id)


def collect_and_complete(order_id: int) -> TransitionResult:
    with transaction.atomic():
        order = _get_locked_order(order_id)
        _ensure_active(order)
        payment_changed = False
        if order.payment_method == "mp":
            if order.payment_status != "approved":
                raise OrderTransitionError(
                    "Mercado Pago debe estar aprobado por la API antes de completar."
                )
        elif order.payment_status == "pending":
            order.payment_status = "approved"
            payment_changed = True
        elif order.payment_status != "approved":
            raise OrderTransitionError(
                "El pago no puede cobrarse desde su estado actual."
            )

        changed = payment_changed
        update_fields = []
        if payment_changed:
            update_fields.append("payment_status")
        if order.fulfillment_status == "completed":
            pass
        elif order.fulfillment_status in {"pending", "shipped", "ready_for_pickup"}:
            order.fulfillment_status = "completed"
            order.completed_at = timezone.now()
            update_fields.extend(["fulfillment_status", "completed_at"])
            changed = True
        else:
            raise OrderTransitionError(
                "La orden no puede completarse desde su estado actual."
            )
        if update_fields:
            order.save(update_fields=list(dict.fromkeys(update_fields)))
    send_order_completed(order_id)
    return TransitionResult(changed=changed, order_id=order_id)


def cancel_and_restore(order_id: int) -> TransitionResult:
    with transaction.atomic():
        order = _get_locked_order(order_id)
        if order.fulfillment_status == "cancelled":
            return TransitionResult(changed=False, order_id=order_id)
        if order.fulfillment_status in {"shipped", "ready_for_pickup", "completed"}:
            raise OrderTransitionError(
                "No se repuso stock: primero debe confirmarse la devolución física."
            )
        if order.payment_method == "mp" and order.payment_status in {
            "approved",
            "partially_refunded",
            "review",
        }:
            raise OrderTransitionError(
                "Primero debe reintegrarse el dinero y conciliarse Mercado Pago."
            )
        if order.stock_deducted and not order.stock_restored:
            for item in order.items.all():
                if item.variant_id:
                    Variant.objects.filter(id=item.variant_id).update(
                        stock_qty=F("stock_qty") + item.quantity
                    )
            order.stock_restored = True
        order.fulfillment_status = "cancelled"
        if order.payment_method != "mp":
            order.payment_status = "cancelled"
        order.save(
            update_fields=["fulfillment_status", "payment_status", "stock_restored"]
        )
    return TransitionResult(changed=True, order_id=order_id)
