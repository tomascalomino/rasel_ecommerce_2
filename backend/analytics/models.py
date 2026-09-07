import uuid

from django.db import models
from django.utils import timezone


class Measurement(models.Model):
    """Singleton: first successful measurement and bounded maintenance lease."""

    started_at = models.DateTimeField(default=timezone.now)
    cleanup_after = models.DateTimeField(default=timezone.now)

    class Meta:
        default_permissions = ()
        permissions = [
            ("view_reports", "Puede consultar reportes de visitas y compras")
        ]


class Visit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    day = models.DateField()
    cart_added = models.BooleanField(default=False)
    checkout_opened = models.BooleanField(default=False)
    checkout_submitted = models.BooleanField(default=False)

    class Meta:
        default_permissions = ()


class DailyTotal(models.Model):
    day = models.DateField(primary_key=True)
    visits = models.PositiveIntegerField(default=0)
    pageviews = models.PositiveIntegerField(default=0)
    cart_added = models.PositiveIntegerField(default=0)
    checkout_opened = models.PositiveIntegerField(default=0)
    checkout_submitted = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()


class DailySource(models.Model):
    day = models.DateField(db_index=True)
    source = models.CharField(max_length=64)
    medium = models.CharField(max_length=64, blank=True)
    campaign = models.CharField(max_length=64, blank=True)
    visits = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=("day", "source", "medium", "campaign"),
                name="analytics_source_day",
            )
        ]


class DailyDevice(models.Model):
    day = models.DateField(db_index=True)
    device = models.CharField(max_length=12)
    visits = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=("day", "device"), name="analytics_device_day"
            )
        ]


class DailyProduct(models.Model):
    day = models.DateField(db_index=True)
    # Snapshot, deliberately not a FK: deleting a product must retain its totals.
    product_id = models.PositiveBigIntegerField()
    product_name = models.CharField(max_length=200)
    pageviews = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=("day", "product_id"), name="analytics_product_day"
            )
        ]
