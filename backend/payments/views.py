import hashlib
import hmac
import os
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from orders.models import Order
from .mercadopago import create_preference, get_payment, MercadoPagoError
from urllib.parse import urlparse
from .models import PaymentEvent


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

def _build_preference_payload(order: Order) -> dict:
    items = []
    for it in order.items.all():
        items.append(
            {
                "title": f"{it.product_name} - {it.variant_name}",
                "quantity": int(it.quantity),
                "unit_price": float(it.unit_price),
                "currency_id": "ARS",
            }
        )

    base = _site_url().rstrip("/")

    payload = {
        "items": items,
        "external_reference": str(order.id),
        "payer": {"email": order.email},
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
def start(request, order_id: int):
    order = get_object_or_404(Order.objects.prefetch_related("items"), id=order_id)

    if order.status == "paid":
        return redirect("orders:confirmation", order_id=order.id)

    # Si ya existe preference, no la recreamos
    if not order.mp_preference_id:
        payload = _build_preference_payload(order)
        print("MP preference payload:", json.dumps(payload, indent=2))
        pref = create_preference(payload)
        order.mp_preference_id = pref.get("id", "") or ""
        order.save(update_fields=["mp_preference_id"])

        init_point = pref.get("init_point")  # con credenciales de test redirige a sandbox
    else:
        # Para MVP, recrear init_point sin GET preference (evitamos dependencia extra).
        # Si querés, luego podemos implementar GET /checkout/preferences/{id}.
        init_point = None

    if not init_point:
        # fallback: recrear preference (simple y robusto en MVP)
        payload = _build_preference_payload(order)
        pref = create_preference(payload)
        order.mp_preference_id = pref.get("id", "") or ""
        order.save(update_fields=["mp_preference_id"])
        init_point = pref.get("init_point")

    return redirect(init_point)


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
    if external_reference.isdigit():
        order = Order.objects.filter(id=int(external_reference)).first()

    if order:
        changed = False
        if payment_id and order.mp_payment_id != payment_id:
            order.mp_payment_id = payment_id
            changed = True
        if status and order.mp_status != status:
            order.mp_status = status
            changed = True

        # Si vuelve approved, marcamos paid (igual lo confirmamos con webhook luego)
        if status == "approved" and order.status != "paid":
            order.status = "paid"
            changed = True

        if changed:
            order.save(update_fields=["mp_payment_id", "mp_status", "status"])

    return render(
        request,
        "payments/payment_result.html",
        {
            "result": result,
            "order": order,
            "payment_id": payment_id,
            "status": status,
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
        return True

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
    return hmac.compare_digest(digest, v1)


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

def _mark_order_paid(order_id: str, payment_id: str = "", mp_status: str = "approved") -> None:
    """
    Marca la orden como pagada y guarda los datos de MercadoPago.
    """
    try:
        order = Order.objects.get(id=int(order_id))
    except Exception:
        return

    order.status = "paid"
    if payment_id:
        order.mp_payment_id = payment_id
    order.mp_status = mp_status
    order.save(update_fields=["status", "mp_payment_id", "mp_status"])


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
        or str(data.get("data", {}).get("id", "") if isinstance(data.get("data"), dict) else "")
        or str(data.get("id", ""))
    )
    resource = request.GET.get("resource") or data.get("resource", "")

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
        return HttpResponse(status=401)

    try:
        if str(topic).lower() in {"payment", "payments"} and event_id:
            payment = get_payment(str(event_id))

            mp_status = str(payment.get("status", ""))
            external_ref = str(payment.get("external_reference", ""))
            payment_id = str(payment.get("id", event_id))

            if mp_status == "approved" and external_ref:
                _mark_order_paid(external_ref, payment_id=payment_id, mp_status=mp_status)
                ev.processed_ok = True
                ev.notes = f"approved payment_id={payment_id} order={external_ref}"
            elif mp_status in ("cancelled", "rejected") and external_ref:
                # Actualizar estado sin marcar paid
                try:
                    order = Order.objects.get(id=int(external_ref))
                    order.mp_payment_id = payment_id
                    order.mp_status = mp_status
                    order.status = "cancelled"
                    order.save(update_fields=["mp_payment_id", "mp_status", "status"])
                except Exception:
                    pass
                ev.notes = f"{mp_status} payment_id={payment_id} order={external_ref}"
            else:
                ev.notes = f"status={mp_status} external_ref={external_ref} (no action)"

            ev.save(update_fields=["processed_ok", "notes"])
            return JsonResponse({"ok": True})

        ev.notes = "event received but not processed (not payment topic or missing id)"
        ev.save(update_fields=["notes"])
        return JsonResponse({"ok": True})
    except Exception as e:
        ev.notes = f"processing error: {e}"
        ev.save(update_fields=["notes"])
        return JsonResponse({"ok": True})