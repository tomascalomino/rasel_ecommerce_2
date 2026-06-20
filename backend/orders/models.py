from django.db import models
from django.utils import timezone


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("shipped", "Shipped"),
        ("cancelled", "Cancelled"),
    ]

    created_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    payment_method = models.CharField(max_length=20, default="mp")

    # Datos cliente (MVP sin login)
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)

    address_line = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    # MercadoPago tracking (MVP)
    mp_preference_id = models.CharField(max_length=120, blank=True, default="")
    mp_payment_id = models.CharField(max_length=120, blank=True, default="")
    mp_status = models.CharField(max_length=60, blank=True, default="")

    # Email de confirmación (idempotencia: evita reenvíos en reintentos de webhook)
    confirmation_email_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"Order #{self.id} - {self.full_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "shop.Variant",
        on_delete=models.SET_NULL,
        related_name="order_items",
        null=True,
        blank=True,
    )

    product_name = models.CharField(max_length=150)
    variant_name = models.CharField(max_length=80)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} ({self.variant_name})"
