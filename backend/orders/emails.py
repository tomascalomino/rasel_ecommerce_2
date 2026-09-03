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
    discount = getattr(order, "payment_discount_amount", 0) or 0
    subtotal = order.total_amount - shipping + discount
    lines = [f"Subtotal: ${subtotal}"]
    if discount > 0:
        lines.append(
            f"Descuento por transferencia/efectivo "
            f"(mínimo {order.payment_discount_percent}%): -${discount}"
        )
    if getattr(order, "delivery_method", "ship") == "pickup":
        lines.extend(
            [
                "Retiro en punto de retiro: Sin cargo",
                f"Total: ${order.total_amount}",
            ]
        )
        return "\n".join(lines)
    zona = f" ({order.shipping_zone})" if order.shipping_zone else ""
    if getattr(order, "shipping_carrier_arranged", False):
        envio = "a cargo del comprador y a coordinar vía WhatsApp"
    elif shipping and shipping > 0:
        envio = f"${shipping}"
    else:
        envio = "Gratis"
    lines.extend([f"Envío{zona}: {envio}", f"Total: ${order.total_amount}"])
    return "\n".join(lines)


def _delivery_block(order) -> str:
    """Bloque de entrega: dirección de envío o punto de retiro (snapshot)."""
    if getattr(order, "delivery_method", "ship") == "pickup":
        return f"Retiro en:\n  {order.pickup_point_label}\n"
    extra = f" ({order.address_extra})" if getattr(order, "address_extra", "") else ""
    return f"Envío a:\n  {order.address_line}{extra}, {order.city} ({order.postal_code})\n"


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


def _whatsapp() -> str:
    return getattr(settings, "WHATSAPP_NUMBER", "") or ""


def _customer_body(order) -> str:
    whatsapp = _whatsapp()
    if order.payment_method == "transfer":
        bank_block = _bank_block()
        datos = (
            f"\nDatos para transferir:\n{bank_block}\n" if bank_block else ""
        )
        comprobante = (
            f"\nEnviá el comprobante de pago vía WhatsApp al {whatsapp} "
            f"indicando tu número de orden (#{order.id}).\n"
        )
        if order.delivery_method == "pickup":
            entrega = (
                "\nEl retiro se coordina por el mismo WhatsApp cuando envíes "
                "el comprobante.\n"
                f"Te avisamos cuando tu pedido esté listo para retirar en "
                f"{order.pickup_point_label}.\n"
            )
        elif order.shipping_carrier_arranged:
            entrega = (
                "\nLa entrega se coordina por el mismo WhatsApp cuando envíes "
                "el comprobante.\n"
            )
        else:
            entrega = (
                "\nTu pedido será entregado dentro de las 48hs, contadas "
                "desde que hayamos recibido el pago realizado.\n"
            )
        estado = (
            "Tu pedido quedó RESERVADO y está pendiente de pago por transferencia.\n"
            f"{datos}{comprobante}{entrega}"
        )
    elif order.payment_method == "cod":
        if order.delivery_method == "pickup":
            estado = (
                "Tu pedido ha sido realizado y será abonado en efectivo al "
                "momento del retiro.\n\n"
                f"Contactanos vía WhatsApp al {whatsapp} indicando tu número "
                f"de orden (#{order.id}) para coordinar el retiro en "
                f"{order.pickup_point_label}.\n"
            )
        else:
            estado = (
                "Tu pedido ha sido realizado y será abonado en efectivo al "
                "momento de la entrega.\n\n"
                "Tu pedido será entregado dentro de las 48hs de realizado.\n\n"
                f"Contactanos vía WhatsApp al {whatsapp} indicando tu número "
                f"de orden (#{order.id}) para coordinar la entrega.\n"
            )
    else:
        estado = "¡Tu pago fue confirmado! Estamos preparando tu pedido.\n"

    return (
        f"Hola {order.full_name}!\n\n"
        f"Recibimos tu pedido Orden N° #{order.id}.\n\n"
        f"{estado}\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"{_totals_block(order)}\n\n"
        f"{_delivery_block(order)}"
        f"{_shipping_legend(order)}\n"
        f"Gracias por elegirnos!\nRaSel — Aceite de Oliva\n"
    )


