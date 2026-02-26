from django.contrib import admin
from .models import PaymentEvent, PaymentDraft


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "topic", "event_id", "processed_ok", "created_at", "notes")
    list_filter = ("processed_ok", "topic", "provider")
    search_fields = ("event_id", "notes", "resource")
    readonly_fields = ("provider", "topic", "event_id", "resource", "raw", "created_at")
    ordering = ("-created_at",)


@admin.register(PaymentDraft)
class PaymentDraftAdmin(admin.ModelAdmin):
    list_display = ("token", "email", "total_amount", "mp_status", "created_at", "consumed_at")
    list_filter = ("mp_status", "created_at", "consumed_at")
    search_fields = ("token", "email", "mp_preference_id", "mp_payment_id")
    readonly_fields = ("token", "items", "created_at", "consumed_at")
    ordering = ("-created_at",)
