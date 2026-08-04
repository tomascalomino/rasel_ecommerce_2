import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from orders.emails import send_order_confirmation, send_payment_alert
from orders.models import Order, OrderItem
from shop.models import Variant

from .mercadopago import MercadoPagoError, create_preference
from .models import PaymentDraft


logger = logging.getLogger("payments.services")


class PaymentValidationError(ValueError):
    pass


@dataclass
class PaymentResult:
    draft: PaymentDraft | None
    order: Order | None
    state: str
    error: str = ""


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentValidationError("invalid_amount") from exc


def reserve_payment_draft(*, customer, delivery, cart_rows, total_amount) -> PaymentDraft:
    now = timezone.now()
    expires_at = now + timedelta(minutes=settings.MP_RESERVATION_MINUTES)

    with transaction.atomic():
        snapshots = []
        subtotal = Decimal("0.00")
        for cart_item in cart_rows:
            variant = (
                Variant.objects.select_for_update()
                .select_related("product")
                .get(pk=cart_item.variant.id, is_active=True)
            )
            quantity = int(cart_item.qty)
            if quantity <= 0 or variant.stock_qty < quantity:
                raise PaymentValidationError(
                    f"Sin stock suficiente de {variant.product.name} ({variant.name})."
                )
            unit_price = _decimal(variant.price_ars)
            line_total = unit_price * quantity
            subtotal += line_total
            snapshots.append(
                {
                    "variant_id": variant.id,
                    "sku": variant.sku,
                    "product_name": variant.product.name,
                    "variant_name": variant.name,
                    "unit_price": str(unit_price),
                    "quantity": quantity,
                    "line_total": str(line_total),
                }
            )

        if not snapshots:
            raise PaymentValidationError("El carrito ya no tiene productos disponibles.")

        shipping_cost = _decimal(delivery["shipping_cost"])
        expected_total = (subtotal + shipping_cost).quantize(Decimal("0.01"))
        if expected_total != _decimal(total_amount):
            raise PaymentValidationError("El total del carrito cambio. Volve a intentarlo.")

        for row in snapshots:
            Variant.objects.filter(pk=row["variant_id"]).update(
                stock_qty=F("stock_qty") - row["quantity"]
            )

        return PaymentDraft.objects.create(
            **customer,
            **delivery,
            total_amount=expected_total,
            items=snapshots,
            state="reserved",
            stock_reserved_at=now,
            reservation_expires_at=expires_at,
        )


def build_preference_payload(draft: PaymentDraft) -> dict:
    items = [
        {
            "id": row.get("sku") or str(row["variant_id"]),
            "title": f"{row['product_name']} - {row['variant_name']}",
            "quantity": int(row["quantity"]),
            "unit_price": float(_decimal(row["unit_price"])),
            "currency_id": "ARS",
        }
        for row in draft.items
    ]
    if draft.shipping_cost > 0:
        items.append(
            {
                "id": "shipping",
                "title": f"Envío - {draft.shipping_zone or 'domicilio'}",
                "quantity": 1,
                "unit_price": float(draft.shipping_cost),
                "currency_id": "ARS",
            }
        )

    base = settings.SITE_URL
    token = str(draft.token)
    return {
        "items": items,
        "payer": {"name": draft.full_name, "email": draft.email},
        "external_reference": token,
        "metadata": {"draft_token": token},
        "back_urls": {
            "success": f"{base}/payments/return/success/",
            "pending": f"{base}/payments/return/pending/",
            "failure": f"{base}/payments/return/failure/",
        },
        # Pin the Webhook endpoint to every preference. Mercado Pago gives this
        # URL precedence over the application-level setting, which prevents a
        # payment from depending on the buyer returning to RaSel when sandbox
        # and production notification routes differ in the provider panel.
        "notification_url": f"{base}/payments/webhook/?source_news=webhooks",
        "auto_return": "approved",
        "expires": True,
        "expiration_date_from": draft.stock_reserved_at.isoformat(),
        "expiration_date_to": draft.reservation_expires_at.isoformat(),
        "payment_methods": {
            "excluded_payment_types": [{"id": "ticket"}],
            "installments": settings.MP_MAX_INSTALLMENTS,
        },
        "statement_descriptor": "RASEL",
    }


