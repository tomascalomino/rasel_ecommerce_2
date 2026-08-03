from django.db import migrations, models


def backfill_payment_states(apps, schema_editor):
    PaymentDraft = apps.get_model("payments", "PaymentDraft")
    for mp_status, state in {
        "approved": "approved",
        "pending": "pending",
        "in_process": "pending",
        "rejected": "rejected",
        "cancelled": "cancelled",
        "refunded": "review",
        "charged_back": "review",
    }.items():
        PaymentDraft.objects.filter(mp_status=mp_status).update(state=state)
    PaymentDraft.objects.filter(order__isnull=False, state="created").update(
        state="approved"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0013_order_payment_state_and_mp_constraints"),
        ("payments", "0006_paymentdraft_address_extra"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentevent",
            name="action",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="paymentevent",
            name="processing_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="paymentevent",
            name="provider_event_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="paymentevent",
            name="request_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="paymentevent",
            name="signature_valid",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="last_reconciled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="mp_collector_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="mp_init_point",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="mp_live_mode",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="mp_status_detail",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="processing_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="reservation_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="state",
            field=models.CharField(
                choices=[
                    ("created", "Creado"),
                    ("reserved", "Stock reservado"),
                    ("preference_created", "Preferencia creada"),
                    ("pending", "Pago pendiente"),
                    ("approved", "Aprobado"),
                    ("rejected", "Rechazado"),
                    ("cancelled", "Cancelado"),
                    ("expired", "Expirado"),
                    ("released", "Stock liberado"),
                    ("review", "Revision manual"),
                ],
                db_index=True,
                default="created",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="stock_released_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentdraft",
            name="stock_reserved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_payment_states, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="paymentevent",
            constraint=models.UniqueConstraint(
                fields=("provider", "provider_event_id"),
                condition=~models.Q(provider_event_id=""),
                name="payments_unique_provider_event",
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentdraft",
            constraint=models.UniqueConstraint(
                fields=("mp_payment_id",),
                condition=~models.Q(mp_payment_id=""),
                name="payments_unique_draft_mp_payment_id",
            ),
        ),
    ]
