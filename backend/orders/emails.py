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
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction

logger = logging.getLogger("orders.email")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _send_email(subject: str, body: str, to_email: str) -> None:
    """
    Envía un email de texto plano.

    Render (plan free) bloquea el SMTP saliente (puerto 587), así que en producción
    usamos la **API HTTP de Brevo** (HTTPS 443) cuando hay BREVO_API_KEY. Si no está
    configurada, cae al backend de email de Django (consola en dev, locmem en tests),
    para no romper el entorno local ni la suite.
    """
    api_key = getattr(settings, "BREVO_API_KEY", "")
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""
    sender_name, sender_email = parseaddr(from_email)

    if api_key:
        payload = {
            "sender": {"email": sender_email or "no-reply@rasel.ar", "name": sender_name or "RaSel"},
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": body,
        }
        resp = requests.post(
            BREVO_API_URL,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Brevo API error {resp.status_code}: {resp.text}")
    else:
        EmailMessage(
            subject=subject, body=body, from_email=from_email or None, to=[to_email]
        ).send(fail_silently=False)


def _build_lines(order) -> str:
    rows = []
    for it in order.items.all():
        rows.append(f"  - {it.product_name} ({it.variant_name}) x{it.quantity}: ${it.line_total}")
    return "\n".join(rows)


def _totals_block(order) -> str:
    shipping = order.shipping_cost or 0
    subtotal = order.total_amount - shipping
    zona = f" ({order.shipping_zone})" if order.shipping_zone else ""
    if getattr(order, "shipping_carrier_arranged", False):
        envio = "a cargo del comprador (a coordinar con el correo)"
    elif shipping and shipping > 0:
        envio = f"${shipping}"
    else:
        envio = "Gratis"
    return (
        f"Subtotal: ${subtotal}\n"
        f"Envío{zona}: {envio}\n"
        f"Total: ${order.total_amount}"
    )


def _shipping_legend(order) -> str:
    """Leyenda del envío a coordinar, para sumar al cuerpo del email."""
    if not getattr(order, "shipping_carrier_arranged", False):
        return ""
    from shipping.services import carrier_arranged_legend

    legend = carrier_arranged_legend()
    return f"\nSobre el envío:\n{legend}\n" if legend else ""


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
    elif order.payment_method == "cod":
        estado = (
            "Tu pedido quedó CONFIRMADO. Nos contactamos para coordinar la "
            "entrega y lo abonás en EFECTIVO al recibirlo. Sin recargos.\n"
        )
    else:
        estado = "¡Tu pago fue confirmado! Estamos preparando tu pedido.\n"

    return (
        f"Hola {order.full_name},\n\n"
        f"Recibimos tu pedido #{order.id}.\n\n"
        f"{estado}\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"{_totals_block(order)}\n\n"
        f"Envío a:\n  {order.address_line}, {order.city} ({order.postal_code})\n"
        f"{_shipping_legend(order)}\n"
        f"Gracias por tu compra.\nRaSel — Aceite de Oliva\n"
    )


def _owner_body(order) -> str:
    return (
        f"Nueva orden #{order.id} ({order.get_status_display()})\n"
        f"Método de pago: {order.payment_method}\n\n"
        f"Cliente: {order.full_name} <{order.email}> {order.phone}\n"
        f"Envío: {order.address_line}, {order.city} ({order.postal_code})\n\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"{_totals_block(order)}\n"
    )


def _send(order) -> None:
    # Email al cliente
    _send_email(
        f"RaSel — Confirmación de tu pedido #{order.id}",
        _customer_body(order),
        order.email,
    )

    # Aviso al dueño (si está configurado)
    owner = getattr(settings, "ORDER_NOTIFICATION_EMAIL", "")
    if owner:
        _send_email(
            f"Nueva orden #{order.id} — ${order.total_amount}",
            _owner_body(order),
            owner,
        )


def _paid_body(order) -> str:
    return (
        f"Hola {order.full_name},\n\n"
        f"¡Confirmamos la recepción de tu pago del pedido #{order.id}!\n"
        f"Ya lo estamos preparando para el envío.\n\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"{_totals_block(order)}\n\n"
        f"Envío a:\n  {order.address_line}, {order.city} ({order.postal_code})\n"
        f"{_shipping_legend(order)}\n"
        f"¡Gracias por tu compra!\nRaSel — Aceite de Oliva\n"
    )


def send_payment_confirmed(order_id: int) -> None:
    """
    Email de 'pago confirmado' al cliente (se dispara cuando el dueño valida la
    transferencia en el admin). Idempotente vía Order.paid_email_sent, separado del
    mail de 'pedido reservado' (Order.confirmation_email_sent).
    """
    from .models import Order

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order_id)
            if order.paid_email_sent:
                return
            order.paid_email_sent = True
            order.save(update_fields=["paid_email_sent"])
    except Order.DoesNotExist:
        return

    try:
        order.refresh_from_db()
        _send_email(
            f"RaSel — Pago confirmado · Pedido #{order.id}",
            _paid_body(order),
            order.email,
        )
        logger.info("Email de pago confirmado enviado order=%s", order_id)
    except Exception:
        Order.objects.filter(id=order_id).update(paid_email_sent=False)
        logger.exception("Error enviando email de pago confirmado order %s", order_id)


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
