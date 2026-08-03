from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from orders.emails import send_payment_alert
from payments.mercadopago import (
    MercadoPagoError,
    cancel_payment,
    get_payment,
    search_payments,
)
from payments.models import PaymentDraft, PaymentEvent
from payments.services import (
    PaymentValidationError,
    process_payment,
    release_reserved_stock,
)


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
        max_pending_at = now - timedelta(hours=settings.MP_PENDING_MAX_HOURS)
        drafts = list(
            PaymentDraft.objects.select_related("order")
            .filter(
                Q(order__isnull=True)
                | Q(order__payment_status__in=["pending", "review", "approved"])
            )
            .filter(
                state__in=[
                    "reserved",
                    "preference_created",
                    "pending",
                    "approved",
                    "review",
                ]
            )
            .order_by("created_at")[:batch_size]
        )

        counters = {"checked": 0, "processed": 0, "released": 0, "failed": 0}
        failures = []
        for draft in drafts:
            counters["checked"] += 1
            PaymentDraft.objects.filter(pk=draft.pk).update(last_reconciled_at=now)
            try:
                payment = self._find_payment(draft)
                if payment:
                    status = str(payment.get("status") or "")
                    if status in {"pending", "in_process", "authorized"} and draft.created_at <= max_pending_at:
                        payment_id = str(payment.get("id") or "")
                        cancel_payment(
                            payment_id,
                            idempotency_key=f"rasel-cancel-{payment_id}",
                        )
                        payment = get_payment(payment_id)
                        if str(payment.get("status") or "") not in {
                            "cancelled",
                            "rejected",
                        }:
                            raise MercadoPagoError(
                                "Mercado Pago no confirmo la cancelacion del pago pendiente"
                            )
                    result = process_payment(
                        payment,
                        str(payment.get("id") or ""),
                        reconciled=True,
                    )
                    counters["processed"] += 1
                    if result.state == "review":
                        failures.append(f"draft {draft.token}: payment_review")
                    continue

                if draft.reservation_expires_at and draft.reservation_expires_at <= now:
                    if release_reserved_stock(draft.token, "expired"):
                        counters["released"] += 1
            except (MercadoPagoError, PaymentValidationError, OSError) as exc:
                counters["failed"] += 1
                failures.append(f"draft {draft.token}: {exc}")
                PaymentDraft.objects.filter(pk=draft.pk).update(
                    processing_error=str(exc)[:1000],
                )

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
            f"revisados={counters['checked']} procesados={counters['processed']} "
            f"liberados={counters['released']} fallidos={counters['failed']}"
        )
        self.stdout.write(summary)
        if failures:
            send_payment_alert(
                "Conciliacion de Mercado Pago requiere atencion",
                summary + "\n\n" + "\n".join(failures[:20]),
            )
        if counters["failed"]:
            raise CommandError(summary)

    @staticmethod
    def _find_payment(draft):
        if draft.mp_payment_id:
            return get_payment(draft.mp_payment_id)
        payments = search_payments(str(draft.token))
        for payment in payments:
            if str(payment.get("external_reference") or "") == str(draft.token):
                return payment
        return None
