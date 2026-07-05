from django.db import migrations, models


def enable_cod(apps, schema_editor):
    """
    Habilitamos contraentrega en las zonas donde RaSel reparte en persona:
    todas las activas que no son 'a cargo del comprador' ni la default
    (resto del país). Hoy: CABA/Moreno y AMBA.
    """
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    ShippingZone.objects.filter(
        carrier_arranged=False, is_default=False, is_active=True
    ).update(cod_allowed=True)


def revert_cod(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    ShippingZone.objects.update(cod_allowed=False)


class Migration(migrations.Migration):

    dependencies = [
        ('shipping', '0005_carrier_arranged'),
    ]

    operations = [
        migrations.AddField(
            model_name='shippingzone',
            name='cod_allowed',
            field=models.BooleanField(default=False, help_text='Permite pagar en efectivo a contraentrega en esta zona (solo zonas donde RaSel reparte en persona, ej. CABA/AMBA).'),
        ),
        migrations.RunPython(enable_cod, revert_cod),
    ]
