import os
import requests


MP_API_BASE = "https://api.mercadopago.com"


class MercadoPagoError(RuntimeError):
    pass


def _headers() -> dict:
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        raise MercadoPagoError("Falta MP_ACCESS_TOKEN en variables de entorno")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_preference(payload: dict) -> dict:
    url = f"{MP_API_BASE}/checkout/preferences"
    r = requests.post(url, headers=_headers(), json=payload, timeout=20)
    if r.status_code >= 400:
        raise MercadoPagoError(f"MercadoPago create_preference error {r.status_code}: {r.text}")
    return r.json()


def get_payment(payment_id: str) -> dict:
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    r = requests.get(url, headers=_headers(), timeout=20)
    if r.status_code >= 400:
        raise MercadoPagoError(f"MercadoPago get_payment error {r.status_code}: {r.text}")
    return r.json()