from decimal import Decimal

from django.db import models


class ShippingZone(models.Model):
    """
    Zona de envío con su tarifa. Editable desde el Admin: el negocio puede cambiar
    precios y descripciones sin tocar código ni redeployar.

    - price = 0  -> envío gratis (ej. CABA + Partido de Moreno).
    - is_default -> zona que se aplica cuando ningún PostalCodeRule matchea
                    (ej. "Resto del país"). Debe existir exactamente una activa.
    """

    code = models.SlugField(
        max_length=40,
        unique=True,
        help_text="Identificador interno, ej. 'free', 'amba', 'national'.",
    )
    name = models.CharField(max_length=80, help_text="Ej. 'CABA y Moreno'.")
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Costo del envío. 0 = gratis.",
    )
    free_over = models.DecimalField(
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
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Costo de envío cuando el subtotal no alcanza el mínimo "
            "('Free over'). Solo aplica si 'Free over' está seteado."
        ),
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Texto que se muestra en la página de envíos.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Se aplica cuando el CP no cae en ninguna regla (resto del país).",
    )
    carrier_arranged = models.BooleanField(
        default=False,
        help_text=(
            "El comprador elige y paga el correo; RaSel no cobra el envío (lo lleva "
            "a la sucursal de CABA). Si está activo, se ignoran 'Price' y 'Free over' "
            "y se muestra la leyenda de 'Description'."
        ),
    )
    cod_allowed = models.BooleanField(
        default=False,
        help_text=(
            "Permite pagar en efectivo a contraentrega en esta zona (solo zonas "
            "donde RaSel reparte en persona, ej. CABA/AMBA)."
        ),
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(
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

    name = models.CharField(max_length=80, help_text="Ej. 'Punto de retiro CABA'.")
    address = models.CharField(max_length=200, help_text="Dirección completa del punto.")
    schedule_notes = models.TextField(
        blank=True,
        default="",
        help_text="Horarios o indicaciones para el retiro (se muestran en el checkout).",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)

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
        ShippingZone, on_delete=models.CASCADE, related_name="rules"
    )
    cp_from = models.PositiveIntegerField(help_text="CP inicial del rango (inclusive).")
    cp_to = models.PositiveIntegerField(help_text="CP final del rango (inclusive).")
    note = models.CharField(
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
