from django.conf import settings

import mercadopago
from mercadopago.config import RequestOptions
from mercadopago.webhook import (
    InvalidWebhookSignatureError,
    WebhookSignatureValidator,
)


class MercadoPagoError(RuntimeError):
    """A transient or provider-side Mercado Pago failure."""


def _token() -> str:
    token = settings.MP_ACCESS_TOKEN
    if not token:
        raise MercadoPagoError("MP_ACCESS_TOKEN no esta configurado")
    return token


def _request_options(idempotency_key: str = "") -> RequestOptions:
    headers = {"x-idempotency-key": idempotency_key} if idempotency_key else None
    return RequestOptions(
        access_token=_token(),
        connection_timeout=20.0,
        custom_headers=headers,
        max_retries=2,
    )


def _response(result: dict, operation: str) -> dict:
    status = int(result.get("status", 0) or 0)
    payload = result.get("response")
    if 200 <= status < 300 and isinstance(payload, dict):
        return payload
    raise MercadoPagoError(f"Mercado Pago fallo al {operation} (HTTP {status or 'desconocido'})")


def _sdk():
    return mercadopago.SDK(_token())


def _execute(operation: str, callback) -> dict:
    try:
        result = callback()
    except Exception as exc:
        raise MercadoPagoError(f"Mercado Pago no disponible al {operation}") from exc
    return _response(result, operation)


def create_preference(payload: dict, idempotency_key: str) -> dict:
    return _execute(
        "crear la preferencia",
        lambda: _sdk().preference().create(
            payload,
            request_options=_request_options(idempotency_key),
        ),
    )


def get_preference(preference_id: str) -> dict:
    return _execute(
        "consultar la preferencia",
        lambda: _sdk().preference().get(preference_id),
    )


def get_payment(payment_id: str) -> dict:
    return _execute(
        "consultar el pago",
        lambda: _sdk().payment().get(payment_id),
    )


def search_payments(external_reference: str) -> list[dict]:
    payload = _execute(
        "buscar pagos",
        lambda: _sdk().payment().search(
            {
                "external_reference": external_reference,
                "sort": "date_created",
                "criteria": "desc",
            }
        ),
    )
    return payload.get("results", []) if isinstance(payload.get("results"), list) else []


def cancel_payment(payment_id: str, idempotency_key: str) -> dict:
    return _execute(
        "cancelar el pago",
        lambda: _sdk().payment().update(
            payment_id,
            {"status": "cancelled"},
            request_options=_request_options(idempotency_key),
        ),
    )


def validate_webhook_signature(
    x_signature: str,
    x_request_id: str,
    data_id: str,
    secret: str,
) -> bool:
    if not all((x_signature, x_request_id, data_id, secret)):
        return False
    try:
        WebhookSignatureValidator.validate(
            x_signature,
            x_request_id,
            data_id,
            secret,
        )
    except (InvalidWebhookSignatureError, ValueError, TypeError):
        return False
    return True
