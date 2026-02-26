from django.db import models
from django.utils import timezone
import uuid


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


class PaymentDraft(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)

    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    address_line = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    items = models.JSONField(default=list, blank=True)

    mp_preference_id = models.CharField(max_length=120, blank=True, default="")
    mp_payment_id = models.CharField(max_length=120, blank=True, default="")
    mp_status = models.CharField(max_length=60, blank=True, default="")

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_draft",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Draft {self.token} - {self.email}"
