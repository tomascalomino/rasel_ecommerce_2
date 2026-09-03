from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


def seed_commercial_settings(apps, schema_editor):
    CommercialSettings = apps.get_model("shop", "CommercialSettings")
    CommercialSettings.objects.update_or_create(
        pk=1,
        defaults={"offline_payment_discount_percent": 10},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0006_variant_compare_at_price_ars"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommercialSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "offline_payment_discount_percent",
                    models.PositiveSmallIntegerField(
                        default=10,
                        help_text=(
                            "Porcentaje mínimo aplicado a los productos al pagar por "
                            "transferencia o efectivo. Usá 0 para desactivar el "
                            "descuento y ocultar sus leyendas."
                        ),
                        validators=[MinValueValidator(0), MaxValueValidator(50)],
                        verbose_name="descuento por efectivo/transferencia (%)",
                    ),
                ),
            ],
            options={
                "verbose_name": "configuración comercial",
                "verbose_name_plural": "configuración comercial",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)),
                        name="shop_commercial_settings_singleton",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("offline_payment_discount_percent__gte", 0)
                            )
                            & models.Q(
                                ("offline_payment_discount_percent__lte", 50)
                            )
                        ),
                        name="shop_offline_discount_percent_range",
                    ),
                ],
            },
        ),
        migrations.RunPython(seed_commercial_settings, migrations.RunPython.noop),
    ]
