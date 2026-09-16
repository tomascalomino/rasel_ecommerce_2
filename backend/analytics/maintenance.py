from datetime import timedelta
from datetime import datetime, time

from django.db import transaction
from django.contrib.sessions.models import Session
from django.utils import timezone

from .models import (
    DailyDevice,
    DailyProduct,
    DailySource,
    DailyTotal,
    Measurement,
    Visit,
    DailyExclusion,
    QualityMeasurement,
)


def first_retained_day(today):
    """Current calendar month and preceding eleven months."""
    month_index = today.year * 12 + today.month - 1 - 11
    return today.replace(year=month_index // 12, month=month_index % 12 + 1, day=1)


def cleanup_batch(*, now=None, batch_size=100, force=False):
    """Bounded cleanup of analytics and expired sessions; preserve business data."""
    now = now or timezone.now()
    cutoff = first_retained_day(timezone.localdate(now))
    with transaction.atomic():
        state = Measurement.objects.select_for_update().filter(pk=1).first()
        if not state:
            state = QualityMeasurement.objects.select_for_update().filter(pk=1).first()
        if not state or (not force and state.cleanup_after > now):
            return 0
        state.cleanup_after = now + timedelta(minutes=1)
        state.save(update_fields=["cleanup_after"])
        count = 0
        expired = [(Visit, {"started_at__lt": now - timedelta(days=90)})]
        expired.append((Session, {"expire_date__lt": now}))
        expired += [
            (model, {"day__lt": cutoff})
            for model in (
                DailyTotal,
                DailySource,
                DailyDevice,
                DailyProduct,
                DailyExclusion,
            )
        ]
        for model, filters in expired:
            keys = list(
                model.objects.filter(**filters)
                .order_by("pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            if keys:
                count += model.objects.filter(pk__in=keys).delete()[0]
        # Clear only optional metadata; never delete orders or payment drafts.
        from orders.models import Order
        from payments.models import PaymentDraft

        cutoff_at = timezone.make_aware(datetime.combine(cutoff, time.min))
        for model in (Order, PaymentDraft):
            keys = list(
                model.objects.filter(analytics_attributed_at__lt=cutoff_at)
                .order_by("pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            count += model.objects.filter(
                pk__in=keys, analytics_attributed_at__lt=cutoff_at
            ).update(
                analytics_attribution={},
                analytics_attributed_at=None,
            )
        return count
