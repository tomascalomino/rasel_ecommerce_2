from django.core.management.base import BaseCommand, CommandError

from analytics.maintenance import cleanup_batch


class Command(BaseCommand):
    help = "Elimina detalle analítico de más de 90 días y resúmenes fuera de 12 meses."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--max-batches", type=int, default=10)

    def handle(self, *args, **options):
        size, batches = options["batch_size"], options["max_batches"]
        if not 1 <= size <= 1000 or not 1 <= batches <= 1000:
            raise CommandError("Los límites deben estar entre 1 y 1000.")
        count = 0
        for _ in range(batches):
            removed = cleanup_batch(batch_size=size, force=True)
            count += removed
            if not removed:
                break
        self.stdout.write(
            self.style.SUCCESS(f"Registros analíticos eliminados: {count}")
        )