def create_checkout_preference(draft_token) -> PaymentDraft:
    draft = PaymentDraft.objects.get(token=draft_token)
    if draft.order_id:
        return draft
    if draft.stock_released_at or not draft.reservation_expires_at:
        raise PaymentValidationError("La reserva ya no esta disponible.")
    if draft.reservation_expires_at <= timezone.now():
        raise PaymentValidationError("La reserva vencio. Volve al carrito.")
    if draft.mp_init_point:
        return draft

    preference = create_preference(
        build_preference_payload(draft),
        idempotency_key=f"rasel-draft-{draft.token}",
    )
    preference_id = str(preference.get("id") or "")
    init_point = str(preference.get("init_point") or "")
    collector_id = str(preference.get("collector_id") or "")
    if not all((preference_id, init_point, collector_id)):
        raise MercadoPagoError("Mercado Pago devolvio una preferencia incompleta")

    with transaction.atomic():
        locked = PaymentDraft.objects.select_for_update().get(pk=draft.pk)
        if (
            locked.stock_released_at
            or locked.order_id
            or not locked.reservation_expires_at
            or locked.reservation_expires_at <= timezone.now()
        ):
            raise PaymentValidationError("La reserva vencio antes de iniciar el pago.")
        if not locked.mp_init_point:
            locked.mp_preference_id = preference_id
            locked.mp_init_point = init_point
            locked.mp_collector_id = collector_id
            locked.state = "preference_created"
            locked.processing_error = ""
            locked.save(
                update_fields=[
                    "mp_preference_id",
                    "mp_init_point",
                    "mp_collector_id",
                    "state",
                    "processing_error",
                ]
            )
        return locked


def release_reserved_stock(draft_token, state="released") -> bool:
    with transaction.atomic():
        draft = PaymentDraft.objects.select_for_update().get(token=draft_token)
        if draft.stock_released_at or draft.order_id:
            return False
        if not draft.stock_reserved_at:
            draft.state = state
            draft.save(update_fields=["state"])
            return False
        variant_ids = sorted(int(row["variant_id"]) for row in draft.items)
        variants = {
            variant.id: variant
            for variant in Variant.objects.select_for_update().filter(id__in=variant_ids)
        }
        for row in draft.items:
            variant = variants.get(int(row["variant_id"]))
            if variant:
                variant.stock_qty += int(row["quantity"])
                variant.save(update_fields=["stock_qty"])
        draft.stock_released_at = timezone.now()
        draft.state = state
        draft.save(update_fields=["stock_released_at", "state"])
        return True


def _metadata_token(payment: dict) -> str:
    metadata = payment.get("metadata") or {}
    return str(metadata.get("draft_token") or metadata.get("draft_id") or "")


def _expected_live_mode(draft: PaymentDraft) -> bool:
    """Tie live_mode to the provider-issued checkout endpoint.

    Checkout Pro test users can pay through the regular ``init_point``. Those
    safe test transactions still report ``live_mode=true``; the test Access
    Token and collector ID are what isolate them from the real seller account.
    """
    host = (urlparse(draft.mp_init_point).hostname or "").lower()
    if not host:
        # Compatibilidad con borradores históricos creados antes de guardar la
        # URL de preferencia. Un checkout actual siempre persiste este campo.
        return settings.MP_ENVIRONMENT == "production"
    if host in {"sandbox.mercadopago.com", "sandbox.mercadopago.com.ar"}:
        return False
    if host in {"www.mercadopago.com", "www.mercadopago.com.ar"}:
        return True
    raise PaymentValidationError("checkout_endpoint_mismatch")


def _validate_payment(payment: dict, requested_payment_id: str):
    if settings.MP_ENVIRONMENT not in {"test", "production"}:
        raise PaymentValidationError("environment_not_configured")
    payment_id = str(payment.get("id") or "")
    if not payment_id or payment_id != str(requested_payment_id):
        raise PaymentValidationError("payment_id_mismatch")
    external_reference = str(payment.get("external_reference") or "")
    metadata_token = _metadata_token(payment)
    if not external_reference or (metadata_token and metadata_token != external_reference):
        raise PaymentValidationError("draft_reference_mismatch")
    try:
        draft = PaymentDraft.objects.get(token=external_reference)
    except (PaymentDraft.DoesNotExist, ValidationError, ValueError) as exc:
        raise PaymentValidationError("draft_not_found") from exc

    if _decimal(payment.get("transaction_amount")) != _decimal(draft.total_amount):
        raise PaymentValidationError("amount_mismatch")
    if str(payment.get("currency_id") or "") != "ARS":
        raise PaymentValidationError("currency_mismatch")
    if not draft.mp_collector_id or str(payment.get("collector_id") or "") != draft.mp_collector_id:
        raise PaymentValidationError("collector_mismatch")
    expected_live = _expected_live_mode(draft)
    if not isinstance(payment.get("live_mode"), bool) or payment.get("live_mode") != expected_live:
        raise PaymentValidationError("live_mode_mismatch")
    return draft


def _create_order_items(order, draft, variants):
    for row in draft.items:
        variant = variants.get(int(row["variant_id"]))
        OrderItem.objects.create(
            order=order,
            variant=variant,
            product_name=str(row["product_name"]),
            variant_name=str(row["variant_name"]),
            unit_price=_decimal(row["unit_price"]),
            quantity=int(row["quantity"]),
            line_total=_decimal(row["line_total"]),
        )


