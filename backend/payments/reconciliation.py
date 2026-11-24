from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Case, F, Q, Value, When

from .mercadopago import MercadoPagoError, cancel_payment, get_payment, search_payments
from .models import PaymentDraft
from .services import PaymentValidationError, _validate_payment, process_payment, release_reserved_stock


PENDING = {"pending", "in_process", "authorized"}
UNPAID = {"cancelled", "rejected"}
KNOWN_STATUSES = PENDING | UNPAID | {"approved", "refunded", "charged_back"}
ACTIVE_RESERVATIONS = {"reserved", "preference_created", "pending"}


def pending_deadline(now):
    return now - timedelta(hours=settings.MP_PENDING_MAX_HOURS)


def reconciliation_batch(now, size):
    urgent = Q(
        order__isnull=True,
        stock_released_at__isnull=True,
        state__in=ACTIVE_RESERVATIONS,
    ) & (
        Q(reservation_expires_at__lte=now)
        | Q(state="pending", created_at__lte=pending_deadline(now))
    )
    return (
        PaymentDraft.objects.filter(
            Q(order__isnull=True)
            | Q(order__payment_status__in=["pending", "review", "approved", "partially_refunded"]),
            state__in=ACTIVE_RESERVATIONS | {"approved", "review"},
        )
        .annotate(priority=Case(When(urgent, then=Value(0)), default=Value(1)))
        .order_by("priority", F("last_reconciled_at").asc(nulls_first=True), "created_at", "pk")[:size]
    )


@dataclass
class ReconciliationResult:
    processed: bool = False
    released: bool = False
    review: str = ""
    error: str = ""


def find_payment(draft):
    if draft.mp_payment_id:
        return get_payment(draft.mp_payment_id)
    results = search_payments(str(draft.token))
    candidates = [
        payment
        for payment in results
        if str(payment.get("external_reference") or "") == str(draft.token)
    ]
    if results and not candidates:
        raise PaymentValidationError("draft_reference_mismatch")
    unresolved = [payment for payment in candidates if payment.get("status") not in UNPAID]
    if len(unresolved) > 1:
        raise PaymentValidationError("multiple_unresolved_payments")
    return next(iter(unresolved or candidates), None)


def reconcile_draft(draft, now, *, release_expired):
    PaymentDraft.objects.filter(pk=draft.pk).update(last_reconciled_at=now)
    try:
        payment = find_payment(draft)
        if not payment:
            if draft.mp_payment_id or draft.state == "pending":
                raise PaymentValidationError("pending_payment_not_found")
            released = release_expired and release_reserved_stock(
                draft.token, "expired", unpaid_expiry=now
            )
            return ReconciliationResult(released=released)

        payment_id = draft.mp_payment_id or str(payment.get("id") or "")
        status = str(payment.get("status") or "")
        if status not in KNOWN_STATUSES:
            raise PaymentValidationError("unknown_payment_status")
        if str(payment.get("external_reference") or "") != str(draft.token):
            raise PaymentValidationError("draft_reference_mismatch")
        if release_expired and status in PENDING and draft.created_at <= pending_deadline(now):
            _validate_payment(payment, payment_id)
            cancellation_error = None
            try:
                cancel_payment(payment_id, idempotency_key=f"rasel-cancel-{payment_id}")
            except MercadoPagoError as exc:
                # The provider may reject a cancellation because it settled first.
                cancellation_error = exc
            payment = get_payment(payment_id)
            if str(payment.get("status") or "") not in UNPAID | {"approved"}:
                raise MercadoPagoError(
                    "Mercado Pago no confirmó el estado final del pago"
                ) from cancellation_error
            if str(payment.get("external_reference") or "") != str(draft.token):
                raise PaymentValidationError("draft_reference_mismatch")

        result = process_payment(payment, payment_id, reconciled=True)
        released = (
            not draft.stock_released_at and result.draft is not None
            and result.draft.stock_released_at is not None
        )
        review = (result.error or "payment_review") if result.state == "review" else ""
        return ReconciliationResult(processed=True, released=released, review=review)
    except (MercadoPagoError, PaymentValidationError, OSError) as exc:
        error = str(exc)[:1000]
        PaymentDraft.objects.filter(pk=draft.pk).update(processing_error=error)
        return ReconciliationResult(error=error)
