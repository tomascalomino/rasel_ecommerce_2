from django.db import models
from django.utils import timezone


class PaymentEvent(models.Model):
    provider = models.CharField(max_length=50, default="mercadopago")
    created_at = models.DateTimeField(default=timezone.now)

    # Identificadores típicos
    topic = models.CharField(max_length=50, blank=True, default="")
    event_id = models.CharField(max_length=120, blank=True, default="")
    resource = models.TextField(blank=True, default="")

    # Payload crudo para auditoría
    raw = models.JSONField(default=dict, blank=True)

    # Resultado del procesamiento
    processed_ok = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider} {self.topic} {self.created_at:%Y-%m-%d %H:%M:%S}"
