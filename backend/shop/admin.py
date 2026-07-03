from django.contrib import admin
from .models import Category, Product, Variant


class VariantInline(admin.TabularInline):
    model = Variant
    fk_name = "product"
    extra = 1


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
    list_display = ("product", "name", "sku", "price_ars", "stock_qty", "pack_units", "unit_variant", "is_active")
    list_filter = ("is_active", "product")
    search_fields = ("sku", "product__name", "name")
