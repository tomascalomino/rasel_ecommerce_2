from django.contrib import admin
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("variant", "product_name", "variant_name", "unit_price", "quantity", "line_total")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "status",
        "total_amount",
        "mp_status",
        "mp_payment_id",
        "created_at",
    )
    list_filter = ("status", "created_at", "mp_status")
    search_fields = ("full_name", "email", "mp_preference_id", "mp_payment_id")
    inlines = [OrderItemInline]
