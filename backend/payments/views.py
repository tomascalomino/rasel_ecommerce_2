import json
import logging

from django.conf import settings
from django.db import DatabaseError, IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from cart.cart import Cart
from orders.emails import send_payment_alert

from .mercadopago import MercadoPagoError, get_payment, validate_webhook_signature
from .models import PaymentDraft, PaymentEvent
from .services import (
    PaymentValidationError,
    create_checkout_preference,
    process_payment,
)


logger = logging.getLogger("payments.flow")


def _session_draft(request):
    token = str(request.session.get("active_payment_draft") or "")
    if not token:
        return None
    try:
        return PaymentDraft.objects.select_related("order").filter(token=token).first()
    except (ValueError, DatabaseError):
        return None


@require_POST
def start(request, draft_id):
    """Retry preference creation; the initial attempt happens in checkout POST."""
    if not settings.MP_CHECKOUT_ENABLED:
        return HttpResponse("Mercado Pago no esta disponible para pagos nuevos.", status=503)
    if str(request.session.get("active_payment_draft") or "") != str(draft_id):
        return HttpResponse(status=403)

    draft = get_object_or_404(PaymentDraft, token=draft_id)
    if draft.order_id:
        return redirect("orders:confirmation", order_id=draft.order_id)
    try:
        draft = create_checkout_preference(draft.token)
    except PaymentValidationError as exc:
        logger.warning("No se pudo reintentar draft=%s: %s", draft.token, exc)
        return render(
            request,
            "payments/payment_result.html",
            {"display_state": "expired", "draft": draft},
            status=409,
        )
    except MercadoPagoError:
        logger.exception("Mercado Pago no disponible al reintentar draft=%s", draft.token)
        return render(
            request,
            "payments/payment_retry.html",
            {"draft": draft},
            status=503,
        )
    return redirect(draft.mp_init_point)


@require_GET
def payment_return(request, result: str):
    """Never trusts browser status; it only processes a payment read from MP's API."""
    del result
    payment_id = str(
        request.GET.get("payment_id") or request.GET.get("collection_id") or ""
    )
    active_draft = _session_draft(request)
    processed = None

    if payment_id:
        try:
            payment = get_payment(payment_id)
            processed = process_payment(payment, payment_id)
        except MercadoPagoError:
            logger.exception("No se pudo verificar retorno payment_id=%s", payment_id)
        except PaymentValidationError as exc:
            logger.warning("Retorno no asociado payment_id=%s reason=%s", payment_id, exc)
        except (DatabaseError, IntegrityError):
            logger.exception("Error de base verificando retorno payment_id=%s", payment_id)

    draft = active_draft
    order = active_draft.order if active_draft else None
    if processed and active_draft and processed.draft:
        if processed.draft.pk == active_draft.pk:
            draft = processed.draft
            order = processed.order

    display_state = "verifying"
    if order and order.status == "payment_review":
        display_state = "review"
    elif order and order.payment_status == "approved":
        display_state = "approved"
        Cart(request.session).clear()
        request.session.pop("active_payment_draft", None)
        request.session.modified = True
    elif draft and draft.state in {"rejected", "cancelled", "expired", "released"}:
        display_state = draft.state
    elif draft and draft.state in {"pending", "preference_created", "reserved"}:
        display_state = "pending"

    return render(
        request,
        "payments/payment_result.html",
        {"display_state": display_state, "order": order, "draft": draft},
    )


def _webhook_data(request):
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    body_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data_id = str(request.GET.get("data.id") or body_data.get("id") or "")
    return payload, data_id


@csrf_exempt
@require_POST
def webhook(request):
    try:
        payload, data_id = _webhook_data(request)
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid payload"}, status=400)

    request_id = request.headers.get("x-request-id", "")
    if not validate_webhook_signature(
        request.headers.get("x-signature", ""),
        request_id,
        data_id,
        settings.MP_WEBHOOK_SECRET,
    ):
        logger.warning("Webhook MP con firma invalida request_id=%s", request_id)
        return HttpResponse(status=401)

    topic = str(payload.get("type") or payload.get("topic") or "")
    action = str(payload.get("action") or "")
    provider_event_id = str(payload.get("id") or "")
    defaults = {
        "topic": topic,
        "event_id": data_id,
        "action": action,
        "request_id": request_id,
        "resource": str(payload.get("resource") or ""),
        "raw": payload,
        "signature_valid": True,
    }
    try:
        if provider_event_id:
            event, _ = PaymentEvent.objects.get_or_create(
                provider="mercadopago",
                provider_event_id=provider_event_id,
                defaults=defaults,
            )
        else:
            event = PaymentEvent.objects.create(
                provider="mercadopago",
                provider_event_id="",
                **defaults,
            )
        if event.processed_ok:
            return JsonResponse({"ok": True, "duplicate": True})

        if topic.lower() not in {"payment", "payments"}:
            event.processed_ok = True
            event.notes = "Evento firmado fuera del topico de pagos; ignorado."
            event.processing_error = ""
            event.save(update_fields=["processed_ok", "notes", "processing_error"])
            return JsonResponse({"ok": True, "ignored": True})
        if not data_id:
            event.processing_error = "missing_payment_id"
            event.save(update_fields=["processing_error"])
            return JsonResponse({"ok": False, "error": "missing payment id"}, status=400)

        try:
            payment = get_payment(data_id)
            result = process_payment(payment, data_id)
        except PaymentValidationError as exc:
            event.processing_error = str(exc)
            event.notes = "Evento autentico no asociado a una operacion valida de RaSel."
            event.save(update_fields=["processing_error", "notes"])
            send_payment_alert(
                "Notificacion MP requiere revision",
                f"El pago {data_id} no paso las validaciones internas: {exc}.",
            )
            return JsonResponse({"ok": True, "ignored": True})
        except MercadoPagoError as exc:
            event.processing_error = str(exc)
            event.save(update_fields=["processing_error"])
            return JsonResponse({"ok": False, "error": "provider unavailable"}, status=500)

        event.processed_ok = True
        event.processing_error = ""
        event.notes = (
            f"Pago procesado; estado={result.state}; "
            f"order={result.order.id if result.order else ''}"
        )
        event.save(update_fields=["processed_ok", "processing_error", "notes"])
        return JsonResponse({"ok": True})
    except (DatabaseError, IntegrityError):
        logger.exception("Fallo transitorio procesando webhook request_id=%s", request_id)
        return JsonResponse({"ok": False, "error": "temporary failure"}, status=500)
