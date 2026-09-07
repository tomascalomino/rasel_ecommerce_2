from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from orders.models import Order

from .maintenance import first_retained_day
from .models import DailyDevice, DailyProduct, DailySource, DailyTotal, Measurement

PERIODS = [
    ("today", "Hoy"),
    ("7", "7 días"),
    ("30", "30 días"),
    ("90", "90 días"),
    ("12m", "12 meses"),
]
COUNTERS = (
    "visits",
    "pageviews",
    "cart_added",
    "checkout_opened",
    "checkout_submitted",
)
DEVICE_LABELS = {
    "mobile": "Celular",
    "desktop": "Computadora",
    "tablet": "Tablet",
    "unknown": "Desconocido",
}


def report_context(period):
    if period not in dict(PERIODS):
        period = "30"
    today = timezone.localdate()
    monthly = period == "12m"
    start = (
        first_retained_day(today)
        if monthly
        else today - timedelta(days=(1 if period == "today" else int(period)) - 1)
    )
    state = Measurement.objects.filter(pk=1).first()
    measured_from = timezone.localdate(state.started_at) if state else None
    totals = DailyTotal.objects.filter(day__gte=start, day__lte=today)
    counts = totals.aggregate(**{key: Sum(key) for key in COUNTERS})
    counts = {key: value or 0 for key, value in counts.items()}
    if monthly:
        raw_rows = (
            totals.annotate(bucket=TruncMonth("day"))
            .values("bucket")
            .annotate(**{key: Sum(key) for key in COUNTERS})
            .order_by("bucket")
        )
        rows_by_day = {row["bucket"]: row for row in raw_rows}
        days = []
        cursor = start
        while cursor <= today:
            days.append(cursor)
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        rows_by_day = {row["day"]: row for row in totals.values("day", *COUNTERS)}
        days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    rows = []
    for day in days:
        end = (
            (day.replace(day=28) + timedelta(days=4)).replace(day=1)
            if monthly
            else day + timedelta(days=1)
        )
        available = bool(measured_from and end > measured_from)
        row = dict(rows_by_day.get(day, dict.fromkeys(COUNTERS, 0)))
        row.update(
            day=day,
            label=day.strftime("%m/%Y" if monthly else "%d/%m"),
            available=available,
        )
        rows.append(row)
    peak = max([row["visits"] for row in rows] + [1])
    width = 720 // len(rows)
    for index, row in enumerate(rows):
        row.update(
            x=index * width + 4,
            width=max(2, width - 4),
            height=round(row["visits"] / peak * 170),
        )
        row["y"] = 180 - row["height"]
    sales = (
        Order.objects.filter(
            created_at__gte=timezone.make_aware(datetime.combine(start, time.min)),
            created_at__lt=timezone.make_aware(
                datetime.combine(today + timedelta(days=1), time.min)
            ),
            payment_status__in=("approved", "partially_refunded"),
        )
        .exclude(fulfillment_status="cancelled")
        .aggregate(
            total=Sum(F("total_amount") - F("mp_refunded_amount")), count=Count("pk")
        )
    )
    funnel = []
    for key, label in (
        ("visits", "Visitas"),
        ("cart_added", "Agregaron al carrito"),
        ("checkout_opened", "Abrieron el checkout"),
        ("checkout_submitted", "Enviaron el checkout"),
    ):
        funnel.append(
            dict(
                label=label,
                count=counts[key],
                percent=(
                    round(counts[key] / counts["visits"] * 100, 1)
                    if counts["visits"]
                    else None
                ),
            )
        )
    sources = list(
        DailySource.objects.filter(day__gte=start, day__lte=today)
        .values("source", "medium", "campaign")
        .annotate(count=Sum("visits"))
        .order_by("-count", "source", "medium", "campaign")[:8]
    )
    for source in sources:
        source["label"] = {
            "directo": "Directo / desconocido",
            "otros": "Otros orígenes",
        }.get(source["source"], source["source"])
    devices = dict(
        DailyDevice.objects.filter(day__gte=start, day__lte=today)
        .values("device")
        .annotate(count=Sum("visits"))
        .values_list("device", "count")
    )
    products = (
        DailyProduct.objects.filter(day__gte=start, day__lte=today)
        .values("product_id")
        .annotate(count=Sum("pageviews"))
        .order_by("-count", "product_id")[:5]
    )
    # One bounded query for snapshots; no queries per product in the template.
    products = list(products)
    snapshots = (
        DailyProduct.objects.filter(product_id__in=[p["product_id"] for p in products])
        .order_by("day")
        .values_list("product_id", "product_name")
    )
    names = dict(snapshots)
    for product in products:
        product["label"] = names[product["product_id"]]
    return dict(
        period=period,
        periods=PERIODS,
        start=start,
        end=today,
        monthly=monthly,
        measurement=state,
        tracking_enabled=settings.ANALYTICS_ENABLED,
        counts=counts,
        rows=rows,
        sales={"total": sales["total"] or 0, "count": sales["count"]},
        funnel=funnel,
        sources=sources,
        products=products,
        devices=[
            dict(label=label, count=devices.get(key, 0))
            for key, label in DEVICE_LABELS.items()
        ],
    )
