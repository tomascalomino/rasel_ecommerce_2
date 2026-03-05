from django.contrib import admin
from .models import PaymentEvent


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "topic", "event_id", "processed_ok", "created_at", "notes")
    list_filter = ("processed_ok", "topic", "provider")
    search_fields = ("event_id", "notes", "resource")
    readonly_fields = ("provider", "topic", "event_id", "resource", "raw", "created_at")
    ordering = ("-created_at",)
