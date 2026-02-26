# Runbook de operación (Render)

## 1) Objetivo
Guía rápida para operar, diagnosticar y recuperar la tienda en producción.

## 2) Variables críticas (Render)
- `DEBUG=0`
- `SECRET_KEY` (generada por Render)
- `ALLOWED_HOSTS=.onrender.com`
- `SITE_URL=https://rasel-ecommerce.onrender.com`
- `DATABASE_URL` (conectada al servicio DB)
- `MEDIA_ROOT=/var/data/media`
- `SERVE_MEDIA=1`
- `MP_ACCESS_TOKEN` (obligatorio para pagos)
- `LOG_LEVEL=INFO`

Opcionales de monitoreo:
- `SENTRY_DSN`
- `SENTRY_TRACES_SAMPLE_RATE` (recomendado `0.0` al inicio)
- `SENTRY_ENVIRONMENT=production`

## 3) Health check manual (2-5 min)
1. Abrir home y shop.
2. Verificar imagen en listado y detalle de al menos 1 producto.
3. Hacer checkout + pago de prueba.
4. Validar resultado: orden creada, carrito limpio, stock descontado.
5. Revisar logs en Render para eventos `payments.flow`.

## 4) Incidentes frecuentes

### A. No se ven imágenes en shop
Chequeos:
- `SERVE_MEDIA=1`.
- `MEDIA_ROOT=/var/data/media`.
- Disco montado en `/var/data/media`.
- Producto tiene `image` cargada en admin.

Acción:
- Corregir env vars / mount y redeploy.
- Re-subir imagen si el archivo no existe en disco.

### B. Pago no avanza / error de MercadoPago
Chequeos:
- `MP_ACCESS_TOKEN` válido.
- `SITE_URL` público y correcto.
- Logs: `Error procesando webhook...`.

Acción:
- Rotar token si está vencido.
- Confirmar callback/webhook apuntando al dominio Render.

### C. Webhook llega pero no crea orden
Chequeos:
- En admin: `PaymentEvent` y `PaymentDraft`.
- Campo `notes` en `PaymentEvent` (buscar `finalize_error=`).

Acción:
- Si `insufficient_stock:*`: ajustar stock y reintentar pago.
- Si `draft_not_found`: revisar `external_reference` en MP.
- Si `variant_not_found:*`: variante borrada/inactiva; corregir catálogo.

### D. Orden duplicada
Estado actual:
- La lógica es idempotente por `draft` y `payment_id`.

Chequeos:
- Buscar mismo `mp_payment_id` en órdenes.
- Revisar `PaymentEvent` duplicados.

Acción:
- Si aparece duplicado, escalar como bug crítico y congelar reintentos automáticos hasta corregir.

### E. Stock no coincide
Chequeos:
- `OrderItem.variant` existe y apunta a variante válida.
- Orden creada con estado `paid`.

Acción:
- Reconciliación manual de stock en admin.
- Registrar incidencia y revisar logs `Finalizar pago approved`.

## 5) Rollback rápido
Si un deploy rompe producción:
1. En Render, rollback al deploy anterior estable.
2. Verificar home + shop + checkout.
3. Si hubo migración nueva problemática, no borrar datos; evaluar fix-forward.

## 6) Operación diaria recomendada
- Revisar logs de `payments.flow` al menos 1 vez por día.
- Revisar eventos fallidos en `PaymentEvent`.
- Revisar drafts sin consumir (`consumed_at` null) para detectar abandono o fallos de pago.
- Ejecutar KPI rápido: `python backend/manage.py ops_kpis --days 7`.

## 7) Comandos útiles local
- `python backend/manage.py check --deploy`
- `python backend/manage.py test payments orders`
- `python backend/manage.py migrate`
- `python backend/manage.py ops_kpis --days 7`

## 8) Criterios de escalamiento
Escalar de inmediato si ocurre cualquiera:
- No se crean órdenes con pagos `approved`.
- Duplicación de órdenes confirmada.
- Pérdida persistente de imágenes en producción.
- Error sostenido en webhook (> 10 min).
