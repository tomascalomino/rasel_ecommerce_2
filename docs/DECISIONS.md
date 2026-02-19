## 2026-02-18
- Catálogo MVP: stock y precio se gestionan por Variant (no por Product) para soportar tamaños/packs.

## 2026-02-18
- Carrito MVP: persistencia por sesión (sin login) usando variant_id como key.

## 2026-02-18
- Checkout sin login (guest checkout).
- Order guarda snapshot del producto (nombre y precio) para evitar inconsistencias futuras.

## 2026-02-18
- En entorno local se omite `notification_url` de MercadoPago porque requiere URL pública alcanzable.
- Se valida host de SITE_URL para habilitar webhook solo en URL pública (túnel).

## 2026-02-19
- Front MVP: Django templates + CSS propio (sin frameworks) para mantener dependencias mínimas y controlar el look & feel.
