"""Cupones con cupo global por pedido e historial de asignaciones."""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone


class Coupon(models.Model):
    code = models.CharField(
        "código",
        max_length=40,
        validators=[
            RegexValidator(
                r"^[a-zA-Z0-9_-]{3,40}$",
                "Usá entre 3 y 40 letras, números, guiones o guiones bajos.",
            )
        ],
    )
    discount_percent = models.PositiveSmallIntegerField(
        "descuento (%)",
        validators=[MinValueValidator(1), MaxValueValidator(99)],
    )
    max_uses = models.PositiveIntegerField(
        "cantidad total de usos",
        validators=[MinValueValidator(1)],
        help_text="Un uso por pedido, aunque incluya varias cajas.",
    )
    variants = models.ManyToManyField(
        "shop.Variant",
        verbose_name="presentaciones que reciben el descuento",
        related_name="coupons",
    )
    enabled = models.BooleanField("habilitado", default=False)
    starts_at = models.DateTimeField("inicio (hora argentina)", default=timezone.now)
    ends_at = models.DateTimeField(
        "fin (exclusivo, hora argentina)", null=True, blank=True
    )
    combine_payment_discount = models.BooleanField(
        "acumular con efectivo/transferencia",
        default=False,
        help_text="Si está apagado, cada presentación recibe el descuento más conveniente.",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "shop"
        verbose_name = "cupón de descuento"
        verbose_name_plural = "cupones de descuento"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(Lower("code"), name="shop_coupon_code_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(discount_percent__gte=1, discount_percent__lte=99),
                name="shop_coupon_percent_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_uses__gte=1), name="shop_coupon_positive_limit"
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__isnull=True)
                | models.Q(ends_at__gt=models.F("starts_at")),
                name="shop_coupon_valid_dates",
            ),
        ]

    def __str__(self):
        return self.code

    @property
    def allocated_uses(self):
        return (
            self.redemptions.filter(state__in=("reserved", "used")).count()
            if self.pk
            else 0
        )

    @property
    def remaining_uses(self):
        return max(0, self.max_uses - self.allocated_uses)

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().lower()
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "El fin debe ser posterior al inicio."})
        if self.pk and self.max_uses < self.allocated_uses:
            raise ValidationError(
                {
                    "max_uses": "El cupo no puede ser menor a los usos consumidos o reservados."
                }
            )

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().lower()
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().get(pk=self.pk)
                self.clean()
            return super().save(*args, **kwargs)


class CouponSnapshot(models.Model):
    coupon = models.ForeignKey(
        "shop.Coupon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    coupon_code = models.CharField(
        "cupón aplicado", max_length=40, blank=True, default="", editable=False
    )
    coupon_discount_percent = models.PositiveSmallIntegerField(
        "porcentaje del cupón", default=0, editable=False
    )
    coupon_discount_amount = models.DecimalField(
        "descuento por cupón",
        max_digits=12,
        decimal_places=2,
        default=0,
        editable=False,
    )

    class Meta:
        abstract = True


class CouponRedemption(models.Model):
    STATE_CHOICES = [
        ("reserved", "Reservado para pago"),
        ("used", "Consumido"),
        ("released", "Devuelto al cupo"),
        ("review", "Pago tardío sin cupo: revisar"),
    ]
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.PROTECT,
        related_name="redemptions",
        verbose_name="cupón",
    )
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coupon_redemption",
        verbose_name="pedido",
    )
    draft = models.OneToOneField(
        "payments.PaymentDraft",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coupon_redemption",
        verbose_name="borrador Mercado Pago",
    )
    state = models.CharField("estado", max_length=12, choices=STATE_CHOICES)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "shop"
        verbose_name = "uso de cupón"
        verbose_name_plural = "usos de cupones"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(order__isnull=False) | models.Q(draft__isnull=False),
                name="shop_coupon_use_has_checkout",
            )
        ]

    def __str__(self):
        return f"{self.coupon.code} · {self.get_state_display()}"