def _owner_body(order) -> str:
    if order.delivery_method == "pickup":
        entrega = f"Retiro en: {order.pickup_point_label}"
    else:
        extra = f" ({order.address_extra})" if getattr(order, "address_extra", "") else ""
        entrega = f"Envío: {order.address_line}{extra}, {order.city} ({order.postal_code})"
    return (
        # Sin <email> entre corchetes angulares: Brevo genera una parte HTML
        # a partir del texto plano y los interpreta como etiquetas (se pierden).
        f"Nueva orden #{order.id} ({order.get_status_display()})\n"
        f"Método de pago: {order.payment_method}\n\n"
        f"Cliente: {order.full_name}\n"
        f"Email: {order.email}\n"
        f"Teléfono: {order.phone or '-'}\n"
        f"{entrega}\n\n"
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
    whatsapp = _whatsapp()
    if order.delivery_method == "pickup":
        proximo = (
            f"Coordinamos el retiro por WhatsApp al {whatsapp}. "
            f"Te avisamos cuando esté listo para retirar en "
            f"{order.pickup_point_label}."
        )
    elif getattr(order, "shipping_carrier_arranged", False):
        proximo = f"Coordinamos la entrega por WhatsApp al {whatsapp}."
    else:
        proximo = "Tu pedido será entregado dentro de las 48hs."
    return (
        f"Hola {order.full_name}!\n\n"
        f"¡Confirmamos la recepción de tu pago del pedido Orden N° #{order.id}!\n"
        f"{proximo}\n\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"{_totals_block(order)}\n\n"
        f"{_delivery_block(order)}"
        f"{_shipping_legend(order)}\n"
        f"Gracias por elegirnos!\nRaSel — Aceite de Oliva\n"
    )


def _shipped_body(order) -> str:
    whatsapp = _whatsapp()
    if order.delivery_method == "pickup":
        estado = (
            f"¡Tu pedido está listo para retirar en {order.pickup_point_label}!\n"
            f"Cualquier duda, escribinos por WhatsApp al {whatsapp} indicando "
            f"tu número de orden (#{order.id}).\n"
        )
    else:
        estado = "¡Tu pedido fue despachado y está en camino!\n"
        if getattr(order, "shipping_carrier_arranged", False):
            estado += (
                f"Cualquier duda sobre la entrega, escribinos por WhatsApp al "
                f"{whatsapp} indicando tu número de orden (#{order.id}).\n"
            )
    return (
        f"Hola {order.full_name}!\n\n"
        f"{estado}\n"
        f"Detalle:\n{_build_lines(order)}\n\n"
        f"{_totals_block(order)}\n\n"
        f"{_delivery_block(order)}\n"
        f"Gracias por elegirnos!\nRaSel — Aceite de Oliva\n"
    )


def _idempotent_send(order_id: int, flag_field: str, send_fn, label: str) -> None:
    """
    Claim atómico: marcamos el flag antes de mandar para evitar reenvíos ante
    disparadores concurrentes (webhooks repetidos, retorno + webhook, doble clic
    en el admin). Si el envío falla, se libera el claim para poder reintentar.
    """
    from .models import Order

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order_id)
            if getattr(order, flag_field):
                return
            setattr(order, flag_field, True)
            order.save(update_fields=[flag_field])
    except Order.DoesNotExist:
        return

    try:
        order.refresh_from_db()
        send_fn(order)
        logger.info("Email de %s enviado order=%s", label, order_id)
    except Exception:
        Order.objects.filter(id=order_id).update(**{flag_field: False})
        logger.exception("Error enviando email de %s order %s", label, order_id)


def send_payment_confirmed(order_id: int) -> None:
    """
    Email de 'pago confirmado' al cliente (se dispara cuando el dueño valida la
    transferencia en el admin). Idempotente vía Order.paid_email_sent, separado del
    mail de 'pedido reservado' (Order.confirmation_email_sent).
    """
    _idempotent_send(
        order_id,
        "paid_email_sent",
        lambda order: _send_email(
            f"RaSel — Pago confirmado · Pedido #{order.id}",
            _paid_body(order),
            order.email,
        ),
        "pago confirmado",
    )


def send_order_shipped(order_id: int) -> None:
    """
    Email de 'pedido enviado' (o 'listo para retirar' si es pickup) al cliente.
    Se dispara al marcar la orden como enviada en el admin. Idempotente vía
    Order.shipped_email_sent.
    """
    _idempotent_send(
        order_id,
        "shipped_email_sent",
        lambda order: _send_email(
            (
                f"RaSel — Tu pedido #{order.id} está listo para retirar"
                if order.delivery_method == "pickup"
                else f"RaSel — Tu pedido #{order.id} está en camino"
            ),
            _shipped_body(order),
            order.email,
        ),
        "pedido enviado",
    )


def send_payment_alert(subject: str, body: str) -> None:
    """Send an operational payment alert without exposing credentials or payloads."""
    recipient = getattr(settings, "PAYMENT_ALERT_EMAIL", "")
    if not recipient:
        logger.error("Alerta de pagos sin destinatario configurado: %s", subject)
        return
    try:
        _send_email(f"RaSel - {subject}", body, recipient)
    except Exception:
        logger.exception("No se pudo enviar alerta operativa de pagos: %s", subject)


def send_order_confirmation(order_id: int) -> None:
    _idempotent_send(order_id, "confirmation_email_sent", _send, "confirmación")
