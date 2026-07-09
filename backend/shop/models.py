import re

from django.db import models
from django.utils.text import slugify


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

    price_ars = models.DecimalField("precio (ARS)", max_digits=12, decimal_places=2)
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

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name}"

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
