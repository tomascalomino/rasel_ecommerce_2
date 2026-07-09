from django.conf import settings
from django.contrib import admin
from .models import PaymentEvent, PaymentDraft


class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "topic", "event_id", "processed_ok", "created_at", "notes")
    list_filter = ("processed_ok", "topic", "provider")
    search_fields = ("event_id", "notes", "resource")
    readonly_fields = ("provider", "topic", "event_id", "resource", "raw", "created_at")
    ordering = ("-created_at",)


class PaymentDraftAdmin(admin.ModelAdmin):
    list_display = ("token", "email", "total_amount", "mp_status", "created_at", "consumed_at")
    list_filter = ("mp_status", "created_at", "consumed_at")
    search_fields = ("token", "email", "mp_preference_id", "mp_payment_id")
    readonly_fields = ("token", "items", "created_at", "consumed_at")
    ordering = ("-created_at",)


# Logs técnicos de MercadoPago: solo aparecen en el menú si MP está activo.
if settings.MP_ENABLED:
    admin.site.register(PaymentEvent, PaymentEventAdmin)
    admin.site.register(PaymentDraft, PaymentDraftAdmin)
