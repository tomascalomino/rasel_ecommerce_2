"""
Envío de emails transaccionales de órdenes.

Diseño:
- `send_order_confirmation(order_id)` es idempotente: usa el flag
  `Order.confirmation_email_sent` con un claim atómico para que, aunque
  MercadoPago dispare el webhook varias veces (o se solapen webhook y retorno),
  el cliente reciba un único email.
- Nunca rompe el flujo de pago: cualquier error de SMTP se loguea y se traga.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction

logger = logging.getLogger("orders.email")


def _build_lines(order) -> str:
    rows = []
    for it in order.items.all():
        rows.append(f"  - {it.product_name} ({it.variant_name}) x{it.quantity}: ${it.line_total}")
    return "\n".join(rows)


def _bank_block() -> str:
    bank = getattr(settings, "BANK_TRANSFER", {}) or {}
    lines = []
    if bank.get("holder"):
        lines.append(f"  Titular: {bank['holder']}")
    if bank.get("alias"):
        lines.append(f"  Alias: {bank['alias']}")
    if bank.get("cbu"):
        lines.append(f"  CBU/CVU: {bank['cbu']}")
    if bank.get("bank"):
        lines.append(f"  Banco: {bank['bank']}")
    return "\n".join(lines)


def _customer_body(order) -> str:
    if order.payment_method == "transfer":
        bank_block = _bank_block()
        datos = (
            f"\nDatos para transferir:\n{bank_block}\n" if bank_block else ""
        )
        notify = getattr(settings, "ORDER_NOTIFICATION_EMAIL", "") or ""
        comprobante = (
            f"Enviá el comprobante a {notify} indicando tu orden #{order.id}.\n"
            if notify else ""
        )
        estado = (
            "Tu pedido quedó RESERVADO y está pendiente de pago por transferencia.\n"
            f"{datos}{comprobante}"
        )
    else:
        estado = "¡Tu pago fue confirmado! Estamos preparando tu pedido.\n"

    return (
        f"Hola {order.full_name},\n\n"
        f"Recibimos tu pedido #{order.id}.\n\n"
        f"{estado}\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"Total: ${order.total_amount}\n\n"
        f"Envío a:\n  {order.address_line}, {order.city} ({order.postal_code})\n\n"
        f"Gracias por tu compra.\nRaSel — Aceite de Oliva\n"
    )


def _owner_body(order) -> str:
    return (
        f"Nueva orden #{order.id} ({order.get_status_display()})\n"
        f"Método de pago: {order.payment_method}\n\n"
        f"Cliente: {order.full_name} <{order.email}> {order.phone}\n"
        f"Envío: {order.address_line}, {order.city} ({order.postal_code})\n\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"Total: ${order.total_amount}\n"
    )


def _send(order) -> None:
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)

    # Email al cliente
    EmailMessage(
        subject=f"RaSel — Confirmación de tu pedido #{order.id}",
        body=_customer_body(order),
        from_email=from_email,
        to=[order.email],
    ).send(fail_silently=False)

    # Aviso al dueño (si está configurado)
    owner = getattr(settings, "ORDER_NOTIFICATION_EMAIL", "")
    if owner:
        EmailMessage(
            subject=f"Nueva orden #{order.id} — ${order.total_amount}",
            body=_owner_body(order),
            from_email=from_email,
            to=[owner],
        ).send(fail_silently=False)


def send_order_confirmation(order_id: int) -> None:
    from .models import Order

    # Claim atómico: marcamos enviado antes de mandar para evitar reenvíos
    # ante webhooks concurrentes.
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order_id)
            if order.confirmation_email_sent:
                return
            order.confirmation_email_sent = True
            order.save(update_fields=["confirmation_email_sent"])
    except Order.DoesNotExist:
        return

    try:
        order.refresh_from_db()
        _send(order)
        logger.info("Email de confirmación enviado order=%s", order_id)
    except Exception:
        # Liberamos el claim para poder reintentar más adelante.
        Order.objects.filter(id=order_id).update(confirmation_email_sent=False)
        logger.exception("Error enviando email de orden %s", order_id)
