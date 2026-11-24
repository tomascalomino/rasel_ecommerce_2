from django.contrib import admin, messages
from django.utils import timezone

from .models import PaymentDraft, PaymentEvent
from .reconciliation import reconcile_draft


def _reconcile_selection(request, queryset, *, release_expired):
    now = timezone.now()
    checked = processed = released = failed = review = 0
    for draft in queryset:
        result = reconcile_draft(draft, now, release_expired=release_expired)
        checked += 1
        processed += result.processed
        released += result.released
        failed += bool(result.error)
        review += bool(result.review)

    if checked:
        level = messages.WARNING if failed or review else messages.INFO
        messages.add_message(
            request, level,
            f"{checked} revisados · {processed} procesados · {released} reservas liberadas · "
            f"{failed} fallidos · {review} para revisión.",
        )


@admin.action(description="Reconciliar con Mercado Pago")
def reconcile_with_mercadopago(modeladmin, request, queryset):
    _reconcile_selection(request, queryset, release_expired=False)


@admin.action(description="Conciliar y liberar reservas vencidas")
def reconcile_expired_reservations(modeladmin, request, queryset):
    _reconcile_selection(
        request, queryset.filter(order__isnull=True, stock_released_at__isnull=True),
        release_expired=True,
    )


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
    @admin.display(description="Ahorro adicional de envío")
    def shipping_promotion_savings(self, obj):
        return obj.shipping_promotion_savings

    list_display = (
        "token",
        "email",
        "total_amount",
        "gift_label",
        "coupon_code",
        "state",
        "mp_status",
        "reservation_expires_at",
        "stock_released_at",
        "created_at",
    )
    list_filter = (
        "state",
        "mp_status",
        "mp_live_mode",
        "created_at",
        "shipping_promotion",
    )
    search_fields = ("token", "email", "mp_preference_id", "mp_payment_id")
    readonly_fields = (
        "gift_label",
        "coupon",
        "coupon_code",
        "coupon_discount_percent",
        "coupon_discount_amount",
        "gift_applied_at",
        "shipping_promotion",
        "shipping_promotion_label",
        "shipping_promotion_applied_at",
        "shipping_cost_before_promotion",
        "shipping_promotion_savings",
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
    actions = [reconcile_with_mercadopago, reconcile_expired_reservations]
