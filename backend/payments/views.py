import hashlib
import hmac
import os
import json
import logging
from decimal import Decimal

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from cart.cart import Cart
from orders.models import Order, OrderItem
from orders.emails import send_order_confirmation
from shop.models import Variant
from .mercadopago import create_preference, get_payment, MercadoPagoError
from urllib.parse import urlparse
from .models import PaymentEvent, PaymentDraft


logger = logging.getLogger("payments.flow")


def _site_url() -> str:
    return os.getenv("SITE_URL", "http://127.0.0.1:8000").rstrip("/")

def _is_public_url(url: str) -> bool:
    """
    MercadoPago necesita una URL pública para notification_url (webhook).
    En local (127.0.0.1/localhost) no sirve.
    """
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    return host not in {"127.0.0.1", "localhost"}

def _build_preference_payload(draft: PaymentDraft) -> dict:
    items = [
        {
            "title": f"{row.get('product_name', 'Producto')} - {row.get('variant_name', 'Variante')}",
            "quantity": int(row.get("quantity", 0) or 0),
            "unit_price": float(row.get("unit_price", 0) or 0),
            "currency_id": "ARS",
        }
        for row in draft.items
        if int(row.get("quantity", 0) or 0) > 0
    ]

    # Cobrar el envío: MercadoPago calcula el total a partir de `items`, así que
    # si no agregamos esta línea el envío no se cobra. Zona gratis (cost 0) = sin línea.
    if draft.shipping_cost and float(draft.shipping_cost) > 0:
        items.append(
            {
                "title": f"Envío — {draft.shipping_zone or 'Envío'}",
                "quantity": 1,
                "unit_price": float(draft.shipping_cost),
                "currency_id": "ARS",
            }
        )

    base = _site_url().rstrip("/")

    payload = {
        "items": items,
        "external_reference": str(draft.token),
        "payer": {"email": draft.email},
        "back_urls": {
            "success": f"{base}/payments/return/success/",
            "pending": f"{base}/payments/return/pending/",
            "failure": f"{base}/payments/return/failure/",
        },
        # OJO: NO auto_return por ahora (ya te había tirado error)
        # "auto_return": "approved",
    }

    # ✅ OJO: ES notification_url (sin 'a' extra)
    # ✅ Solo incluir si la URL es pública (no localhost/127.0.0.1)
    if _is_public_url(base):
        payload["notification_url"] = f"{base}/payments/webhook/"

    return payload

@require_GET
def start(request, draft_id):
    draft = get_object_or_404(PaymentDraft, token=draft_id)

    if draft.order_id:
        return redirect("orders:confirmation", order_id=draft.order_id)

    if not draft.items:
        return redirect("orders:checkout")

    if not draft.mp_preference_id:
        payload = _build_preference_payload(draft)
        logger.info("Creando preference draft=%s email=%s", draft.token, draft.email)
        try:
            pref = create_preference(payload)
            draft.mp_preference_id = pref.get("id", "") or ""
            draft.save(update_fields=["mp_preference_id"])
            init_point = pref.get("init_point")
        except MercadoPagoError as e:
            logger.error("Error creating preference: %s", str(e))
            return HttpResponse(f"Error de MercadoPago: {e}", status=500)
    else:
        init_point = None

    if not init_point:
        payload = _build_preference_payload(draft)
        logger.info("Recreando preference draft=%s", draft.token)
        try:
            pref = create_preference(payload)
            draft.mp_preference_id = pref.get("id", "") or ""
            draft.save(update_fields=["mp_preference_id"])
            init_point = pref.get("init_point")
        except MercadoPagoError as e:
            logger.error("Error recreating preference: %s", str(e))
            return HttpResponse(f"Error de MercadoPago: {e}", status=500)

    return redirect(init_point)


def _set_draft_status(external_reference: str, payment_id: str, status: str) -> None:
    try:
        draft = PaymentDraft.objects.get(token=external_reference)
    except PaymentDraft.DoesNotExist:
        return

    changed = False
    if payment_id and draft.mp_payment_id != payment_id:
        draft.mp_payment_id = payment_id
        changed = True
    if status and draft.mp_status != status:
        draft.mp_status = status
        changed = True

    if changed:
        draft.save(update_fields=["mp_payment_id", "mp_status"])


