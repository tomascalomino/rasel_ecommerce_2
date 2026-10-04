from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone


def promotion_start():
    return (timezone.localtime() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def promotion_end():
    return promotion_start() + timedelta(days=7)


class ShippingPromotion(models.Model):
    title = models.CharField(
        "título", max_length=120, default="Una semana de envío gratis en CABA"
    )
    introduction = models.TextField(
        "introducción",
        max_length=1500,
        blank=True,
        default="De nuestro olivar a tu mesa, con envío gratis en CABA.",
    )
    slug = models.SlugField("URL permanente", max_length=160, unique=True, blank=True)
    starts_at = models.DateTimeField("inicio (hora argentina)", default=promotion_start)
    ends_at = models.DateTimeField(
        "fin exclusivo (hora argentina)",
        default=promotion_end,
        help_text="A partir de este instante vuelve la tarifa habitual. Duración sugerida: siete días corridos.",
    )
    enabled = models.BooleanField("habilitada", default=False)
    published_at = models.DateTimeField(
        "publicada el", null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ["-starts_at", "-pk"]
        verbose_name = "promoción de envío"
        verbose_name_plural = "promociones de envío"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="shipping_promotion_valid_dates",
            )
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("shipping_promotion", kwargs={"slug": self.slug})

    def state_at(self, now):
        if not self.published_at:
            return "draft"
        if now >= self.ends_at:
            return "finished"
        if not self.enabled:
            return "suspended"
        return "scheduled" if now < self.starts_at else "active"

    @property
    def state(self):
        return self.state_at(timezone.now())

    @property
    def state_label(self):
        return {
            "draft": "Borrador",
            "scheduled": "Programada",
            "active": "Vigente",
            "suspended": "Suspendida",
            "finished": "Finalizada",
        }[self.state]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "El fin debe ser posterior al inicio."})
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old and old.published_at:
            frozen = ("title", "introduction", "slug", "starts_at", "ends_at")
            if any(getattr(old, field) != getattr(self, field) for field in frozen):
                raise ValidationError(
                    "Las condiciones publicadas son permanentes. Creá una nueva campaña."
                )
            self.published_at = old.published_at
        if self.enabled and self.starts_at and self.ends_at:
            if not self.published_at and self.ends_at <= timezone.now():
                raise ValidationError(
                    {"ends_at": "No se puede publicar una campaña ya finalizada."}
                )
            if (
                type(self)
                .objects.filter(
                    enabled=True, starts_at__lt=self.ends_at, ends_at__gt=self.starts_at
                )
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError(
                    "Ya existe una campaña habilitada en ese período."
                )

    def save(self, *args, **kwargs):
        # A permanent singleton serializes ALL admin activations, including when
        # the campaign table is empty. Row locks work across PostgreSQL workers.
        from shop.models import CommercialSettings

        with transaction.atomic():
            CommercialSettings.objects.select_for_update().get(pk=1)
            if not self.slug:
                self.slug = f"envio-gratis-caba-{uuid4().hex[:12]}"
            self.full_clean()
            if self.enabled and not self.published_at:
                self.published_at = timezone.now()
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                        "published_at"
                    }
            return super().save(*args, **kwargs)


