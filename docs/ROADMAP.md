# Roadmap

## Hito 1 – Base proyecto
[x] Crear repo y estructura de carpetas
[x] Crear entorno virtual (conda: rasel-ecomm_venv)
[x] Instalar dependencias base y congelarlas en requirements.txt
[x] Crear proyecto Django (config) y apps base
[x] Primer run (migrate + runserver)
[x] Settings con .env + Whitenoise + templates
[x] Home básica conectada por URLs

## Hito 2 – Catálogo funcional
[x] Modelos Category/Product/Variant
[x] Admin para carga rápida
[x] Tienda (listado) + detalle de producto

## Hito 3 – Carrito
[x] Carrito por sesión (add/update/remove)
[x] Página carrito
[x] Integración desde tienda/detalle

## Hito 4 – Checkout
[x] Modelo Order
[x] Crear Order desde carrito
[x] Página confirmación

## Hito 5 – Pagos (MercadoPago)
[x] Token y env vars
[x] back_urls correctos
[x] Redirección a checkout (debería quedar con este fix)
[x] Retornos success/pending/failure
[x] Webhook con túnel (cloudflared/ngrok) + actualización de estado

## Hito Front MVP (UI)
[x] Base layout (header/footer)
[x] Home simple
[x] Grilla de productos (cards)
[x] Página producto (CTA agregar al carrito)
[x] Carrito con tabla prolija

## Pendientes para productivo (P0/P1)
[x] Corregir media en Render (disco persistente + `MEDIA_ROOT` + `SERVE_MEDIA`)
[x] Corregir URL callback `payments:return` (`result`)
[x] Endurecer settings de seguridad base en producción
[x] Crear orden solo con pago confirmado (idempotencia)
[x] Descuento de stock transaccional al confirmar pago
[x] Logging estructurado y monitoreo de errores
[x] Tests de flujo crítico checkout/pagos/webhook
