"""
Correcciones de clasificación tras verificar datos reales de CP:

1. El CP 1763 NO es La Reja (Moreno) sino Virrey del Pino (La Matanza), una
   localidad populosa del conurbano que debe pagar AMBA, no envío gratis.
   Se quita 1763 de la zona gratis; La Reja sigue gratis vía el rango 1742-1746.

Nota histórica: esta migración también partía el rango AMBA (1500-1929) para
excluir Magdalena (1913). Quedó obsoleto cuando el negocio dejó de cubrir el
Gran La Plata: el seed de AMBA ahora corta en 1893 (ver 0002, igual que en
producción), así que 1913 ya cae en la zona default.
"""
from django.db import migrations


def fix(apps, schema_editor):
    PostalCodeRule = apps.get_model("shipping", "PostalCodeRule")

    # Sacar 1763 de "gratis" (Virrey del Pino, La Matanza).
    PostalCodeRule.objects.filter(
        zone__code="free", cp_from=1763, cp_to=1763
    ).delete()


def unfix(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    PostalCodeRule = apps.get_model("shipping", "PostalCodeRule")

    free = ShippingZone.objects.filter(code="free").first()
    if free:
        PostalCodeRule.objects.get_or_create(
            zone=free, cp_from=1763, cp_to=1763, defaults={"note": "La Reja (Moreno)"}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0002_seed_zones"),
    ]

    operations = [
        migrations.RunPython(fix, unfix),
    ]
