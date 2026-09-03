from django.db import migrations, models


def split_historical_statuses(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(fulfillment_status="paid").update(fulfillment_status="pending")
    Order.objects.filter(fulfillment_status="payment_review").update(
        fulfillment_status="pending"
    )
    Order.objects.filter(fulfillment_status="shipped", delivery_method="pickup").update(
        fulfillment_status="ready_for_pickup"
    )


def restore_legacy_statuses(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(fulfillment_status="completed").update(
        fulfillment_status="shipped"
    )
    Order.objects.filter(fulfillment_status="ready_for_pickup").update(
        fulfillment_status="shipped"
    )
    Order.objects.filter(
        fulfillment_status="pending", payment_status="approved"
    ).update(fulfillment_status="paid")
    Order.objects.filter(fulfillment_status="pending", payment_status="review").update(
        fulfillment_status="payment_review"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0015_order_payment_discount_percent"),
    ]

    operations = [
        migrations.RenameField(
            model_name="order",
            old_name="status",
            new_name="fulfillment_status",
        ),
        migrations.AddField(
            model_name="order",
            name="completed_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="fecha de entrega/retiro"
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="completion_email_sent",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(split_historical_statuses, restore_legacy_statuses),
        migrations.AlterField(
            model_name="order",
            name="fulfillment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("shipped", "Despachada"),
                    ("ready_for_pickup", "Lista para retirar"),
                    ("completed", "Completada"),
                    ("cancelled", "Cancelada"),
                ],
                default="pending",
                max_length=20,
                verbose_name="estado de entrega",
            ),
        ),
    ]
