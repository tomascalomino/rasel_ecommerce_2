"""Context processors globales del sitio."""
import re

from django.conf import settings


def site(request):
    """Expone datos de contacto del sitio a todos los templates."""
    number = getattr(settings, "WHATSAPP_NUMBER", "") or ""
    digits = re.sub(r"\D", "", number)
    if digits and not digits.startswith("54"):
        digits = f"549{digits}"
    return {
        "whatsapp_number": number,
        "whatsapp_link": f"https://wa.me/{digits}" if digits else "",
    }