def _finalize_approved_payment(external_reference: str, payment_id: str, mp_status: str):
    try:
        with transaction.atomic():
            draft = PaymentDraft.objects.select_for_update().select_related("order").get(token=external_reference)
            logger.info("Finalizar pago approved draft=%s payment_id=%s", external_reference, payment_id)

            if draft.order_id:
                if payment_id and draft.mp_payment_id != payment_id:
                    draft.mp_payment_id = payment_id
                    draft.mp_status = mp_status
                    draft.save(update_fields=["mp_payment_id", "mp_status"])
                return draft.order, None

            existing = Order.objects.filter(mp_payment_id=payment_id).first() if payment_id else None
            if existing:
                logger.warning("Order ya existente para payment_id=%s draft=%s order=%s", payment_id, external_reference, existing.id)
                draft.order = existing
                draft.mp_payment_id = payment_id
                draft.mp_status = mp_status
                draft.consumed_at = draft.consumed_at or timezone.now()
                draft.save(update_fields=["order", "mp_payment_id", "mp_status", "consumed_at"])
                return existing, None

            draft_rows = draft.items or []
            if not draft_rows:
                logger.warning("Draft sin items draft=%s payment_id=%s", external_reference, payment_id)
                return None, "draft_without_items"

            variant_rows = []
            for row in draft_rows:
                variant_id = int(row.get("variant_id", 0) or 0)
                qty = int(row.get("quantity", 0) or 0)
                if variant_id <= 0 or qty <= 0:
                    logger.warning("Draft item inválido draft=%s variant_id=%s qty=%s", external_reference, variant_id, qty)
                    return None, "invalid_draft_item"

                variant = Variant.objects.select_for_update().select_related("product").filter(id=variant_id, is_active=True).first()
                if not variant:
                    logger.warning("Variant inexistente o inactiva draft=%s variant_id=%s", external_reference, variant_id)
                    return None, f"variant_not_found:{variant_id}"
                if variant.stock_qty < qty:
                    logger.warning("Stock insuficiente draft=%s variant_id=%s requested=%s stock=%s", external_reference, variant_id, qty, variant.stock_qty)
                    return None, f"insufficient_stock:{variant_id}"

                variant_rows.append((variant, row, qty))

            for variant, _, qty in variant_rows:
                variant.stock_qty -= qty
                variant.save(update_fields=["stock_qty"])

            order = Order.objects.create(
                full_name=draft.full_name,
                email=draft.email,
                phone=draft.phone,
                address_line=draft.address_line,
                city=draft.city,
                postal_code=draft.postal_code,
                shipping_cost=draft.shipping_cost,
                shipping_zone=draft.shipping_zone,
                total_amount=draft.total_amount,
                status="paid",
                mp_preference_id=draft.mp_preference_id,
                mp_payment_id=payment_id,
                mp_status=mp_status,
            )

            for variant, row, qty in variant_rows:
                unit_price = Decimal(str(row.get("unit_price", "0") or "0"))
                line_total = Decimal(str(row.get("line_total", "0") or "0"))
                OrderItem.objects.create(
                    order=order,
                    variant=variant,
                    product_name=str(row.get("product_name", variant.product.name)),
                    variant_name=str(row.get("variant_name", variant.name)),
                    unit_price=unit_price,
                    quantity=qty,
                    line_total=line_total,
                )

            draft.order = order
            draft.mp_payment_id = payment_id
            draft.mp_status = mp_status
            draft.consumed_at = timezone.now()
            draft.save(update_fields=["order", "mp_payment_id", "mp_status", "consumed_at"])
            logger.info("Order creada draft=%s order=%s payment_id=%s", external_reference, order.id, payment_id)
            return order, None
    except PaymentDraft.DoesNotExist:
        logger.warning("Draft no encontrado draft=%s payment_id=%s", external_reference, payment_id)
        return None, "draft_not_found"


