"""Reglas comerciales compartidas para calcular importes de la tienda."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP


MONEY_QUANTUM = Decimal("0.01")
OFFLINE_PRICE_ROUNDING_QUANTUM = Decimal("50.00")
OFFLINE_PAYMENT_DISCOUNT_PERCENT = 5
OFFLINE_PAYMENT_DISCOUNT_RATE = Decimal("0.05")
OFFLINE_PAYMENT_METHODS = frozenset({"transfer", "cod"})


def money(value) -> Decimal:
    """Normaliza un importe a centavos usando redondeo comercial."""
    return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def payment_discount(subtotal, payment_method: str) -> Decimal:
    """Devuelve el descuento de una unidad o importe aislado."""
    normalized = money(subtotal)
    if payment_method not in OFFLINE_PAYMENT_METHODS or normalized <= 0:
        return Decimal("0.00")
    return normalized - _rounded_offline_price(normalized)


def payment_discount_for_lines(lines, payment_method: str) -> Decimal:
    """Calcula el descuento por precio unitario y luego lo multiplica.

    ``lines`` contiene pares ``(precio_unitario, cantidad)``. Calcular por
    variante garantiza que el checkout coincida con el precio promocional que
    el cliente vio en el detalle del producto, incluso al comprar varias
    unidades o combinar presentaciones.
    """
    if payment_method not in OFFLINE_PAYMENT_METHODS:
        return Decimal("0.00")

    discount = Decimal("0.00")
    for unit_price, quantity in lines:
        qty = int(quantity)
        if qty <= 0:
            continue
        discount += payment_discount(unit_price, payment_method) * qty
    return money(discount)


def _rounded_offline_price(amount: Decimal) -> Decimal:
    """Aplica 5% y baja el resultado al múltiplo de $50 anterior."""
    percentage_price = amount * (Decimal("1.00") - OFFLINE_PAYMENT_DISCOUNT_RATE)
    increments = (percentage_price / OFFLINE_PRICE_ROUNDING_QUANTUM).to_integral_value(
        rounding=ROUND_FLOOR
    )
    return money(increments * OFFLINE_PRICE_ROUNDING_QUANTUM)


def discounted_amount(amount) -> Decimal | None:
    """Precio final redondeado pagando por transferencia o efectivo."""
    if amount is None:
        return None
    normalized = money(amount)
    if normalized <= 0:
        return normalized
    return _rounded_offline_price(normalized)
