"""Condiciones confirmadas: staging ficticio y borrador productivo separado."""

from django.conf import settings
from django.db import migrations
from django.utils import timezone


CODE = "cybercajarasel11"
STAGING = "https://rasel-mp-staging.onrender.com"
PRODUCTION = {"https://rasel.ar", "https://www.rasel.ar"}
BOXES = (("pack-6x500ml-blend", 6), ("pack-9x250ml-blend", 9))


def prepare_coupon(apps, schema_editor):
    site = settings.SITE_URL
    if site not in PRODUCTION and site != STAGING:
        return
    alias = schema_editor.connection.alias
    Coupon = apps.get_model("shop", "Coupon")
    # Nunca reactivar, reponer cupo ni reemplazar condiciones ya administradas.
    if Coupon.objects.using(alias).filter(code__iexact=CODE).exists():
        return
    Product = apps.get_model("shop", "Product")
    Variant = apps.get_model("shop", "Variant")
    variants = []
    if site == STAGING:
        product, _ = Product.objects.using(alias).get_or_create(
            slug="cajas-cyber-staging",
            defaults={
                "name": "Cajas Cyber ficticias para pruebas",
                "short_description": "Solo staging. No son productos reales.",
            },
        )
        for units, size, price in ((6, 500, 83340), (9, 250, 67780)):
            variant, _ = Variant.objects.using(alias).get_or_create(
                sku=f"STAGING-CYBER-{units}X{size}",
                defaults={
                    "product_id": product.pk,
                    "name": f"Caja ficticia {units} x {size} ml",
                    "pack_units": units,
                    "price_ars": price,
                    "stock_qty": 100,
                },
            )
            variants.append(variant)
    else:
        # Los slugs corresponden a las dos fichas públicas verificadas.
        # Un catálogo distinto requiere seleccionar ambas cajas en el admin.
        for slug, units in BOXES:
            matches = list(
                Variant.objects.using(alias).filter(
                    product__slug=slug, pack_units=units
                )[:2]
            )
            if len(matches) != 1:
                variants = []
                break
            variants.append(matches[0])
    coupon = Coupon.objects.using(alias).create(
        code=CODE,
        discount_percent=5,
        max_uses=50,
        combine_payment_discount=True,
        starts_at=timezone.now(),
        ends_at=None,
        enabled=(site == STAGING),
    )
    coupon.variants.add(*variants)


class Migration(migrations.Migration):
    dependencies = [("shop", "0012_seed_staging_coupon_demo")]
    operations = [migrations.RunPython(prepare_coupon, migrations.RunPython.noop)]