@require_GET
def payment_return(request, result: str):
    """
    MercadoPago suele devolver query params como payment_id, status, merchant_order_id.
    Acá guardamos lo que venga, y mostramos pantalla.
    """
    payment_id = request.GET.get("payment_id", "") or request.GET.get("collection_id", "")
    status = request.GET.get("status", "") or request.GET.get("collection_status", "")
    external_reference = request.GET.get("external_reference", "")

    order = None
    draft = None
    finalize_error = ""

    if external_reference:
        draft = PaymentDraft.objects.filter(token=external_reference).first()

    if status == "approved" and external_reference:
        order, finalize_error = _finalize_approved_payment(external_reference, payment_id=payment_id, mp_status=status)
        if order:
            send_order_confirmation(order.id)
            active_draft = str(request.session.get("active_payment_draft", ""))
            if active_draft == external_reference:
                Cart(request.session).clear()
                request.session.pop("active_payment_draft", None)
                request.session.modified = True
        if draft and not order:
            logger.warning("Approved sin order draft=%s payment_id=%s error=%s", external_reference, payment_id, finalize_error)
            draft.mp_status = status
            if payment_id:
                draft.mp_payment_id = payment_id
            draft.save(update_fields=["mp_status", "mp_payment_id"])
    elif external_reference:
        _set_draft_status(external_reference, payment_id=payment_id, status=status)
        if draft:
            draft.refresh_from_db()

    return render(
        request,
        "payments/payment_result.html",
        {
            "result": result,
            "order": order,
            "draft": draft,
            "payment_id": payment_id,
            "status": status,
            "finalize_error": finalize_error,
        },
    )


def _verify_webhook_signature(request, event_id: str) -> bool:
    """
    Validación HMAC (opcional pero recomendado si configurás MP_WEBHOOK_SECRET).
    MercadoPago usa x-signature + x-request-id para calcular un hash.
    Si no hay secret, devolvemos True para no bloquear MVP.
    """
    secret = os.getenv("MP_WEBHOOK_SECRET", "").strip()
    if not secret:
        # En producción NO aceptamos webhooks sin firma: cualquiera podría
        # postear un "pago aprobado" falso. En DEBUG lo permitimos para testear.
        from django.conf import settings as dj_settings
        if dj_settings.DEBUG or dj_settings.RUNNING_TESTS:
            return True
        logger.error(
            "MP_WEBHOOK_SECRET no configurado en producción: webhook rechazado event_id=%s",
            event_id,
        )
        return False

    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    # x-signature suele venir como: "ts=...,v1=..."
    parts = {}
    for part in x_signature.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.strip()] = v.strip()

    ts = parts.get("ts")
    v1 = parts.get("v1")
    if not (ts and v1 and x_request_id and event_id):
        return False

    manifest = f"id:{event_id};request-id:{x_request_id};ts:{ts};"
    # ✅ Fix: hmac.new() es la API correcta en Python (hmac.HMAC alias)
    digest = hmac.new(secret.encode(), msg=manifest.encode(), digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, str(v1))


# @csrf_exempt
# @require_POST
# def webhook(request):
#     """
#     Webhook puede llegar como:
#     - Webhooks: body con type + data.id
#     - IPN: query params topic + id
#     Luego consultamos /v1/payments/{id} para estado y external_reference.
#     """
#     # Intento 1: Webhooks (body JSON)
#     try:
#         payload = request.json if hasattr(request, "json") else None  # no siempre existe
#     except Exception:
#         payload = None

#     if payload is None:
#         import json
#         try:
#             payload = json.loads(request.body.decode("utf-8") or "{}")
#         except Exception:
#             payload = {}

#     event_type = payload.get("type") or payload.get("topic")
#     data = payload.get("data") or {}
#     event_id = str(data.get("id") or request.GET.get("id") or request.GET.get("data.id") or "")

#     # Validar firma si está configurada
#     if event_id and not _verify_webhook_signature(request, event_id):
#         return HttpResponse(status=401)

#     # Solo manejamos pagos en MVP
#     if event_type not in ("payment", "payments"):
#         return JsonResponse({"ok": True, "ignored": True})

#     if not event_id:
#         return JsonResponse({"ok": False, "error": "missing payment id"}, status=400)

#     try:
#         p = get_payment(event_id)
#     except MercadoPagoError as e:
#         return JsonResponse({"ok": False, "error": str(e)}, status=400)

#     external_reference = str(p.get("external_reference") or "")
#     status = str(p.get("status") or "")
#     payment_id = str(p.get("id") or event_id)

#     if not external_reference.isdigit():
#         return JsonResponse({"ok": True, "warning": "no external_reference to map order"})

