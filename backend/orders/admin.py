from django.contrib import admin, messages
from django.db import transaction
from django.db.models import F

from shop.models import Variant
from .models import Order, OrderItem
from .emails import send_payment_confirmed


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("variant", "product_name", "variant_name", "unit_price", "quantity", "line_total")


@admin.action(description="Marcar como pagada y avisar al cliente")
def mark_paid(modeladmin, request, queryset):
    count = 0
    for order in queryset:
        if order.status != "paid":
            order.status = "paid"
            order.save(update_fields=["status"])
        send_payment_confirmed(order.id)
        count += 1
    messages.success(request, f"{count} orden(es) marcadas como pagadas y notificadas al cliente.")


@admin.action(description="Cancelar y devolver stock")
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
        "full_name",
        "email",
        "status",
        "payment_method",
        "total_amount",
        "created_at",
    )
    list_filter = ("status", "payment_method", "created_at")
    search_fields = ("full_name", "email", "mp_preference_id", "mp_payment_id")
    inlines = [OrderItemInline]
    actions = [mark_paid, cancel_and_restore_stock]
