from django.contrib import admin, messages
from django.db import transaction
from django.db.models import F
from django.utils.html import format_html

from shop.models import Variant
from .models import Order, OrderItem
from .emails import send_payment_confirmed


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("variant", "product_name", "variant_name", "unit_price", "quantity", "line_total")


@admin.action(description="Marcar como pagada y avisar al cliente", permissions=["change"])
def mark_paid(modeladmin, request, queryset):
    count = 0
    for order in queryset:
        if order.status != "paid":
            order.status = "paid"
            order.save(update_fields=["status"])
        send_payment_confirmed(order.id)
        count += 1
    messages.success(request, f"{count} orden(es) marcadas como pagadas y notificadas al cliente.")


@admin.action(description="Cancelar y devolver stock", permissions=["change"])
def cancel_and_restore_stock(modeladmin, request, queryset):
    restored = 0
    for order in queryset:
        with transaction.atomic():
            o = Order.objects.select_for_update().get(id=order.id)
            if not o.stock_restored:
                for item in o.items.all():
                    if item.variant_id:
                        Variant.objects.filter(id=item.variant_id).update(
                            stock_qty=F("stock_qty") + item.quantity
                        )
                o.stock_restored = True
            o.status = "cancelled"
            o.save(update_fields=["status", "stock_restored"])
            restored += 1
    messages.success(request, f"{restored} orden(es) canceladas y stock repuesto.")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "full_name",
        "email",
        "status_badge",
        "payment_method",
        "delivery_method",
        "total_amount",
    )
    list_filter = ("status", "payment_method", "delivery_method", "created_at")
    date_hierarchy = "created_at"
    search_fields = (
        "full_name", "email", "mp_preference_id", "mp_payment_id",
        "pickup_point_label",
    )
    inlines = [OrderItemInline]
    actions = [mark_paid, cancel_and_restore_stock]

    @admin.display(description="Estado", ordering="status")
    def status_badge(self, obj):
        return format_html(
            '<span class="rasel-status rasel-status-{}">{}</span>',
            obj.status,
            obj.get_status_display(),
        )
