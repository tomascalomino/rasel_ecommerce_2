"""Bounded, shared traffic classification. Never persist raw request headers."""

import re

from django.conf import settings

PAGES = {
    "home",
    "about",
    "virgen_extra",
    "conservacion",
    "contact",
    "shipping_info",
    "terms",
    "privacy",
    "returns",
    "regret",
    "shop:product_list",
    "shop:product_detail",
    "cart:detail",
    "orders:checkout",
}
MONITOR = re.compile(
    r"uptimerobot|monitor|pingdom|go-http-client|healthcheck|health[-_]?probe", re.I
)
BOT = re.compile(
    r"bot|crawler|spider|slurp|headless|preview|facebookexternalhit|"
    r"meta-externalagent|meta-externalfetcher|whatsapp|curl|wget|python|"
    r"http[-_]?client|lighthouse|pagespeed|selenium|okhttp|axios|node-fetch|"
    r"undici|scrapy|libwww|^java/|^dart/|^ruby|^perl",
    re.I,
)
REASONS = {
    "staff": "Personal autenticado",
    "monitor": "Monitoreo reconocido",
    "bot": "Bots / clientes automatizados",
    "prefetch": "Precargas",
    "missing_agent": "Agente ausente",
}


def exclusion_reason(request):
    if getattr(request.user, "is_staff", False):
        return "staff"
    ua = request.META.get("HTTP_USER_AGENT", "").strip()
    if MONITOR.search(ua):
        return "monitor"
    if BOT.search(ua):
        return "bot"
    if any(
        re.search(r"prefetch|prerender", request.META.get(key, ""), re.I)
        for key in ("HTTP_PURPOSE", "HTTP_SEC_PURPOSE", "HTTP_X_PURPOSE")
    ):
        return "prefetch"
    return "" if ua else "missing_agent"


def eligible(request):
    return settings.ANALYTICS_ENABLED and not exclusion_reason(request)
