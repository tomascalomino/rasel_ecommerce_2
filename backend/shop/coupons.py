"""Cotización firmada y cupo transaccional. Consultar no reserva un uso."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core import signing
from django.db import transaction
from django.utils import timezone

from config.pricing import money, payment_discount
from .models import Coupon, CouponRedemption

SESSION_KEY = "rasel_coupon_code"
OFFER_SALT = "rasel.coupon.offer.v1"
SNAPSHOT_FIELDS = (
    "coupon_id",
    "coupon_code",
    "coupon_discount_percent",
    "coupon_discount_amount",
)
ZERO = Decimal("0.00")


class CouponError(ValueError):
    pass


@dataclass
class CouponQuote:
    code: str = ""
    coupon: Coupon | None = None
    error: str = ""
    payment_amount: Decimal = ZERO
    mp_amount: Decimal = ZERO
    offline_amount: Decimal = ZERO
    unit_discounts: dict = field(default_factory=dict)
    terms: dict = field(default_factory=dict)

    def amount(self, method):
        return self.offline_amount if method in {"transfer", "cod"} else self.mp_amount

    def snapshot(self, method):
        if not self.coupon or self.amount(method) <= 0:
            return {}
        return dict(
            zip(
                SNAPSHOT_FIELDS,
                (
                    self.coupon.pk,
                    self.coupon.code,
                    self.coupon.discount_percent,
                    self.amount(method),
                ),
            )
        )

    @property
    def token(self):
        return signing.dumps(
            {"code": self.code, "terms": self.terms, "error": self.error},
            salt=OFFER_SALT,
        )


def normalize_code(code):
    return str(code or "").strip().lower()


def lock_coupon(code=None, *, coupon_id=None):
    """Dentro de atomic: cupón antes de variantes, también en admin y liberación.

    M2M adquiere bloqueos de las variantes por sus FK. Mantener este orden
    evita invertir esos bloqueos al editar las presentaciones durante una compra.
    """
    code = normalize_code(code)
    if not code and not coupon_id:
        return None
    query = Coupon.objects.select_for_update()
    coupon = (
        query.filter(pk=coupon_id).first()
        if coupon_id
        else query.filter(code__iexact=code).first()
    )
    if not coupon:
        raise CouponError(
            "Este cupón ya no está disponible. Quitalo o aplicá otro código."
        )
    return coupon


def quote_coupon(code, rows, discount_percent, *, now=None, lock=False):
    """Rows son objetos con variant, qty, unit_price; usa siempre precios del servidor."""
    now = now or timezone.now()
    rows = list(rows)
    result = CouponQuote(code=normalize_code(code))
    result.payment_amount = sum(
        (
            payment_discount(r.unit_price, "transfer", discount_percent) * r.qty
            for r in rows
        ),
        ZERO,
    )
    if not result.code:
        return result
    query = Coupon.objects.select_for_update() if lock else Coupon.objects
    coupon = query.filter(code__iexact=result.code).first()
    if not coupon:
        result.error = "No encontramos ese código. Revisá cómo está escrito."
        return result
    if (
        not coupon.enabled
        or coupon.starts_at > now
        or (coupon.ends_at and now >= coupon.ends_at)
    ):
        result.error = "Este cupón no está vigente."
        return result
    if coupon.remaining_uses < 1:
        result.error = "Se agotaron los usos disponibles de este cupón."
        return result
    variant_ids = set(coupon.variants.values_list("pk", flat=True))
    eligible = [r for r in rows if r.variant.pk in variant_ids]
    if not eligible:
        result.error = "Este cupón no aplica a los productos de tu carrito."
        return result
    result.coupon = coupon
    rate = Decimal(coupon.discount_percent) / Decimal(100)
    for row in eligible:
        unit = money(row.unit_price)
        payment = payment_discount(unit, "transfer", discount_percent)
        mp_discount = min(
            unit - money(unit * (1 - rate)), max(ZERO, unit - Decimal("0.01"))
        )
        if coupon.combine_payment_discount:
            offline = unit - payment - money((unit - payment) * (1 - rate))
        elif mp_discount > payment:
            result.payment_amount -= payment * row.qty
            offline = mp_discount
        else:
            offline = ZERO
        result.mp_amount += mp_discount * row.qty
        result.offline_amount += offline * row.qty
        result.unit_discounts[row.variant.pk] = mp_discount
    result.terms = {
        "id": coupon.pk,
        "percent": coupon.discount_percent,
        "combine": coupon.combine_payment_discount,
        "variants": sorted(variant_ids),
        "starts": coupon.starts_at.isoformat(),
        "ends": coupon.ends_at.isoformat() if coupon.ends_at else None,
        "mp": str(result.mp_amount),
        "offline": str(result.offline_amount),
        "payment": str(result.payment_amount),
    }
    return result


def checkout_coupon(code, rows, discount_percent, token, method, *, now=None):
    """El caller está en atomic y bloqueó primero el cupón y después las variantes."""
    quote = quote_coupon(code, rows, discount_percent, now=now, lock=True)
    try:
        accepted = signing.loads(token or "", salt=OFFER_SALT)
    except (signing.BadSignature, TypeError, ValueError):
        accepted = {"code": "", "terms": {}, "error": ""}
    current = {"code": quote.code, "terms": quote.terms, "error": quote.error}
    if quote.error:
        raise CouponError(
            quote.error
            + " Quitalo o aplicá otro antes de continuar; todavía no creamos el pedido ni reservamos stock."
        )
    if accepted != current:
        raise CouponError(
            "El cupón o su descuento cambió. Revisá el resumen y volvé a confirmar; todavía no creamos el pedido ni reservamos stock."
        )
    return quote


def assign_coupon(quote, *, order=None, draft=None, method="mp"):
    if quote.snapshot(method):
        # La fila del cupón sigue bloqueada hasta que el checkout entero termine.
        CouponRedemption.objects.create(
            coupon=quote.coupon,
            order=order,
            draft=draft,
            state="reserved" if draft else "used",
        )


def release_coupon(*, order=None, draft=None):
    lookup = {"order_id": order.pk} if order else {"draft_id": draft.pk}
    use = CouponRedemption.objects.filter(**lookup).first()
    if not use:
        return
    with transaction.atomic():
        Coupon.objects.select_for_update().get(pk=use.coupon_id)
        CouponRedemption.objects.filter(
            pk=use.pk, state__in=("reserved", "used")
        ).update(state="released", updated_at=timezone.now())


def consume_draft_coupon(draft, order):
    """Conserva el precio pagado; un pago tardío sin cupo exige revisión."""
    if not draft.coupon_id:
        return True
    coupon = Coupon.objects.select_for_update().get(pk=draft.coupon_id)
    use = CouponRedemption.objects.select_for_update().filter(draft=draft).first()
    if not use:
        return False
    if use.state == "released" and coupon.remaining_uses < 1:
        use.state = "review"
    elif use.state != "review":
        use.state = "used"
    use.order = order
    use.updated_at = timezone.now()
    use.save(update_fields=["state", "order", "updated_at"])
    return use.state == "used"
