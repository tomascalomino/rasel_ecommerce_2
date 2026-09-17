"""Signed per-page signals bound to the current session and visit."""

import json
import logging
from datetime import timedelta

from django.core import signing
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .classification import PAGES, eligible
from .models import DailyTotal, Visit
from .tracking import SESSION_KEY

logger = logging.getLogger(__name__)
SALT = "analytics.activity.v1"


def context(request):
    visit = getattr(request, "_analytics_candidate", None)
    if (
        visit is None
        or visit.quality_version != 2
        or request.method != "GET"
        or getattr(request.resolver_match, "view_name", "") not in PAGES
    ):
        return {}
    return {
        "analytics_activity_token": signing.dumps(
            {"visit": str(visit.id), "issued": timezone.now().timestamp()}, salt=SALT
        )
    }


@never_cache
@require_POST
def activity(request):
    try:
        if not eligible(request):
            return HttpResponse(status=204)
        if request.content_type != "application/json" or len(request.body) > 2048:
            return HttpResponse(status=400)
        data = json.loads(request.body)
        if (
            not isinstance(data, dict)
            or set(data) != {"event", "token"}
            or data["event"] not in {"visible", "interaction"}
        ):
            return HttpResponse(status=400)
        page = signing.loads(data["token"], salt=SALT, max_age=1800)
        if page["visit"] != request.session.get(SESSION_KEY):
            return HttpResponse(status=204)
        now = timezone.now()
        if data["event"] == "visible" and now.timestamp() - page["issued"] < 10:
            return HttpResponse(status=204)
        with transaction.atomic():
            visit = (
                Visit.objects.select_for_update()
                .filter(
                    pk=page["visit"],
                    quality_version=2,
                    last_seen_at__gt=now - timedelta(minutes=30),
                )
                .first()
            )
            if visit and not visit.active:
                visit.active = True
                visit.save(update_fields=["active"])
                DailyTotal.objects.filter(day=visit.day).update(
                    active_visits=F("active_visits") + 1
                )
        return HttpResponse(status=204)
    except (ValueError, TypeError, KeyError, signing.BadSignature):
        return HttpResponse(status=400)
    except Exception:
        logger.warning("No se pudo registrar la actividad de la visita.")
        return HttpResponse(status=204)
