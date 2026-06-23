from django.contrib import admin

from .models import PostalCodeRule, ShippingZone


class PostalCodeRuleInline(admin.TabularInline):
    model = PostalCodeRule
    extra = 1


@admin.register(ShippingZone)
class ShippingZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price", "is_default", "is_active", "sort_order")
    list_editable = ("price", "is_active", "sort_order")
    list_filter = ("is_active", "is_default")
    search_fields = ("name", "code")
    inlines = [PostalCodeRuleInline]


@admin.register(PostalCodeRule)
class PostalCodeRuleAdmin(admin.ModelAdmin):
    list_display = ("cp_from", "cp_to", "zone", "note")
    list_filter = ("zone",)
    search_fields = ("note",)
