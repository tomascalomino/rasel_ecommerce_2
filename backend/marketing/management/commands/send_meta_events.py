from collections import Counter
from datetime import timedelta

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
            "--fail-on-problems",
            action="store_true",
            help="Para tareas automáticas: salida fallida ante configuración o cola con errores.",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Tras corregir el error: requiere --send y --order; conserva el evento.",
        )

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 1000:
            raise CommandError("--limit debe estar entre 1 y 1000")
        if options["fail_on_problems"] and not options["send"]:
            raise CommandError("--fail-on-problems requiere --send")
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
        if problem and options["fail_on_problems"]:
            raise CommandError(problem)
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
            f"Resultado Meta: {dict(results)}. Los reintentos requieren otra ejecución del comando."
        )
        if options["fail_on_problems"]:
            problems = {
                "temporales_en_este_lote": results["pending"],
                "configuracion_desactivada": results["disabled"],
                "errores_por_revisar": queryset.filter(status="failed").count(),
                "destino_o_prueba_no_coincide": queryset.filter(
                    status="pending", diagnostic="destination_or_test_mode_mismatch"
                ).count(),
                "pendientes_mayores_a_una_hora": queryset.filter(
                    status__in=["pending", "sending"],
                    created_at__lt=timezone.now() - timedelta(hours=1),
                ).count(),
                "vencidos_en_este_lote": queryset.filter(
                    pk__in=ids, status="expired"
                ).count(),
            }
            problems = {key: count for key, count in problems.items() if count}
            if problems:
                raise CommandError(
                    f"Meta requiere revisión (solo cantidades): {problems}"
                )
