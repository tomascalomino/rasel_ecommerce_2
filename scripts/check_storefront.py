"""Check the public catalogue from outside Render, without credentials."""

import argparse
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

URLS = {
    "production": "https://rasel.ar/shop/",
    "staging": "https://rasel-mp-staging.onrender.com/shop/",
}
USER_AGENT = "RaSel Storefront Monitor/1.0"
CATALOGUE_TITLE = re.compile(rb'<h1\b[^>]*>\s*Tienda\s*</h1>', re.IGNORECASE)


class ProbeError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate(status, content_type, echoed_nonce, body, nonce):
    if status != 200:
        raise ProbeError(f"HTTP {status}")
    if content_type != "text/html" or not CATALOGUE_TITLE.search(body):
        raise ProbeError("La respuesta no contiene el catálogo.")
    if echoed_nonce != nonce:
        raise ProbeError("La respuesta no proviene de esta comprobación.")


def check(target):
    nonce = uuid4().hex
    request = Request(
        f"{URLS[target]}?_rasel_probe={nonce}",
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache", "Accept": "text/html"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=45) as response:
            validate(
                response.status, response.headers.get_content_type(),
                response.headers.get("X-RaSel-Probe"), response.read(128 * 1024), nonce,
            )
    except HTTPError as exc:
        raise ProbeError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProbeError("No se pudo contactar al catálogo.") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=URLS)
    parser.add_argument("--test-alert", action="store_true")
    args = parser.parse_args()
    if args.test_alert and args.target != "staging":
        parser.error("--test-alert solo se puede usar en staging")
    try:
        if args.test_alert:
            print("Prueba de entrega en staging con HTTP 503 simulado.")
            validate(503, "text/html", None, b"", "test-alert")
        check(args.target)
    except ProbeError as exc:
        print(f"Catálogo {args.target}: {exc}", file=sys.stderr)
        return 1
    print(f"Catálogo {args.target}: disponible y respuesta fresca.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
