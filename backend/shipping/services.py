"""
Resolución de envío por código postal.

Esta es la *fuente de verdad* del costo de envío: se usa tanto en el endpoint
AJAX (`/shipping/quote/`) como en el POST del checkout, así que el precio nunca
depende de lo que mande el cliente. Es determinístico y no llama a servicios
externos: si el dataset de localidades no tiene el CP, igual resolvemos la zona
y el precio por rango (degradación elegante).
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .models import PostalCodeRule, ShippingZone

_DATA_FILE = Path(__file__).resolve().parent / "data" / "postal_codes.json"


@dataclass(frozen=True)
class ShippingQuote:
    cp: Optional[int]
    zone_code: str
    zone_name: str
    cost: Decimal
    is_free: bool
    locality: str
    province: str
    # Mínimo de compra para envío gratis en esta zona (None si no tiene mínimo).
    free_over: Optional[Decimal] = None
    # Cuánto falta de subtotal para alcanzar el envío gratis (None si ya es
    # gratis, si la zona no tiene mínimo, o si no se pasó el subtotal).
    remaining_for_free: Optional[Decimal] = None
    # Envío a cargo del comprador (resto del país): costo 0 pero NO es gratis.
    carrier_arranged: bool = False
    # Leyenda a mostrar cuando carrier_arranged.
    note: str = ""

    @property
    def cost_display(self) -> str:
        if self.carrier_arranged:
            return "A coordinar"
        return "Gratis" if self.is_free else f"$ {self.cost:.0f}"

    @property
    def location_label(self) -> str:
        parts = [p for p in (self.locality, self.province) if p]
        return ", ".join(parts)


def normalize_cp(raw) -> Optional[int]:
    """
    Extrae el núcleo numérico de 4 dígitos de un código postal.
    Acepta CPA ("C1425ABC" -> 1425), numérico ("1425") y con espacios/guiones.
    Devuelve None si no hay 4 dígitos.
    """
    if raw is None:
        return None
    match = re.search(r"\d{4}", str(raw).strip().upper())
    if not match:
        return None
    return int(match.group(0))


@functools.lru_cache(maxsize=1)
def _localities() -> dict:
    try:
        with open(_DATA_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def lookup_locality(cp: Optional[int]) -> tuple[str, str]:
    """Devuelve (localidad, provincia) para un CP normalizado, o ('', '')."""
    if cp is None:
        return ("", "")
    record = _localities().get(str(cp))
    if record:
        return (record.get("localidad", ""), record.get("provincia", ""))
    # Fallback: todo el rango de CABA es la Ciudad de Buenos Aires.
    if 1000 <= cp <= 1499:
        return ("Ciudad Autónoma de Buenos Aires", "CABA")
    return ("", "")


def _zone_for_cp(cp: Optional[int]) -> Optional[ShippingZone]:
    if cp is not None:
        rule = (
            PostalCodeRule.objects.filter(
                cp_from__lte=cp, cp_to__gte=cp, zone__is_active=True
            )
            .select_related("zone")
            .order_by("zone__sort_order", "id")
            .first()
        )
        if rule:
            return rule.zone
    return (
        ShippingZone.objects.filter(is_default=True, is_active=True)
        .order_by("sort_order")
        .first()
    )


def resolve_shipping(raw_cp, subtotal=None) -> ShippingQuote:
    """
    Resuelve la zona y el costo de envío para un CP.

    `subtotal` (subtotal de productos, sin envío) se usa para las zonas con
    mínimo de compra (`free_over`): si el subtotal lo alcanza, el envío es
    gratis; si no, se cobra `below_min_price`. Si no se pasa el subtotal, se
    asume que NO alcanza el mínimo (default seguro: cobra `below_min_price`).
    """
    cp = normalize_cp(raw_cp)
    locality, province = lookup_locality(cp)
    zone = _zone_for_cp(cp)

    if zone is None:
        # No hay zonas configuradas: no rompemos el checkout, envío a coordinar.
        return ShippingQuote(
            cp=cp,
            zone_code="",
            zone_name="Envío a coordinar",
            cost=Decimal("0.00"),
            is_free=True,
            locality=locality,
            province=province,
        )

    # Envío a cargo del comprador: RaSel no cobra (costo 0) pero NO es gratis.
    if zone.carrier_arranged:
        return ShippingQuote(
            cp=cp,
            zone_code=zone.code,
            zone_name=zone.name,
            cost=Decimal("0.00"),
            is_free=False,
            locality=locality,
            province=province,
            carrier_arranged=True,
            note=zone.description,
        )

    cost = zone.price
    free_over = zone.free_over
    remaining_for_free = None

    if free_over and free_over > 0:
        sub = Decimal(subtotal) if subtotal is not None else Decimal("0.00")
        if sub >= free_over:
            cost = zone.price  # alcanzó el mínimo -> precio base (0 = gratis)
        else:
            cost = zone.below_min_price
            remaining_for_free = free_over - sub

    return ShippingQuote(
        cp=cp,
        zone_code=zone.code,
        zone_name=zone.name,
        cost=cost,
        is_free=cost <= Decimal("0.00"),
        locality=locality,
        province=province,
        free_over=free_over,
        remaining_for_free=remaining_for_free,
    )


def carrier_arranged_legend() -> str:
    """
    Leyenda de la zona 'a cargo del comprador' activa, para contextos que no
    tienen la zona a mano (emails, páginas de confirmación). '' si no hay.
    """
    zone = (
        ShippingZone.objects.filter(carrier_arranged=True, is_active=True)
        .order_by("sort_order")
        .first()
    )
    return zone.description if zone else ""
