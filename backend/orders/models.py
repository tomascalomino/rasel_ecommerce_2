from django.db import models
from django.utils import timezone


class Order(models.Model):
    FULFILLMENT_STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("shipped", "Despachada"),
        ("ready_for_pickup", "Lista para retirar"),
        ("completed", "Completada"),
        ("cancelled", "Cancelada"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("approved", "Aprobado"),
        ("rejected", "Rechazado"),
        ("cancelled", "Cancelado"),
        ("partially_refunded", "Reintegro parcial"),
        ("refunded", "Reintegrado"),
        ("charged_back", "Contracargo"),
        ("review", "Revision"),
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
    fulfillment_status = models.CharField(
        "estado de entrega",
        max_length=20,
        choices=FULFILLMENT_STATUS_CHOICES,
        default="pending",
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
    postal_code = models.CharField(
        "código postal", max_length=20, blank=True, default=""
    )

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
    # total_amount = subtotal (items) - payment_discount_amount + shipping_cost.
    shipping_cost = models.DecimalField(
        "costo de envío", max_digits=12, decimal_places=2, default=0
    )
    shipping_zone = models.CharField(
        "zona de envío", max_length=80, blank=True, default=""
    )
    # Envío a cargo del comprador (resto del país): costo 0 pero NO es gratis,
    # el comprador contrata y paga el correo. Distingue de "envío gratis real".
    shipping_carrier_arranged = models.BooleanField(
        "correo a cargo del comprador", default=False
    )

    payment_discount_amount = models.DecimalField(
        "descuento por medio de pago",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    payment_discount_percent = models.PositiveSmallIntegerField(
        "porcentaje de descuento aplicado",
        default=0,
        help_text="Snapshot del porcentaje aplicado al crear la orden.",
    )

    total_amount = models.DecimalField("total", max_digits=12, decimal_places=2)

    @property
    def items_subtotal(self):
        """Subtotal histórico antes del descuento y del envío."""
        return self.total_amount - self.shipping_cost + self.payment_discount_amount

    # MercadoPago tracking (MVP)
    mp_preference_id = models.CharField(max_length=120, blank=True, default="")
    mp_payment_id = models.CharField(max_length=120, blank=True, default="")
    mp_status = models.CharField(max_length=60, blank=True, default="")
    payment_status = models.CharField(
        "estado financiero",
        max_length=30,
        choices=PAYMENT_STATUS_CHOICES,
        default="pending",
    )
    mp_refunded_amount = models.DecimalField(
        "monto reintegrado", max_digits=12, decimal_places=2, default=0
    )
    stock_deducted = models.BooleanField("stock descontado", default=True)

    # Email de confirmación (idempotencia: evita reenvíos en reintentos de webhook)
    confirmation_email_sent = models.BooleanField(default=False)
    # Email de "pago confirmado" (se envía al marcar la orden como pagada en el admin)
    paid_email_sent = models.BooleanField(default=False)
    # Email de "pedido enviado / listo para retirar" (al marcar la orden como enviada)
    shipped_email_sent = models.BooleanField(default=False)
    # Email final de entrega/retiro (independiente de pago y despacho).
    completion_email_sent = models.BooleanField(default=False)
    completed_at = models.DateTimeField(
        "fecha de entrega/retiro", null=True, blank=True
    )
    # Idempotencia de reposición de stock al cancelar (evita devolver stock dos veces)
    stock_restored = models.BooleanField("stock repuesto", default=False)

    class Meta:
        verbose_name = "orden"
        verbose_name_plural = "órdenes"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["mp_payment_id"],
                condition=~models.Q(mp_payment_id=""),
                name="orders_unique_mp_payment_id",
            )
        ]

    def __str__(self):
        return f"Orden #{self.id} - {self.full_name}"

    @property
    def fulfillment_label(self):
        if self.fulfillment_status == "completed":
            return "Retirada" if self.delivery_method == "pickup" else "Entregada"
        return self.get_fulfillment_status_display()

    @property
    def situation_label(self):
        if self.payment_status == "review":
            return "Revisar pago"
        if self.payment_status in {
            "rejected",
            "refunded",
            "partially_refunded",
            "charged_back",
        }:
            return "Revisar postventa"
        if self.fulfillment_status == "cancelled" or self.payment_status == "cancelled":
            return "Cancelada"
        if self.fulfillment_status == "completed":
            return (
                "Completada" if self.payment_status == "approved" else "Cobro pendiente"
            )
        if self.fulfillment_status == "shipped":
            return (
                "En camino"
                if self.payment_status == "approved"
                else "En camino · cobrar"
            )
        if self.fulfillment_status == "ready_for_pickup":
            return (
                "Lista para retirar"
                if self.payment_status == "approved"
                else "Lista · cobrar"
            )
        if self.payment_status == "approved":
            return "Preparar pedido"
        if self.payment_method == "cod" and self.payment_status == "pending":
            return "Preparar contraentrega"
        return "Esperando pago"

    @property
    def situation_tone(self):
        if self.payment_status in {
            "review",
            "rejected",
            "refunded",
            "partially_refunded",
            "charged_back",
        }:
            return "alert"
        if self.fulfillment_status == "cancelled" or self.payment_status == "cancelled":
            return "cancelled"
        if self.fulfillment_status == "completed":
            return "completed"
        if self.fulfillment_status in {"shipped", "ready_for_pickup"}:
            return self.fulfillment_status
        return "pending"


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
