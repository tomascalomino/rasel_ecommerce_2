from django.contrib import admin, messages

from .mercadopago import MercadoPagoError, get_payment, search_payments
from .models import PaymentDraft, PaymentEvent
from .services import PaymentValidationError, process_payment


@admin.action(description="Reconciliar con Mercado Pago")
def reconcile_with_mercadopago(modeladmin, request, queryset):
    processed = 0
    failed = 0
    for draft in queryset:
        try:
            if draft.mp_payment_id:
                payment = get_payment(draft.mp_payment_id)
            else:
                candidates = search_payments(str(draft.token))
                payment = next(
                    (
                        row
                        for row in candidates
                        if str(row.get("external_reference") or "") == str(draft.token)
                    ),
                    None,
                )
            if not payment:
                failed += 1
                continue
            process_payment(payment, str(payment.get("id") or ""), reconciled=True)
            processed += 1
        except (MercadoPagoError, PaymentValidationError):
            failed += 1
    if processed:
        messages.success(request, f"{processed} pago(s) conciliados.")
    if failed:
        messages.warning(request, f"{failed} pago(s) requieren revision o reintento.")


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "topic",
        "provider_event_id",
        "event_id",
        "signature_valid",
        "processed_ok",
        "created_at",
    )
    list_filter = ("signature_valid", "processed_ok", "topic", "provider")
    search_fields = (
        "provider_event_id",
        "event_id",
        "request_id",
        "notes",
        "resource",
    )
    readonly_fields = (
        "provider",
        "topic",
        "provider_event_id",
        "event_id",
        "action",
        "request_id",
        "resource",
        "raw",
        "signature_valid",
        "processed_ok",
        "processing_error",
        "notes",
        "created_at",
    )
    ordering = ("-created_at",)


@admin.register(PaymentDraft)
class PaymentDraftAdmin(admin.ModelAdmin):
    list_display = (
        "token",
        "email",
        "total_amount",
        "state",
        "mp_status",
        "reservation_expires_at",
        "stock_released_at",
        "created_at",
    )
    list_filter = ("state", "mp_status", "mp_live_mode", "created_at")
    search_fields = ("token", "email", "mp_preference_id", "mp_payment_id")
    readonly_fields = (
        "token",
        "items",
        "state",
        "stock_reserved_at",
        "reservation_expires_at",
        "stock_released_at",
        "mp_preference_id",
        "mp_payment_id",
        "mp_status",
        "mp_status_detail",
        "mp_init_point",
        "mp_collector_id",
        "mp_live_mode",
        "last_reconciled_at",
        "processing_error",
        "created_at",
        "consumed_at",
        "order",
    )
    ordering = ("-created_at",)
    actions = [reconcile_with_mercadopago]
