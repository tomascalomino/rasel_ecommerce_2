from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from orders.emails import send_payment_alert
from payments.models import PaymentEvent
from payments.reconciliation import reconcile_draft, reconciliation_batch


class Command(BaseCommand):
    help = "Concilia reservas y pagos de Mercado Pago sin depender del webhook."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size <= 0:
            raise CommandError("--batch-size debe ser mayor que cero")
        if not settings.MP_ACCESS_TOKEN or settings.MP_ENVIRONMENT not in {
            "test",
            "production",
        }:
            raise CommandError(
                "La conciliacion requiere MP_ACCESS_TOKEN y MP_ENVIRONMENT valido."
            )

        now = timezone.now()
        drafts = list(reconciliation_batch(now, batch_size))

        counters = {"processed": 0, "released": 0, "failed": 0, "review": 0}
        failures = []
        for draft in drafts:
            result = reconcile_draft(draft, now, release_expired=True)
            counters["processed"] += result.processed
            counters["released"] += result.released
            counters["review"] += bool(result.review)
            counters["failed"] += bool(result.error)
            if result.error or result.review:
                failures.append(f"draft {draft.token}: {result.error or result.review}")

        failed_events = list(
            PaymentEvent.objects.filter(
                signature_valid=True,
                processed_ok=False,
            )
            .exclude(processing_error="")
            .order_by("-created_at")
            .values_list("provider_event_id", "event_id", "processing_error")[:20]
        )
        for notification_id, payment_id, error in failed_events:
            failures.append(
                f"evento {notification_id or '-'} pago {payment_id or '-'}: {error}"
            )

        summary = (
            "Conciliacion MP: "
            f"revisados={len(drafts)} procesados={counters['processed']} "
            f"liberados={counters['released']} fallidos={counters['failed']} "
            f"para_revision={counters['review']}"
        )
        self.stdout.write(summary)
        if failures:
            send_payment_alert(
                "Conciliacion de Mercado Pago requiere atencion",
                summary + "\n\n" + "\n".join(failures[:20]),
            )
        if counters["failed"]:
            raise CommandError(summary)
