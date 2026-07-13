"""
La zona "AMBA" pasa a llamarse "Gran Buenos Aires" en todo lo visible
(tarjeta en /envios/, checkout, emails, título en MercadoPago). Además,
la descripción en producción todavía decía "(conurbano y La Plata)"
pese a que el Gran La Plata quedó fuera del reparto propio (los CPs se
excluyeron desde el admin; el seed de 0002 corta en 1893).

El código interno de la zona sigue siendo "amba": es un identificador
interno y las órdenes históricas guardan el nombre como snapshot, que
no se toca. Solo se pisa la descripción si coincide con los textos
viejos conocidos, para no borrar un texto personalizado desde el admin.
"""
from django.db import migrations


def fix(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")

    zone = ShippingZone.objects.filter(code="amba").first()
    if not zone:
        return

    fields = []
    if zone.name == "AMBA":
        zone.name = "Gran Buenos Aires"
        fields.append("name")
    if any(s in zone.description for s in ("La Plata", "AMBA", "Metropolitana")):
        zone.description = "Gran Buenos Aires. Envío con un valor fijo."
        fields.append("description")
    if fields:
        zone.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0009_alter_pickuppoint_address_and_more"),
    ]

    operations = [
        migrations.RunPython(fix, migrations.RunPython.noop),
    ]
