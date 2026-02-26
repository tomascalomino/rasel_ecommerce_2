from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products", null=True, blank=True
    )

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)

    short_description = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    image = models.ImageField(upload_to="products/", blank=True, null=True)

    class Meta:
        ordering = ["name"]

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
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")

    name = models.CharField(max_length=80)  # ej: "250 ml"
    sku = models.CharField(max_length=64, unique=True)

    price_ars = models.DecimalField(max_digits=12, decimal_places=2)
    stock_qty = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("product", "name")]
        ordering = ["product__name", "name"]

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name}"
