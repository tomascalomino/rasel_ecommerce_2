from django.contrib import admin, messages
from django.db import transaction
from django.db.models import F
from django.utils.html import format_html

from shop.models import Variant

from .emails import send_order_shipped, send_payment_confirmed
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "variant",
        "product_name",
        "variant_name",
        "unit_price",
        "quantity",
        "line_total",
    )


@admin.action(description="Marcar como pagada y avisar al cliente", permissions=["change"])
def mark_paid(modeladmin, request, queryset):
    count = 0
    skipped = 0
    for order in queryset:
        if order.payment_method == "mp":
            skipped += 1
            continue
        order.status = "paid"
        order.payment_status = "approved"
        order.save(update_fields=["status", "payment_status"])
        send_payment_confirmed(order.id)
        count += 1
    if count:
        messages.success(request, f"{count} orden(es) marcadas como pagadas.")
    if skipped:
        messages.error(
            request,
            f"{skipped} orden(es) de Mercado Pago no se modificaron: deben conciliarse con la API.",
        )


@admin.action(description="Marcar como enviada y avisar al cliente", permissions=["change"])
def mark_shipped(modeladmin, request, queryset):
    count = 0
    skipped = 0
    for order in queryset:
        if order.status == "payment_review" or (
            order.payment_method == "mp" and order.payment_status != "approved"
        ):
            skipped += 1
            continue
        order.status = "shipped"
        order.save(update_fields=["status"])
        send_order_shipped(order.id)
        count += 1
    if count:
        messages.success(request, f"{count} orden(es) marcadas como enviadas.")
    if skipped:
        messages.error(request, f"{skipped} orden(es) no se enviaron por su estado financiero.")


@admin.action(description="Cancelar y devolver stock", permissions=["change"])
def cancel_and_restore_stock(modeladmin, request, queryset):
    restored = 0
    skipped = 0
    for order in queryset:
        with transaction.atomic():
            current = Order.objects.select_for_update().get(id=order.id)
            if current.payment_method == "mp" and (
                current.payment_status in {"approved", "partially_refunded", "review"}
                or current.status == "shipped"
            ):
                skipped += 1
                continue
            if current.stock_deducted and not current.stock_restored:
                for item in current.items.all():
                    if item.variant_id:
                        Variant.objects.filter(id=item.variant_id).update(
                            stock_qty=F("stock_qty") + item.quantity
                        )
                current.stock_restored = True
            current.status = "cancelled"
            if current.payment_method != "mp":
                current.payment_status = "cancelled"
            current.save(update_fields=["status", "payment_status", "stock_restored"])
            restored += 1
    if restored:
        messages.success(request, f"{restored} orden(es) canceladas.")
    if skipped:
        messages.error(
            request,
            f"{skipped} orden(es) MP no se cancelaron: reintegra primero en Mercado Pago. "
            "Si ya se envio, confirma la devolucion fisica antes de reponer stock.",
        )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "full_name",
        "status_badge",
        "payment_badge",
        "payment_method",
        "delivery_method",
        "payment_discount_amount",
        "total_amount",
        "mp_refunded_amount",
    )
    list_filter = (
        "status",
        "payment_status",
        "payment_method",
        "delivery_method",
        "created_at",
    )
    date_hierarchy = "created_at"
    search_fields = (
        "full_name",
        "email",
        "mp_preference_id",
        "mp_payment_id",
        "pickup_point_label",
    )
    readonly_fields = (
        "payment_status",
        "payment_discount_amount",
        "mp_refunded_amount",
        "mp_preference_id",
        "mp_payment_id",
        "mp_status",
        "stock_deducted",
        "stock_restored",
    )
    inlines = [OrderItemInline]
    actions = [mark_paid, mark_shipped, cancel_and_restore_stock]

    def save_model(self, request, obj, form, change):
        old = Order.objects.filter(pk=obj.pk).first() if change else None
        if old and old.payment_method == "mp":
            if obj.status == "paid" and old.payment_status != "approved":
                messages.error(request, "Una orden MP solo se paga mediante conciliacion con la API.")
                obj.status = old.status
            if obj.status == "cancelled" and old.payment_status in {
                "approved",
                "partially_refunded",
                "review",
            }:
                messages.error(
                    request,
                    "Cancelar la orden no reintegra el dinero. Realiza el reintegro en Mercado Pago.",
                )
                obj.status = old.status
        super().save_model(request, obj, form, change)
        if old and old.status != obj.status:
            if obj.status == "paid" and obj.payment_method != "mp":
                Order.objects.filter(pk=obj.pk).update(payment_status="approved")
                send_payment_confirmed(obj.id)
            elif obj.status == "shipped":
                send_order_shipped(obj.id)

    @admin.display(description="Estado", ordering="status")
    def status_badge(self, obj):
        return format_html(
            '<span class="rasel-status rasel-status-{}">{}</span>',
            obj.status,
            obj.get_status_display(),
        )

    @admin.display(description="Pago", ordering="payment_status")
    def payment_badge(self, obj):
        label = obj.get_payment_status_display()
        if obj.payment_status == "review" and not obj.stock_deducted:
            label = "REINTEGRO REQUERIDO"
        elif obj.payment_status == "review":
            label = "REVISION DE PAGO"
        elif obj.payment_status == "refunded":
            label = "REINTEGRADO"
        elif obj.payment_status == "partially_refunded":
            label = "REINTEGRO PARCIAL"
        return format_html(
            '<span class="rasel-status rasel-status-{}">{}</span>',
            obj.payment_status,
            label,
        )
