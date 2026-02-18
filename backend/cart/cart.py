from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from shop.models import Variant


SESSION_KEY = "cart"


@dataclass(frozen=True)
class CartItem:
    variant: Variant
    qty: int

    @property
    def unit_price(self) -> Decimal:
        return self.variant.price_ars

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * Decimal(self.qty)


class Cart:
    def __init__(self, session):
        self.session = session
        self._cart = session.get(SESSION_KEY, {})  # { "variant_id": {"qty": 2} }

    def save(self) -> None:
        self.session[SESSION_KEY] = self._cart
        self.session.modified = True

    def clear(self) -> None:
        self.session.pop(SESSION_KEY, None)
        self.session.modified = True

    def add(self, variant_id: int, qty: int = 1, override: bool = False) -> None:
        key = str(variant_id)
        qty = int(qty)
        if qty < 1:
            return

        if key not in self._cart:
            self._cart[key] = {"qty": 0}

        if override:
            self._cart[key]["qty"] = qty
        else:
            self._cart[key]["qty"] += qty

        self.save()

    def remove(self, variant_id: int) -> None:
        key = str(variant_id)
        if key in self._cart:
            del self._cart[key]
            self.save()

    def set_qty(self, variant_id: int, qty: int) -> None:
        key = str(variant_id)
        qty = int(qty)
        if qty <= 0:
            self.remove(variant_id)
            return
        if key in self._cart:
            self._cart[key]["qty"] = qty
            self.save()

    def __len__(self) -> int:
        return sum(item["qty"] for item in self._cart.values())

    def items(self) -> Iterable[CartItem]:
        variant_ids = [int(k) for k in self._cart.keys()]
        variants = Variant.objects.filter(id__in=variant_ids, is_active=True).select_related("product")
        variants_by_id = {v.id: v for v in variants}

        for key, payload in self._cart.items():
            vid = int(key)
            variant = variants_by_id.get(vid)
            if not variant:
                continue
            yield CartItem(variant=variant, qty=int(payload["qty"]))

    def total(self) -> Decimal:
        total = Decimal("0.00")
        for item in self.items():
            total += item.line_total
        return total
