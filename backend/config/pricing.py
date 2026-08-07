"""Reglas comerciales compartidas para calcular importes de la tienda."""

from decimal import Decimal, ROUND_HALF_UP


MONEY_QUANTUM = Decimal("0.01")
OFFLINE_PAYMENT_DISCOUNT_PERCENT = 5
OFFLINE_PAYMENT_DISCOUNT_RATE = Decimal("0.05")
OFFLINE_PAYMENT_METHODS = frozenset({"transfer", "cod"})


def money(value) -> Decimal:
    """Normaliza un importe a centavos usando redondeo comercial."""
    return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def payment_discount(subtotal, payment_method: str) -> Decimal:
    """Devuelve el descuento aplicable al subtotal según el medio de pago."""
    normalized = money(subtotal)
    if payment_method not in OFFLINE_PAYMENT_METHODS or normalized <= 0:
        return Decimal("0.00")
    return (normalized * OFFLINE_PAYMENT_DISCOUNT_RATE).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def discounted_amount(amount) -> Decimal | None:
    """Precio final de productos pagando por transferencia o efectivo."""
    if amount is None:
        return None
    normalized = money(amount)
    return normalized - payment_discount(normalized, "transfer")
