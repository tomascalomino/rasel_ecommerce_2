from datetime import timedelta

from django.utils import timezone

from .models import BrowserEventReceipt, Consent, MetaPurchase


def cleanup():
    from orders.models import Order
    from payments.models import PaymentDraft

    now = timezone.now()
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
