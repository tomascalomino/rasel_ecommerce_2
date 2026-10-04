from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from marketing.delivery import configuration_problem, due_events, send_event
from marketing.maintenance import cleanup
from marketing.models import MetaPurchase


class Command(BaseCommand):
    help = "Diagnostica Meta sin enviar. --send habilita envío y limpieza; no reconstruye compras."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--order", type=int)
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Tras corregir el error: requiere --send y --order; conserva el evento.",
        )

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 1000:
            raise CommandError("--limit debe estar entre 1 y 1000")
        if options["retry_failed"] and (
            not options["send"] or options["order"] is None
        ):
            raise CommandError("--retry-failed requiere --send y --order")
        queryset = MetaPurchase.objects.all()
        if options["order"] is not None:
            queryset = queryset.filter(order_id=options["order"])
        summary = {
            row["status"]: row["count"]
            for row in queryset.values("status").annotate(count=Count("pk"))
        }
        self.stdout.write(f"Cola Meta (sin datos personales): {summary}")
        problem = configuration_problem()
        if problem:
            self.stdout.write(problem)
        if not options["send"]:
            self.stdout.write(
                "Diagnóstico: no se enviaron eventos ni se modificó la cola."
            )
            return
        cleanup()
        if problem:
            return
        if options["retry_failed"]:
            MetaPurchase.objects.filter(
                order_id=options["order"], status="failed"
            ).update(
                status="pending",
                next_attempt_at=timezone.now(),
                diagnostic="manual_retry",
            )
        ids = list(
            due_events(options["order"]).values_list("pk", flat=True)[
                : options["limit"]
            ]
        )
        results = Counter(send_event(pk) for pk in ids)
        self.stdout.write(
            f"Resultado Meta: {dict(results)}. Los reintentos requieren ejecutar nuevamente el comando."
        )
