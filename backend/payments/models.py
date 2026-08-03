from django.db import models
from django.utils import timezone
import uuid


class PaymentEvent(models.Model):
    provider = models.CharField(max_length=50, default="mercadopago")
    created_at = models.DateTimeField(default=timezone.now)

    # Identificadores típicos
    topic = models.CharField(max_length=50, blank=True, default="")
    event_id = models.CharField(max_length=120, blank=True, default="")
    provider_event_id = models.CharField(max_length=120, blank=True, default="")
    action = models.CharField(max_length=120, blank=True, default="")
    request_id = models.CharField(max_length=120, blank=True, default="")
    resource = models.TextField(blank=True, default="")

    # Payload crudo para auditoría
    raw = models.JSONField(default=dict, blank=True)

    # Resultado del procesamiento
    processed_ok = models.BooleanField(default=False)
    signature_valid = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"],
                condition=~models.Q(provider_event_id=""),
                name="payments_unique_provider_event",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider} {self.topic} {self.created_at:%Y-%m-%d %H:%M:%S}"


class PaymentDraft(models.Model):
    STATE_CHOICES = [
        ("created", "Creado"),
        ("reserved", "Stock reservado"),
        ("preference_created", "Preferencia creada"),
        ("pending", "Pago pendiente"),
        ("approved", "Aprobado"),
        ("rejected", "Rechazado"),
        ("cancelled", "Cancelado"),
        ("expired", "Expirado"),
        ("released", "Stock liberado"),
        ("review", "Revision manual"),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(
        max_length=30, choices=STATE_CHOICES, default="created", db_index=True
    )
    stock_reserved_at = models.DateTimeField(null=True, blank=True)
    reservation_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stock_released_at = models.DateTimeField(null=True, blank=True)

    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    address_line = models.CharField(max_length=200, blank=True, default="")
    address_extra = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    postal_code = models.CharField(max_length=20, blank=True, default="")

    # Modalidad de entrega (se copia al Order al finalizar el pago).
    delivery_method = models.CharField(max_length=10, default="ship")
    pickup_point = models.ForeignKey(
        "shipping.PickupPoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_drafts",
    )
    pickup_point_label = models.CharField(max_length=300, blank=True, default="")

    # Envío: se copia al Order al finalizar el pago. total_amount ya incluye el envío.
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_zone = models.CharField(max_length=80, blank=True, default="")
    shipping_carrier_arranged = models.BooleanField(default=False)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    items = models.JSONField(default=list, blank=True)

    mp_preference_id = models.CharField(max_length=120, blank=True, default="")
    mp_payment_id = models.CharField(max_length=120, blank=True, default="")
    mp_status = models.CharField(max_length=60, blank=True, default="")
    mp_status_detail = models.CharField(max_length=120, blank=True, default="")
    mp_init_point = models.URLField(max_length=500, blank=True, default="")
    mp_collector_id = models.CharField(max_length=120, blank=True, default="")
    mp_live_mode = models.BooleanField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True, default="")

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_draft",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["mp_payment_id"],
                condition=~models.Q(mp_payment_id=""),
                name="payments_unique_draft_mp_payment_id",
            )
        ]

    def __str__(self) -> str:
        return f"Draft {self.token} - {self.email}"
