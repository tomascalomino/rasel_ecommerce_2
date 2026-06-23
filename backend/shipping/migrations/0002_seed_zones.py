from decimal import Decimal

from django.db import migrations


ZONES = [
    {
        "code": "free",
        "name": "CABA y Moreno",
        "price": Decimal("0.00"),
        "is_default": False,
        "sort_order": 1,
        "description": (
            "Envío sin cargo. Los pedidos dentro de la Ciudad de Buenos Aires (CABA) "
            "y del Partido de Moreno se entregan gratis."
        ),
        "rules": [
            (1000, 1499, "CABA"),
            (1742, 1746, "Moreno"),
            (1763, 1763, "La Reja (Moreno)"),
        ],
    },
    {
        "code": "amba",
        "name": "AMBA",
        "price": Decimal("5000.00"),
        "is_default": False,
        "sort_order": 2,
        "description": (
            "Área Metropolitana de Buenos Aires (conurbano y La Plata). "
            "Envío con un valor fijo."
        ),
        "rules": [
            (1500, 1929, "Conurbano y La Plata"),
        ],
    },
    {
        "code": "national",
        "name": "Resto del país",
        "price": Decimal("12000.00"),
        "is_default": True,
        "sort_order": 3,
        "description": (
            "Resto del país. El envío se gestiona a través de encomiendas de correo "
            "con un valor fijo."
        ),
        "rules": [],
    },
]


def seed(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    PostalCodeRule = apps.get_model("shipping", "PostalCodeRule")

    for data in ZONES:
        zone, _ = ShippingZone.objects.get_or_create(
            code=data["code"],
            defaults={
                "name": data["name"],
                "price": data["price"],
                "description": data["description"],
                "is_default": data["is_default"],
                "is_active": True,
                "sort_order": data["sort_order"],
            },
        )
        for cp_from, cp_to, note in data["rules"]:
            PostalCodeRule.objects.get_or_create(
                zone=zone,
                cp_from=cp_from,
                cp_to=cp_to,
                defaults={"note": note},
            )


def unseed(apps, schema_editor):
    ShippingZone = apps.get_model("shipping", "ShippingZone")
    ShippingZone.objects.filter(
        code__in=[z["code"] for z in ZONES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
