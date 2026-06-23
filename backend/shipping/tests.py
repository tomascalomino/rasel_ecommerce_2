from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from payments.models import PaymentDraft
from payments.views import _build_preference_payload

from .services import normalize_cp, resolve_shipping


class NormalizeCpTests(TestCase):
    def test_cpa_format(self):
        self.assertEqual(normalize_cp("C1425ABC"), 1425)

    def test_numeric(self):
        self.assertEqual(normalize_cp("1744"), 1744)

    def test_with_spaces_and_prefix(self):
        self.assertEqual(normalize_cp("  B1828 "), 1828)

    def test_invalid_returns_none(self):
        self.assertIsNone(normalize_cp("abcd"))
        self.assertIsNone(normalize_cp(""))
        self.assertIsNone(normalize_cp(None))


class ResolveShippingTests(TestCase):
    """Las zonas se siembran en la migración shipping.0002_seed_zones."""

    def test_caba_is_free(self):
        # Gratis solo si se alcanza el mínimo de compra.
        q = resolve_shipping("C1425ABC", subtotal=Decimal("30000"))
        self.assertTrue(q.is_free)
        self.assertEqual(q.cost, Decimal("0.00"))
        self.assertEqual(q.zone_code, "free")

    def test_moreno_is_free(self):
        q = resolve_shipping("1744", subtotal=Decimal("30000"))
        self.assertTrue(q.is_free)
        self.assertEqual(q.zone_code, "free")
        self.assertEqual(q.locality, "Moreno")

    def test_amba_fixed_price(self):
        q = resolve_shipping("1828")
        self.assertFalse(q.is_free)
        self.assertEqual(q.cost, Decimal("5000.00"))
        self.assertEqual(q.zone_code, "amba")

    def test_rest_of_country_default(self):
        q = resolve_shipping("5000")
        self.assertEqual(q.cost, Decimal("12000.00"))
        self.assertEqual(q.zone_code, "national")

    def test_invalid_cp_falls_back_to_default_zone(self):
        q = resolve_shipping("abcd")
        self.assertIsNone(q.cp)
        self.assertEqual(q.zone_code, "national")

    def test_1763_is_amba_not_free(self):
        # 1763 = Virrey del Pino (La Matanza), no La Reja: debe cobrar AMBA.
        q = resolve_shipping("1763")
        self.assertEqual(q.zone_code, "amba")
        self.assertEqual(q.cost, Decimal("5000.00"))

    def test_la_reja_still_free(self):
        # La Reja (Moreno) usa 1743/1744: sigue gratis por el rango 1742-1746.
        self.assertEqual(resolve_shipping("1744").zone_code, "free")
        self.assertEqual(resolve_shipping("1743").zone_code, "free")

    def test_magdalena_is_national_not_amba(self):
        # 1913 = Magdalena (partido rural costero): no es AMBA.
        q = resolve_shipping("1913")
        self.assertEqual(q.zone_code, "national")
        self.assertEqual(q.cost, Decimal("12000.00"))

    def test_la_plata_neighbors_still_amba(self):
        # Los bordes del corte 1913 siguen siendo AMBA.
        self.assertEqual(resolve_shipping("1912").zone_code, "amba")
        self.assertEqual(resolve_shipping("1925").zone_code, "amba")


class FreeShippingThresholdTests(TestCase):
    """Mínimo de compra para envío gratis en CABA/Moreno (free_over=30000)."""

    def test_caba_free_when_subtotal_reaches_min(self):
        q = resolve_shipping("1425", subtotal=Decimal("30000"))
        self.assertTrue(q.is_free)
        self.assertEqual(q.cost, Decimal("0.00"))
        self.assertIsNone(q.remaining_for_free)

    def test_caba_charges_amba_below_min(self):
        q = resolve_shipping("1425", subtotal=Decimal("20000"))
        self.assertFalse(q.is_free)
        self.assertEqual(q.cost, Decimal("5000.00"))
        self.assertEqual(q.free_over, Decimal("30000.00"))
        self.assertEqual(q.remaining_for_free, Decimal("10000.00"))

    def test_moreno_shares_the_threshold(self):
        below = resolve_shipping("1744", subtotal=Decimal("10000"))
        self.assertFalse(below.is_free)
        self.assertEqual(below.cost, Decimal("5000.00"))
        above = resolve_shipping("1744", subtotal=Decimal("50000"))
        self.assertTrue(above.is_free)

    def test_no_subtotal_charges_below_min_price(self):
        # Sin subtotal asumimos que no alcanza el mínimo (default seguro).
        q = resolve_shipping("1425")
        self.assertFalse(q.is_free)
        self.assertEqual(q.cost, Decimal("5000.00"))

    def test_threshold_does_not_affect_amba_or_national(self):
        self.assertEqual(
            resolve_shipping("1828", subtotal=Decimal("1")).cost, Decimal("5000.00")
        )
        self.assertEqual(
            resolve_shipping("5000", subtotal=Decimal("999999")).cost,
            Decimal("12000.00"),
        )


class QuoteEndpointTests(TestCase):
    def test_quote_json_free_with_subtotal(self):
        resp = self.client.get(
            reverse("shipping:quote"), {"postal_code": "1744", "subtotal": "30000"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["free"])
        self.assertEqual(data["cp"], 1744)
        self.assertEqual(data["locality"], "Moreno")

    def test_quote_json_below_min_returns_nudge(self):
        resp = self.client.get(
            reverse("shipping:quote"), {"postal_code": "1744", "subtotal": "10000"}
        )
        data = resp.json()
        self.assertFalse(data["free"])
        self.assertEqual(data["cost"], "5000.00")
        self.assertEqual(data["free_over"], "30000.00")
        self.assertEqual(data["remaining_for_free"], "20000.00")


class ShippingInfoPageTests(TestCase):
    def test_page_renders_zones(self):
        resp = self.client.get(reverse("shipping_info"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AMBA")
        self.assertContains(resp, "Resto del país")


class MercadoPagoShippingLineTests(TestCase):
    def _draft(self, shipping_cost):
        return PaymentDraft.objects.create(
            full_name="Test",
            email="t@example.com",
            address_line="Calle 1",
            city="Ciudad",
            postal_code="1828",
            shipping_cost=shipping_cost,
            shipping_zone="AMBA",
            total_amount=Decimal("17000.00"),
            items=[
                {
                    "variant_id": 1,
                    "product_name": "Aceite",
                    "variant_name": "500ml",
                    "unit_price": "12000.00",
                    "quantity": 1,
                    "line_total": "12000.00",
                }
            ],
        )

    def test_shipping_line_added_when_cost_positive(self):
        payload = _build_preference_payload(self._draft(Decimal("5000.00")))
        ship = [i for i in payload["items"] if i["title"].startswith("Envío")]
        self.assertEqual(len(ship), 1)
        self.assertEqual(ship[0]["unit_price"], 5000.0)

    def test_no_shipping_line_when_free(self):
        payload = _build_preference_payload(self._draft(Decimal("0.00")))
        ship = [i for i in payload["items"] if i["title"].startswith("Envío")]
        self.assertEqual(len(ship), 0)
