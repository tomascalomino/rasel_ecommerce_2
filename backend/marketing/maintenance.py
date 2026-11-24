from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import BrowserEventReceipt, Consent, MetaMaintenance, MetaPurchase


def cleanup_if_due():
    now = timezone.now()
    with transaction.atomic():
        state, _ = MetaMaintenance.objects.get_or_create(
            pk=1, defaults={"cleanup_after": now}
        )
        if state.cleanup_after > now:
            return
        due = MetaMaintenance.objects.filter(pk=state.pk, cleanup_after__lte=now)
        if due.update(cleanup_after=now + timedelta(days=1)):
            cleanup(now=now)


def cleanup(*, now=None):
    from orders.models import Order
    from payments.models import PaymentDraft

    now = now or timezone.now()
    cutoff = now - timedelta(days=90)
    for model in (Order, PaymentDraft):
        model.objects.filter(marketing_captured_at__lt=cutoff).exclude(
            marketing_context={}
        ).update(
            marketing_context={},
            marketing_consent=None,
        )
    MetaPurchase.objects.filter(
        created_at__lt=cutoff, payload_purged_at__isnull=True
    ).update(
        payload={},
        payload_purged_at=now,
        test_event_code="",
    )
    MetaPurchase.objects.filter(created_at__lt=now - timedelta(days=365)).delete()
    BrowserEventReceipt.objects.filter(created_at__lt=cutoff).delete()
    Consent.objects.filter(expires_at__lt=cutoff).delete()