def _reservation_holds_stock(draft):
    return bool(draft.stock_reserved_at and not draft.stock_released_at)


def _create_order(draft, payment, *, review=False, stock_deducted=True):
    payment_id = str(payment["id"])
    existing = Order.objects.filter(mp_payment_id=payment_id).first()
    if existing:
        draft.order = existing
        draft.save(update_fields=["order"])
        return existing

    variants = {
        variant.id: variant
        for variant in Variant.objects.filter(
            id__in=[int(row["variant_id"]) for row in draft.items]
        )
    }
    order = Order.objects.create(
        full_name=draft.full_name,
        email=draft.email,
        phone=draft.phone,
        address_line=draft.address_line,
        address_extra=draft.address_extra,
        city=draft.city,
        postal_code=draft.postal_code,
        delivery_method=draft.delivery_method,
        pickup_point=draft.pickup_point,
        pickup_point_label=draft.pickup_point_label,
        shipping_cost=draft.shipping_cost,
        shipping_zone=draft.shipping_zone,
        shipping_carrier_arranged=draft.shipping_carrier_arranged,
        total_amount=draft.total_amount,
        status="payment_review" if review else "paid",
        payment_method="mp",
        payment_status="review" if review else "approved",
        mp_preference_id=draft.mp_preference_id,
        mp_payment_id=payment_id,
        mp_status=str(payment.get("status") or ""),
        stock_deducted=stock_deducted,
    )
    _create_order_items(order, draft, variants)
    draft.order = order
    draft.consumed_at = timezone.now()
    draft.save(update_fields=["order", "consumed_at"])
    return order


def _approve(draft_id, payment):
    with transaction.atomic():
        draft = PaymentDraft.objects.select_for_update().get(pk=draft_id)
        if draft.order_id:
            order = draft.order
            if order.mp_payment_id and order.mp_payment_id != str(payment.get("id") or ""):
                order.status = "payment_review"
                order.payment_status = "review"
                order.save(update_fields=["status", "payment_status"])
                draft.state = "review"
                draft.processing_error = "multiple_approved_payments"
                draft.save(update_fields=["state", "processing_error"])
                transaction.on_commit(
                    lambda: send_payment_alert(
                        f"Posible cobro duplicado MP - orden #{order.id}",
                        "Se detecto mas de un pago aprobado para el mismo borrador. "
                        "Revisar y reintegrar el cobro adicional si corresponde.",
                    )
                )
                return order
            resolving_live_mode_review = (
                order.status == "payment_review"
                and order.payment_status == "review"
                and order.stock_deducted
                and draft.processing_error == "live_mode_mismatch"
            )
            if order.status == "payment_review" and not resolving_live_mode_review:
                return order
            if order.payment_status not in {"refunded", "charged_back"}:
                order.payment_status = "approved"
                if order.status == "pending" or resolving_live_mode_review:
                    order.status = "paid"
                order.mp_status = "approved"
                order.save(update_fields=["payment_status", "status", "mp_status"])
            draft.state = "approved"
            draft.processing_error = ""
            draft.save(update_fields=["state", "processing_error"])
            if resolving_live_mode_review:
                transaction.on_commit(lambda: send_order_confirmation(order.id))
            return order

        stock_deducted = _reservation_holds_stock(draft)
        if stock_deducted:
            variant_ids = {int(row["variant_id"]) for row in draft.items}
            existing_ids = set(
                Variant.objects.select_for_update()
                .filter(id__in=variant_ids)
                .values_list("id", flat=True)
            )
            if existing_ids != variant_ids:
                order = _create_order(draft, payment, review=True, stock_deducted=True)
                draft.state = "review"
                draft.processing_error = "reserved_variant_missing"
                draft.save(update_fields=["state", "processing_error"])
                transaction.on_commit(
                    lambda: send_payment_alert(
                        f"Pago MP en revision - orden #{order.id}",
                        "El pago fue aprobado pero un producto reservado ya no existe. "
                        "Revisar la orden y reintegrar si corresponde.",
                    )
                )
                return order
        if not stock_deducted:
            rows = []
            for row in draft.items:
                variant = (
                    Variant.objects.select_for_update()
                    .filter(pk=int(row["variant_id"]), is_active=True)
                    .first()
                )
                if not variant or variant.stock_qty < int(row["quantity"]):
                    order = _create_order(
                        draft, payment, review=True, stock_deducted=False
                    )
                    draft.state = "review"
                    draft.processing_error = "approved_without_stock"
                    draft.save(update_fields=["state", "processing_error"])
                    transaction.on_commit(
                        lambda: send_payment_alert(
                            f"Pago MP en revision - orden #{order.id}",
                            "El pago fue aprobado pero no hay stock para prometer la entrega. "
                            "Revisar la orden y reintegrar si corresponde.",
                        )
                    )
                    return order
                rows.append((variant, int(row["quantity"])))
            for variant, quantity in rows:
                variant.stock_qty -= quantity
                variant.save(update_fields=["stock_qty"])
            stock_deducted = True

        order = _create_order(draft, payment, stock_deducted=stock_deducted)
        draft.state = "approved"
        draft.processing_error = ""
        draft.save(update_fields=["state", "processing_error"])
        transaction.on_commit(lambda: send_order_confirmation(order.id))
        return order


