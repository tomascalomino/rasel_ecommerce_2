from django.db import models
from django.utils import timezone


class Order(models.Model):
    # Los valores guardados no cambian (pending/paid/...), solo las etiquetas.
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("paid", "Pagada"),
        ("shipped", "Enviada"),
        ("cancelled", "Cancelada"),
    ]

    PAYMENT_CHOICES = [
        ("transfer", "Transferencia"),
        ("cod", "Efectivo (contraentrega)"),
        ("mp", "MercadoPago"),
    ]

    DELIVERY_CHOICES = [
        ("ship", "Envío a domicilio"),
        ("pickup", "Retiro en punto de retiro"),
    ]

    created_at = models.DateTimeField("fecha", default=timezone.now)
    status = models.CharField(
        "estado", max_length=20, choices=STATUS_CHOICES, default="pending"
    )
    payment_method = models.CharField(
        "método de pago", max_length=20, choices=PAYMENT_CHOICES, default="mp"
    )

    # Datos cliente (MVP sin login)
    full_name = models.CharField("nombre y apellido", max_length=120)
    email = models.EmailField("email")
    phone = models.CharField("teléfono", max_length=30, blank=True)

    # Con retiro en punto la dirección queda vacía.
    address_line = models.CharField("dirección", max_length=200, blank=True, default="")
    address_extra = models.CharField(
        "piso / depto / info adicional", max_length=200, blank=True, default=""
    )
    city = models.CharField("ciudad", max_length=100, blank=True, default="")
    postal_code = models.CharField("código postal", max_length=20, blank=True, default="")

    # Modalidad de entrega. Con "pickup" el envío es sin cargo y el cliente
    # retira en el punto elegido; pickup_point_label es el snapshot histórico
    # (los emails/páginas usan siempre el label, nunca el FK).
    delivery_method = models.CharField(
        "entrega", max_length=10, choices=DELIVERY_CHOICES, default="ship"
    )
    pickup_point = models.ForeignKey(
        "shipping.PickupPoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="punto de retiro",
    )
    pickup_point_label = models.CharField(
        "punto de retiro (histórico)", max_length=300, blank=True, default=""
    )

    # Envío: costo y nombre de la zona resuelta a partir del CP.
    # total_amount = subtotal (items) + shipping_cost.
    shipping_cost = models.DecimalField(
        "costo de envío", max_digits=12, decimal_places=2, default=0
    )
    shipping_zone = models.CharField("zona de envío", max_length=80, blank=True, default="")
    # Envío a cargo del comprador (resto del país): costo 0 pero NO es gratis,
    # el comprador contrata y paga el correo. Distingue de "envío gratis real".
    shipping_carrier_arranged = models.BooleanField(
        "correo a cargo del comprador", default=False
    )

    total_amount = models.DecimalField("total", max_digits=12, decimal_places=2)

    # MercadoPago tracking (MVP)
    mp_preference_id = models.CharField(max_length=120, blank=True, default="")
    mp_payment_id = models.CharField(max_length=120, blank=True, default="")
    mp_status = models.CharField(max_length=60, blank=True, default="")

    # Email de confirmación (idempotencia: evita reenvíos en reintentos de webhook)
    confirmation_email_sent = models.BooleanField(default=False)
    # Email de "pago confirmado" (se envía al marcar la orden como pagada en el admin)
    paid_email_sent = models.BooleanField(default=False)
    # Email de "pedido enviado / listo para retirar" (al marcar la orden como enviada)
    shipped_email_sent = models.BooleanField(default=False)
    # Idempotencia de reposición de stock al cancelar (evita devolver stock dos veces)
    stock_restored = models.BooleanField("stock repuesto", default=False)

    class Meta:
        verbose_name = "orden"
        verbose_name_plural = "órdenes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Orden #{self.id} - {self.full_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "shop.Variant",
        on_delete=models.SET_NULL,
        related_name="order_items",
        null=True,
        blank=True,
    )

    product_name = models.CharField("producto", max_length=150)
    variant_name = models.CharField("variante", max_length=80)

    unit_price = models.DecimalField("precio unitario", max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField("cantidad")
    line_total = models.DecimalField("subtotal", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "ítem"
        verbose_name_plural = "ítems"

    def __str__(self):
        return f"{self.product_name} ({self.variant_name})"
