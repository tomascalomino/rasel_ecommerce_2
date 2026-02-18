# Roadmap

## Hito 1 – Base proyecto
[x] Crear repo y estructura de carpetas
[x] Crear entorno virtual (conda: rasel-ecomm_venv)
[x] Instalar dependencias base y congelarlas en requirements.txt
[x] Crear proyecto Django (config) y apps base
[x] Primer run (migrate + runserver)
[ ] Settings con .env + Whitenoise + templates
[ ] Home básica conectada por URLs

## Hito 2 – Catálogo funcional
[ ] Modelos Category/Product/Variant
[ ] Admin para carga rápida
[ ] Tienda (listado) + detalle de producto

## Hito 3 – Carrito
[ ] Carrito por sesión (add/update/remove)
[ ] Página carrito
[ ] Integración desde tienda/detalle

## Hito 4 – Checkout
[ ] Modelo Order
[ ] Crear Order desde carrito
[ ] Página confirmación

## Hito 5 – Pagos (MercadoPago)
[x] Token y env vars
[x] back_urls correctos
[ ] Redirección a checkout (debería quedar con este fix)
[ ] Retornos success/pending/failure
[ ] Webhook con túnel (cloudflared/ngrok) + actualización de estado
