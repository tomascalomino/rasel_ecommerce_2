# Historial de funcionamiento

Este historial registra cambios ya aplicados. El comportamiento vigente se
documenta en `CURRENT_SYSTEM.md` y los procedimientos en `OPERATIONS.md`.

## 2026-08-03 — Liberación manual segura de reservas vencidas

- Cambio aplicado: el admin de borradores incorpora **Conciliar y liberar
  reservas vencidas** para consultar Mercado Pago y reponer stock únicamente
  cuando la reserva venció y no existe un pago.
- Seguridad: una falla de API conserva el stock y registra el error; pagos
  encontrados se procesan mediante el mismo servicio idempotente del webhook.
- Operación: staging puede omitir un Cron Job pago y usar esta acción para sus
  pruebas. El Cron cada diez minutos continúa siendo obligatorio en producción.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-03 — Validación de entorno de Checkout Pro

- Cambio aplicado: `live_mode` se valida contra el endpoint de Checkout Pro
  emitido por Mercado Pago, ya que una compra con cuentas y tarjetas de prueba
  mediante el `init_point` regular puede informar `true`.
- Recuperación: una orden puesta en revisión exclusivamente por la regla
  anterior puede reconciliarse a pagada sin crear otra orden, descontar stock
  nuevamente ni repetir el email.
- Seguridad: siguen siendo obligatorios la referencia, metadata, importe, ARS,
  collector, token de prueba y aislamiento de la base staging.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-02 — Checkout Pro seguro y conciliable

- Cambio aplicado: se reemplazó el flujo legado de Mercado Pago por Checkout
  Pro con SDK oficial, preferencias idempotentes, reservas de stock, retorno
  verificado por API, webhook firmado antes de toda escritura, estados
  financieros, reintegros sincronizados y revisión manual de anomalías.
- Flujo afectado: checkout, stock, pagos, retornos, webhooks, emails, admin,
  conciliación e incidentes. Transferencia y efectivo conservan su flujo.
- Migraciones o variables: `orders.0013` y `payments.0007`; se sustituye
  `MP_ENABLED` por `MP_CHECKOUT_ENABLED`, ambiente, límites de cuotas/reserva,
  plazo pendiente y email de alertas. Se agrega `mercadopago==3.3.0`.
- Operación: se agrega `reconcile_mp_payments` y el Blueprint declara
  `rasel-mp-reconcile` cada diez minutos. Checkout continúa apagado por defecto
  hasta completar staging, credenciales, webhook, cron y prueba controlada.
- Documentación actualizada: `README.md`, `docs/CURRENT_SYSTEM.md`,
  `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## Formato para nuevas entradas

```md
## AAAA-MM-DD — Título breve

- Cambio aplicado: ...
- Flujo afectado: ...
- Migraciones o variables: ...
- Documentación actualizada: ...
```

## 2026-08-02 — Baseline documental auditado

- Cambio aplicado: se reemplazó la documentación histórica fragmentada por una
  descripción del sistema actual, un manual de operación y este historial.
- Flujo afectado: despliegue, catálogo, checkout, pedidos, emails,
  administración, recuperación y servicios externos.
- Migraciones o variables: no se modificaron migraciones ni valores de
  producción; se documentaron las variables existentes.
- Documentación actualizada: `README.md`, `AGENTS.md`, `CLAUDE.md`,
  `docs/CURRENT_SYSTEM.md` y `docs/OPERATIONS.md`.
- Base auditada: `bundle_work` en `384e455`; producción en `rasel.ar`.
