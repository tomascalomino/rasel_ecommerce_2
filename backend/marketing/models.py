import uuid

from django.db import models
from django.utils import timezone


class Consent(models.Model):
    """First-party choice, never used as a Meta customer identifier."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    accepted = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    def permits(self, revision=None):
        return (
            self.accepted
            and self.expires_at > timezone.now()
            and (revision is None or self.revision == revision)
        )


class MarketingSnapshot(models.Model):
    # NULL on historical/admin-created orders. Only checkout assigns this UUID.
    web_checkout_id = models.UUIDField(
        null=True, blank=True, unique=True, editable=False
    )
    marketing_consent = models.ForeignKey(
        Consent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    marketing_context = models.JSONField(default=dict, blank=True, editable=False)
    marketing_captured_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        abstract = True


class BrowserEventReceipt(models.Model):
    """Claim a confirmed cart action/checkout once across tabs and reloads."""

    id = models.UUIDField(primary_key=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)


class MetaPurchase(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("sending", "En envío"),
        ("sent", "Recibido por Meta"),
        ("failed", "Revisar"),
        ("expired", "Vencido"),
        ("cancelled", "Consentimiento retirado"),
    ]
    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE)
    consent = models.ForeignKey(Consent, null=True, on_delete=models.SET_NULL)
    consent_revision = models.PositiveIntegerField()
    event_id = models.CharField(max_length=80, unique=True)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    # Frozen payload includes hashes, not plaintext customer contact information.
    payload = models.JSONField(default=dict)
    pixel_id = models.CharField(max_length=30)
    graph_version = models.CharField(max_length=15)
    test_event_code = models.CharField(max_length=100, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    claim_id = models.UUIDField(null=True, editable=False)
    claim_expires_at = models.DateTimeField(null=True)
    sent_at = models.DateTimeField(null=True)
    diagnostic = models.CharField(max_length=120, blank=True, default="")
    payload_purged_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["created_at"]
