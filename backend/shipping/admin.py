from django.contrib import admin

from .models import PickupPoint, PostalCodeRule, ShippingPromotion, ShippingZone
from django.db import transaction
from django.utils.html import format_html
from shop.models import CommercialSettings


@admin.register(ShippingPromotion)
class ShippingPromotionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "campaign_state",
        "starts_at",
        "ends_at",
        "enabled",
        "conditions_link",
    )
    list_filter = ("enabled", "starts_at")
    fields = (
        "campaign_state",
        "title",
        "introduction",
        "starts_at",
        "ends_at",
        "enabled",
        "slug",
        "published_at",
        "conditions_link",
    )
    readonly_fields = ("campaign_state", "slug", "published_at", "conditions_link")

    @admin.display(description="Estado")
    def campaign_state(self, obj):
        return obj.state_label

    @admin.display(description="Condiciones")
    def conditions_link(self, obj):
        if obj and obj.published_at:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">Ver condiciones publicadas</a>',
                obj.get_absolute_url(),
            )
        return "Disponibles después de habilitar la campaña."

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj and obj.published_at:
            fields.extend(("title", "introduction", "starts_at", "ends_at"))
        return fields

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            with transaction.atomic():
                CommercialSettings.objects.select_for_update().get(pk=1)
                return super().changeform_view(
                    request, object_id, form_url, extra_context
                )
        return super().changeform_view(request, object_id, form_url, extra_context)


class PostalCodeRuleInline(admin.TabularInline):
    model = PostalCodeRule
    extra = 1


@admin.register(ShippingZone)
class ShippingZoneAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "price",
        "free_over",
        "below_min_price",
        "carrier_arranged",
        "cod_allowed",
        "is_default",
        "is_active",
        "sort_order",
    )
    list_editable = (
        "price",
        "free_over",
        "below_min_price",
        "carrier_arranged",
        "cod_allowed",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active", "is_default")
    search_fields = ("name", "code")
    inlines = [PostalCodeRuleInline]


# PostalCodeRule no tiene sección propia en el menú: se edita inline
# dentro de cada zona de envío (PostalCodeRuleInline).


@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name", "address")
