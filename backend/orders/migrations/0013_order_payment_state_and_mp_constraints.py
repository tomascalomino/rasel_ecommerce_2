from decimal import Decimal

from django.db import migrations, models


def backfill_financial_state(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(status__in=["paid", "shipped"]).update(
        payment_status="approved",
        stock_deducted=True,
    )
    Order.objects.filter(status="cancelled").update(payment_status="cancelled")


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0012_order_address_extra"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("paid", "Pagada"),
                    ("shipped", "Enviada"),
                    ("cancelled", "Cancelada"),
                    ("payment_review", "Revision de pago"),
                ],
                default="pending",
                max_length=20,
                verbose_name="estado",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("approved", "Aprobado"),
                    ("rejected", "Rechazado"),
                    ("cancelled", "Cancelado"),
                    ("partially_refunded", "Reintegro parcial"),
                    ("refunded", "Reintegrado"),
                    ("charged_back", "Contracargo"),
                    ("review", "Revision"),
                ],
                default="pending",
                max_length=30,
                verbose_name="estado financiero",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="mp_refunded_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                max_digits=12,
                verbose_name="monto reintegrado",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="stock_deducted",
            field=models.BooleanField(default=True, verbose_name="stock descontado"),
        ),
        migrations.RunPython(backfill_financial_state, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                fields=("mp_payment_id",),
                condition=~models.Q(mp_payment_id=""),
                name="orders_unique_mp_payment_id",
            ),
        ),
    ]
