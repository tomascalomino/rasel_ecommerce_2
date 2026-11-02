"""Fixture de revisión únicamente en el servicio de staging conocido."""

from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.utils import timezone


def seed_demo(apps, schema_editor):
    if settings.SITE_URL != "https://rasel-mp-staging.onrender.com":
        return
    alias = schema_editor.connection.alias
    product_model = apps.get_model("shop", "Product")
    variant_model = apps.get_model("shop", "Variant")
    coupon_model = apps.get_model("shop", "Coupon")
    product, _ = product_model.objects.using(alias).get_or_create(
        slug="caja-prueba-cupon-staging",
        defaults={
            "name": "Caja ficticia para probar cupones",
            "short_description": "Solo staging. No es un producto real.",
        },
    )
    variant, _ = variant_model.objects.using(alias).get_or_create(
        sku="STAGING-COUPON-BOX6",
        defaults={
            "product_id": product.pk,
            "name": "Caja de prueba x6",
            "pack_units": 6,
            "price_ars": 100000,
            "stock_qty": 20,
        },
    )
    now = timezone.now()
    coupon, created = coupon_model.objects.using(alias).get_or_create(
        code="pruebacajas20",
        defaults={
            "discount_percent": 20,
            "max_uses": 5,
            "enabled": True,
            "combine_payment_discount": True,
            "starts_at": now,
            "ends_at": now + timedelta(days=7),
        },
    )
    if created:
        coupon.variants.add(variant)


class Migration(migrations.Migration):
    dependencies = [("shop", "0011_coupon_couponredemption_and_more")]
    operations = [migrations.RunPython(seed_demo, migrations.RunPython.noop)]
