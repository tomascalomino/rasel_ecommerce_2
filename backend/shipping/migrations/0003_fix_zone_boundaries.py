"""
Correcciones de clasificación tras verificar datos reales de CP:

1. El CP 1763 NO es La Reja (Moreno) sino Virrey del Pino (La Matanza), una
   localidad populosa del conurbano que debe pagar AMBA, no envío gratis.
   Se quita 1763 de la zona gratis; La Reja sigue gratis vía el rango 1742-1746.

2. Magdalena (1913) no integra el AMBA (es un partido rural costero). Se parte
   el rango AMBA 1500-1929 en 1500-1912 y 1914-1929 para que 1913 caiga en la
   zona default (resto del país).
"""
from django.db import migrations


def fix(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    PostalCodeRule = apps.get_model("shipping", "PostalCodeRule")

    # 1) Sacar 1763 de "gratis" (Virrey del Pino, La Matanza).
    PostalCodeRule.objects.filter(
        zone__code="free", cp_from=1763, cp_to=1763
    ).delete()

    # 2) Excluir Magdalena (1913) de AMBA partiendo el rango.
    try:
        amba = ShippingZone.objects.get(code="amba")
    except ShippingZone.DoesNotExist:
        return
    PostalCodeRule.objects.filter(zone=amba, cp_from=1500, cp_to=1929).delete()
    for cp_from, cp_to, note in [
        (1500, 1912, "Conurbano y La Plata"),
        (1914, 1929, "La Plata / Ensenada / Berisso"),
    ]:
        PostalCodeRule.objects.get_or_create(
            zone=amba, cp_from=cp_from, cp_to=cp_to, defaults={"note": note}
        )


def unfix(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    PostalCodeRule = apps.get_model("shipping", "PostalCodeRule")

    free = ShippingZone.objects.filter(code="free").first()
    if free:
        PostalCodeRule.objects.get_or_create(
            zone=free, cp_from=1763, cp_to=1763, defaults={"note": "La Reja (Moreno)"}
        )

    amba = ShippingZone.objects.filter(code="amba").first()
    if amba:
        PostalCodeRule.objects.filter(
            zone=amba, cp_from__in=[1500, 1914]
        ).delete()
        PostalCodeRule.objects.get_or_create(
            zone=amba, cp_from=1500, cp_to=1929,
            defaults={"note": "Conurbano y La Plata"},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0002_seed_zones"),
    ]

    operations = [
        migrations.RunPython(fix, unfix),
    ]