def _review_payment(draft, payment, reason):
    with transaction.atomic():
        locked = PaymentDraft.objects.select_for_update().get(pk=draft.pk)
        order = locked.order or _create_order(
            locked,
            payment,
            review=True,
            stock_deducted=_reservation_holds_stock(locked),
        )
        order.status = "payment_review"
        order.payment_status = "review"
        order.save(update_fields=["status", "payment_status"])
        locked.state = "review"
        locked.processing_error = reason
        locked.save(update_fields=["state", "processing_error"])
        transaction.on_commit(
            lambda: send_payment_alert(
                f"Anomalia de pago MP - orden #{order.id}",
                f"El pago {payment.get('id')} requiere revision: {reason}.",
            )
        )
        return order


def _sync_refund(order, payment):
    refunded = _decimal(payment.get("transaction_amount_refunded") or 0)
    status = str(payment.get("status") or "")
    if status == "charged_back":
        financial = "charged_back"
    elif refunded >= order.total_amount:
        financial = "refunded"
    elif refunded > 0:
        financial = "partially_refunded"
    else:
        return
    order.payment_status = financial
    order.mp_refunded_amount = refunded
    order.mp_status = status
    order.save(update_fields=["payment_status", "mp_refunded_amount", "mp_status"])


def process_payment(payment: dict, requested_payment_id: str, *, reconciled=False) -> PaymentResult:
    try:
        draft = _validate_payment(payment, requested_payment_id)
    except PaymentValidationError as exc:
        reference = str(payment.get("external_reference") or "")
        try:
            draft = PaymentDraft.objects.filter(token=reference).first() if reference else None
        except (ValidationError, ValueError):
            draft = None
        if draft and str(payment.get("status") or "") == "approved":
            order = _review_payment(draft, payment, str(exc))
            return PaymentResult(draft, order, "review", str(exc))
        raise

    payment_id = str(payment["id"])
    status = str(payment.get("status") or "")
    status_detail = str(payment.get("status_detail") or "")
    now = timezone.now()
    PaymentDraft.objects.filter(pk=draft.pk).update(
        mp_payment_id=payment_id,
        mp_status=status,
        mp_status_detail=status_detail,
        mp_live_mode=payment.get("live_mode"),
        last_reconciled_at=now if reconciled else draft.last_reconciled_at,
    )
    draft.refresh_from_db()

    if status == "approved":
        order = _approve(draft.pk, payment)
        order.refresh_from_db()
        _sync_refund(order, payment)
        draft.refresh_from_db()
        return PaymentResult(draft, order, draft.state)
    if status in {"pending", "in_process", "authorized"}:
        # Extend from the current deadline (or from now if it already passed),
        # so receiving a pending status always adds a real reservation window.
        extension_base = max(draft.reservation_expires_at or now, now)
        extension = extension_base + timedelta(
            minutes=settings.MP_RESERVATION_MINUTES
        )
        PaymentDraft.objects.filter(pk=draft.pk, stock_released_at__isnull=True).update(
            state="pending", reservation_expires_at=extension, processing_error=""
        )
        draft.refresh_from_db()
        return PaymentResult(draft, draft.order, "pending")
    if status in {"rejected", "cancelled"}:
        if draft.order_id:
            draft.order.payment_status = status
            draft.order.mp_status = status
            draft.order.save(update_fields=["payment_status", "mp_status"])
        release_reserved_stock(draft.token, status)
        draft.refresh_from_db()
        return PaymentResult(draft, draft.order, status)
    if status in {"refunded", "charged_back"} or payment.get("transaction_amount_refunded"):
        if draft.order:
            _sync_refund(draft.order, payment)
            return PaymentResult(draft, draft.order, draft.order.payment_status)
        order = _review_payment(draft, payment, f"{status}_without_order")
        return PaymentResult(draft, order, "review", f"{status}_without_order")

    PaymentDraft.objects.filter(pk=draft.pk).update(state="pending")
    draft.refresh_from_db()
    return PaymentResult(draft, draft.order, "pending")
