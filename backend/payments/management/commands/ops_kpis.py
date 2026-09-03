from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from orders.models import Order
from payments.models import PaymentDraft, PaymentEvent
from shop.models import Variant


class Command(BaseCommand):
    help = "Muestra KPIs operativos de pagos/órdenes para monitoreo rápido"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Ventana en días para el reporte (default: 7)",
        )

    def handle(self, *args, **options):
        days = max(1, int(options["days"]))
        now = timezone.now()
        since = now - timedelta(days=days)
        stale_cutoff = now - timedelta(hours=2)

        paid_orders = Order.objects.filter(
            payment_status__in=["approved", "partially_refunded"],
            created_at__gte=since,
        ).exclude(fulfillment_status="cancelled")
        cancelled_orders = Order.objects.filter(
            fulfillment_status="cancelled", created_at__gte=since
        )

        payment_events = PaymentEvent.objects.filter(created_at__gte=since)
        payment_topics = payment_events.filter(topic__in=["payment", "payments"])
        payment_errors = payment_topics.filter(
            Q(notes__icontains="processing error")
            | Q(notes__icontains="finalize_error")
            | Q(processed_ok=False)
        )

        drafts = PaymentDraft.objects.filter(created_at__gte=since)
        consumed_drafts = drafts.exclude(consumed_at__isnull=True)
        pending_drafts = drafts.filter(consumed_at__isnull=True)
        stale_pending_drafts = pending_drafts.filter(created_at__lt=stale_cutoff)

        active_variants = Variant.objects.filter(is_active=True)
        out_of_stock_variants = active_variants.filter(stock_qty=0)
        low_stock_variants = active_variants.filter(stock_qty__gt=0, stock_qty__lte=5)

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"KPIs operativos (últimos {days} días)")
        )
        self.stdout.write(f"Ventana: {since.isoformat()} -> {now.isoformat()}")
        self.stdout.write("")

        self.stdout.write(self.style.HTTP_INFO("Pagos y órdenes"))
        self.stdout.write(f"- Órdenes cobradas: {paid_orders.count()}")
        self.stdout.write(f"- Órdenes canceladas: {cancelled_orders.count()}")
        self.stdout.write(f"- Eventos payment/payments: {payment_topics.count()}")
        self.stdout.write(
            f"- Eventos procesados OK: {payment_topics.filter(processed_ok=True).count()}"
        )
        self.stdout.write(f"- Eventos con error/alerta: {payment_errors.count()}")
        self.stdout.write("")

        self.stdout.write(self.style.HTTP_INFO("Drafts de pago"))
        self.stdout.write(f"- Drafts creados: {drafts.count()}")
        self.stdout.write(f"- Drafts consumidos: {consumed_drafts.count()}")
        self.stdout.write(f"- Drafts pendientes: {pending_drafts.count()}")
        self.stdout.write(f"- Drafts pendientes >2h: {stale_pending_drafts.count()}")
        self.stdout.write("")

        self.stdout.write(self.style.HTTP_INFO("Salud de stock"))
        self.stdout.write(f"- Variantes activas: {active_variants.count()}")
        self.stdout.write(f"- Variantes sin stock: {out_of_stock_variants.count()}")
        self.stdout.write(
            f"- Variantes con stock bajo (<=5): {low_stock_variants.count()}"
        )

        if (
            payment_errors.exists()
            or stale_pending_drafts.exists()
            or out_of_stock_variants.exists()
        ):
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Alertas operativas detectadas"))
            self.stdout.write("- Revisar admin: PaymentEvent, PaymentDraft, Variant")
