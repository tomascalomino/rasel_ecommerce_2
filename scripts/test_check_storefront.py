import unittest

from check_storefront import ProbeError, validate


class CatalogueResponseTests(unittest.TestCase):
    catalogue = b'<h1 class="section-title">Tienda</h1>'

    def test_checks_status_html_and_freshness(self):
        validate(200, "text/html", "request", self.catalogue, "request")
        for status, kind, echoed, body in (
            (503, "text/html", "request", self.catalogue),
            (200, "text/plain", "request", self.catalogue),
            (200, "text/html", "stale", self.catalogue),
            (200, "text/html", "request", b"Error"),
        ):
            with self.subTest(status=status, kind=kind, echoed=echoed, body=body):
                with self.assertRaises(ProbeError):
                    validate(status, kind, echoed, body, "request")


if __name__ == "__main__":
    unittest.main()
