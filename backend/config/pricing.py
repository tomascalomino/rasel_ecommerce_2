"""Reglas comerciales compartidas para calcular importes de la tienda."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP


MONEY_QUANTUM = Decimal("0.01")
OFFLINE_PRICE_ROUNDING_QUANTUM = Decimal("50.00")
DEFAULT_OFFLINE_PAYMENT_DISCOUNT_PERCENT = 10
OFFLINE_PAYMENT_METHODS = frozenset({"transfer", "cod"})


def get_offline_payment_discount_percent(request=None) -> int:
    """Obtiene la tasa vigente y la reutiliza durante el mismo request."""
    request_attribute = "_rasel_offline_payment_discount_percent"
    if request is not None and hasattr(request, request_attribute):
        return getattr(request, request_attribute)

    # Import diferido para mantener este módulo utilitario libre de ciclos.
    from shop.models import CommercialSettings

    value = (
        CommercialSettings.objects.filter(pk=1)
        .values_list("offline_payment_discount_percent", flat=True)
        .first()
    )
    percent = (
        DEFAULT_OFFLINE_PAYMENT_DISCOUNT_PERCENT if value is None else int(value)
    )
    if request is not None:
        setattr(request, request_attribute, percent)
    return percent


def money(value) -> Decimal:
    """Normaliza un importe a centavos usando redondeo comercial."""
    return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def price_discount_percent(reference_amount, final_amount) -> int | None:
    """Porcentaje entero de ahorro entre un precio de referencia y uno final."""
    if reference_amount is None or final_amount is None:
        return None

    reference = money(reference_amount)
    final = money(final_amount)
    if reference <= 0 or final >= reference:
        return None

    percentage = ((reference - final) / reference) * Decimal("100")
    return int(percentage.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_discount_label(reference_amount, final_amount) -> str:
    """Etiqueta comercial derivada, incluida la diferencia menor a 0,5%."""
    percentage = price_discount_percent(reference_amount, final_amount)
    if percentage is None:
        return ""
    if percentage == 0:
        return "<1% OFF"
    return f"{percentage}% OFF"


def payment_discount(subtotal, payment_method: str, discount_percent: int) -> Decimal:
    """Devuelve el descuento de una unidad o importe aislado."""
    normalized = money(subtotal)
    if (
        payment_method not in OFFLINE_PAYMENT_METHODS
        or normalized <= 0
        or discount_percent <= 0
    ):
        return Decimal("0.00")
    return normalized - _rounded_offline_price(normalized, discount_percent)


def payment_discount_for_lines(
    lines, payment_method: str, discount_percent: int
) -> Decimal:
    """Calcula el descuento por precio unitario y luego lo multiplica.

    ``lines`` contiene pares ``(precio_unitario, cantidad)``. Calcular por
    variante garantiza que el checkout coincida con el precio promocional que
    el cliente vio en el detalle del producto, incluso al comprar varias
    unidades o combinar presentaciones.
    """
    if payment_method not in OFFLINE_PAYMENT_METHODS or discount_percent <= 0:
        return Decimal("0.00")

    discount = Decimal("0.00")
    for unit_price, quantity in lines:
        qty = int(quantity)
        if qty <= 0:
            continue
        discount += payment_discount(unit_price, payment_method, discount_percent) * qty
    return money(discount)


def _rounded_offline_price(amount: Decimal, discount_percent: int) -> Decimal:
    """Aplica la tasa y baja el resultado al múltiplo de $50 anterior."""
    discount_rate = Decimal(discount_percent) / Decimal("100")
    percentage_price = amount * (Decimal("1.00") - discount_rate)
    increments = (percentage_price / OFFLINE_PRICE_ROUNDING_QUANTUM).to_integral_value(
        rounding=ROUND_FLOOR
    )
    return money(increments * OFFLINE_PRICE_ROUNDING_QUANTUM)


def discounted_amount(amount, discount_percent: int) -> Decimal | None:
    """Precio final redondeado pagando por transferencia o efectivo."""
    if amount is None or discount_percent <= 0:
        return None
    normalized = money(amount)
    if normalized <= 0:
        return normalized
    return _rounded_offline_price(normalized, discount_percent)