class ShippingPromotionSnapshot(models.Model):
    shipping_promotion = models.ForeignKey(
        ShippingPromotion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
    )
    shipping_promotion_label = models.CharField(
        "promoción de envío (histórico)",
        max_length=120,
        blank=True,
        default="",
        editable=False,
    )
    shipping_promotion_applied_at = models.DateTimeField(
        "beneficio aplicado el", null=True, blank=True, editable=False
    )
    shipping_cost_before_promotion = models.DecimalField(
        "envío habitual (histórico)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        abstract = True

    @property
    def shipping_promotion_savings(self):
        if self.shipping_cost_before_promotion is None:
            return Decimal("0.00")
        return max(
            Decimal("0.00"), self.shipping_cost_before_promotion - self.shipping_cost
        )


class ShippingZone(models.Model):
    """
    Zona de envío con su tarifa. Editable desde el Admin: el negocio puede cambiar
    precios y descripciones sin tocar código ni redeployar.

    - price = 0  -> envío gratis (ej. CABA + Partido de Moreno).
    - is_default -> zona que se aplica cuando ningún PostalCodeRule matchea
                    (ej. "Resto del país"). Debe existir exactamente una activa.
    """

    code = models.SlugField(
        "código",
        max_length=40,
        unique=True,
        help_text="Identificador interno, ej. 'free', 'amba', 'national'.",
    )
    name = models.CharField("nombre", max_length=80, help_text="Ej. 'CABA y Moreno'.")
    price = models.DecimalField(
        "precio",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Costo del envío. 0 = gratis.",
    )
    free_over = models.DecimalField(
        "gratis desde",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Envío gratis a partir de este subtotal de compra. "
            "Vacío = siempre gratis (sin mínimo)."
        ),
    )
    below_min_price = models.DecimalField(
        "precio bajo el mínimo",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Costo de envío cuando el subtotal no alcanza el mínimo "
            "('Gratis desde'). Solo aplica si 'Gratis desde' está seteado."
        ),
    )
    description = models.TextField(
        "descripción",
        blank=True,
        default="",
        help_text="Texto que se muestra en la página de envíos.",
    )
    is_default = models.BooleanField(
        "zona por defecto",
        default=False,
        help_text="Se aplica cuando el CP no cae en ninguna regla (resto del país).",
    )
    carrier_arranged = models.BooleanField(
        "correo a cargo del comprador",
        default=False,
        help_text=(
            "El comprador elige y paga el correo; RaSel no cobra el envío (lo lleva "
            "a la sucursal de CABA). Si está activo, se ignoran 'Precio' y 'Gratis "
            "desde' y se muestra la leyenda de 'Descripción'."
        ),
    )
    cod_allowed = models.BooleanField(
        "acepta efectivo",
        default=False,
        help_text=(
            "Permite pagar en efectivo a contraentrega en esta zona (solo zonas "
            "donde RaSel reparte en persona, ej. CABA/GBA)."
        ),
    )
    is_active = models.BooleanField("activa", default=True)
    sort_order = models.PositiveIntegerField(
        "prioridad",
        default=100,
        help_text="Orden de prioridad. Menor gana ante rangos superpuestos.",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Zona de envío"
        verbose_name_plural = "Zonas de envío"

    def __str__(self) -> str:
        return f"{self.name} (${self.price})"

    @property
    def is_free(self) -> bool:
        return self.price <= Decimal("0.00")


class PickupPoint(models.Model):
    """
    Punto de retiro sin cargo. Editable desde el Admin: el negocio puede
    actualizar dirección y horarios sin redeployar (mismo criterio que
    ShippingZone). Las órdenes guardan un snapshot de texto, así el dato
    histórico no cambia si el punto se edita o desactiva.
    """

    name = models.CharField(
        "nombre", max_length=80, help_text="Ej. 'Punto de retiro CABA'."
    )
    address = models.CharField(
        "dirección", max_length=200, help_text="Dirección completa del punto."
    )
    schedule_notes = models.TextField(
        "horarios e indicaciones",
        blank=True,
        default="",
        help_text="Horarios o indicaciones para el retiro (se muestran en el checkout).",
    )
    is_active = models.BooleanField("activo", default=True)
    sort_order = models.PositiveIntegerField("prioridad", default=100)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Punto de retiro"
        verbose_name_plural = "Puntos de retiro"

    def __str__(self) -> str:
        return f"{self.name} — {self.address}"


class PostalCodeRule(models.Model):
    """
    Asocia un rango de códigos postales (numéricos) a una zona.
    El CP se normaliza a su núcleo de 4 dígitos antes de comparar
    (ver shipping.services.normalize_cp), así "C1425ABC" matchea 1425.
    """

    zone = models.ForeignKey(
        ShippingZone,
        on_delete=models.CASCADE,
        related_name="rules",
        verbose_name="zona",
    )
    cp_from = models.PositiveIntegerField(
        "CP desde", help_text="CP inicial del rango (inclusive)."
    )
    cp_to = models.PositiveIntegerField(
        "CP hasta", help_text="CP final del rango (inclusive)."
    )
    note = models.CharField(
        "referencia",
        max_length=120,
        blank=True,
        default="",
        help_text="Referencia, ej. 'CABA', 'Moreno', 'Conurbano'.",
    )

    class Meta:
        ordering = ["cp_from", "cp_to"]
        verbose_name = "Regla de código postal"
        verbose_name_plural = "Reglas de código postal"

    def __str__(self) -> str:
        label = self.note or self.zone.name
        return f"{self.cp_from}-{self.cp_to} → {label}"
