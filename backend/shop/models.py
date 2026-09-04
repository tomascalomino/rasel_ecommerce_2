import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from config.pricing import price_discount_label, price_discount_percent


class Category(models.Model):
    name = models.CharField("nombre", max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class CommercialSettings(models.Model):
    """Configuración comercial global administrable por el equipo de RaSel."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    offline_payment_discount_percent = models.PositiveSmallIntegerField(
        "descuento por efectivo/transferencia (%)",
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text=(
            "Porcentaje aplicado a los productos al pagar por transferencia "
            "o efectivo. Usá 0 para desactivar el descuento y ocultar sus leyendas."
        ),
    )

    class Meta:
        verbose_name = "configuración comercial"
        verbose_name_plural = "configuración comercial"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="shop_commercial_settings_singleton",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(offline_payment_discount_percent__gte=0)
                    & models.Q(offline_payment_discount_percent__lte=50)
                ),
                name="shop_offline_discount_percent_range",
            ),
        ]

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "Descuento por medios de pago"


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
        verbose_name="categoría",
    )

    name = models.CharField("nombre", max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)

    short_description = models.CharField("descripción corta", max_length=240, blank=True)
    description = models.TextField("descripción", blank=True)

    is_active = models.BooleanField("activo", default=True)
    image = models.ImageField("imagen", upload_to="products/", blank=True, null=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["-name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Variant(models.Model):
    """
    Variante de compra (ej: 250ml, 500ml, pack x2).
    El stock y precio viven acá (MVP).
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants", verbose_name="producto"
    )

    name = models.CharField("nombre", max_length=80)  # ej: "250 ml"
    sku = models.CharField("SKU", max_length=64, unique=True)

    price_ars = models.DecimalField(
        "precio de venta (ARS)", max_digits=12, decimal_places=2
    )
    compare_at_price_ars = models.DecimalField(
        "precio regular (ARS)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Precio de referencia verdadero de la presentación. Se muestra "
            "tachado, debe ser mayor al precio de venta y se carga junto con "
            "el texto de promoción."
        ),
    )
    promotion_label = models.CharField(
        "texto de promoción",
        max_length=40,
        blank=True,
        default="",
        help_text=(
            "Texto visible en la burbuja, por ejemplo: Precio de lanzamiento "
            "o Black Friday. Se carga junto con el precio regular."
        ),
    )
    stock_qty = models.PositiveIntegerField("stock", default=0)
    is_active = models.BooleanField("activa", default=True)

    pack_units = models.PositiveIntegerField(
        "unidades por caja", default=1, help_text="Unidades por caja (1 = no es pack)"
    )
    unit_variant = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="packs",
        verbose_name="variante unitaria",
        help_text="Variante unitaria equivalente, para calcular el ahorro del pack",
    )

    class Meta:
        verbose_name = "variante"
        verbose_name_plural = "stock y precios"
        unique_together = [("product", "name")]
        ordering = ["product__name", "price_ars"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(compare_at_price_ars__isnull=True)
                    | models.Q(compare_at_price_ars__gt=models.F("price_ars"))
                ),
                name="shop_variant_compare_at_gt_price",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(compare_at_price_ars__isnull=True, promotion_label="")
                    | (
                        models.Q(compare_at_price_ars__isnull=False)
                        & ~models.Q(promotion_label="")
                    )
                ),
                name="shop_variant_promotion_fields_together",
            ),
        ]

    def clean(self):
        super().clean()
        self.promotion_label = (self.promotion_label or "").strip()
        has_regular_price = self.compare_at_price_ars is not None
        has_promotion_label = bool(self.promotion_label)

        if has_regular_price and not has_promotion_label:
            raise ValidationError(
                {
                    "promotion_label": (
                        "Ingresá el texto de promoción junto con el precio regular."
                    )
                }
            )
        if has_promotion_label and not has_regular_price:
            raise ValidationError(
                {
                    "compare_at_price_ars": (
                        "Ingresá el precio regular junto con el texto de promoción."
                    )
                }
            )
        if (
            has_regular_price
            and self.price_ars is not None
            and self.compare_at_price_ars <= self.price_ars
        ):
            raise ValidationError(
                {
                    "compare_at_price_ars": (
                        "El precio regular debe ser mayor al precio de venta."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name}"

    @property
    def promotion_discount_percent(self):
        """Porcentaje entero entre el precio regular y el precio de venta."""
        return price_discount_percent(self.compare_at_price_ars, self.price_ars)

    @property
    def promotion_discount_label(self):
        """Texto breve para la insignia comercial derivada de los precios."""
        return price_discount_label(self.compare_at_price_ars, self.price_ars)

    @property
    def pack_savings_ars(self):
        """Ahorro vs. comprar las unidades sueltas (None si no aplica)."""
        if not self.unit_variant_id or self.pack_units <= 1:
            return None
        savings = self.unit_variant.price_ars * self.pack_units - self.price_ars
        return savings if savings > 0 else None

    @property
    def unit_size_label(self):
        """Tamaño de la unidad, ej: '250ml' (extraído del nombre de la variante unitaria)."""
        if not self.unit_variant_id:
            return ""
        name = self.unit_variant.name
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|cc|l)\b", name, re.IGNORECASE)
        if match:
            return f"{match.group(1)}{match.group(2).lower()}"
        return name
