from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0007_commercialsettings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="commercialsettings",
            name="offline_payment_discount_percent",
            field=models.PositiveSmallIntegerField(
                default=10,
                help_text=(
                    "Porcentaje aplicado a los productos al pagar por transferencia "
                    "o efectivo. Usá 0 para desactivar el descuento y ocultar sus "
                    "leyendas."
                ),
                validators=[MinValueValidator(0), MaxValueValidator(50)],
                verbose_name="descuento por efectivo/transferencia (%)",
            ),
        ),
    ]
