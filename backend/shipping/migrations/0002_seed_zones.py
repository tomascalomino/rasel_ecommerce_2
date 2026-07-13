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
        "name": "Gran Buenos Aires",
        "price": Decimal("7000.00"),
        "is_default": False,
        "sort_order": 2,
        "description": (
            "Gran Buenos Aires. Envío con un valor fijo."
        ),
        "rules": [
            # El Gran La Plata (City Bell 1896, La Plata 1900, Berisso 1923,
            # Ensenada 1925) quedó fuera del reparto propio: el rango corta
            # en 1893 y esos CPs caen en la zona default (resto del país).
            (1500, 1893, "Conurbano"),
        ],
    },
    {
        "code": "national",
        "name": "Resto del país",
        "price": Decimal("20000.00"),
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
