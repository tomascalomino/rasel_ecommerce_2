from django.db import migrations


POINTS = [
    {
        "name": "Punto de retiro CABA",
        "address": "A completar — CABA",
        "schedule_notes": "Coordinamos día y horario por WhatsApp.",
        "sort_order": 1,
    },
    {
        "name": "Punto de retiro Moreno",
        "address": "A completar — Moreno, Bs. As.",
        "schedule_notes": "Coordinamos día y horario por WhatsApp.",
        "sort_order": 2,
    },
]


def seed_points(apps, schema_editor):
    """Dos puntos placeholder; el dueño completa la dirección desde el admin."""
    PickupPoint = apps.get_model("shipping", "PickupPoint")
    for data in POINTS:
        PickupPoint.objects.get_or_create(name=data["name"], defaults=data)


def remove_points(apps, schema_editor):
    PickupPoint = apps.get_model("shipping", "PickupPoint")
    PickupPoint.objects.filter(name__in=[p["name"] for p in POINTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('shipping', '0007_pickuppoint'),
    ]

    operations = [
        migrations.RunPython(seed_points, remove_points),
    ]
