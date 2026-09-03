from django.db import migrations, models


def backfill_payment_discount_percent(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(
        payment_method__in=("transfer", "cod"),
        payment_discount_amount__gt=0,
    ).update(payment_discount_percent=5)


def clear_payment_discount_percent(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.update(payment_discount_percent=0)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0014_order_payment_discount_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="payment_discount_percent",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Snapshot del porcentaje aplicado al crear la orden.",
                verbose_name="porcentaje de descuento aplicado",
            ),
        ),
        migrations.RunPython(
            backfill_payment_discount_percent,
            clear_payment_discount_percent,
        ),
    ]
