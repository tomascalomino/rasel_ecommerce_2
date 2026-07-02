from django import template

register = template.Library()


@register.filter
def ars(value):
    """Formatea un monto como '$ 6.000' (es-AR, sin decimales).

    Mismo formato que money() en el JS del checkout.
    """
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return "$ " + f"{n:,}".replace(",", ".")
