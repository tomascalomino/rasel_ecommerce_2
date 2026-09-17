from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from orders.models import Order

from .maintenance import first_retained_day
from .models import (
    DailyDevice,
    DailyProduct,
    DailySource,
    DailyTotal,
    Measurement,
    QualityMeasurement,
    DailyExclusion,
)
from .classification import REASONS

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
    "quality_visits",
    "active_visits",
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
    quality = QualityMeasurement.objects.filter(pk=1).first()
    quality_from = timezone.localdate(quality.started_at) if quality else None
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
            quality_available=bool(quality_from and end > quality_from),
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
        row["active_height"] = round(row["active_visits"] / peak * 170)
        row["active_y"] = 180 - row["active_height"]
    sales_query = Order.objects.filter(
        created_at__gte=timezone.make_aware(datetime.combine(start, time.min)),
        created_at__lt=timezone.make_aware(
            datetime.combine(today + timedelta(days=1), time.min)
        ),
        payment_status__in=("approved", "partially_refunded"),
    ).exclude(fulfillment_status="cancelled")
    sales = sales_query.aggregate(
        total=Sum(F("total_amount") - F("mp_refunded_amount")), count=Count("pk")
    )
    retained_at = timezone.make_aware(
        datetime.combine(first_retained_day(today), time.min)
    )
    attributed = sales_query.filter(analytics_attributed_at__gte=retained_at)
    attributed_total = attributed.aggregate(
        total=Sum(F("total_amount") - F("mp_refunded_amount")), count=Count("pk")
    )
    attribution_rows = []
    for item in (
        attributed.values(
            "analytics_attribution__source",
            "analytics_attribution__medium",
            "analytics_attribution__campaign",
        )
        .annotate(
            total=Sum(F("total_amount") - F("mp_refunded_amount")), count=Count("pk")
        )
        .order_by(
            "-total",
            "analytics_attribution__source",
            "analytics_attribution__medium",
            "analytics_attribution__campaign",
        )[:8]
    ):
        source = item["analytics_attribution__source"]
        attribution_rows.append(
            dict(
                label="Directo / desconocido" if source == "directo" else source,
                medium=item["analytics_attribution__medium"],
                campaign=item["analytics_attribution__campaign"],
                count=item["count"],
                total=item["total"],
            )
        )
    rest_count = attributed_total["count"] - sum(
        row["count"] for row in attribution_rows
    )
    if rest_count:
        attribution_rows.append(
            dict(
                label="Orígenes restantes",
                count=rest_count,
                total=(attributed_total["total"] or 0)
                - sum(row["total"] for row in attribution_rows),
            )
        )
    attribution_rows.append(
        dict(
            label="Sin atribución",
            count=sales["count"] - attributed_total["count"],
            total=(sales["total"] or 0) - (attributed_total["total"] or 0),
        )
    )
    excluded = dict(
        DailyExclusion.objects.filter(day__gte=start, day__lte=today)
        .values("reason")
        .annotate(count=Sum("requests"))
        .values_list("reason", "count")
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
    source_rest = counts["visits"] - sum(source["count"] for source in sources)
    if source_rest > 0:
        sources.append(dict(label="Orígenes restantes", count=source_rest))
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
        quality=quality,
        activity_percent=(
            round(counts["active_visits"] / counts["quality_visits"] * 100, 1)
            if counts["quality_visits"]
            else None
        ),
        exclusions=[
            dict(label=label, count=excluded.get(key, 0))
            for key, label in REASONS.items()
        ],
        attribution_rows=attribution_rows,
        unknown_devices=devices.get("unknown", 0),
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