#     order = Order.objects.filter(id=int(external_reference)).first()
#     if not order:
#         return JsonResponse({"ok": True, "warning": "order not found"})

#     order.mp_payment_id = payment_id
#     order.mp_status = status

#     if status == "approved":
#         order.status = "paid"
#     elif status in ("cancelled", "rejected"):
#         order.status = "cancelled"
#     else:
#         order.status = "pending"

#     order.save(update_fields=["mp_payment_id", "mp_status", "status"])

#     return JsonResponse({"ok": True})

@csrf_exempt
def webhook(request):
    """
    Webhook MercadoPago.
    Soporta:
    - Webhooks modernos: body JSON con {type, data: {id}}
    - IPN clásico: query params topic + id, o data.id
    Guarda PaymentEvent para auditoría y responde siempre 200 para evitar reintentos infinitos.
    """
    try:
        body = request.body.decode("utf-8") if request.body else ""
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    # MercadoPago puede enviar parámetros por query string o body.
    # Webhooks modernos: body {type: "payment", data: {id: "123"}}
    # IPN clásico: ?topic=payment&id=123   o   ?data.id=123
    topic = (
        request.GET.get("topic")
        or request.GET.get("type")
        or data.get("type", "")
    )
    event_id = (
        request.GET.get("id")
        or request.GET.get("data.id")  # IPN query param alternativo
        or str(data.get("data", {}).get("id", "") if isinstance(data, dict) and isinstance(data.get("data"), dict) else "")
        or str(data.get("id", "") if isinstance(data, dict) else "")
    )
    resource = request.GET.get("resource") or (data.get("resource", "") if isinstance(data, dict) else "")

    ev = PaymentEvent.objects.create(
        topic=str(topic or ""),
        event_id=str(event_id or ""),
        resource=str(resource or ""),
        raw=data or {},
        processed_ok=False,
    )

    # Validar firma si está configurada
    if event_id and not _verify_webhook_signature(request, event_id):
        ev.notes = "firma HMAC inválida"
        ev.save(update_fields=["notes"])
        logger.warning("Webhook firma inválida event_id=%s topic=%s", event_id, topic)
        return HttpResponse(status=401)

    try:
        if str(topic).lower() in {"payment", "payments"} and event_id:
            logger.info("Webhook payment event_id=%s topic=%s", event_id, topic)
            payment = get_payment(str(event_id))

            mp_status = str(payment.get("status", ""))
            external_ref = str(payment.get("external_reference", ""))
            payment_id = str(payment.get("id", event_id))

            if mp_status == "approved" and external_ref:
                order, error = _finalize_approved_payment(external_ref, payment_id=payment_id, mp_status=mp_status)
                ev.processed_ok = order is not None
                if order:
                    send_order_confirmation(order.id)
                    ev.notes = f"approved payment_id={payment_id} order={order.id}"
                else:
                    ev.notes = f"approved payment_id={payment_id} finalize_error={error}"
                    logger.warning("Webhook approved sin finalize event_id=%s payment_id=%s error=%s", event_id, payment_id, error)
            elif mp_status in ("cancelled", "rejected") and external_ref:
                _set_draft_status(external_ref, payment_id=payment_id, status=mp_status)
                if draft := PaymentDraft.objects.filter(token=external_ref).select_related("order").first():
                    if draft.order_id and draft.order.status != "paid":
                        draft.order.status = "cancelled"
                        draft.order.mp_status = mp_status
                        draft.order.mp_payment_id = payment_id
                        draft.order.save(update_fields=["status", "mp_status", "mp_payment_id"])
                ev.notes = f"{mp_status} payment_id={payment_id} external_ref={external_ref}"
            else:
                ev.notes = f"status={mp_status} external_ref={external_ref} (no action)"

            ev.save(update_fields=["processed_ok", "notes"])
            return JsonResponse({"ok": True})

        ev.notes = "event received but not processed (not payment topic or missing id)"
        ev.save(update_fields=["notes"])
        logger.info("Webhook ignorado topic=%s event_id=%s", topic, event_id)
        return JsonResponse({"ok": True})
    except Exception as e:
        ev.notes = f"processing error: {e}"
        ev.save(update_fields=["notes"])
        logger.exception("Error procesando webhook event_id=%s topic=%s", event_id, topic)
        return JsonResponse({"ok": True})