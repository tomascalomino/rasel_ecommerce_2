from datetime import timedelta

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
)


def first_retained_day(today):
    """Current calendar month and preceding eleven months."""
    month_index = today.year * 12 + today.month - 1 - 11
    return today.replace(year=month_index // 12, month=month_index % 12 + 1, day=1)


def cleanup_batch(*, now=None, batch_size=100, force=False):
    """At most one small batch per minute across workers. No customer/order data."""
    now = now or timezone.now()
    cutoff = first_retained_day(timezone.localdate(now))
    with transaction.atomic():
        state = Measurement.objects.select_for_update().filter(pk=1).first()
        if not state or (not force and state.cleanup_after > now):
            return 0
        state.cleanup_after = now + timedelta(minutes=1)
        state.save(update_fields=["cleanup_after"])
        count = 0
        expired = [(Visit, {"started_at__lt": now - timedelta(days=90)})]
        expired.append((Session, {"expire_date__lt": now}))
        expired += [
            (model, {"day__lt": cutoff})
            for model in (DailyTotal, DailySource, DailyDevice, DailyProduct)
        ]
        for model, filters in expired:
            keys = list(
                model.objects.filter(**filters)
                .order_by("pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            if keys:
                count += model.objects.filter(pk__in=keys).delete()[0]
        return count
