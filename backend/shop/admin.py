from django.contrib import admin
from django.db import transaction
from .models import (
    Category,
    CommercialSettings,
    Coupon,
    CouponRedemption,
    Product,
    Variant,
)


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    fields = (
        "code",
        "discount_percent",
        "max_uses",
        "variants",
        "enabled",
        "starts_at",
        "ends_at",
        "combine_payment_discount",
        "reserved_uses",
        "used_uses",
        "remaining_uses",
    )
    list_display = (
        "code",
        "discount_percent",
        "enabled",
        "max_uses",
        "reserved_uses",
        "used_uses",
        "remaining_uses",
        "ends_at",
    )
    readonly_fields = ("reserved_uses", "used_uses", "remaining_uses")
    list_filter = ("enabled", "combine_payment_discount")
    search_fields = ("code",)
    filter_horizontal = ("variants",)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        with transaction.atomic():
            if request.method == "POST" and object_id and object_id.isdigit():
                Coupon.objects.select_for_update().filter(pk=object_id).first()
            return super().changeform_view(request, object_id, form_url, extra_context)

    @admin.display(description="Disponibles")
    def remaining_uses(self, obj):
        return obj.remaining_uses if obj and obj.pk else 0

    @admin.display(description="Reservados para pago")
    def reserved_uses(self, obj):
        return obj.redemptions.filter(state="reserved").count() if obj and obj.pk else 0

    @admin.display(description="Consumidos")
    def used_uses(self, obj):
        return obj.redemptions.filter(state="used").count() if obj and obj.pk else 0

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("coupon", "state", "order", "draft", "created_at", "updated_at")
    list_filter = ("state", "coupon")
    search_fields = ("coupon__code",)
    readonly_fields = ("coupon", "state", "order", "draft", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class VariantInline(admin.TabularInline):
    model = Variant
    fk_name = "product"
    fields = (
        "name",
        "sku",
        "price_ars",
        "compare_at_price_ars",
        "promotion_label",
        "stock_qty",
        "is_active",
        "pack_units",
        "unit_variant",
    )
    extra = 1


@admin.register(CommercialSettings)
class CommercialSettingsAdmin(admin.ModelAdmin):
    fields = (
        "offline_payment_discount_percent",
        "cyber_gift_enabled",
        "cyber_gift_started_at",
    )
    readonly_fields = ("cyber_gift_started_at",)
    list_display = (
        "offline_payment_discount_percent",
        "cyber_gift_enabled",
        "cyber_gift_started_at",
    )

    def has_add_permission(self, request):
        return not CommercialSettings.objects.exists() and super().has_add_permission(
            request
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name", "short_description", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [VariantInline]


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    """Sección "Stock y precios": reposición rápida editando en la lista."""

    list_display = (
        "product",
        "name",
        "sku",
        "price_ars",
        "compare_at_price_ars",
        "promotion_label",
        "stock_qty",
        "is_active",
    )
    list_editable = (
        "price_ars",
        "compare_at_price_ars",
        "promotion_label",
        "stock_qty",
        "is_active",
    )
    list_filter = ("is_active", "product")
    search_fields = ("sku", "product__name", "name")
