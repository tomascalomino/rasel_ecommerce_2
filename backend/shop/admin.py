from django.contrib import admin
from .models import Category, CommercialSettings, Product, Variant


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
    fields = ("offline_payment_discount_percent",)
    list_display = ("offline_payment_discount_percent",)

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
